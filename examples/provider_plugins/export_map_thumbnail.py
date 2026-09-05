"""Example capability provider (Harness 2.0, H7): render/export.

``export.map_thumbnail`` renders a real :class:`~paleo_workbench.mapping.layers.MapDocument`
through the production :class:`~paleo_workbench.mapping.map_render_backend.FallbackMapRenderBackend`
(the documented snapshot-in/frame-out seam) to a workspace-contained PNG,
and demonstrates the V2 ``verify`` hook by checking the emitted file is a
real non-trivial PNG.

Third-party render/export providers follow exactly this shape: typed
document input, containment-checked output (``resolve_contained_output``,
#1177), catalog registration when a run is bound, honest verification.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paleo_workbench.providers.base import ProviderContext
from paleo_workbench.providers.contracts import (
    ProviderDescriptor,
    ProviderFamily,
    ResourceProfile,
)
from paleo_workbench.providers.errors import ProviderRejectedInputError
from paleo_workbench.providers.paths import resolve_contained_output
from paleo_workbench.providers.refs import ArtifactRef, PathRef, ProviderResult

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class MapThumbnailProvider:
    """EXPORTER family: MapDocument → contained PNG thumbnail."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="export.map_thumbnail",
            family=ProviderFamily.EXPORTER,
            version="1.0.0",
            build_identity="examples/provider-plugins@2026-09-06",
            display_name="图件缩略图导出（示例）",
            description=(
                "Render a MapDocument through the production fallback render "
                "backend to a workspace-contained PNG thumbnail; verifies the "
                "artifact is a real PNG after render."
            ),
            capabilities=("export", "thumbnail"),
            input_types=("MapDocumentRef", "MapDocument"),
            output_types=("PathRef",),
            parameters_schema={
                "type": "object",
                "properties": {
                    "output_path": {"type": "string", "description": "PNG 输出路径（工作区内相对路径）"},
                    "width": {"type": "integer", "minimum": 64, "maximum": 4096},
                    "height": {"type": "integer", "minimum": 64, "maximum": 4096},
                },
                "required": ["output_path"],
                "additionalProperties": False,
            },
            resource_profile=ResourceProfile(
                estimated_cpu_cores=1.0,
                estimated_ram_bytes=256 * 1024**2,
                io_weight=1.0,
                category="export",
            ),
            threading_model="worker_thread",
            deterministic=True,
        )

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: ProviderContext,
    ) -> ProviderResult:
        document = inputs.get("document")
        if document is None:
            ref = inputs.get("map_document")
            if ref is not None:
                document = (context.extras or {}).get("map_documents", {}).get(
                    getattr(ref, "document_id", "")
                )
        from paleo_workbench.mapping.layers import MapDocument

        if not isinstance(document, MapDocument):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"input 'document' must be a MapDocument or MapDocumentRef, got "
                f"{type(document).__name__}",
            )
        out_path = resolve_contained_output(
            context,
            Path(str(parameters["output_path"])),
            provider_id=self.descriptor.provider_id,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend

        backend = FallbackMapRenderBackend()
        try:
            backend.initialize()
            backend.set_layer_snapshot(document.to_snapshot())
            extent = document.extent or (0.0, 0.0, 1.0, 1.0)
            backend.set_extent(tuple(float(v) for v in extent))
            backend.set_output_size(
                int(parameters.get("width", 640)), int(parameters.get("height", 480))
            )
            frame = backend.render_sync()
            from PySide6.QtGui import QImage

            image = QImage(
                frame.rgba, frame.width, frame.height, frame.stride, QImage.Format_RGBA8888
            )
            if not image.save(str(out_path)):
                raise ProviderRejectedInputError(
                    self.descriptor.provider_id, f"QImage could not write {out_path.name}"
                )
        finally:
            backend.shutdown()

        return ProviderResult(
            artifacts=[
                ArtifactRef(
                    name=out_path.name,
                    kind="file",
                    path=str(out_path),
                    metadata={
                        "width": int(parameters.get("width", 640)),
                        "height": int(parameters.get("height", 480)),
                    },
                )
            ],
            diagnostics={"bytes": out_path.stat().st_size if out_path.exists() else 0},
        )

    def verify(self, result: ProviderResult, context: ProviderContext) -> dict[str, Any]:
        """Fail-closed: the artifact must be a real, non-empty PNG."""
        for artifact in result.artifacts:
            if artifact.path is None:
                return {"verdict": "fail", "reasons": ["thumbnail artifact has no path"]}
            path = Path(artifact.path)
            if not path.exists() or path.stat().st_size < len(_PNG_MAGIC) + 8:
                return {"verdict": "fail", "reasons": [f"{path.name} is not a plausible PNG"]}
            with open(path, "rb") as fh:
                if fh.read(len(_PNG_MAGIC)) != _PNG_MAGIC:
                    return {"verdict": "fail", "reasons": [f"{path.name} lacks the PNG signature"]}
        if not result.artifacts:
            return {"verdict": "fail", "reasons": ["no artifact produced"]}
        return {"verdict": "pass", "reasons": []}
