"""Host-owned map authoring state built on revisioned vector edit buffers.

This module is the compatibility bridge between the persisted ``PaleoMapDocument``
record shape and the new vector model.  It deliberately contains no Qt or QGIS
objects: UI widgets and native render mirrors consume its state but never own it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from paleo_workbench.mapping.document_io import features_from_document
from paleo_workbench.mapping.vector_layer import VectorEditSession, VectorFeature, VectorLayer

__all__ = ["MapAuthoringDocument", "record_to_feature", "feature_to_record"]


_LAYER_KINDS = ("facies", "well", "line", "label")


def _point(value: object) -> list[float]:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        raise ValueError("point coordinates are required")
    return [float(value[0]), float(value[1])]


def record_to_feature(record: Mapping[str, Any]) -> VectorFeature:
    """Convert one existing map record without losing compatible attributes."""
    kind = str(record.get("kind") or "")
    feature_id = str(record.get("id") or "")
    if not feature_id or kind not in _LAYER_KINDS:
        raise ValueError("map record must have a supported kind and id")
    if kind == "facies":
        raw_geometry = record.get("geometry")
        if not isinstance(raw_geometry, Mapping):
            raise ValueError("facies record geometry is required")
        geometry = {
            "type": str(raw_geometry.get("type") or "Polygon"),
            "coordinates": raw_geometry.get("coordinates") or (),
        }
    elif kind in {"well", "label"}:
        geometry = {"type": "Point", "coordinates": _point(record.get("coordinates"))}
    else:
        geometry = {
            "type": "LineString",
            "coordinates": [list(_point(point)) for point in record.get("coordinates") or ()],
        }
    attributes = dict(record.get("properties") or {})
    # Preserve the small established editor schema at the top level.  The layer
    # kind is an authoring property, not a geometry or a graphics-item type.
    attributes["_paleo_kind"] = kind
    for key in (
        "name", "facies", "text", "topology_status", "probability", "region_id",
        "lng", "lat", "style",
    ):
        if key in record:
            attributes[key] = record[key]
    return VectorFeature(feature_id, geometry, attributes)


def feature_to_record(feature: VectorFeature, *, kind: str) -> dict[str, Any]:
    """Return the established document/edit record form from semantic vector data."""
    if kind not in _LAYER_KINDS:
        raise ValueError(f"unsupported authoring layer kind {kind!r}")
    attributes = dict(feature.attributes)
    attributes.pop("_paleo_kind", None)
    geometry = feature.as_record()["geometry"]
    properties = {
        str(key): value
        for key, value in attributes.items()
        if key not in {"name", "facies", "text", "topology_status", "probability", "region_id", "lng", "lat", "style"}
    }
    record: dict[str, Any] = {"id": feature.feature_id, "kind": kind, "properties": properties}
    if kind == "facies":
        record.update(
            {
                "name": str(attributes.get("name") or attributes.get("facies") or ""),
                "facies": attributes.get("facies"),
                "geometry": geometry,
                "coordinates": geometry["coordinates"],
                "style": dict(attributes.get("style") or {}),
            }
        )
        for key in ("probability", "region_id", "topology_status"):
            if key in attributes:
                record[key] = attributes[key]
    elif kind == "well":
        coordinates = list(geometry["coordinates"])
        record.update(
            {
                "name": str(attributes.get("name") or ""),
                "coordinates": coordinates,
                "lng": attributes.get("lng", coordinates[0]),
                "lat": attributes.get("lat", coordinates[1]),
            }
        )
    elif kind == "line":
        record.update(
            {
                "name": str(attributes.get("name") or ""),
                "coordinates": geometry["coordinates"],
            }
        )
    else:
        record.update(
            {
                "name": str(attributes.get("name") or attributes.get("text") or ""),
                "text": str(attributes.get("text") or attributes.get("name") or ""),
                "coordinates": list(geometry["coordinates"]),
            }
        )
    return record


@dataclass(slots=True)
class _LayerBinding:
    kind: str
    layer: VectorLayer


class MapAuthoringDocument:
    """One map's editable vector state and the active-layer selection service.

    ``commit_changes`` promotes buffers into the managed working version in memory;
    the caller alone decides when to persist those records into a project document.
    Raw catalog resources are never opened or mutated here.
    """

    def __init__(self, *, document_id: str, project_crs: str = "", records: Iterable[Mapping[str, Any]] = ()) -> None:
        self.document_id = str(document_id)
        self.project_crs = str(project_crs)
        grouped: dict[str, list[VectorFeature]] = {kind: [] for kind in _LAYER_KINDS}
        for record in records:
            try:
                feature = record_to_feature(record)
            except (TypeError, ValueError):
                continue
            grouped[str(feature.attributes["_paleo_kind"])].append(feature)
        self._bindings: dict[str, _LayerBinding] = {}
        for kind in _LAYER_KINDS:
            self._bindings[kind] = _LayerBinding(
                kind,
                VectorLayer(
                    id=f"{self.document_id}:{kind}",
                    name={"facies": "Facies", "well": "Wells", "line": "Lines", "label": "Labels"}[kind],
                    crs=self.project_crs,
                    source_ref=f"map-working:{self.document_id}:{kind}",
                    features=grouped[kind],
                ),
            )
        self.active_kind = "facies"
        # Per-kind record cache keyed by (data_revision, session revision,
        # session epoch). A render refresh walks the document even when nothing
        # changed; these keys make repeated ``records()`` calls O(changed
        # layers) instead of O(all features). Cached record dicts are shared,
        # never mutated. The epoch increments whenever the session *object*
        # changes (start/discard/commit/rollback): revisions alone collide
        # after rollback because a fresh session restarts its revision at 0.
        self._records_cache: dict[str, tuple[tuple[int, int, int], list[dict[str, Any]]]] = {}
        self._session_generation: dict[str, int] = {kind: 0 for kind in _LAYER_KINDS}
        self._session_refs: dict[str, object] = {}

    @classmethod
    def from_document(cls, document, *, project_crs: str | None = None) -> "MapAuthoringDocument":
        result = cls(
            document_id=str(getattr(document, "id", "") or "map"),
            project_crs=str(project_crs or getattr(document, "map_crs", "") or ""),
            records=features_from_document(document),
        )
        state = dict(getattr(document, "layer_state", None) or {})
        active_kind = str(state.get("active_kind") or "facies")
        if active_kind in result._bindings:
            result.active_kind = active_kind
        for entry in list(state.get("vector_layers") or []):
            if not isinstance(entry, Mapping):
                continue
            kind = str(entry.get("kind") or "")
            if kind not in result._bindings:
                continue
            layer = result.layer(kind)
            layer.style = dict(entry.get("style") or {})
            layer.labels = dict(entry.get("labels") or {})
        return result

    @property
    def active_layer(self) -> VectorLayer:
        return self._bindings[self.active_kind].layer

    @property
    def active_session(self) -> VectorEditSession | None:
        return self.active_layer.edit_session

    def layer(self, kind: str) -> VectorLayer:
        return self._bindings[str(kind)].layer

    def layers(self) -> tuple[VectorLayer, ...]:
        return tuple(self._bindings[kind].layer for kind in _LAYER_KINDS)

    def set_active_kind(self, kind: str) -> VectorLayer:
        if kind not in self._bindings:
            raise ValueError(f"unknown authoring layer {kind!r}")
        self.active_kind = kind
        return self.active_layer

    def start_editing(self, kind: str | None = None) -> VectorEditSession:
        if kind is not None:
            self.set_active_kind(kind)
        return self.active_layer.start_editing()

    def editing(self) -> bool:
        return any(binding.layer.edit_session is not None for binding in self._bindings.values())

    def is_dirty(self) -> bool:
        return any(
            binding.layer.edit_session is not None and binding.layer.edit_session.is_dirty
            for binding in self._bindings.values()
        )

    def _session_epoch(self, kind: str) -> int:
        """Bump-and-report when the layer's session object was replaced."""
        layer = self.layer(kind)
        session = layer.edit_session
        if session is not self._session_refs.get(kind):
            self._session_refs[kind] = session
            self._session_generation[kind] = self._session_generation.get(kind, 0) + 1
        return self._session_generation[kind]

    def records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for kind in _LAYER_KINDS:
            layer = self.layer(kind)
            session = layer.edit_session
            key = (
                layer.data_revision,
                session.revision if session is not None else -1,
                self._session_epoch(kind),
            )
            cached = self._records_cache.get(kind)
            if cached is not None and cached[0] == key:
                records.extend(cached[1])
                continue
            source = session.features() if session is not None else layer.features()
            built = [feature_to_record(feature, kind=kind) for feature in source]
            self._records_cache[kind] = (key, built)
            records.extend(built)
        return records

    def data_revision_key(self, kind: str) -> tuple[int, int, int]:
        """Cheap change key for one layer covering commits plus live edits.

        Includes the session epoch so a rollback (which discards the session
        without bumping ``data_revision``) followed by different edits never
        reuses a previous key.
        """
        layer = self.layer(kind)
        session = layer.edit_session
        return (
            layer.data_revision,
            session.revision if session is not None else -1,
            self._session_epoch(kind),
        )
    def data_revisions(self) -> dict[str, int]:
        """Per-layer data revision counters for render snapshot cache keys.

        The committed ``VectorLayer.data_revision`` and the open edit-session
        revision are packed into one int so every mutation (edit record, undo,
        redo, rollback, commit) yields a distinct revision without hashing
        feature payloads.
        """
        revisions: dict[str, int] = {}
        for binding in self._bindings.values():
            layer = binding.layer
            session = layer.edit_session
            session_revision = session.revision if session is not None else 0
            revisions[layer.id] = (layer.data_revision << 32) + session_revision
        return revisions

    def selected_feature_ids(self) -> set[str]:
        return self.active_layer.selection

    def clear_selection(self) -> None:
        for binding in self._bindings.values():
            binding.layer.set_selection(())

    def commit_changes(self) -> list[dict[str, object]]:
        audit: list[dict[str, object]] = []
        for binding in self._bindings.values():
            session = binding.layer.edit_session
            if session is None:
                continue
            audit.extend(session.audit_history())
            session.commit_changes()
        return audit

    def rollback_changes(self) -> None:
        for binding in self._bindings.values():
            session = binding.layer.edit_session
            if session is not None:
                session.rollback_changes()

    def state(self) -> dict[str, object]:
        """Persist semantic authoring presentation, never transient edit overlays."""
        return {
            "schema_version": 1,
            "active_kind": self.active_kind,
            "vector_layers": [
                {
                    "kind": kind,
                    "id": self.layer(kind).id,
                    "style": dict(self.layer(kind).style),
                    "labels": dict(self.layer(kind).labels),
                    "source_ref": self.layer(kind).source_ref,
                }
                for kind in _LAYER_KINDS
            ],
        }

    def change_attribute(self, feature_id: str, key: str, value: object) -> bool:
        for binding in self._bindings.values():
            layer = binding.layer
            source = layer.edit_session.features() if layer.edit_session is not None else layer.features()
            if any(feature.feature_id == str(feature_id) for feature in source):
                if layer.edit_session is None:
                    return False
                layer.edit_session.change_attribute(str(feature_id), str(key), value)
                return True
        return False
