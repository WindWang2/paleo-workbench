"""Incremental migration adapter from legacy map documents to ``MapScene``.

The adapter preserves the current document/editor contract while projecting it into a
single native ``LayerRegistry``. It owns no semantic geometry: persisted documents and
explicit live edit records remain the source until VectorEditSession becomes the
authoritative editor in Phase 3.

Synchronization is revision-driven: per-layer content revisions supplied by the host
(authoring vector layers) decide whether features/styles are pushed into the scene.
Layers without authoritative revisions fall back to the snapshot's content revisions,
which the document adapter guarantees are stable for unchanged content. No full
deep-equality walk over feature tuples happens on the refresh path.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
from paleo_workbench.viz.native_factor_map import MapScene

__all__ = ["LegacyDocumentSceneAdapter"]


class LegacyDocumentSceneAdapter:
    """Keep one ``MapScene`` synchronized with the active legacy document."""

    def __init__(self) -> None:
        try:
            self.scene = MapScene()
        except Exception:
            self.scene = None
        self._document_id: str | None = None
        self._legacy_layer_ids: set[str] = set()
        # layer_id → (data_revision, style_revision, visible, opacity, name, crs, extent)
        self._synced_state: dict[str, tuple] = {}
        self._last_snapshot = None

    def clear(self) -> None:
        try:
            self.scene = MapScene()
        except Exception:
            self.scene = None
        self._document_id = None
        self._legacy_layer_ids.clear()
        self._synced_state.clear()
        self._last_snapshot = None

    def sync(
        self,
        document,
        *,
        project_crs: str | None,
        visibility: Mapping[str, bool] | None = None,
        records: Iterable[Mapping[str, object]] | None = None,
        layer_revisions: Mapping[str, int] | None = None,
        excluded_layer_ids: Iterable[str] = (),
        data_revisions: Mapping[str, int] | None = None,
        cache_owner: object | None = None,
    ):
        """Synchronize revisions into the scene and return its render snapshot."""
        if self.scene is None:
            return None
        if document is None:
            self.clear()
            if self.scene is None:
                return None
            return self.scene.render_snapshot(project_crs=str(project_crs or ""))
        document_id = str(getattr(document, "id", "") or "map")
        if document_id != self._document_id:
            self.scene = MapScene()
            self._document_id = document_id
            self._legacy_layer_ids.clear()
            self._synced_state.clear()
            self._last_snapshot = None

        source = document_render_snapshot(
            document,
            project_crs=project_crs,
            visibility=visibility,
            records=records,
            data_revisions=data_revisions,
            cache_owner=cache_owner,
            layer_revisions=layer_revisions,
            previous_layers=None if self._last_snapshot is None else self._last_snapshot.layers,
        )
        excluded = {str(layer_id) for layer_id in excluded_layer_ids}
        source_layers = tuple(layer for layer in source.layers if layer.id not in excluded)
        wanted_ids = {layer.id for layer in source_layers}
        for layer_id in self._legacy_layer_ids - wanted_ids:
            self.scene.remove_layer(layer_id)
            self._synced_state.pop(layer_id, None)
        for layer in source_layers:
            desired = (
                int(layer.data_revision),
                int(layer.style_revision),
                bool(layer.visible),
                float(layer.opacity),
                str(layer.name),
                str(layer.crs),
                tuple(layer.extent),
            )
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
                self._synced_state[layer.id] = desired
                continue
            synced = self._synced_state.get(layer.id)
            if synced is None or synced[0] != desired[0]:
                # The source revision is authoritative: skip the scene's deep
                # feature comparison, which would otherwise walk every tuple.
                self.scene.set_vector_features(
                    layer.id, layer.features, extent=layer.extent, assume_changed=True
                )
            elif tuple(existing.extent) != desired[6]:
                existing.extent = layer.extent
            if synced is None or synced[1] != desired[1]:
                self.scene.set_vector_style(layer.id, dict(layer.style))
            if synced is None or synced[2] != desired[2]:
                existing.visible = layer.visible
            if synced is None or synced[3] != desired[3]:
                existing.opacity = layer.opacity
            if synced is None or synced[4] != desired[4]:
                existing.name = layer.name
            if synced is None or synced[5] != desired[5]:
                existing.crs = layer.crs
            self._synced_state[layer.id] = desired
        self._legacy_layer_ids = wanted_ids
        self._last_snapshot = source
        return self.scene.render_snapshot(project_crs=str(project_crs or ""))
