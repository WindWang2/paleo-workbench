from __future__ import annotations

from dataclasses import replace

from geoviz import (
    GeoVizEngine,
    GeoVizError,
    PreparedPreview,
    PreviewOptions,
    PreviewRequest,
)

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult


def request_from_resource(resource: ResourceItem) -> PreviewRequest:
    return PreviewRequest(
        resource_id=resource.id,
        path=resource.path,
        semantic_type=resource.type,
        format=resource.format,
        label=resource.name,
    )


class LocalVisualizationProvider(PreviewProvider):
    def __init__(self, engine: GeoVizEngine | None = None) -> None:
        super().__init__()
        self.engine = engine or GeoVizEngine.default()

    def _build_preview(self, asset):
        if isinstance(asset, ResourceItem):
            request = request_from_resource(asset)
            if self.engine.supports(request):
                try:
                    prepared = self.engine.prepare(request, PreviewOptions.local())
                    return self._engine_result(asset, prepared)
                except GeoVizError as error:
                    fallback = super()._build_preview(asset)
                    return replace(
                        fallback,
                        warning=self._merge_warning(fallback.warning, str(error)),
                    )
        return super()._build_preview(asset)

    @staticmethod
    def _engine_result(asset: ResourceItem, prepared: PreparedPreview) -> PreviewResult:
        return PreviewResult(
            mode="geoviz",
            title=asset.name,
            path=asset.path,
            format=asset.format,
            status=asset.status,
            type_label=asset.type,
            warning=prepared.warning,
            summary_rows=prepared.summary_rows,
            engine_preview=prepared,
            estimated_bytes=prepared.estimated_bytes,
        )

    @staticmethod
    def _merge_warning(existing: str, engine_message: str) -> str:
        return " · ".join(part for part in (existing, engine_message) if part)
