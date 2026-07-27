from __future__ import annotations

from dataclasses import replace

from geoviz import (
    ErrorCode,
    GeoVizEngine,
    GeoVizError,
    PreparedPreview,
)

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.viz.preview_request import request_from_resource


class LocalVisualizationProvider(PreviewProvider):
    def __init__(self, engine: GeoVizEngine | None = None, settings=None) -> None:
        super().__init__(settings=settings)
        self.engine = engine or GeoVizEngine.default()

    def _build_preview(self, asset):
        if isinstance(asset, ResourceItem):
            if asset.format in {"sgy", "segy"} or asset.type == "seismic":
                return super()._build_preview(asset)
            request = request_from_resource(asset)
            if self.engine.supports(request):
                try:
                    prepared = self.engine.prepare(
                        request,
                        self.settings.to_geoviz_options(),
                    )
                    return self._engine_result(asset, prepared)
                except GeoVizError as error:
                    fallback = super()._build_preview(asset)
                    return replace(
                        fallback,
                        warning=self._merge_warning(fallback.warning, str(error)),
                    )
        return super()._build_preview(asset)

    def preview_summary(self, asset) -> PreviewResult:
        if asset is None:
            return PreviewProvider.preview(self, None)
        result = PreviewProvider._build_preview(self, asset)
        if not isinstance(asset, ResourceItem) or result.status == "missing":
            return result
        if asset.format in {"sgy", "segy"} or asset.type == "seismic":
            return result
        request = request_from_resource(asset)
        try:
            available = self.engine.supports(request)
        except GeoVizError as error:
            return replace(
                result,
                warning=self._merge_warning(result.warning, str(error)),
            )
        return replace(result, visualization_available=available)

    def preview_visualization(self, asset) -> PreviewResult:
        if not isinstance(asset, ResourceItem):
            return super().preview_visualization(asset)
        if asset.format in {"sgy", "segy"} or asset.type == "seismic":
            return super().preview_visualization(asset)
        request = request_from_resource(asset)
        try:
            prepared = self.engine.prepare(
                request,
                self.settings.to_geoviz_options(),
            )
        except GeoVizError as error:
            fallback = super().preview_visualization(asset)
            if error.code is ErrorCode.UNSUPPORTED:
                return fallback
            return replace(
                fallback,
                message=str(error),
                warning=str(error),
                cacheable=False,
                retryable=error.code in {ErrorCode.IO_ERROR, ErrorCode.RENDER_ERROR},
            )
        return self._engine_result(asset, prepared)

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
            visualization_available=True,
        )

    @staticmethod
    def _merge_warning(existing: str, engine_message: str) -> str:
        return " · ".join(part for part in (existing, engine_message) if part)
