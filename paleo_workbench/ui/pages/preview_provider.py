from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from paleo_workbench.project.models import ExportArtifact, ResourceItem

try:
    import segyio
except ImportError:  # pragma: no cover
    segyio = None

MAX_TEXT_PREVIEW_BYTES = 256 * 1024
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 40

PreviewMode = Literal[
    "empty",
    "pdf",
    "image",
    "text",
    "table",
    "well_log",
    "seismic",
    "message",
    "rich_text",
    "json_tree",
    "geotiff",
    "media",
]

TEXT_FORMATS = {"txt", "text", "log", "dat", "json", "xml"}
TABLE_FORMATS = {"csv", "tsv"}
EXCEL_FORMATS = {"xlsx", "xls"}
IMAGE_FORMATS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}
PDF_FORMATS = {"pdf"}
LAS_FORMATS = {"las"}
SEGY_FORMATS = {"sgy", "segy"}
MARKDOWN_FORMATS = {"md", "markdown", "htm", "html"}
JSON_FORMATS = {"json", "geojson"}
GEOTIFF_FORMATS = {"tif", "tiff"}
AUDIO_FORMATS = {"wav", "mp3", "flac", "ogg", "m4a"}
MAX_JSON_PARSE_BYTES = 5 * 1024 * 1024
JSON_ARRAY_COLLAPSE_THRESHOLD = 100


@dataclass(frozen=True)
class PreviewResult:
    mode: PreviewMode
    title: str
    path: str = ""
    revision: tuple[object, ...] | None = None
    format: str = ""
    status: str = ""
    type_label: str = ""
    message: str = ""
    warning: str = ""
    text: str = ""
    table_headers: tuple[str, ...] = field(default_factory=tuple)
    table_rows: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    summary_rows: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    sheets: tuple[str, ...] = field(default_factory=tuple)
    truncated: bool = False
    # Media file bytes loaded off the UI thread; decoded/loaded on the UI.
    image_bytes: bytes = b""
    pdf_bytes: bytes = b""
    rich_html: str = ""
    json_payload: object | None = None
    json_truncated: bool = False
    geo_metadata: tuple[tuple[str, str], ...] = ()
    media_path: str = ""


class PreviewProvider:
    def clear(self) -> None:
        """No-op: caching lives on the UI-thread PreviewCache (Task 4)."""

    def preview(self, asset: ResourceItem | ExportArtifact | None) -> PreviewResult:
        if asset is None:
            return PreviewResult(
                mode="empty",
                title="请选择数据项",
                message="从列表中选择一个数据、成果或文件",
            )

        # Pure build — safe for worker threads. LRU cache is owned by
        # PreviewRequestController on the UI thread.
        return self._build_preview(asset)

    def _resource_revision_token(self, asset: ResourceItem) -> tuple[object, ...]:
        path = Path(asset.path)
        return (
            "resource",
            asset.id,
            asset.path,
            asset.type,
            asset.format,
            asset.status,
            asset.checksum,
            self._safe_stat(path),
        )

    def _safe_stat(self, path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    def _build_preview(self, asset: ResourceItem | ExportArtifact) -> PreviewResult:
        if isinstance(asset, ExportArtifact):
            return self._artifact_preview(asset)

        path = Path(asset.path)
        revision = self._resource_revision_token(asset)
        fmt = asset.format.lower()
        title = asset.name

        if not path.exists():
            return PreviewResult(
                mode="message",
                title=title,
                path=asset.path,
                revision=revision,
                format=asset.format,
                status="missing",
                type_label=asset.type,
                message="文件不存在",
            )

        if fmt in PDF_FORMATS:
            return PreviewResult(
                mode="pdf",
                title=title,
                path=asset.path,
                revision=revision,
                format=asset.format,
                status=asset.status,
                type_label=asset.type,
            )

        if fmt in IMAGE_FORMATS or asset.type in {"image_reference", "reference_map"}:
            return PreviewResult(
                mode="image",
                title=title,
                path=asset.path,
                revision=revision,
                format=asset.format,
                status=asset.status,
                type_label=asset.type,
            )

        if fmt in TABLE_FORMATS:
            delimiter = "\t" if fmt == "tsv" else ","
            return self._table_preview(asset, delimiter=delimiter)

        if fmt in EXCEL_FORMATS:
            return self._excel_preview(asset)

        if fmt in LAS_FORMATS or asset.type == "well_log":
            return self._las_preview(asset)

        if fmt in SEGY_FORMATS or asset.type == "seismic":
            return self._segy_preview(asset)

        if fmt in MARKDOWN_FORMATS:
            return self._rich_text_preview(asset)

        if fmt in TEXT_FORMATS:
            return self._text_preview(asset)

        return PreviewResult(
            mode="message",
            title=title,
            path=asset.path,
            revision=revision,
            format=asset.format,
            status=asset.status,
            type_label=asset.type,
            message="此格式暂不支持内置阅读，可使用打开目录定位文件",
        )

    def _artifact_preview(self, artifact: ExportArtifact) -> PreviewResult:
        title = Path(artifact.output_path).name or artifact.output_path
        return PreviewResult(
            mode="message",
            title=title,
            path=artifact.output_path,
            revision=self._safe_stat(Path(artifact.output_path)),
            format=artifact.format,
            status="generated",
            type_label="成果",
            message=f"成果文件 · 关联对象 {artifact.linked_id}",
        )

    def _text_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        preview_bytes, truncated = self._read_preview_chunk(path)
        text = preview_bytes.decode("utf-8", errors="replace")
        warning = f"仅显示前 {MAX_TEXT_PREVIEW_BYTES // 1024} KiB" if truncated else ""
        return PreviewResult(
            mode="text",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            text=text,
            warning=warning,
            truncated=truncated,
        )

    def _table_preview(self, resource: ResourceItem, delimiter: str) -> PreviewResult:
        path = Path(resource.path)
        preview_bytes, truncated = self._read_preview_chunk(path)
        preview_text = preview_bytes.decode("utf-8", errors="replace")
        parsed_rows: list[tuple[str, ...]] = []

        with io.StringIO(preview_text, newline="") as buffer:
            reader = csv.reader(buffer, delimiter=delimiter)
            for row_index, row in enumerate(reader):
                if row_index > MAX_TABLE_ROWS:
                    truncated = True
                    break

                if len(row) > MAX_TABLE_COLUMNS:
                    truncated = True
                parsed_rows.append(tuple(row[:MAX_TABLE_COLUMNS]))

        headers = parsed_rows[0] if parsed_rows else ()
        body = tuple(parsed_rows[1:]) if parsed_rows else ()
        warning = "表格预览已按行列上限截断" if truncated else ""
        return PreviewResult(
            mode="table",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            table_headers=headers,
            table_rows=body,
            warning=warning,
            truncated=truncated,
        )

    def _excel_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        try:
            import pandas as pd

            workbook = pd.ExcelFile(path)
            sheets = tuple(str(sheet) for sheet in workbook.sheet_names)
            if not sheets:
                return self._parse_error_preview(resource, "Excel 文件没有可预览的工作表")
            frame = pd.read_excel(workbook, sheet_name=sheets[0], nrows=MAX_TABLE_ROWS + 1)
        except Exception as exc:
            return self._parse_error_preview(resource, f"Excel 预览失败: {exc.__class__.__name__}")

        headers, rows, truncated = self._dataframe_rows(frame)
        warning = "表格预览已按行上限截断" if truncated else ""
        return PreviewResult(
            mode="table",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            table_headers=headers,
            table_rows=rows,
            sheets=sheets,
            warning=warning,
            truncated=truncated,
        )

    def _las_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        try:
            import lasio

            las = lasio.read(path)
        except Exception as exc:
            return self._parse_error_preview(resource, f"LAS 预览失败: {exc.__class__.__name__}")

        curves = list(getattr(las, "curves", []))
        rows = tuple(
            (
                str(getattr(curve, "mnemonic", "") or ""),
                str(getattr(curve, "unit", "") or ""),
                str(getattr(curve, "descr", "") or ""),
            )
            for curve in curves[:MAX_TABLE_ROWS]
        )
        well_name = self._las_well_value(las, "WELL") or Path(resource.path).stem
        sample_count = str(self._las_sample_count(las))
        summary_rows = (
            ("井名", str(well_name)),
            ("曲线数", str(len(curves))),
            ("采样点", sample_count),
        )
        truncated = len(curves) > MAX_TABLE_ROWS
        return PreviewResult(
            mode="well_log",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            summary_rows=summary_rows,
            table_headers=("曲线", "单位", "描述"),
            table_rows=rows,
            warning="曲线列表已按行上限截断" if truncated else "",
            truncated=truncated,
        )

    def _segy_preview(self, resource: ResourceItem) -> PreviewResult:
        if segyio is None:
            return self._parse_error_preview(resource, "SEG-Y 预览依赖不可用")

        path = Path(resource.path)
        try:
            with segyio.open(str(path), "r", ignore_geometry=True) as cube:
                trace_count = int(getattr(cube, "tracecount", 0) or 0)
                sample_count = len(getattr(cube, "samples", ()) or ())
                interval = self._field_value(
                    getattr(cube, "bin", {}),
                    getattr(segyio.BinField, "Interval", None),
                )
                first_header = self._field_value(getattr(cube, "header", {}), 0) or {}
                inline = self._field_value(
                    first_header,
                    getattr(segyio.TraceField, "INLINE_3D", None),
                )
                crossline = self._field_value(
                    first_header,
                    getattr(segyio.TraceField, "CROSSLINE_3D", None),
                )
        except Exception as exc:
            return self._parse_error_preview(resource, f"SEG-Y 预览失败: {exc.__class__.__name__}")

        summary_rows = [
            ("道数", str(trace_count)),
            ("采样点", str(sample_count)),
        ]
        if interval is not None:
            summary_rows.append(("采样间隔", f"{interval} us"))
        table_rows = []
        if inline is not None:
            table_rows.append(("Inline", str(inline)))
        if crossline is not None:
            table_rows.append(("Crossline", str(crossline)))

        return PreviewResult(
            mode="seismic",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            summary_rows=tuple(summary_rows),
            table_headers=("字段", "值"),
            table_rows=tuple(table_rows),
        )

    def _rich_text_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return PreviewResult(
                mode="message",
                title=resource.name,
                path=resource.path,
                revision=self._resource_revision_token(resource),
                format=resource.format,
                status=resource.status,
                type_label=resource.type,
                message="文件不存在",
            )
        fmt = resource.format.lower()
        if fmt in {"htm", "html"}:
            html = raw
        else:
            import markdown as md_lib
            html = md_lib.markdown(raw, extensions=["extra", "codehilite"])
        return PreviewResult(
            mode="rich_text",
            title=resource.name,
            path=resource.path,
            revision=self._resource_revision_token(resource),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            rich_html=html,
        )

    def _dataframe_rows(
        self,
        frame,
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], bool]:
        truncated = len(frame.index) > MAX_TABLE_ROWS
        preview = frame.head(MAX_TABLE_ROWS)
        headers = tuple(str(column) for column in preview.columns[:MAX_TABLE_COLUMNS])
        rows = []
        for _, row in preview.iloc[:, :MAX_TABLE_COLUMNS].iterrows():
            rows.append(tuple("" if frame_value != frame_value else str(frame_value) for frame_value in row))
        if len(frame.columns) > MAX_TABLE_COLUMNS:
            truncated = True
        return headers, tuple(rows), truncated

    def _las_well_value(self, las, mnemonic: str) -> object:
        well = getattr(las, "well", None)
        if well is None:
            return ""
        item = getattr(well, mnemonic, None)
        return getattr(item, "value", item) if item is not None else ""

    def _las_sample_count(self, las) -> int:
        try:
            data_shape = getattr(getattr(las, "data", None), "shape", ())
        except Exception:
            return 0
        return int(data_shape[0]) if data_shape else 0

    def _field_value(self, container, key) -> object:
        if key is None or container is None:
            return None
        getter = getattr(container, "get", None)
        if callable(getter):
            try:
                return getter(key)
            except Exception:
                pass
        try:
            return container[key]
        except Exception:
            return None

    def _parse_error_preview(self, resource: ResourceItem, message: str) -> PreviewResult:
        path = Path(resource.path)
        return PreviewResult(
            mode="message",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            message=message,
            warning=message,
        )

    def _read_preview_chunk(self, path: Path) -> tuple[bytes, bool]:
        stat = path.stat()
        with path.open("rb") as handle:
            data = handle.read(MAX_TEXT_PREVIEW_BYTES)
        return data, stat.st_size > MAX_TEXT_PREVIEW_BYTES
