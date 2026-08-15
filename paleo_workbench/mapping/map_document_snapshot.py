"""Legacy-document adapter for the renderer-neutral map composition seam.

This module is deliberately an adapter, not a second document or layer registry. It
turns the persisted ``PaleoMapDocument`` record shape into immutable render inputs
until Phase 3 migrates those records to authoritative vector layers/edit sessions.
"""

from __future__ import annotations

from collections import OrderedDict
import math
from typing import Any, Iterable, Mapping

from paleo_workbench.mapping.document_io import features_from_document
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot
from paleo_workbench.mapping.map_styles import default_style_for

__all__ = ["document_render_snapshot", "extent_for_snapshot"]


_LAYER_KINDS = ("facies", "well", "line", "label")
_LAYER_NAMES = {"facies": "Facies", "well": "Wells", "line": "Lines", "label": "Labels"}

# Per-(owner, document, kind, revision) cache of built feature tuples and
# extents. A composition refresh that changes nothing (or one layer) must not
# re-walk every record and coordinate; entries are immutable and shared across
# snapshots. Each entry holds its owning authoring object and only hits on
# exact object identity: revisions are per-owner counters, so entries from a
# replaced owner can never leak into a new one. The bounded LRU keeps retired
# owners from accumulating.
_FEATURE_CACHE_LIMIT = 24
_FEATURE_CACHE: OrderedDict[
    tuple[int, str, str, int],
    tuple[object, tuple[dict[str, Any], ...], tuple[float, float, float, float]],
] = OrderedDict()


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
    """Content-stable revision via recursive tuple freezing (no JSON round-trip).

    Stable within one process (used only for in-memory change detection);
    unhashable attribute values fall back to their string form so arbitrary
    persisted properties never raise here.
    """

    def freeze(item: object) -> object:
        if isinstance(item, Mapping):
            return tuple(sorted((str(key), freeze(child)) for key, child in item.items()))
        if isinstance(item, (list, tuple)):
            return tuple(freeze(child) for child in item)
        if isinstance(item, (bool, int, float, str)) or item is None:
            return item
        return str(item)

    return hash(freeze(value))


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


def _grouped_features(
    records: Iterable[Mapping[str, Any]],
    needed: set[str],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """One pass over the records, bucketing only the requested kinds.

    Also accumulates each bucket's coordinate bounds inline, so the snapshot
    never re-walks every coordinate a second time for extents.
    """
    buckets: dict[str, list[dict[str, Any]]] = {kind: [] for kind in needed}
    bounds: dict[str, list[float]] = {kind: [math.inf, math.inf, -math.inf, -math.inf] for kind in needed}

    def expand(kind: str, coordinates: object) -> None:
        box = bounds[kind]
        if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
            try:
                x, y = float(coordinates[0]), float(coordinates[1])
            except (TypeError, ValueError):
                pass
            else:
                if math.isfinite(x) and math.isfinite(y):
                    if x < box[0]:
                        box[0] = x
                    if y < box[1]:
                        box[1] = y
                    if x > box[2]:
                        box[2] = x
                    if y > box[3]:
                        box[3] = y
                return
        for child in coordinates or ():  # nested ring / line levels
            expand(kind, child)

    for record in records:
        kind = str(record.get("kind") or "")
        if kind not in buckets:
            continue
        geometry = _geometry_from_record(record)
        if geometry is None:
            continue
        properties = dict(record.get("properties") or {})
        for key in ("name", "facies", "text", "topology_status"):
            if record.get(key) is not None:
                properties[key] = record[key]
        buckets[kind].append(
            {"id": str(record.get("id") or ""), "geometry": geometry, "properties": properties}
        )
        expand(kind, geometry.get("coordinates"))
    return {kind: tuple(features) for kind, features in buckets.items() if kind in needed}, bounds


def _extent_from_bounds(bounds: list[float]) -> tuple[float, float, float, float]:
    if not math.isfinite(bounds[0]):
        return (0.0, 0.0, 1.0, 1.0)
    return _positive_extent((bounds[0], bounds[1], bounds[2], bounds[3]))


def document_render_snapshot(
    document,
    *,
    project_crs: str | None,
    visibility: Mapping[str, bool] | None = None,
    records: Iterable[Mapping[str, Any]] | None = None,
    data_revisions: Mapping[str, int] | None = None,
    cache_owner: object | None = None,
) -> MapRenderSnapshot:
    """Create a revisioned render snapshot from a legacy document or live scene.

    ``records`` allows unsaved MapEditScene output to render without modifying the
    document. ``data_revisions`` optionally supplies authoritative per-kind content
    revisions (from ``MapAuthoringDocument`` vector layers); unchanged revisions
    reuse cached feature tuples and extents without walking the records again.
    Revision-keyed caching additionally requires ``cache_owner``: revisions are
    owner-scoped counters, so the cache is only valid while that exact owner
    object is alive (verified through a weak reference).
    The output has one vector layer per existing compatibility layer kind; future
    LayerRegistry-backed vector layers replace this adapter transparently.
    """
    if document is None:
        return MapRenderSnapshot(project_crs=str(project_crs or ""))
    revisions = dict(data_revisions or {})
    owner_token = id(cache_owner) if cache_owner is not None and revisions else None
    document_id = str(getattr(document, "id", "map") or "map")
    grouped: dict[str, tuple[dict[str, Any], ...]] = {}
    bounds: dict[str, list[float]] = {}

    def grouped_features(needed: set[str]) -> None:
        nonlocal grouped, bounds
        missing = needed - grouped.keys()
        if not missing:
            return
        source = tuple(records) if records is not None else tuple(features_from_document(document))
        built, built_bounds = _grouped_features(source, missing)
        grouped.update(built)
        bounds.update(built_bounds)

    visible_by_kind = dict(visibility or {})
    facies_style = default_style_for("facies").to_dict()
    facies_style.update(dict(getattr(document, "facies_style", None) or {}))
    layers: list[MapLayerSnapshot] = []
    for kind in _LAYER_KINDS:
        revision = revisions.get(kind)
        cache_key = (
            (owner_token, document_id, kind, int(revision))
            if owner_token is not None and revision is not None
            else None
        )
        cached_entry = _FEATURE_CACHE.get(cache_key) if cache_key is not None else None
        if cached_entry is not None and cached_entry[0] is cache_owner:
            _FEATURE_CACHE.move_to_end(cache_key)
            _, features, extent = cached_entry
            data_revision = int(revision)
        else:
            grouped_features({kind})
            features = grouped.get(kind) or ()
            extent = _extent_from_bounds(bounds.get(kind) or [math.inf] * 4)
            data_revision = int(revision) if revision is not None else _stable_revision(features)
            if cache_key is not None:
                _FEATURE_CACHE[cache_key] = (cache_owner, features, extent)
                while len(_FEATURE_CACHE) > _FEATURE_CACHE_LIMIT:
                    _FEATURE_CACHE.popitem(last=False)
        style = dict(facies_style if kind == "facies" else default_style_for(kind).to_dict())
        style.update(_authoring_style(document, kind))
        layers.append(
            MapLayerSnapshot(
                id=f"{document_id}:{kind}",
                name=_LAYER_NAMES[kind],
                layer_type="vector",
                extent=extent,
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
