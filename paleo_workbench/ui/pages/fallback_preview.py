from __future__ import annotations

import heapq
import mmap
from pathlib import Path
import re
import struct
from typing import BinaryIO
import xml.etree.ElementTree as ET
import zipfile
import zlib

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_provider import (
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_TEXT_PREVIEW_BYTES,
    PreviewResult,
)

MAX_ARCHIVE_NAMES = 500
MAX_EMBEDDED_IMAGE_BYTES = 16 * 1024 * 1024

_SPREADSHEETML_NAMESPACE = "urn:schemas-microsoft-com:office:spreadsheet"
_SLIDE_NAME = re.compile(r"ppt/slides/slide[1-9][0-9]*\.xml\Z")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8"


class BoundedReader:
    def __init__(self, raw: BinaryIO, limit: int = MAX_TEXT_PREVIEW_BYTES) -> None:
        self._raw = raw
        self._remaining = limit

    @property
    def limit_reached(self) -> bool:
        return self._remaining <= 0

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        wanted = self._remaining if size < 0 else min(size, self._remaining)
        chunk = self._raw.read(wanted)
        self._remaining -= len(chunk)
        return chunk


class _FirstWorksheetComplete(Exception):
    pass


def spreadsheetml_preview(resource: ResourceItem) -> PreviewResult | None:
    """Read one SpreadsheetML worksheet without claiming ordinary XML files."""

    path = Path(resource.path)
    try:
        source_size = path.stat().st_size
        raw = path.open("rb")
    except OSError:
        return _message(resource, "SpreadsheetML 文件不可读")

    rows: list[tuple[str, ...]] = []
    sheet_name = "工作表 1"
    root_checked = False
    in_first_worksheet = False
    first_worksheet_seen = False
    current_row: list[str] | None = None
    current_cell_position = 1
    current_row_position = 1
    next_row_position = 1
    truncated = False
    malformed_structure = False
    reader: BoundedReader | None = None

    try:
        with raw:
            reader = BoundedReader(raw)
            for event, element in ET.iterparse(reader, events=("start", "end")):
                namespace, local_name = _qualified_name(element.tag)

                if not root_checked and event == "start":
                    root_checked = True
                    if local_name != "Workbook" or namespace != _SPREADSHEETML_NAMESPACE:
                        return None

                if event == "start" and local_name == "Worksheet":
                    if first_worksheet_seen:
                        raise _FirstWorksheetComplete
                    first_worksheet_seen = True
                    in_first_worksheet = True
                    sheet_name = _attribute(element, "Name") or sheet_name
                    continue

                if not in_first_worksheet:
                    continue

                if event == "start" and local_name == "Row":
                    if len(rows) >= MAX_TABLE_ROWS + 1:
                        truncated = True
                        raise _FirstWorksheetComplete
                    current_row = []
                    current_cell_position = 1
                    row_index = _positive_index(_attribute(element, "Index"))
                    if row_index is None and _attribute(element, "Index") is not None:
                        malformed_structure = True
                    current_row_position = row_index or next_row_position
                    if current_row_position < next_row_position:
                        malformed_structure = True
                        current_row_position = next_row_position
                    continue

                if event == "end" and local_name == "Cell" and current_row is not None:
                    index_value = _attribute(element, "Index")
                    cell_index = _positive_index(index_value)
                    if cell_index is None and index_value is not None:
                        malformed_structure = True
                    desired_position = cell_index or current_cell_position
                    if desired_position < current_cell_position:
                        malformed_structure = True
                        desired_position = current_cell_position
                    if desired_position <= MAX_TABLE_COLUMNS:
                        while len(current_row) < desired_position - 1:
                            current_row.append("")
                        current_row.append(_cell_text(element))
                    else:
                        truncated = True
                    current_cell_position = desired_position + 1
                    element.clear()
                    continue

                if event == "end" and local_name == "Row" and current_row is not None:
                    while (
                        next_row_position < current_row_position
                        and len(rows) < MAX_TABLE_ROWS + 1
                    ):
                        rows.append(())
                        next_row_position += 1
                    if next_row_position < current_row_position:
                        truncated = True
                        raise _FirstWorksheetComplete
                    rows.append(tuple(current_row[:MAX_TABLE_COLUMNS]))
                    next_row_position = current_row_position + 1
                    current_row = None
                    element.clear()
                    continue

                if event == "end" and local_name == "Worksheet":
                    in_first_worksheet = False
                    raise _FirstWorksheetComplete

                if event == "end" and current_row is None:
                    element.clear()
    except _FirstWorksheetComplete:
        pass
    except ET.ParseError:
        boundary_truncation = bool(
            reader is not None
            and reader.limit_reached
            and source_size > MAX_TEXT_PREVIEW_BYTES
        )
        if boundary_truncation and first_worksheet_seen:
            truncated = True
        elif not root_checked and source_size == 0:
            return _message(resource, "SpreadsheetML XML 为空")
        else:
            return _message(resource, "SpreadsheetML XML 格式错误")

    if not root_checked:
        return _message(resource, "SpreadsheetML XML 为空")
    if malformed_structure:
        return _message(resource, "SpreadsheetML XML 索引格式错误")
    if not first_worksheet_seen:
        return _message(resource, "SpreadsheetML XML 没有可预览的工作表")

    headers = rows[0] if rows else ()
    body = tuple(rows[1 : MAX_TABLE_ROWS + 1])
    return PreviewResult(
        mode="table",
        title=resource.name,
        path=resource.path,
        revision=_revision(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        table_headers=headers,
        table_rows=body,
        sheets=(sheet_name,),
        truncated=truncated,
        warning="SpreadsheetML 表格预览已按读取或行列上限截断" if truncated else "",
    )


def pptx_preview(resource: ResourceItem) -> PreviewResult:
    path = Path(resource.path)
    try:
        with zipfile.ZipFile(path) as package:
            infos = package.infolist()
            slide_names = {
                info.filename
                for info in infos
                if not info.is_dir() and _SLIDE_NAME.fullmatch(info.filename)
            }
            summary = (("幻灯片数", str(len(slide_names))),)
            thumbnail_infos = [
                info
                for info in infos
                if not info.is_dir()
                and info.filename in {
                    "docProps/thumbnail.jpeg",
                    "docProps/thumbnail.png",
                }
            ]
            grouped: dict[str, list[zipfile.ZipInfo]] = {}
            for info in thumbnail_infos:
                grouped.setdefault(info.filename, []).append(info)
            duplicate_names = [name for name, matches in grouped.items() if len(matches) > 1]
            if duplicate_names:
                return _message(
                    resource,
                    "PPTX 包含重复缩略图条目，已拒绝读取",
                    summary_rows=summary,
                )

            thumbnail = next(
                (
                    grouped[name][0]
                    for name in ("docProps/thumbnail.jpeg", "docProps/thumbnail.png")
                    if name in grouped
                ),
                None,
            )
            if thumbnail is None:
                return _message(
                    resource,
                    "PPTX 未发现可用缩略图",
                    summary_rows=summary,
                )
            if thumbnail.file_size > MAX_EMBEDDED_IMAGE_BYTES:
                return _message(
                    resource,
                    "PPTX 缩略图过大，已拒绝读取",
                    summary_rows=summary,
                )
            with package.open(thumbnail, "r") as source:
                image_bytes = source.read(MAX_EMBEDDED_IMAGE_BYTES + 1)
            if len(image_bytes) > MAX_EMBEDDED_IMAGE_BYTES:
                return _message(
                    resource,
                    "PPTX 缩略图实际内容过大，已拒绝读取",
                    summary_rows=summary,
                )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        return _message(resource, "PPTX 包格式错误，无法读取元数据")

    return PreviewResult(
        mode="image",
        title=resource.name,
        path=resource.path,
        revision=_revision(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        summary_rows=summary,
        image_bytes=image_bytes,
        estimated_bytes=len(image_bytes),
    )


def dfb_preview(resource: ResourceItem) -> PreviewResult:
    path = Path(resource.path)
    sibling = _dfb_sibling(path)
    if sibling is not None:
        return PreviewResult(
            mode="image",
            title=resource.name,
            path=str(sibling),
            revision=_revision(sibling),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            summary_rows=(("预览来源", sibling.name),),
        )

    try:
        size = path.stat().st_size
        with path.open("rb") as source:
            if size == 0:
                return _dfb_metadata(resource, size)
            with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                image_bytes = _find_embedded_image(mapped)
    except (OSError, ValueError):
        return _dfb_metadata(resource, 0)

    if image_bytes is None:
        return _dfb_metadata(resource, size)
    return PreviewResult(
        mode="image",
        title=resource.name,
        path=resource.path,
        revision=_revision(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        summary_rows=(("预览来源", "DFB 内嵌图像"),),
        image_bytes=image_bytes,
        estimated_bytes=len(image_bytes),
    )


def zip_preview(resource: ResourceItem) -> PreviewResult:
    path = Path(resource.path)
    try:
        with zipfile.ZipFile(path) as archive:
            names = heapq.nsmallest(
                MAX_ARCHIVE_NAMES + 1,
                (info.filename for info in archive.infolist()),
            )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        return _message(resource, "ZIP 包格式错误，无法读取目录")

    truncated = len(names) > MAX_ARCHIVE_NAMES
    visible_names = names[:MAX_ARCHIVE_NAMES]
    return PreviewResult(
        mode="table",
        title=resource.name,
        path=resource.path,
        revision=_revision(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        table_headers=("ZIP 条目",),
        table_rows=tuple((name,) for name in visible_names),
        truncated=truncated,
        warning="ZIP 目录仅显示排序后的前 500 个条目，已截断" if truncated else "",
    )


def wlp_preview(resource: ResourceItem) -> PreviewResult:
    return _message(resource, "暂不支持 WLP 内置预览")


def _qualified_name(tag: str) -> tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, local_name = tag[1:].split("}", 1)
        return namespace, local_name
    return "", tag


def _attribute(element: ET.Element, local_name: str) -> str | None:
    return element.attrib.get(f"{{{_SPREADSHEETML_NAMESPACE}}}{local_name}") or element.attrib.get(
        local_name
    )


def _positive_index(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _cell_text(cell: ET.Element) -> str:
    for descendant in cell.iter():
        if _qualified_name(descendant.tag)[1] == "Data":
            return "".join(descendant.itertext())
    return ""


def _dfb_sibling(path: Path) -> Path | None:
    for suffix in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def _find_embedded_image(mapped: mmap.mmap) -> bytes | None:
    for signature, validator in (
        (_PNG_SIGNATURE, _validated_png_range),
        (_JPEG_SIGNATURE, _validated_jpeg_range),
    ):
        start = mapped.find(signature)
        while start >= 0:
            end = validator(mapped, start)
            if end is not None:
                return bytes(mapped[start:end])
            start = mapped.find(signature, start + 1)
    return None


def _validated_png_range(mapped: mmap.mmap, start: int) -> int | None:
    max_end = min(len(mapped), start + MAX_EMBEDDED_IMAGE_BYTES)
    position = start + len(_PNG_SIGNATURE)
    seen_ihdr = False
    seen_idat = False
    while position + 12 <= max_end:
        length = struct.unpack(">I", mapped[position : position + 4])[0]
        chunk_type = bytes(mapped[position + 4 : position + 8])
        chunk_end = position + 12 + length
        if chunk_end > max_end or not all(
            65 <= value <= 90 or 97 <= value <= 122 for value in chunk_type
        ):
            return None
        expected_crc = struct.unpack(">I", mapped[chunk_end - 4 : chunk_end])[0]
        actual_crc = zlib.crc32(mapped[position + 4 : chunk_end - 4]) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return None
        if not seen_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                return None
            seen_ihdr = True
        elif chunk_type == b"IHDR":
            return None
        if chunk_type == b"IDAT":
            seen_idat = True
        if chunk_type == b"IEND":
            if length != 0 or not seen_idat:
                return None
            return chunk_end
        position = chunk_end
    return None


def _validated_jpeg_range(mapped: mmap.mmap, start: int) -> int | None:
    max_end = min(len(mapped), start + MAX_EMBEDDED_IMAGE_BYTES)
    position = start + 2
    seen_frame = False
    seen_scan = False

    while position < max_end:
        if mapped[position] != 0xFF:
            return None
        marker_start = position
        while position < max_end and mapped[position] == 0xFF:
            position += 1
        if position >= max_end:
            return None
        marker = mapped[position]
        position += 1
        if marker == 0xD9:
            return position if seen_frame and seen_scan else None
        if marker in {0x00, 0xD8} or 0xD0 <= marker <= 0xD7:
            return None
        if position + 2 > max_end:
            return None
        segment_length = struct.unpack(">H", mapped[position : position + 2])[0]
        if segment_length < 2 or position + segment_length > max_end:
            return None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            seen_frame = True
        if marker != 0xDA:
            position += segment_length
            continue

        seen_scan = True
        position += segment_length
        while position < max_end:
            marker_start = mapped.find(b"\xff", position, max_end)
            if marker_start < 0:
                return None
            position = marker_start + 1
            while position < max_end and mapped[position] == 0xFF:
                position += 1
            if position >= max_end:
                return None
            marker = mapped[position]
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                position += 1
                continue
            if marker == 0xD9:
                return position + 1 if seen_frame else None
            position = marker_start
            break
    return None


def _dfb_metadata(resource: ResourceItem, size: int) -> PreviewResult:
    return PreviewResult(
        mode="message",
        title=resource.name,
        path=resource.path,
        revision=_revision(Path(resource.path)),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        message="未发现经过结构验证的 DFB 预览图像",
        summary_rows=(("文件大小", f"{size} bytes"), ("预览状态", "仅元数据")),
    )


def _message(
    resource: ResourceItem,
    message: str,
    *,
    summary_rows: tuple[tuple[str, str], ...] = (),
) -> PreviewResult:
    return PreviewResult(
        mode="message",
        title=resource.name,
        path=resource.path,
        revision=_revision(Path(resource.path)),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        message=message,
        warning=message,
        summary_rows=summary_rows,
    )


def _revision(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns
