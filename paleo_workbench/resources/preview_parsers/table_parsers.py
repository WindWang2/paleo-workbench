from __future__ import annotations

import csv
import io
from pathlib import Path
import shlex
from typing import TYPE_CHECKING

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import safe_file_stat
from paleo_workbench.resources.preview_parsers.models import (
    MAX_TEXT_PREVIEW_BYTES,
    PreviewResult,
)

if TYPE_CHECKING:
    from paleo_workbench.resources.preview_settings import PreviewSettings


# Backward-compatible alias: several modules import ``safe_stat`` from here.
safe_stat = safe_file_stat


def parse_error_preview(resource: ResourceItem, message: str) -> PreviewResult:
    path = Path(resource.path)
    return PreviewResult(
        mode="message",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        message=message,
        warning=message,
    )


def read_preview_chunk(path: Path, limit_kib: int) -> tuple[bytes, bool]:
    limit = limit_kib * 1024
    stat = path.stat()
    with path.open("rb") as handle:
        data = handle.read(limit)
    return data, stat.st_size > limit


def decode_text_with_fallback(raw_bytes: bytes) -> str:
    """Decode bytes attempting UTF-8-sig, then GB18030/GBK, then replace (#1004)."""
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return raw_bytes.decode("gb18030")
    except UnicodeDecodeError:
        pass
    return raw_bytes.decode("utf-8-sig", errors="replace")


def text_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    path = Path(resource.path)
    preview_bytes, truncated = read_preview_chunk(path, settings.text_limit_kib)
    text = decode_text_with_fallback(preview_bytes)
    warning = f"仅显示前 {settings.text_limit_kib} KiB" if truncated else ""
    return PreviewResult(
        mode="text",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        text=text,
        warning=warning,
        truncated=truncated,
    )


def dat_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    """Read a bounded whitespace-delimited DAT list when structure is stable."""
    path = Path(resource.path)
    preview_bytes, byte_truncated = read_preview_chunk(path, settings.text_limit_kib)
    if byte_truncated and preview_bytes and not preview_bytes.endswith((b"\n", b"\r")):
        last_break = max(preview_bytes.rfind(b"\n"), preview_bytes.rfind(b"\r"))
        preview_bytes = preview_bytes[: last_break + 1] if last_break >= 0 else b""
    preview_text = preview_bytes.decode("utf-8-sig", errors="replace")
    header_candidates: list[tuple[str, ...]] = []
    data_rows: list[tuple[str, ...]] = []

    for raw_line in preview_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        is_comment = line.startswith("#")
        token_source = line.lstrip("#").strip() if is_comment else line
        try:
            tokens = tuple(shlex.split(token_source))
        except ValueError:
            return text_preview(resource, settings)
        if not tokens:
            continue
        if is_comment:
            first = tokens[0].casefold().rstrip(":")
            marker = " ".join(tokens).casefold()
            if first not in {"field", "type"} and "file from smi" not in marker:
                header_candidates.append(tokens)
            continue
        data_rows.append(tokens)

    if len(data_rows) < 2:
        return text_preview(resource, settings)
    row_width = len(data_rows[0])
    if row_width < 2 or any(len(row) != row_width for row in data_rows):
        return text_preview(resource, settings)

    header = next(
        (candidate for candidate in reversed(header_candidates) if len(candidate) == row_width),
        tuple(f"列 {index + 1}" for index in range(row_width)),
    )
    column_limit = settings.table_max_columns
    row_limit = settings.table_max_rows
    headers = tuple(header[:column_limit])
    rows = tuple(tuple(value for value in row[:column_limit]) for row in data_rows[:row_limit])
    truncated = (
        byte_truncated
        or len(data_rows) > row_limit
        or row_width > column_limit
    )
    return PreviewResult(
        mode="table",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        table_headers=headers,
        table_rows=rows,
        warning="数据列表已按预览上限截断" if truncated else "",
        truncated=truncated,
    )


def table_preview(resource: ResourceItem, delimiter: str, settings: PreviewSettings) -> PreviewResult:
    path = Path(resource.path)
    preview_bytes, truncated = read_preview_chunk(path, settings.text_limit_kib)
    # utf-8-sig strips a leading BOM so it cannot leak into the first header
    # cell (Excel's "CSV UTF-8" export writes one).
    preview_text = preview_bytes.decode("utf-8-sig", errors="replace")
    parsed_rows: list[tuple[str, ...]] = []

    # csv raises _csv.Error for a single field larger than its (131072-char
    # default) limit, which is below the preview byte budget. The chunk read
    # above is already bounded, so accept fields up to that bound; raise-only
    # so a larger pre-existing process-wide limit is never lowered.
    csv.field_size_limit(
        max(len(preview_bytes), MAX_TEXT_PREVIEW_BYTES, csv.field_size_limit())
    )

    try:
        with io.StringIO(preview_text, newline="") as buffer:
            reader = csv.reader(buffer, delimiter=delimiter)
            for row_index, row in enumerate(reader):
                if row_index > settings.table_max_rows:
                    truncated = True
                    break

                if len(row) > settings.table_max_columns:
                    truncated = True
                parsed_rows.append(tuple(row[: settings.table_max_columns]))
    except csv.Error as exc:
        return parse_error_preview(resource, f"表格解析失败: {exc.__class__.__name__}")

    headers = parsed_rows[0] if parsed_rows else ()
    body = tuple(parsed_rows[1:]) if parsed_rows else ()
    warning = "表格预览已按行列上限截断" if truncated else ""
    return PreviewResult(
        mode="table",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        table_headers=headers,
        table_rows=body,
        warning=warning,
        truncated=truncated,
    )


def excel_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    path = Path(resource.path)
    try:
        import pandas as pd

        workbook = pd.ExcelFile(path)
        sheets = tuple(str(sheet) for sheet in workbook.sheet_names)
        if not sheets:
            return parse_error_preview(resource, "Excel 文件没有可预览的工作表")
        frame = pd.read_excel(
            workbook,
            sheet_name=sheets[0],
            nrows=settings.table_max_rows + 1,
        )
    except Exception as exc:
        return parse_error_preview(resource, f"Excel 预览失败: {exc.__class__.__name__}")

    headers, rows, truncated = _dataframe_rows(frame, settings)
    warning = "表格预览已按行上限截断" if truncated else ""
    return PreviewResult(
        mode="table",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        table_headers=headers,
        table_rows=rows,
        sheets=sheets,
        warning=warning,
        truncated=truncated,
    )


def _dataframe_rows(
    frame,
    settings: PreviewSettings,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], bool]:
    truncated = len(frame.index) > settings.table_max_rows
    preview = frame.head(settings.table_max_rows)
    headers = tuple(
        str(column)
        for column in preview.columns[: settings.table_max_columns]
    )
    rows = []
    for _, row in preview.iloc[:, : settings.table_max_columns].iterrows():
        rows.append(tuple("" if frame_value != frame_value else str(frame_value) for frame_value in row))
    if len(frame.columns) > settings.table_max_columns:
        truncated = True
    return headers, tuple(rows), truncated
