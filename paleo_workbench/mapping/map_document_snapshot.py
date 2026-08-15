"""Legacy-document adapter for the renderer-neutral map composition seam.

This module is deliberately an adapter, not a second document or layer registry. It
turns the persisted ``PaleoMapDocument`` record shape into immutable render inputs
until Phase 3 migrates those records to authoritative vector layers/edit sessions.
"""

from __future__ import annotations

from hashlib import blake2b
import json
import math
from typing import Any, Iterable, Mapping

from paleo_workbench.mapping.document_io import features_from_document
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot

__all__ = ["document_render_snapshot", "extent_for_snapshot"]


_DEFAULT_STYLES: dict[str, Mapping[str, Any]] = {
    "facies": {"fill": "#6c8ebf", "stroke": "#26364d", "stroke_width": 1.0},
    "well": {"fill": "#22b8a7", "stroke": "#182431", "marker_size": 7.0},
    "line": {"fill": "transparent", "stroke": "#f08c46", "stroke_width": 2.0},
    # Label points are retained for the later QGIS labeling pass; fallback keeps
    # a subtle marker so an otherwise empty annotation layer remains visible.
    "label": {"fill": "#eff3f8", "stroke": "#182431", "marker_size": 4.0},
}


def _authoring_style(document, kind: str) -> dict[str, Any]:
    """Merge persisted unified-canvas style without changing legacy geometry data."""
    state = dict(getattr(document, "layer_state", None) or {})
    for entry in list(state.get("vector_layers") or []):
        if not isinstance(entry, Mapping) or str(entry.get("kind") or "") != kind:
            continue
        style = dict(entry.get("style") or {})
        labels = dict(entry.get("labels") or {})
        if labels:
            style["labels"] = labels
        return style
    return {}


def _stable_revision(value: object) -> int:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return int.from_bytes(blake2b(encoded.encode("utf-8"), digest_size=8).digest(), "big")


def _point(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return [x, y] if math.isfinite(x) and math.isfinite(y) else None


def _geometry_from_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = str(record.get("kind") or "")
    if kind == "facies":
        geometry = record.get("geometry")
        if isinstance(geometry, Mapping) and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            return {"type": str(geometry["type"]), "coordinates": geometry.get("coordinates") or []}
        return None
    if kind in {"well", "label"}:
        coordinates = _point(record.get("coordinates"))
        return {"type": "Point", "coordinates": coordinates} if coordinates else None
    if kind == "line":
        points = [_point(point) for point in record.get("coordinates") or ()]
        valid = [point for point in points if point is not None]
        return {"type": "LineString", "coordinates": valid} if len(valid) >= 2 else None
    return None


def _features_for_kind(records: Iterable[Mapping[str, Any]], kind: str) -> tuple[dict[str, Any], ...]:
    features: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("kind") or "") != kind:
            continue
        geometry = _geometry_from_record(record)
        if geometry is None:
            continue
        properties = dict(record.get("properties") or {})
        for key in ("name", "facies", "text", "topology_status"):
            if record.get(key) is not None:
                properties[key] = record[key]
        features.append(
            {"id": str(record.get("id") or ""), "geometry": geometry, "properties": properties}
        )
    return tuple(features)


def document_render_snapshot(
    document,
    *,
    project_crs: str | None,
    visibility: Mapping[str, bool] | None = None,
    records: Iterable[Mapping[str, Any]] | None = None,
    layer_revisions: Mapping[str, int] | None = None,
) -> MapRenderSnapshot:
    """Create a revisioned render snapshot from a legacy document or live scene.

    ``records`` allows unsaved MapEditScene output to render without modifying the
    document. ``layer_revisions`` supplies authoritative per-layer data revision
    counters (keyed by layer id) so data edits bump a counter instead of hashing
    every feature; without it the full-content hash is used as a fallback. The
    output has one vector layer per existing compatibility layer kind; future
    LayerRegistry-backed vector layers replace this adapter transparently.
    """
    if document is None:
        return MapRenderSnapshot(project_crs=str(project_crs or ""))
    source_records = tuple(records) if records is not None else tuple(features_from_document(document))
    visible_by_kind = dict(visibility or {})
    document_id = str(getattr(document, "id", "map") or "map")
    facies_style = dict(_DEFAULT_STYLES["facies"])
    facies_style.update(dict(getattr(document, "facies_style", None) or {}))
    layers: list[MapLayerSnapshot] = []
    for kind in ("facies", "well", "line", "label"):
        features = _features_for_kind(source_records, kind)
        layer_id = f"{document_id}:{kind}"
        if layer_revisions is not None:
            data_revision = int(layer_revisions.get(layer_id) or 0)
        else:
            data_revision = _stable_revision(features)
        style = dict(facies_style if kind == "facies" else _DEFAULT_STYLES[kind])
        style.update(_authoring_style(document, kind))
        layers.append(
            MapLayerSnapshot(
                id=layer_id,
                name={"facies": "Facies", "well": "Wells", "line": "Lines", "label": "Labels"}[kind],
                layer_type="vector",
                extent=_extent_for_features(features),
                crs=str(project_crs or ""),
                data_revision=data_revision,
                style_revision=_stable_revision(style),
                features=features,
                style=style,
                visible=bool(visible_by_kind.get(kind, True)),
            )
        )
    return MapRenderSnapshot(project_crs=str(project_crs or ""), layers=tuple(layers))


def _coordinates(value: object) -> Iterable[list[float]]:
    point = _point(value)
    if point is not None:
        yield point
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _coordinates(child)


def _extent_for_features(features: Iterable[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    points = [point for feature in features for point in _coordinates(feature.get("geometry", {}).get("coordinates"))]
    if not points:
        return (0.0, 0.0, 1.0, 1.0)
    xs, ys = zip(*points)
    return _positive_extent((min(xs), min(ys), max(xs), max(ys)))


def _positive_extent(extent: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = extent
    pad = max(1.0, abs(xmin), abs(ymin), abs(xmax), abs(ymax)) * 1e-9
    return (
        xmin if xmax > xmin else xmin - pad,
        ymin if ymax > ymin else ymin - pad,
        xmax if xmax > xmin else xmax + pad,
        ymax if ymax > ymin else ymax + pad,
    )


def extent_for_snapshot(snapshot: MapRenderSnapshot) -> tuple[float, float, float, float]:
    """Return a non-degenerate full extent for all populated composition layers."""
    populated = [layer.extent for layer in snapshot.layers if layer.features]
    if not populated:
        return (0.0, 0.0, 1.0, 1.0)
    return _positive_extent(
        (
            min(extent[0] for extent in populated),
            min(extent[1] for extent in populated),
            max(extent[2] for extent in populated),
            max(extent[3] for extent in populated),
        )
    )
