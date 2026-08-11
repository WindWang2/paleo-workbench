"""Incremental migration adapter from legacy map documents to ``MapScene``.

The adapter preserves the current document/editor contract while projecting it into a
single native ``LayerRegistry``. It owns no semantic geometry: persisted documents and
explicit live edit records remain the source until VectorEditSession becomes the
authoritative editor in Phase 3.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
from paleo_workbench.viz.native_factor_map import MapScene

__all__ = ["LegacyDocumentSceneAdapter"]


class LegacyDocumentSceneAdapter:
    """Keep one ``MapScene`` synchronized with the active legacy document."""

    def __init__(self) -> None:
        self.scene = MapScene()
        self._document_id: str | None = None

    def clear(self) -> None:
        self.scene = MapScene()
        self._document_id = None

    def sync(
        self,
        document,
        *,
        project_crs: str | None,
        visibility: Mapping[str, bool] | None = None,
        records: Iterable[Mapping[str, object]] | None = None,
    ):
        """Synchronize revisions into the scene and return its render snapshot."""
        if document is None:
            self.clear()
            return self.scene.render_snapshot(project_crs=str(project_crs or ""))
        document_id = str(getattr(document, "id", "") or "map")
        if document_id != self._document_id:
            self.scene = MapScene()
            self._document_id = document_id

        source = document_render_snapshot(
            document,
            project_crs=project_crs,
            visibility=visibility,
            records=records,
        )
        wanted_ids = {layer.id for layer in source.layers}
        for existing in tuple(self.scene.registry.layers()):
            if existing.id not in wanted_ids:
                self.scene.remove_layer(existing.id)
        for layer in source.layers:
            existing = self.scene.registry.get(layer.id)
            if existing is None:
                existing = self.scene.add_vector_layer(
                    layer.id,
                    layer.features,
                    name=layer.name,
                    extent=layer.extent,
                    crs=layer.crs,
                    style=dict(layer.style),
                )
                existing.visible = layer.visible
                existing.opacity = layer.opacity
                continue
            if self.scene.vector_features(layer.id) != layer.features:
                self.scene.set_vector_features(layer.id, layer.features, extent=layer.extent)
            if self.scene.vector_style(layer.id) != dict(layer.style):
                self.scene.set_vector_style(layer.id, dict(layer.style))
            if existing.visible != layer.visible:
                existing.visible = layer.visible
            if existing.opacity != layer.opacity:
                existing.opacity = layer.opacity
            if existing.name != layer.name:
                existing.name = layer.name
            if tuple(existing.extent) != layer.extent:
                existing.extent = layer.extent
            if existing.crs != layer.crs:
                existing.crs = layer.crs
        return self.scene.render_snapshot(project_crs=str(project_crs or ""))
