from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.resources.preview_parsers.document_parsers import (
    artifact_preview,
    audio_preview,
    geotiff_preview,
    json_preview,
    markdown_rich_preview,
    read_preview_chunk,
    resource_revision_token,
)
from paleo_workbench.resources.preview_parsers.models import (
    AUDIO_FORMATS,
    EXCEL_FORMATS,
    GEOTIFF_FORMATS,
    HTML_FORMATS,
    IMAGE_FORMATS,
    JSON_FORMATS,
    LAS_FORMATS,
    MARKDOWN_FORMATS,
    PDF_FORMATS,
    SEGY_FORMATS,
    TABLE_FORMATS,
    TEXT_FORMATS,
    PreviewResult,
)
from paleo_workbench.resources.preview_parsers.office_parsers import (
    dfb_preview,
    pptx_preview,
    spreadsheetml_preview,
    wlp_preview,
    zip_preview,
)
from paleo_workbench.resources.preview_parsers.seismic_parsers import segy_preview
from paleo_workbench.resources.preview_parsers.table_parsers import (
    dat_preview,
    excel_preview,
    safe_stat,
    table_preview,
    text_preview,
)
from paleo_workbench.resources.preview_parsers.well_log_parsers import las_preview, xml_well_log_preview

if TYPE_CHECKING:
    from paleo_workbench.ui.pages.preview_settings import PreviewSettings

PreviewParserCallable = Callable[[ResourceItem, "PreviewSettings"], PreviewResult]


class PreviewRegistry:
    def __init__(self) -> None:
        self._format_parsers: dict[str, PreviewParserCallable] = {}

    def register_format(self, fmt: str, parser: PreviewParserCallable) -> None:
        self._format_parsers[fmt.lower()] = parser

    def build_preview(
        self,
        asset: ResourceItem | ExportArtifact,
        settings: PreviewSettings,
        safe_stat_fn: Callable[[Path], tuple[int, int] | None] = safe_stat,
    ) -> PreviewResult:
        if isinstance(asset, ExportArtifact):
            return artifact_preview(asset)

        path = Path(asset.path)
        revision = resource_revision_token(asset, safe_stat_fn=safe_stat_fn)
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
            return pptx_preview(asset)

        if fmt == "dfb":
            return dfb_preview(asset)

        if fmt == "zip":
            return zip_preview(asset, max_rows=settings.table_max_rows)

        if fmt == "wlp":
            return wlp_preview(asset)

        # GeoTIFF takes precedence before generic image formats
        if fmt in GEOTIFF_FORMATS:
            return geotiff_preview(asset, settings)

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
            return table_preview(asset, delimiter, settings)

        if fmt in EXCEL_FORMATS:
            return excel_preview(asset, settings)

        if fmt in LAS_FORMATS:
            return las_preview(asset, settings)

        if asset.type == "well_log":
            if fmt == "xml":
                xml_log = xml_well_log_preview(asset, settings)
                if xml_log is not None:
                    return xml_log
            return las_preview(asset, settings)

        if fmt in SEGY_FORMATS or asset.type == "seismic":
            return segy_preview(asset, settings)

        if fmt in HTML_FORMATS:
            preview_bytes, truncated = read_preview_chunk(path, settings.text_limit_kib)
            raw_html = preview_bytes.decode("utf-8", errors="replace")
            warning = f"仅显示前 {settings.text_limit_kib} KiB" if truncated else ""
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
            return markdown_rich_preview(asset, settings)

        if fmt in JSON_FORMATS:
            return json_preview(asset, settings)

        if fmt in AUDIO_FORMATS:
            return audio_preview(asset)

        if fmt == "xml":
            xml_log = xml_well_log_preview(asset, settings)
            if xml_log is not None:
                return xml_log

            spreadsheet = spreadsheetml_preview(
                asset,
                max_text_bytes=settings.text_limit_kib * 1024,
                max_rows=settings.table_max_rows,
                max_columns=settings.table_max_columns,
            )
            if spreadsheet is not None:
                return spreadsheet

        if fmt == "dat":
            return dat_preview(asset, settings)

        if fmt in TEXT_FORMATS:
            return text_preview(asset, settings)

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


_DEFAULT_REGISTRY = PreviewRegistry()


def default_registry() -> PreviewRegistry:
    return _DEFAULT_REGISTRY
