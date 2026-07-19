from __future__ import annotations

import csv
import copy
import html
import io
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_settings import PreviewSettings

try:
    import segyio
except ImportError:  # pragma: no cover
    segyio = None

MAX_TEXT_PREVIEW_BYTES = 256 * 1024
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 40

PreviewMode = Literal[
    "empty",
    "geoviz",
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
    "web_document",
]

TEXT_FORMATS = {"txt", "text", "log", "dat", "xml"}
TABLE_FORMATS = {"csv", "tsv"}
EXCEL_FORMATS = {"xlsx", "xls"}
IMAGE_FORMATS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}
PDF_FORMATS = {"pdf"}
LAS_FORMATS = {"las"}
SEGY_FORMATS = {"sgy", "segy"}
MARKDOWN_FORMATS = {"md", "markdown", "htm", "html"}
HTML_FORMATS = {"htm", "html"}
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
    engine_preview: object | None = None
    estimated_bytes: int = 0
    visualization_available: bool = False
    # Transient build failures must be retried, never retained in memory/disk.
    cacheable: bool = True
    retryable: bool = False
    data_headers: tuple[str, ...] = field(default_factory=tuple)
    data_rows: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    seismic_volume: np.ndarray | None = None


class PreviewProvider:
    def __init__(self, settings: PreviewSettings | None = None) -> None:
        self.settings = settings or PreviewSettings.defaults()

    def with_settings(self, settings: PreviewSettings) -> "PreviewProvider":
        """Return a request-local provider snapshot without copying its engine."""
        configured = copy.copy(self)
        configured.settings = settings
        return configured

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

    def preview_summary(
        self,
        asset: ResourceItem | ExportArtifact | None,
    ) -> PreviewResult:
        """Build the lightweight reader payload for an asset."""
        return self.preview(asset)

    def preview_visualization(
        self,
        asset: ResourceItem | ExportArtifact | None,
    ) -> PreviewResult:
        """Return a stable result when no professional backend is available."""
        if asset is None:
            return self.preview(None)
        if isinstance(asset, ResourceItem):
            title = asset.name
            path = asset.path
            fmt = asset.format
            status = asset.status
            type_label = asset.type
        else:
            title = Path(asset.output_path).name or asset.output_path
            path = asset.output_path
            fmt = asset.format
            status = "generated"
            type_label = "成果"
        return PreviewResult(
            mode="message",
            title=title,
            path=path,
            format=fmt,
            status=status,
            type_label=type_label,
            message="此数据不支持可视化预览",
        )

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

        if fmt == "pptx":
            from paleo_workbench.ui.pages.fallback_preview import pptx_preview

            return pptx_preview(asset)

        if fmt == "dfb":
            from paleo_workbench.ui.pages.fallback_preview import dfb_preview

            return dfb_preview(asset)

        if fmt == "zip":
            from paleo_workbench.ui.pages.fallback_preview import zip_preview

            return zip_preview(asset, max_rows=self.settings.table_max_rows)

        if fmt == "wlp":
            from paleo_workbench.ui.pages.fallback_preview import wlp_preview

            return wlp_preview(asset)

        # GeoTIFF must be checked BEFORE the generic image branch: tif/tiff is
        # in both GEOTIFF_FORMATS and IMAGE_FORMATS. GeoTIFF takes precedence;
        # a non-raster tiff fails rasterio and falls back to image mode below.
        if fmt in GEOTIFF_FORMATS:
            return self._geotiff_preview(asset)

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

        if fmt in HTML_FORMATS:
            # Use lightweight QTextBrowser (rich_text) instead of QWebEngineView.
            # Read at most MAX_TEXT_PREVIEW_BYTES to avoid blocking on huge files.
            preview_bytes, truncated = self._read_preview_chunk(path)
            raw_html = preview_bytes.decode("utf-8", errors="replace")
            warning = (
                f"仅显示前 {self.settings.text_limit_kib} KiB" if truncated else ""
            )
            return PreviewResult(
                mode="rich_text",
                title=title,
                path=asset.path,
                revision=revision,
                format=asset.format,
                status=asset.status,
                type_label=asset.type,
                rich_html=raw_html,
                warning=warning,
                truncated=truncated,
            )

        if fmt in MARKDOWN_FORMATS:
            return self._markdown_rich_preview(asset)

        if fmt in JSON_FORMATS:
            return self._json_preview(asset)

        if fmt in AUDIO_FORMATS:
            return self._audio_preview(asset)

        if fmt == "xml":
            from paleo_workbench.ui.pages.fallback_preview import spreadsheetml_preview

            spreadsheet = spreadsheetml_preview(
                asset,
                max_text_bytes=self.settings.text_limit_kib * 1024,
                max_rows=self.settings.table_max_rows,
                max_columns=self.settings.table_max_columns,
            )
            if spreadsheet is not None:
                return spreadsheet

        if fmt == "dat":
            return self._dat_preview(asset)

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

    def _geotiff_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        revision = self._resource_revision_token(resource)
        try:
            import rasterio
        except ImportError:
            return self._image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
        try:
            with rasterio.open(str(path)) as dataset:
                crs = str(dataset.crs or "未知")
                bounds = dataset.bounds
                meta = (
                    ("CRS", crs),
                    (
                        "范围",
                        f"{bounds.left:.4f}, {bounds.bottom:.4f}, {bounds.right:.4f}, {bounds.top:.4f}",
                    ),
                    ("尺寸", f"{dataset.width} × {dataset.height} × {dataset.count}"),
                    ("数据类型", str(dataset.dtypes[0]) if dataset.dtypes else "未知"),
                    ("Nodata", str(dataset.nodata) if dataset.nodata is not None else "无"),
                )
                # Read a decimated overview bounded by the configured long side.
                target_px = self.settings.geotiff_thumbnail_px
                long_side = max(dataset.width, dataset.height)
                decim = max(1, (long_side + target_px - 1) // target_px)
                overviews = dataset.overviews(1)
                if decim > 1 and overviews:
                    suitable_overview = next(
                        (value for value in overviews if value >= decim),
                        None,
                    )
                    if suitable_overview is not None:
                        decim = suitable_overview
                thumbnail = dataset.read(
                    1,
                    out_shape=(
                        1,
                        max(1, dataset.height // decim),
                        max(1, dataset.width // decim),
                    ),
                )
        except Exception:
            return self._image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
        # Encode the thumbnail as PNG bytes off-thread (Pillow). PIL may be
        # unavailable or reject the array dtype; both degrade to image mode.
        try:
            from PIL import Image

            buf = io.BytesIO()
            Image.fromarray(thumbnail).save(buf, format="PNG")
            image_bytes = buf.getvalue()
        except Exception:
            return self._image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
        return PreviewResult(
            mode="geotiff",
            title=resource.name,
            path=resource.path,
            revision=revision,
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            geo_metadata=meta,
            image_bytes=image_bytes,
        )

    def _image_fallback(
        self, resource: ResourceItem, revision, warning: str
    ) -> PreviewResult:
        path = Path(resource.path)
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        return PreviewResult(
            mode="image",
            title=resource.name,
            path=resource.path,
            revision=revision,
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            image_bytes=data,
            warning=warning,
        )

    def _text_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        preview_bytes, truncated = self._read_preview_chunk(path)
        text = preview_bytes.decode("utf-8", errors="replace")
        warning = f"仅显示前 {self.settings.text_limit_kib} KiB" if truncated else ""
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

    def _dat_preview(self, resource: ResourceItem) -> PreviewResult:
        """Read a bounded whitespace-delimited DAT list when structure is stable."""
        path = Path(resource.path)
        preview_bytes, byte_truncated = self._read_preview_chunk(path)
        if byte_truncated and preview_bytes and not preview_bytes.endswith((b"\n", b"\r")):
            # The byte budget may stop in the middle of a field or between
            # fields.  Parse only complete logical records; the text fallback
            # can still show the original bounded payload when structure is
            # genuinely irregular.
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
                return self._text_preview(resource)
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
            return self._text_preview(resource)
        row_width = len(data_rows[0])
        if row_width < 2 or any(len(row) != row_width for row in data_rows):
            return self._text_preview(resource)

        header = next(
            (candidate for candidate in reversed(header_candidates) if len(candidate) == row_width),
            tuple(f"列 {index + 1}" for index in range(row_width)),
        )
        column_limit = self.settings.table_max_columns
        row_limit = self.settings.table_max_rows
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
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            table_headers=headers,
            table_rows=rows,
            warning="数据列表已按预览上限截断" if truncated else "",
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
                if row_index > self.settings.table_max_rows:
                    truncated = True
                    break

                if len(row) > self.settings.table_max_columns:
                    truncated = True
                parsed_rows.append(tuple(row[: self.settings.table_max_columns]))

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
            frame = pd.read_excel(
                workbook,
                sheet_name=sheets[0],
                nrows=self.settings.table_max_rows + 1,
            )
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
            # Professional LAS inspection belongs to geo-viz-engine.  This
            # pass streams metadata/rows without retaining the sample matrix;
            # bounded curve data is loaded only by explicit visualization.
            from geoviz import inspect_las_file

            header = inspect_las_file(str(path))
        except ValueError as exc:
            if str(exc) == "LAS contains no curve headers":
                return PreviewResult(
                    mode="well_log",
                    title=resource.name,
                    path=resource.path,
                    revision=self._safe_stat(path),
                    format=resource.format,
                    status=resource.status,
                    type_label=resource.type,
                    summary_rows=(
                        ("井名", path.stem),
                        ("曲线数", "0"),
                        ("采样点", "0"),
                    ),
                    table_headers=("曲线", "单位", "描述"),
                    warning="LAS 文件缺少曲线定义",
                )
            return self._parse_error_preview(resource, "LAS 预览失败: ValueError")
        except Exception as exc:
            return self._parse_error_preview(resource, f"LAS 预览失败: {exc.__class__.__name__}")

        curves = header.curves
        rows = tuple(
            (
                str(curve.mnemonic or ""),
                str(curve.unit or ""),
                str(curve.description or ""),
            )
            for curve in curves[: self.settings.table_max_rows]
        )
        well_name = header.well_name or Path(resource.path).stem
        summary_rows = (
            ("井名", str(well_name)),
            ("曲线数", str(len(curves))),
            ("采样点", str(header.row_count)),
        )
        truncated = len(curves) > self.settings.table_max_rows

        # Fetch actual data preview rows using lasio
        data_headers = ()
        data_rows = ()
        try:
            import lasio
            import numpy as np
            las = lasio.read(str(path))
            data_headers = tuple(c.mnemonic for c in las.curves)
            limit = min(len(las.data), 100)
            rows_list = []
            for i in range(limit):
                row_vals = []
                for val in las.data[i]:
                    if np.isnan(val):
                        row_vals.append("NaN")
                    else:
                        row_vals.append(f"{val:.4f}".rstrip('0').rstrip('.'))
                rows_list.append(tuple(row_vals))
            data_rows = tuple(rows_list)
        except Exception:
            pass

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
            data_headers=data_headers,
            data_rows=data_rows,
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
                _samples = getattr(cube, "samples", None)
                sample_count = len(_samples) if _samples is not None else 0
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

        volume = None
        try:
            from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path
            volume, load_warning = load_seismic_volume_from_path(str(path))
        except Exception:
            pass

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
            seismic_volume=volume,
        )

    def _markdown_rich_preview(self, resource: ResourceItem) -> PreviewResult:
        """Markdown -> HTML -> QTextBrowser (rich_text mode, no WebEngine)."""
        path = Path(resource.path)
        preview_bytes, truncated = self._read_preview_chunk(path)
        markdown = preview_bytes.decode("utf-8", errors="replace")
        warning = f"仅显示前 {self.settings.text_limit_kib} KiB" if truncated else ""
        return PreviewResult(
            mode="rich_text",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            rich_html=self._markdown_to_html(markdown),
            warning=warning,
            truncated=truncated,
        )

    @staticmethod
    def _markdown_to_html(markdown: str) -> str:
        rendered: list[str] = []
        paragraph: list[str] = []
        list_items: list[str] = []
        list_tag = ""
        code_lines: list[str] = []
        in_code_block = False

        def flush_paragraph() -> None:
            if paragraph:
                rendered.append(f"<p>{' '.join(paragraph)}</p>")
                paragraph.clear()

        def flush_list() -> None:
            nonlocal list_tag
            if list_items:
                rendered.append(f"<{list_tag}>{''.join(list_items)}</{list_tag}>")
                list_items.clear()
            list_tag = ""

        for line in markdown.splitlines():
            if line.startswith("```"):
                flush_paragraph()
                flush_list()
                if in_code_block:
                    code = "\n".join(code_lines)
                    rendered.append(f"<pre><code>{code}</code></pre>")
                    code_lines.clear()
                in_code_block = not in_code_block
                continue

            escaped = html.escape(line)
            if in_code_block:
                code_lines.append(escaped)
                continue

            if not line.strip():
                flush_paragraph()
                flush_list()
                continue

            heading = re.match(r"^(#{1,6})\s+(.*)$", line)
            if heading:
                flush_paragraph()
                flush_list()
                level = len(heading.group(1))
                rendered.append(f"<h{level}>{html.escape(heading.group(2))}</h{level}>")
                continue

            unordered = re.match(r"^[-*]\s+(.*)$", line)
            ordered = re.match(r"^\d+\.\s+(.*)$", line)
            if unordered or ordered:
                next_list_tag = "ul" if unordered else "ol"
                if list_tag and list_tag != next_list_tag:
                    flush_list()
                flush_paragraph()
                list_tag = next_list_tag
                item = unordered.group(1) if unordered else ordered.group(1)
                list_items.append(f"<li>{html.escape(item)}</li>")
                continue

            flush_list()
            paragraph.append(escaped)

        if in_code_block:
            code = "\n".join(code_lines)
            rendered.append(f"<pre><code>{code}</code></pre>")
        flush_paragraph()
        flush_list()
        return "\n".join(rendered)

    def _dataframe_rows(
        self,
        frame,
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], bool]:
        truncated = len(frame.index) > self.settings.table_max_rows
        preview = frame.head(self.settings.table_max_rows)
        headers = tuple(
            str(column)
            for column in preview.columns[: self.settings.table_max_columns]
        )
        rows = []
        for _, row in preview.iloc[:, : self.settings.table_max_columns].iterrows():
            rows.append(tuple("" if frame_value != frame_value else str(frame_value) for frame_value in row))
        if len(frame.columns) > self.settings.table_max_columns:
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
        limit = self.settings.text_limit_kib * 1024
        stat = path.stat()
        with path.open("rb") as handle:
            data = handle.read(limit)
        return data, stat.st_size > limit

    def _json_preview(self, resource: ResourceItem) -> PreviewResult:
        import json as json_lib

        path = Path(resource.path)
        limit = self.settings.json_limit_mib * 1024 * 1024
        try:
            size = path.stat().st_size
        except OSError:
            return self._parse_error_preview(resource, "文件不存在")
        if size > limit:
            return self._parse_error_preview(
                resource,
                f"JSON 文件超过预览设置上限 {self.settings.json_limit_mib} MiB，"
                "请在预览设置中提高上限",
            )
        try:
            with path.open("rb") as handle:
                raw_bytes = handle.read(limit + 1)
        except OSError:
            return self._parse_error_preview(resource, "文件不存在")
        raw = raw_bytes.decode("utf-8", errors="replace")
        try:
            payload = json_lib.loads(raw)
        except (json_lib.JSONDecodeError, ValueError) as exc:
            return self._parse_error_preview(
                resource, f"JSON 解析失败: {exc.__class__.__name__}"
            )
        return PreviewResult(
            mode="json_tree",
            title=resource.name,
            path=resource.path,
            revision=self._resource_revision_token(resource),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            json_payload=payload,
            json_truncated=False,
        )

    def _audio_preview(self, resource: ResourceItem) -> PreviewResult:
        # No off-thread decode: QMediaPlayer is UI-thread-only. The provider just
        # hands the file path to the widget, which sets the media source on the UI
        # thread in set_media_path.
        return PreviewResult(
            mode="media",
            title=resource.name,
            path=resource.path,
            revision=self._resource_revision_token(resource),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            media_path=resource.path,
        )
