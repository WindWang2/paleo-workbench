"""Built-in visualization + exporter providers (P2-B).

- :class:`MapRenderBackendProvider` exposes the production render backends
  (QGIS primary / QPainter fallback, availability probed honestly through
  ``create_map_render_backend``) as VISUALIZATION capabilities.
- :class:`MapProductExportProvider` renders a :class:`MapDocument` snapshot
  to PNG/SVG/PDF through the same fallback interpreter the off-GUI export
  worker uses (``render_and_save_map_export``) — canvas/export parity — and
  registers the file as a catalog OUTPUT when a run is bound.
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
from paleo_workbench.providers.errors import ProviderExecutionError, ProviderRejectedInputError
from paleo_workbench.providers.paths import resolve_contained_output
from paleo_workbench.providers.refs import (
    ArtifactRef,
    MapDocumentRef,
    PathRef,
    ProviderResult,
)

_EXPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "output_path": {"type": "string", "description": "导出文件路径（.png/.svg/.pdf）"},
        "width": {"type": "integer", "minimum": 64, "maximum": 16384},
        "height": {"type": "integer", "minimum": 64, "maximum": 16384},
        "dpi": {"type": "number", "minimum": 36.0, "maximum": 1200.0},
    },
    "required": ["output_path"],
    "additionalProperties": False,
}


class MapRenderBackendProvider:
    """VISUALIZATION family: the probed production render backends."""

    def __init__(self, backend_name: str, available: bool):
        self._backend_name = backend_name
        self._available = available

    @property
    def descriptor(self) -> ProviderDescriptor:
        name = self._backend_name
        display = {"qgis": "QGIS 制图渲染后端", "fallback": "QPainter 兜底渲染后端"}.get(name, name)
        return ProviderDescriptor(
            provider_id=f"viz.map_render.{name}",
            family=ProviderFamily.VISUALIZATION,
            version="1.0.0",
            display_name=display,
            description=(
                "Production map render backend (snapshot-in/frame-out contract). "
                "Availability is probed at registration; unavailable backends stay "
                "registered-but-flagged instead of being hidden."
            ),
            capabilities=("map_render", name),
            input_types=("MapDocumentRef", "MapDocument"),
            output_types=("PathRef",),
            parameters_schema={
                "type": "object",
                "properties": {
                    "output_path": {"type": "string", "description": "PNG 输出路径"},
                    "width": {"type": "integer", "minimum": 16, "maximum": 8192},
                    "height": {"type": "integer", "minimum": 16, "maximum": 8192},
                },
                "required": ["output_path"],
                "additionalProperties": False,
            },
            resource_profile=ResourceProfile(
                estimated_cpu_cores=1.0,
                estimated_ram_bytes=256 * 1024**2,
                estimated_vram_bytes=64 * 1024**2 if name == "qgis" else 0,
                io_weight=0.5,
                category="interactive.render",
            ),
            threading_model="worker_thread",
        )

    @property
    def available(self) -> bool:
        return self._available

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: ProviderContext,
    ) -> ProviderResult:
        """Render a MapDocument snapshot to a PNG through THIS backend.

        Real execution, not metadata: a throwaway backend instance of this
        family renders the snapshot (the same contract the canvas uses);
        unavailable backends (probe failed) reject honestly.
        """
        document = inputs.get("document")
        if not self._available:
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"backend {self._backend_name!r} unavailable on this host (probe failed)",
            )
        from paleo_workbench.mapping.layers import MapDocument

        if not isinstance(document, MapDocument):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"input 'document' must be a MapDocument, got {type(document).__name__}",
            )
        output = parameters.get("output_path")
        if not output:
            raise ProviderRejectedInputError(
                self.descriptor.provider_id, "output_path parameter required"
            )
        from pathlib import Path

        out_path = Path(str(output))
        if out_path.suffix.lower() != ".png":
            raise ProviderRejectedInputError(
                self.descriptor.provider_id, "backend render outputs PNG (use export.map_product for svg/pdf)"
            )
        # #1177: containment before any mkdir/write — the destination must
        # stay inside the workspace the context provides.
        out_path = resolve_contained_output(context, out_path, provider_id=self.descriptor.provider_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend

        if self._backend_name == "qgis":
            from paleo_workbench.mapping.map_render_backend import (
                create_map_render_backend,
            )

            backend = create_map_render_backend(prefer_qgis=True)
        else:
            backend = FallbackMapRenderBackend()
        try:
            backend.initialize()
            backend.set_layer_snapshot(document.to_snapshot())
            extent = document.extent or (0.0, 0.0, 1.0, 1.0)
            backend.set_extent(tuple(float(v) for v in extent))
            backend.set_output_size(int(parameters.get("width", 1200)), int(parameters.get("height", 900)))
            frame = backend.render_sync()
            from PySide6.QtGui import QImage

            image = QImage(
                frame.rgba, frame.width, frame.height, frame.stride, QImage.Format_RGBA8888
            )
            image.save(str(out_path))
        finally:
            backend.shutdown()
        return ProviderResult(
            artifacts=[
                ArtifactRef(name=out_path.name, kind="file", path=str(out_path),
                            metadata={"backend": self._backend_name})
            ],
            diagnostics={"backend": self._backend_name, "bytes": out_path.stat().st_size},
        )


class MapProductExportProvider:
    """EXPORTER family: MapDocument → PNG/SVG/PDF on the production path."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="export.map_product",
            family=ProviderFamily.EXPORTER,
            version="1.0.0",
            display_name="图件产品导出 (PNG/SVG/PDF)",
            description=(
                "Render a MapDocument snapshot to an image/vector file via the "
                "off-GUI export path (same interpreter as the screen, canvas/export "
                "parity) and register it as a catalog OUTPUT when a run is bound."
            ),
            capabilities=("export", "map_product"),
            input_types=("MapDocumentRef", "MapDocument"),
            output_types=("DataVersionRef", "PathRef"),
            parameters_schema=_EXPORT_SCHEMA,
            resource_profile=ResourceProfile(
                estimated_cpu_cores=1.0,
                estimated_ram_bytes=512 * 1024**2,
                io_weight=2.0,
                category="export",
            ),
            threading_model="worker_thread",
        )

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: ProviderContext,
    ) -> ProviderResult:
        document = inputs.get("document")
        # The harness may pass the live MapDocument object (in-process) or a
        # MapDocumentRef resolved through context.extras["map_documents"].
        if isinstance(document, MapDocumentRef):
            document = (context.extras or {}).get("map_documents", {}).get(document.document_id)
        from paleo_workbench.mapping.layers import MapDocument

        if not isinstance(document, MapDocument):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"input 'document' must be a MapDocument or MapDocumentRef, got {type(document).__name__}",
            )
        output_path = Path(str(parameters["output_path"]))
        if output_path.suffix.lower() not in (".png", ".svg", ".pdf"):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"unsupported export format {output_path.suffix!r} (png/svg/pdf)",
            )
        # #1177: containment before any mkdir/write — the export destination
        # must stay inside the workspace the context provides (no absolute
        # escapes, no ../ traversal, no silent overwrite).
        output_path = resolve_contained_output(
            context, output_path, provider_id=self.descriptor.provider_id
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from paleo_workbench.ui.map_export_worker import (
                MapExportSpec,
                render_and_save_map_export,
            )
        except Exception as exc:
            raise ProviderRejectedInputError(
                self.descriptor.provider_id, f"export stack unavailable: {exc}"
            ) from exc

        snapshot = document.to_snapshot()
        extent = document.extent or (0.0, 0.0, 1.0, 1.0)
        width = int(parameters.get("width", 2400))
        height = int(parameters.get("height", 1800))
        dpi = float(parameters.get("dpi", 300.0))
        spec = MapExportSpec(
            snapshot=snapshot,
            extent=tuple(float(v) for v in extent),
            width=width,
            height=height,
            dpi=dpi,
            decorations={},
            path=str(output_path),
            prefer_native_renderer=False,
        )
        context.report_progress(0.2, "渲染图面")
        try:
            render_and_save_map_export(spec)
        except Exception as exc:
            raise ProviderExecutionError(self.descriptor.provider_id, exc) from exc
        context.report_progress(1.0, "导出完成")

        version = None
        catalog = context.catalog
        if catalog is not None and context.run_id:
            try:
                version = catalog.register_output(
                    run_id=context.run_id,
                    name=output_path.stem,
                    path=str(output_path),
                    kind="map_product",
                    format=output_path.suffix.lstrip(".").lower(),
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "map product catalog registration failed (file kept on disk)"
                )

        return ProviderResult(
            artifacts=[
                ArtifactRef(
                    name=output_path.name,
                    kind="file",
                    version=version,
                    path=str(output_path),
                    metadata={"width": width, "height": height, "dpi": dpi},
                )
            ],
            diagnostics={"bytes": output_path.stat().st_size if output_path.exists() else 0},
        )


def make_visualization_providers() -> list[MapRenderBackendProvider]:
    """Probe the production backends once; register honest availability."""
    providers: list[MapRenderBackendProvider] = []
    try:
        from paleo_workbench.mapping.map_render_backend import qgis_backend_probe

        providers.append(MapRenderBackendProvider("qgis", bool(qgis_backend_probe())))
    except Exception:
        providers.append(MapRenderBackendProvider("qgis", False))
    providers.append(MapRenderBackendProvider("fallback", True))
    return providers
