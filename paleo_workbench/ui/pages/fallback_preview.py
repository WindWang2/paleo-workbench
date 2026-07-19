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
from paleo_workbench.ui.tokens import format_size
from paleo_workbench.ui.pages.preview_provider import (
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_TEXT_PREVIEW_BYTES,
    PreviewResult,
)

MAX_ARCHIVE_NAMES = 500
MAX_EMBEDDED_IMAGE_BYTES = 16 * 1024 * 1024
MAX_CENTRAL_DIRECTORY_BYTES = 4 * 1024 * 1024
MAX_CENTRAL_ENTRIES = 10_000
MAX_CENTRAL_NAME_BYTES = 1024 * 1024

_SPREADSHEETML_NAMESPACE = "urn:schemas-microsoft-com:office:spreadsheet"
_SLIDE_NAME = re.compile(r"ppt/slides/slide[1-9][0-9]*\.xml\Z")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8"


class BoundedReader:
    def __init__(self, raw: BinaryIO, limit: int = MAX_TEXT_PREVIEW_BYTES) -> None:
        self._raw = raw
        self._remaining = limit
        self._artificial_eof_received = False

    @property
    def limit_reached(self) -> bool:
        return self._remaining <= 0

    @property
    def artificial_eof_received(self) -> bool:
        return self._artificial_eof_received

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            self._artificial_eof_received = True
            return b""
        wanted = self._remaining if size < 0 else min(size, self._remaining)
        chunk = self._raw.read(wanted)
        self._remaining -= len(chunk)
        return chunk


class _FirstWorksheetComplete(Exception):
    pass


class _ArchiveSafetyError(ValueError):
    pass


def spreadsheetml_preview(
    resource: ResourceItem,
    *,
    max_text_bytes: int = MAX_TEXT_PREVIEW_BYTES,
    max_rows: int = MAX_TABLE_ROWS,
    max_columns: int = MAX_TABLE_COLUMNS,
) -> PreviewResult | None:
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
    in_first_table = False
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
            reader = BoundedReader(raw, limit=max_text_bytes)
            for event, element in ET.iterparse(reader, events=("start", "end")):
                namespace, local_name = _qualified_name(element.tag)

                if not root_checked and event == "start":
                    root_checked = True
                    if not _is_spreadsheet_element(namespace, local_name, "Workbook"):
                        return None

                if event == "start" and _is_spreadsheet_element(
                    namespace, local_name, "Worksheet"
                ):
                    if first_worksheet_seen:
                        raise _FirstWorksheetComplete
                    first_worksheet_seen = True
                    in_first_worksheet = True
                    sheet_name = _attribute(element, "Name") or sheet_name
                    continue

                if not in_first_worksheet:
                    continue

                if event == "end" and _is_spreadsheet_element(
                    namespace, local_name, "Worksheet"
                ):
                    in_first_worksheet = False
                    raise _FirstWorksheetComplete

                if event == "start" and _is_spreadsheet_element(
                    namespace, local_name, "Table"
                ):
                    in_first_table = True
                    continue

                if event == "end" and _is_spreadsheet_element(
                    namespace, local_name, "Table"
                ):
                    in_first_table = False
                    element.clear()
                    continue

                if not in_first_table:
                    continue

                if event == "start" and _is_spreadsheet_element(
                    namespace, local_name, "Row"
                ):
                    if len(rows) >= max_rows + 1:
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

                if (
                    event == "end"
                    and _is_spreadsheet_element(namespace, local_name, "Cell")
                    and current_row is not None
                ):
                    index_value = _attribute(element, "Index")
                    cell_index = _positive_index(index_value)
                    if cell_index is None and index_value is not None:
                        malformed_structure = True
                    desired_position = cell_index or current_cell_position
                    if desired_position < current_cell_position:
                        malformed_structure = True
                        desired_position = current_cell_position
                    if desired_position <= max_columns:
                        while len(current_row) < desired_position - 1:
                            current_row.append("")
                        current_row.append(_cell_text(element))
                    else:
                        truncated = True
                    current_cell_position = desired_position + 1
                    element.clear()
                    continue

                if (
                    event == "end"
                    and _is_spreadsheet_element(namespace, local_name, "Row")
                    and current_row is not None
                ):
                    while (
                        next_row_position < current_row_position
                        and len(rows) < max_rows + 1
                    ):
                        rows.append(())
                        next_row_position += 1
                    if next_row_position < current_row_position:
                        truncated = True
                        raise _FirstWorksheetComplete
                    rows.append(tuple(current_row[:max_columns]))
                    next_row_position = current_row_position + 1
                    current_row = None
                    element.clear()
                    continue

                if event == "end" and current_row is None:
                    element.clear()
    except _FirstWorksheetComplete:
        pass
    except ET.ParseError:
        boundary_truncation = bool(
            reader is not None
            and reader.artificial_eof_received
            and source_size > max_text_bytes
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
    body = tuple(rows[1 : max_rows + 1])
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
        _validate_zip_central_directory(path)
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
    except _ArchiveSafetyError as exc:
        return _message(resource, f"PPTX ZIP 目录不安全: {exc}")
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
        try:
            sibling_size = sibling.stat().st_size
            if sibling_size > MAX_EMBEDDED_IMAGE_BYTES:
                return _dfb_metadata(
                    resource,
                    sibling_size,
                    "DFB 同名预览图超过 16 MiB，已拒绝读取",
                )
            with sibling.open("rb") as source:
                sibling_bytes = source.read(MAX_EMBEDDED_IMAGE_BYTES + 1)
        except OSError:
            return _dfb_metadata(resource, 0, "DFB 同名预览图不可读")
        if len(sibling_bytes) > MAX_EMBEDDED_IMAGE_BYTES:
            return _dfb_metadata(
                resource,
                len(sibling_bytes),
                "DFB 同名预览图实际内容超过 16 MiB，已拒绝读取",
            )
        return PreviewResult(
            mode="image",
            title=resource.name,
            path=str(sibling),
            revision=_revision(sibling),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            summary_rows=(("预览来源", sibling.name),),
            image_bytes=sibling_bytes,
            estimated_bytes=len(sibling_bytes),
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


def zip_preview(
    resource: ResourceItem,
    *,
    max_rows: int = MAX_ARCHIVE_NAMES,
) -> PreviewResult:
    path = Path(resource.path)
    try:
        _validate_zip_central_directory(path)
        with zipfile.ZipFile(path) as archive:
            visible_limit = min(max_rows, MAX_ARCHIVE_NAMES)
            names = heapq.nsmallest(
                visible_limit + 1,
                (info.filename for info in archive.infolist()),
            )
    except _ArchiveSafetyError as exc:
        return _message(resource, f"ZIP 目录不安全: {exc}")
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        return _message(resource, "ZIP 包格式错误，无法读取目录")

    truncated = len(names) > visible_limit
    visible_names = names[:visible_limit]
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
        warning=f"ZIP 目录仅显示排序后的前 {visible_limit} 个条目，已截断"
        if truncated
        else "",
    )


def wlp_preview(resource: ResourceItem) -> PreviewResult:
    return _message(resource, "暂不支持 WLP 内置预览")


def _qualified_name(tag: str) -> tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, local_name = tag[1:].split("}", 1)
        return namespace, local_name
    return "", tag


def _is_spreadsheet_element(namespace: str, local_name: str, expected: str) -> bool:
    return namespace == _SPREADSHEETML_NAMESPACE and local_name == expected


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
        namespace, local_name = _qualified_name(descendant.tag)
        if _is_spreadsheet_element(namespace, local_name, "Data"):
            return "".join(descendant.itertext())
    return ""


def _dfb_sibling(path: Path) -> Path | None:
    suffix_rank = {".png": 0, ".jpg": 1, ".jpeg": 2}
    best: tuple[tuple[int, str, str], Path] | None = None
    try:
        candidates = path.parent.iterdir()
        for candidate in candidates:
            rank = suffix_rank.get(candidate.suffix.lower())
            if rank is None or candidate.stem != path.stem or not candidate.is_file():
                continue
            key = (rank, candidate.name.casefold(), candidate.name)
            if best is None or key < best[0]:
                best = (key, candidate)
    except OSError:
        return None
    return best[1] if best is not None else None


def _validate_zip_central_directory(path: Path) -> None:
    """Validate a bounded, single-disk non-ZIP64 central directory."""

    try:
        file_size = path.stat().st_size
        tail_size = min(file_size, 22 + 65_535)
        with path.open("rb") as source:
            source.seek(file_size - tail_size)
            tail = source.read(tail_size)
    except OSError as exc:
        raise _ArchiveSafetyError("无法读取 EOCD") from exc

    eocd_position = _find_eocd(tail)
    if eocd_position is None:
        raise _ArchiveSafetyError("EOCD 缺失或损坏")
    absolute_eocd = file_size - tail_size + eocd_position
    (
        _signature,
        disk_number,
        central_disk,
        entries_on_disk,
        total_entries,
        central_size,
        central_offset,
        _comment_length,
    ) = struct.unpack_from("<4s4H2LH", tail, eocd_position)

    if disk_number != 0 or central_disk != 0 or entries_on_disk != total_entries:
        raise _ArchiveSafetyError("不支持 multi-disk ZIP")
    if (
        entries_on_disk == 0xFFFF
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
    ):
        raise _ArchiveSafetyError("不支持 ZIP64")
    if total_entries > MAX_CENTRAL_ENTRIES:
        raise _ArchiveSafetyError("central entries 超过 10000")
    if central_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise _ArchiveSafetyError("central directory 超过 4 MiB")
    central_end = central_offset + central_size
    if central_offset > file_size or central_end != absolute_eocd:
        raise _ArchiveSafetyError("central directory offset/size 越界")

    try:
        with path.open("rb") as source:
            source.seek(central_offset)
            central = source.read(central_size)
    except OSError as exc:
        raise _ArchiveSafetyError("无法读取 central directory") from exc
    if len(central) != central_size:
        raise _ArchiveSafetyError("central directory 截断")

    position = 0
    parsed_entries = 0
    utf8_name_bytes = 0
    while position < central_size:
        if position + 46 > central_size or central[position : position + 4] != b"PK\x01\x02":
            raise _ArchiveSafetyError("central directory entry 损坏")
        fields = struct.unpack_from("<4s6H3L5H2L", central, position)
        flags = fields[3]
        compressed_size = fields[8]
        uncompressed_size = fields[9]
        name_length = fields[10]
        extra_length = fields[11]
        comment_length = fields[12]
        start_disk = fields[13]
        local_offset = fields[16]
        entry_end = position + 46 + name_length + extra_length + comment_length
        if entry_end > central_size:
            raise _ArchiveSafetyError("central directory entry 越界")
        if (
            compressed_size == 0xFFFFFFFF
            or uncompressed_size == 0xFFFFFFFF
            or local_offset == 0xFFFFFFFF
            or start_disk == 0xFFFF
        ):
            raise _ArchiveSafetyError("不支持 ZIP64 entry")
        if start_disk != 0 or local_offset >= central_offset:
            raise _ArchiveSafetyError("entry offset/disk 无效")

        raw_name = central[position + 46 : position + 46 + name_length]
        try:
            encoding = "utf-8" if flags & 0x800 else "cp437"
            decoded_name = raw_name.decode(encoding)
        except UnicodeDecodeError as exc:
            raise _ArchiveSafetyError("entry 名称编码无效") from exc
        utf8_name_bytes += len(decoded_name.encode("utf-8"))
        if utf8_name_bytes > MAX_CENTRAL_NAME_BYTES:
            raise _ArchiveSafetyError("central 名称总量超过 1 MiB")

        parsed_entries += 1
        if parsed_entries > MAX_CENTRAL_ENTRIES:
            raise _ArchiveSafetyError("central entries 超过 10000")
        position = entry_end

    if parsed_entries != total_entries:
        raise _ArchiveSafetyError("EOCD entry count 不一致")


def _find_eocd(tail: bytes) -> int | None:
    position = tail.rfind(b"PK\x05\x06")
    while position >= 0:
        if position + 22 <= len(tail):
            comment_length = struct.unpack_from("<H", tail, position + 20)[0]
            if position + 22 + comment_length == len(tail):
                return position
        position = tail.rfind(b"PK\x05\x06", 0, position)
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
    if start + 2 > max_end or mapped[start : start + 2] != _JPEG_SIGNATURE:
        return None
    position = start + 2
    frame_components: set[int] | None = None
    seen_scan = False
    sof_markers = {
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
    }

    while position < max_end:
        if mapped[position] != 0xFF:
            return None
        while position < max_end and mapped[position] == 0xFF:
            position += 1
        if position >= max_end:
            return None
        marker = mapped[position]
        position += 1
        if marker == 0xD9:
            return position if frame_components is not None and seen_scan else None
        if marker in {0x00, 0xD8} or 0xD0 <= marker <= 0xD7:
            return None
        if marker == 0x01:  # TEM is the only other standalone marker.
            continue
        if position + 2 > max_end:
            return None
        segment_length = struct.unpack(">H", mapped[position : position + 2])[0]
        if segment_length < 2 or position + segment_length > max_end:
            return None
        body_start = position + 2
        segment_end = position + segment_length

        if marker in sof_markers:
            if frame_components is not None or seen_scan or segment_length < 8:
                return None
            precision = mapped[body_start]
            height = struct.unpack(">H", mapped[body_start + 1 : body_start + 3])[0]
            width = struct.unpack(">H", mapped[body_start + 3 : body_start + 5])[0]
            component_count = mapped[body_start + 5]
            if (
                precision == 0
                or precision > 16
                or width == 0
                or height == 0
                or component_count == 0
                or component_count > 4
                or segment_length != 8 + 3 * component_count
            ):
                return None
            components: set[int] = set()
            component_position = body_start + 6
            for _ in range(component_count):
                identifier = mapped[component_position]
                sampling = mapped[component_position + 1]
                quantization_table = mapped[component_position + 2]
                horizontal = sampling >> 4
                vertical = sampling & 0x0F
                if (
                    identifier in components
                    or horizontal == 0
                    or horizontal > 4
                    or vertical == 0
                    or vertical > 4
                    or quantization_table > 3
                ):
                    return None
                components.add(identifier)
                component_position += 3
            frame_components = components

        if marker != 0xDA:
            position = segment_end
            continue

        if frame_components is None or segment_length < 6:
            return None
        scan_component_count = mapped[body_start]
        if (
            scan_component_count == 0
            or scan_component_count > len(frame_components)
            or segment_length != 6 + 2 * scan_component_count
        ):
            return None
        scan_components: set[int] = set()
        component_position = body_start + 1
        for _ in range(scan_component_count):
            identifier = mapped[component_position]
            table_selectors = mapped[component_position + 1]
            if (
                identifier not in frame_components
                or identifier in scan_components
                or table_selectors >> 4 > 3
                or table_selectors & 0x0F > 3
            ):
                return None
            scan_components.add(identifier)
            component_position += 2
        spectral_start = mapped[component_position]
        spectral_end = mapped[component_position + 1]
        approximation = mapped[component_position + 2]
        if (
            spectral_start > 63
            or spectral_end > 63
            or approximation >> 4 > 13
            or approximation & 0x0F > 13
        ):
            return None

        seen_scan = True
        position = segment_end
        scan_has_entropy = False
        while position < max_end:
            marker_start = mapped.find(b"\xff", position, max_end)
            if marker_start < 0:
                return None
            if marker_start > position:
                scan_has_entropy = True
            position = marker_start + 1
            while position < max_end and mapped[position] == 0xFF:
                position += 1
            if position >= max_end:
                return None
            marker = mapped[position]
            if marker == 0x00:
                scan_has_entropy = True
                position += 1
                continue
            if 0xD0 <= marker <= 0xD7:
                position += 1
                continue
            if marker == 0xD9:
                if not scan_has_entropy:
                    return None
                return position + 1 if frame_components is not None else None
            if not scan_has_entropy:
                return None
            position = marker_start
            break
    return None


def _dfb_metadata(
    resource: ResourceItem,
    size: int,
    message: str = "未发现经过结构验证的 DFB 预览图像",
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
        summary_rows=(("文件大小", format_size(size)), ("预览状态", "仅元数据")),
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
