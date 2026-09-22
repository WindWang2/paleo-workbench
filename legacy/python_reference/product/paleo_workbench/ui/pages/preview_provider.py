from __future__ import annotations

import copy
from pathlib import Path

try:
    import segyio
except ImportError:  # pragma: no cover
    segyio = None

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.resources.preview_parsers import (
    AUDIO_FORMATS,
    EXCEL_FORMATS,
    GEOTIFF_FORMATS,
    HTML_FORMATS,
    IMAGE_FORMATS,
    JSON_ARRAY_COLLAPSE_THRESHOLD,
    JSON_FORMATS,
    LAS_FORMATS,
    MAX_JSON_PARSE_BYTES,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_TEXT_PREVIEW_BYTES,
    MARKDOWN_FORMATS,
    PDF_FORMATS,
    SEGY_FORMATS,
    TABLE_FORMATS,
    TEXT_FORMATS,
    PreviewMode,
    PreviewResult,
)
from paleo_workbench.resources.preview_parsers.registry import default_registry
from paleo_workbench.ui.pages.preview_settings import PreviewSettings

__all__ = [
    "AUDIO_FORMATS",
    "EXCEL_FORMATS",
    "GEOTIFF_FORMATS",
    "HTML_FORMATS",
    "IMAGE_FORMATS",
    "JSON_ARRAY_COLLAPSE_THRESHOLD",
    "JSON_FORMATS",
    "LAS_FORMATS",
    "MAX_JSON_PARSE_BYTES",
    "MAX_TABLE_COLUMNS",
    "MAX_TABLE_ROWS",
    "MAX_TEXT_PREVIEW_BYTES",
    "MARKDOWN_FORMATS",
    "PDF_FORMATS",
    "SEGY_FORMATS",
    "TABLE_FORMATS",
    "TEXT_FORMATS",
    "PreviewMode",
    "PreviewProvider",
    "PreviewResult",
]


class PreviewProvider:
    def __init__(self, settings: PreviewSettings | None = None) -> None:
        self.settings = settings or PreviewSettings.defaults()

    def with_settings(self, settings: PreviewSettings) -> "PreviewProvider":
        """Return a request-local provider snapshot without copying its engine."""
        configured = copy.copy(self)
        configured.settings = settings
        return configured

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

    def _build_preview(self, asset: ResourceItem | ExportArtifact) -> PreviewResult:
        return default_registry().build_preview(asset, self.settings)
