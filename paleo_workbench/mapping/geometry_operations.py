"""Unified generic-GIS geometry operations facade (goal §4).

ONE entry point per generic GIS operation.  Preferred engine is the
vendored QGIS geometry engine exposed by ``qgis_render_bridge.geometry``
(15 ops); without the bridge the same operations run on their documented
fallback engines (shapely / host).  Every result discloses the engine via
``.engine`` — degradation is visible, never silent, and no result ever
pretends to be QGIS when it is not.

Scientific algorithms (marching squares, deterministic raster
polygonization, kriging/IDW, fusion) stay in their own modules — this
facade is for GENERIC GIS geometry only.

What is deliberately host/shapely here (recorded in
``engine_status()["ops"]``):

* point-in-polygon — host ray-cast (:mod:`geometry_planar`), the single
  shared implementation replacing three in-repo duplicates;
* area/length — CRS-unit-honest scientific measurements (V6 §15);
* nearest feature — host brute force on first coordinates (the IDW
  kNN authority stays scipy cKDTree inside the interpolator, but this
  facade entry is deliberately linear);
* topology checks — TopologyService (shapely explain_validity);
* CRS transform — pyproj reproject_xy (existing transformation authority);
* polygonize / line_merge — shapely (bridge does not expose them yet).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from paleo_workbench.mapping.qgis_style import qgis_bridge_available

__all__ = [
    "ENGINE_HOST",
    "ENGINE_QGIS",
    "ENGINE_SHAPELY",
    "area_with_unit",
    "bbox_intersects",
    "bounding_geometry",
    "buffer",
    "centroid",
    "clip",
    "crs_transform_xy",
    "densify",
    "difference",
    "dissolve",
    "engine_status",
    "intersection",
    "line_merge",
    "length_with_unit",
    "make_valid",
    "multipart_to_singlepart",
    "nearest_feature",
    "offset_curve",
    "point_in_polygon",
    "polygonize",
    "repair",
    "simplify",
    "singlepart_to_multipart",
    "smooth",
    "split_by_line",
    "symdifference",
    "topology_check",
    "union",
    "validate",
]

ENGINE_QGIS = "qgis"
ENGINE_SHAPELY = "shapely-fallback"
ENGINE_HOST = "host"

_BRIDGE_OPS = (
    "intersection", "difference", "symdifference", "union", "buffer", "clip",
    "simplify", "smooth", "densify", "repair", "validate",
    "multipart_to_singlepart", "singlepart_to_multipart", "offset_curve",
    "split_by_line",
)
_SHAPELY_OPS = frozenset(_BRIDGE_OPS) | {"polygonize", "line_merge", "dissolve"}
_HOST_OPS = ("point_in_polygon", "area_with_unit", "length_with_unit",
             "bounding_geometry", "nearest_feature", "topology_check",
             "crs_transform_xy")

_BRIDGE_PROBE: bool | None = None


def _bridge_geometry():
    """Import and return the bridge geometry submodule (or None)."""
    global _BRIDGE_PROBE
    if _BRIDGE_PROBE is None:
        _BRIDGE_PROBE = qgis_bridge_available()
    if not _BRIDGE_PROBE:
        return None
    import qgis_render_bridge as native

    return native.geometry


def engine_status() -> dict[str, Any]:
    """Honest per-op engine map (for capability snapshots + diagnostics)."""
    bridge = _bridge_geometry() is not None
    ops: dict[str, str] = {}
    for name in _BRIDGE_OPS:
        ops[name] = ENGINE_QGIS if bridge else ENGINE_SHAPELY
    for name in ("polygonize", "line_merge", "dissolve"):
        ops[name] = ENGINE_SHAPELY
    for name in _HOST_OPS:
        ops[name] = ENGINE_HOST
    return {"bridge_available": bridge, "ops": ops}


# ---------------------------------------------------------------------------
# Result carriers


@dataclass(frozen=True)
class GeometryResult:
    geometry: dict[str, Any]
    engine: str


@dataclass(frozen=True)
class GeometryListResult:
    geometries: list[dict[str, Any]] | None = None
    geometry: dict[str, Any] | None = None
    engine: str = ENGINE_SHAPELY


@dataclass(frozen=True)
class ValidityResult:
    valid: bool
    reason: str = ""
    engine: str = ENGINE_SHAPELY


@dataclass(frozen=True)
class MeasurementResult:
    value: float
    unit: str
    engine: str = ENGINE_HOST


@dataclass(frozen=True)
class ContainsResult:
    contains: bool
    engine: str = ENGINE_HOST


@dataclass(frozen=True)
class TopologyReport:
    invalid_count: int
    issues: list[str] = field(default_factory=list)
    engine: str = ENGINE_SHAPELY


def _geojson(value: str | dict) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _dump(geometry: dict[str, Any]) -> str:
    return json.dumps(geometry, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Shapely fallbacks


def _shapely():
    try:
        import shapely.geometry as sgeom
        from shapely import make_valid as _smake_valid
        from shapely.ops import linemerge, polygonize as _spolygonize, unary_union
    except ImportError as exc:  # pragma: no cover - shapely is a hard dep
        raise RuntimeError(
            "geometry fallback requires shapely and the qgis_render_bridge "
            "is not built; build the bridge (PALEO_WITH_QGIS_RENDERER=1) or "
            "install shapely") from exc
    return sgeom, _smake_valid, linemerge, _spolygonize, unary_union


def _shapely_binary(op: str, a: dict, b: dict) -> GeometryResult:
    sgeom = _shapely()[0]
    ga, gb = sgeom.shape(a), sgeom.shape(b)
    out = getattr(ga, op)(gb)
    if out.is_empty:
        raise ValueError(f"{op} produced an empty geometry")
    return GeometryResult(_geojson(out.__geo_interface__), ENGINE_SHAPELY)


# ---------------------------------------------------------------------------
# Bridge-first binary/unary ops


def _bridge_binary(op: str, a: dict, b: dict) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = getattr(native, op)(_dump(a), _dump(b))
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass  # fall through to shapely with disclosure
    return _shapely_binary(
        {"intersection": "intersection", "difference": "difference",
         "symdifference": "symmetric_difference"}[op], a, b)


def intersection(a: dict, b: dict) -> GeometryResult:
    return _bridge_binary("intersection", a, b)


def difference(a: dict, b: dict) -> GeometryResult:
    return _bridge_binary("difference", a, b)


def symdifference(a: dict, b: dict) -> GeometryResult:
    return _bridge_binary("symdifference", a, b)


def clip(geometry: dict, extent: Sequence[float]) -> GeometryResult:
    """Rectangle clip (bbox).  Domain-ring clipping is a different, scientific
    operation (contour/polygonization clip_to_ring)."""
    try:
        xmin, ymin, xmax, ymax = (float(v) for v in extent)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "clip needs an (xmin, ymin, xmax, ymax) extent of 4 numbers") from exc
    for value in (xmin, ymin, xmax, ymax):
        if not math.isfinite(value):
            raise ValueError("clip extent must be finite numbers")
    if not (xmax > xmin and ymax > ymin):
        raise ValueError(
            f"clip extent needs xmax > xmin and ymax > ymin, got "
            f"({xmin}, {ymin}, {xmax}, {ymax})")
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.clip(_dump(geometry), [xmin, ymin, xmax, ymax])
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    box = {
        "type": "Polygon",
        "coordinates": [[
            [extent[0], extent[1]], [extent[2], extent[1]],
            [extent[2], extent[3]], [extent[0], extent[3]],
            [extent[0], extent[1]],
        ]],
    }
    return _shapely_binary("intersection", geometry, box)


def union(geometries: Sequence[dict]) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.union([_dump(g) for g in geometries])
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    _, _, _, _, unary_union = _shapely()
    merged = unary_union([_shapely()[0].shape(g) for g in geometries])
    return GeometryResult(_geojson(merged.__geo_interface__), ENGINE_SHAPELY)


def dissolve(geometries: Sequence[dict]) -> GeometryResult:
    """Dissolve = union aggregate (same engine chain)."""
    return union(geometries)


def buffer(geometry: dict, distance: float, segments: int = 8) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.buffer(_dump(geometry), float(distance), int(segments))
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    sgeom = _shapely()[0]
    out = sgeom.shape(geometry).buffer(float(distance), quad_segs=int(segments))
    return GeometryResult(_geojson(out.__geo_interface__), ENGINE_SHAPELY)


def offset_curve(line: dict, distance: float) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.offset_curve(_dump(line), float(distance))
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    sgeom = _shapely()[0]
    out = sgeom.shape(line).offset_curve(float(distance))
    if out.is_empty:
        raise ValueError("offset_curve produced an empty geometry")
    return GeometryResult(_geojson(out.__geo_interface__), ENGINE_SHAPELY)


def simplify(geometry: dict, tolerance: float) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.simplify(_dump(geometry), float(tolerance))
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    sgeom = _shapely()[0]
    out = sgeom.shape(geometry).simplify(float(tolerance))
    return GeometryResult(_geojson(out.__geo_interface__), ENGINE_SHAPELY)


def smooth(geometry: dict, iterations: int = 1, offset: float = 0.25) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.smooth(_dump(geometry), int(iterations), float(offset))
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    from paleo_workbench.mapping.geological_pipeline.contouring import chaikin_smooth

    coordinates = geometry.get("coordinates")
    if geometry.get("type") not in {"LineString", "Polygon"} or not coordinates:
        raise ValueError("host smooth supports LineString/Polygon only")
    closed = geometry.get("type") == "Polygon"
    ring = coordinates[0] if closed else coordinates
    del offset  # host fallback: deterministic Chaikin, closure auto-detected
    smoothed = list(ring)
    for _ in range(int(iterations)):
        smoothed = chaikin_smooth([list(pt) for pt in smoothed])
    out = dict(geometry)
    out["coordinates"] = [smoothed] if closed else smoothed
    # host Chaikin (R2-F1): disclosed as host, not shapely
    return GeometryResult(out, ENGINE_HOST)


def densify(geometry: dict, interval: float) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.densify(_dump(geometry), float(interval))
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    sgeom = _shapely()[0]
    from shapely import segmentize

    out = segmentize(sgeom.shape(geometry), float(interval))
    return GeometryResult(_geojson(out.__geo_interface__), ENGINE_SHAPELY)


def multipart_to_singlepart(geometry: dict) -> GeometryListResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            parts = native.multipart_to_singlepart(_dump(geometry))
            return GeometryListResult(
                geometries=[_geojson(p) for p in parts], engine=ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    sgeom = _shapely()[0]
    shape = sgeom.shape(geometry)
    singles = list(getattr(shape, "geoms", [shape]))
    return GeometryListResult(
        geometries=[_geojson(g.__geo_interface__) for g in singles],
        engine=ENGINE_SHAPELY)


def singlepart_to_multipart(parts: Sequence[dict]) -> GeometryResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.singlepart_to_multipart([_dump(p) for p in parts])
            return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    geom_type = parts[0].get("type") if parts else None
    prefix = {"Polygon": "MultiPolygon", "LineString": "MultiLineString",
              "Point": "MultiPoint"}.get(str(geom_type))
    if prefix is None:
        raise ValueError("singlepart_to_multipart needs homogeneous parts")
    if prefix == "MultiPolygon":
        coordinates = [p["coordinates"] for p in parts]
    else:
        coordinates = [p["coordinates"] for p in parts]
    return GeometryResult(
        {"type": prefix, "coordinates": coordinates}, ENGINE_SHAPELY)


def split_by_line(geometry: dict, cutter: dict) -> GeometryListResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            pieces = native.split_by_line(_dump(geometry), _dump(cutter))
            return GeometryListResult(
                geometries=[_geojson(p) for p in pieces], engine=ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    from shapely.ops import split

    sgeom = _shapely()[0]
    pieces = split(sgeom.shape(geometry), sgeom.shape(cutter))
    singles = list(getattr(pieces, "geoms", [pieces]))
    return GeometryListResult(
        geometries=[_geojson(g.__geo_interface__) for g in singles],
        engine=ENGINE_SHAPELY)


# ---------------------------------------------------------------------------
# Validity / repair


def validate(geometry: dict) -> ValidityResult:
    native = _bridge_geometry()
    if native is not None:
        try:
            ok = bool(native.is_valid(_dump(geometry)))
            return ValidityResult(ok, "" if ok else "invalid (qgis)",
                                  ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    try:
        from shapely.geometry import shape
        from shapely.validation import explain_validity
    except ImportError as exc:
        raise RuntimeError(
            "validate requires the qgis bridge or shapely; neither available"
        ) from exc
    candidate = shape(geometry)
    if candidate.is_valid:
        return ValidityResult(True, engine=ENGINE_SHAPELY)
    return ValidityResult(False, explain_validity(candidate) or "invalid",
                          ENGINE_SHAPELY)


def repair(geometry: dict) -> GeometryResult:
    """Single repair entry: QGIS make_valid first, shapely fallback."""
    native = _bridge_geometry()
    if native is not None:
        try:
            result = native.make_valid(_dump(geometry))
            if result:
                return GeometryResult(_geojson(result), ENGINE_QGIS)
        except (RuntimeError, ValueError):
            pass
    from paleo_workbench.mapping.topology import repair_invalid_geometry

    return GeometryResult(repair_invalid_geometry(dict(geometry)), ENGINE_SHAPELY)


make_valid = repair  # back-compat alias


# ---------------------------------------------------------------------------
# Polygonize / line merge (shapely today; bridge surface later)


def polygonize(lines: Sequence[dict]) -> GeometryResult:
    _, _, _, _spolygonize, _ = _shapely()
    from shapely.ops import unary_union as _uu

    shapes = [_shapely()[0].shape(line) for line in lines]
    polygons = list(_spolygonize(_uu(shapes) if len(shapes) > 1 else shapes[0]))
    if not polygons:
        raise ValueError("polygonize produced no polygons (open lines?)")
    if len(polygons) == 1:
        return GeometryResult(_geojson(polygons[0].__geo_interface__),
                              ENGINE_SHAPELY)
    return GeometryResult(_geojson(_uu(polygons).__geo_interface__),
                          ENGINE_SHAPELY)


def line_merge(lines: Sequence[dict]) -> GeometryListResult:
    _, _, linemerge, _, _ = _shapely()
    merged = linemerge([_shapely()[0].shape(line) for line in lines])
    singles = list(getattr(merged, "geoms", [merged]))
    return GeometryListResult(
        geometries=[_geojson(g.__geo_interface__) for g in singles],
        engine=ENGINE_SHAPELY)


# ---------------------------------------------------------------------------
# Domain-ring clipping (scientific pipelines; shapely decomposition —
# the shared single copy of the two former per-module skeletons)


def _ring_polygon(clip_ring: Sequence[Sequence[float]]):
    from shapely.geometry import Polygon
    from shapely.validation import make_valid as _smake_valid

    ring_poly = Polygon([(float(x), float(y)) for x, y in clip_ring])
    if not ring_poly.is_valid:
        ring_poly = _smake_valid(ring_poly)
    return ring_poly


def clip_polyline_to_ring(poly: Sequence[Sequence[float]],
                          clip_ring: Sequence[Sequence[float]],
                          ) -> list[list[list[float]]]:
    """Clip one polyline to a user domain ring; returns the pieces.

    Requires shapely — a requested clip must never degrade to silently
    unclipped output (shared semantics of the former contouring helper).
    """
    from shapely.geometry import LineString, mapping
    from shapely.geometry.collection import GeometryCollection

    line = LineString([(float(x), float(y)) for x, y in poly])
    clipped = line.intersection(_ring_polygon(clip_ring))
    if clipped.is_empty:
        return []
    if clipped.geom_type == "GeometryCollection":
        pieces = [
            g for g in clipped.geoms
            if g.geom_type in ("LineString", "MultiLineString")
        ]
    else:
        pieces = [clipped]
    coords_out: list[list[list[float]]] = []
    for piece in pieces:
        geom = mapping(piece)
        if geom["type"] == "LineString":
            coords_out.append([[float(x), float(y)] for x, y in geom["coordinates"]])
        elif geom["type"] == "MultiLineString":
            coords_out.extend(
                [[float(x), float(y)] for x, y in part]
                for part in geom["coordinates"]
            )
    return [c for c in coords_out if len(c) >= 2]


def clip_polygon_to_ring(geom: dict, clip_ring: Sequence[Sequence[float]],
                         ) -> dict | None:
    """Intersect a GeoJSON polygon with a user domain ring; ``None`` when
    empty.  Requires shapely — never silently unclipped."""
    from shapely.geometry import MultiPolygon, mapping, shape
    from shapely.geometry.collection import GeometryCollection

    clipped = shape(geom).intersection(_ring_polygon(clip_ring))
    if clipped.is_empty:
        return None
    if clipped.geom_type == "GeometryCollection":
        polys = [g for g in clipped.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        polygons = [g for g in polys if g.geom_type == "Polygon"]
        multipolygons = [g for g in polys if g.geom_type == "MultiPolygon"]
        clipped = (
            multipolygons[0]
            if not polygons and multipolygons
            else MultiPolygon(
                [p for p in polygons]
                + [q for mp in multipolygons for q in mp.geoms])
        )
    return json.loads(json.dumps(mapping(clipped)))


# ---------------------------------------------------------------------------
# Host-authority operations


def point_in_polygon(point: Sequence[float], polygon: dict) -> ContainsResult:
    from paleo_workbench.mapping.geometry_planar import point_in_polygon_scalar

    return ContainsResult(
        point_in_polygon_scalar((float(point[0]), float(point[1])), polygon),
        ENGINE_HOST)


def area_with_unit(geometry: dict, crs: str | None) -> MeasurementResult:
    """CRS-honest area (V6 §15): projected → CRS-axis squares; geographic →
    labelled local-scale approximation; undeclared → unknown-unit².

    Sums every part's exterior minus its holes (R1-F2/R3-3: the former
    coordinates[0] shortcut silently truncated holed/multi geometries).
    """
    from paleo_workbench.mapping.geological_pipeline.geometry_units import (
        ring_area_with_unit,
    )

    geom_type = geometry.get("type")
    if geom_type == "Polygon":
        polys = [geometry.get("coordinates") or []]
    elif geom_type == "MultiPolygon":
        polys = [poly for poly in geometry.get("coordinates") or []]
    else:
        raise ValueError("area_with_unit needs a polygon geometry")
    total, unit, _warn = 0.0, "unknown-unit²", None
    for rings in polys:
        if not rings:
            continue
        exterior_value, unit, _warn = ring_area_with_unit(rings[0], crs)
        total += exterior_value
        for hole in rings[1:]:
            hole_value, _, _ = ring_area_with_unit(hole, crs)
            total -= hole_value
    return MeasurementResult(max(total, 0.0), unit, ENGINE_HOST)


def length_with_unit(geometry: dict, crs: str | None) -> MeasurementResult:
    from paleo_workbench.mapping.geological_pipeline.geometry_units import (
        polyline_length_with_unit,
    )

    coords = geometry.get("coordinates") or []
    if geometry.get("type") not in {"LineString", "MultiLineString"} or not coords:
        raise ValueError("length_with_unit needs a line geometry")
    geom_type = geometry.get("type")
    if geom_type == "LineString":
        parts = [coords]
    elif geom_type == "MultiLineString":
        # R3-2: sum ALL parts (the former coords[0] shortcut silently dropped
        # every part after the first).
        parts = [part for part in coords]
    else:  # pragma: no cover - guarded above
        raise ValueError("length_with_unit needs a line geometry")
    total, unit = 0.0, "unknown-unit"
    for part in parts:
        value, unit, _warn = polyline_length_with_unit(part, crs)
        total += value
    return MeasurementResult(total, unit, ENGINE_HOST)


def bounding_geometry(geometries: Iterable[dict]) -> tuple[float, float, float, float]:
    from paleo_workbench.mapping.geometry_planar import extent_of_geometries

    return extent_of_geometries(geometries)


def bbox_intersects(a: tuple[float, float, float, float],
                    b: tuple[float, float, float, float],
                    *,
                    tolerance: float = 0.0) -> bool:
    """AABB overlap（V8 M4 facade 补缺）。

    闭区间语义（touch = 相交）；``tolerance`` 供 QA 规则的数值余量。
    原 cartographic_qa / map_qa_rules 的手工 max/min 判定由此收敛。
    """
    axmin, aymin, axmax, aymax = (float(v) for v in a)
    bxmin, bymin, bxmax, bymax = (float(v) for v in b)
    tol = max(0.0, float(tolerance))
    return not (
        axmax < bxmin - tol
        or bxmax < axmin - tol
        or aymax < bymin - tol
        or bymax < aymin - tol
    )


def centroid(geometry: dict) -> tuple[float, float]:
    """GeoJSON 几何质心（V8 M4 facade 补缺，吸收 qc/workarea 两处顶点均值复刻）。

    Point → 自身；线 → 顶点均值（显式语义——非 shapely 的线密度积分质心，
    与既有 QC/标注放置行为一致）；面 → shoelace 面积质心（含洞、多 part
    加权），洞按符号面积减权，退化面拒绝（fail-closed）。
    """
    from paleo_workbench.mapping.geological_pipeline.polygonization import (
        calculate_signed_area,
        ring_area_centroid,
    )

    geom_type = str(geometry.get("type") or "")
    coords = geometry.get("coordinates")
    if geom_type == "Point":
        return float(coords[0]), float(coords[1])
    if geom_type in {"LineString", "MultiLineString"}:
        parts = [coords] if geom_type == "LineString" else list(coords)
        vertices: list[tuple[float, float]] = []
        for part in parts:
            vertices.extend(
                (float(p[0]), float(p[1]))
                for p in part or ()
                if isinstance(p, (list, tuple)) and len(p) >= 2
            )
        if not vertices:
            raise ValueError("centroid needs a non-empty geometry")
        return (
            sum(v[0] for v in vertices) / len(vertices),
            sum(v[1] for v in vertices) / len(vertices),
        )
    if geom_type in {"Polygon", "MultiPolygon"}:
        polys = [coords] if geom_type == "Polygon" else list(coords)
        # 面积矩守恒（review-1 P1-4）：Σ(A_ext·C_ext − Σ A_hole·C_hole) /
        # Σ(A_ext − Σ A_hole)——洞既减面积也减矩；此前只减面积的版本对
        # 非对称洞给出错误质心（恰好在中心对称洞上与真值重合）。
        area_total = 0.0
        moment_x = 0.0
        moment_y = 0.0
        for rings in polys:
            rings = list(rings or [])
            if not rings:
                continue
            exterior = [p for p in rings[0] if isinstance(p, (list, tuple)) and len(p) >= 2]
            if not exterior:
                continue
            ext_area = abs(calculate_signed_area(exterior))
            ext_cx, ext_cy = ring_area_centroid(exterior)
            part_area = ext_area
            part_moment_x = ext_cx * ext_area
            part_moment_y = ext_cy * ext_area
            for hole in rings[1:]:
                cleaned = [p for p in hole if isinstance(p, (list, tuple)) and len(p) >= 2]
                if cleaned:
                    hole_area = abs(calculate_signed_area(cleaned))
                    hole_cx, hole_cy = ring_area_centroid(cleaned)
                    part_area -= hole_area
                    part_moment_x -= hole_cx * hole_area
                    part_moment_y -= hole_cy * hole_area
            if part_area > 0.0:
                area_total += part_area
                moment_x += part_moment_x
                moment_y += part_moment_y
        if area_total <= 0.0:
            raise ValueError("centroid needs a non-degenerate polygon")
        return moment_x / area_total, moment_y / area_total
    raise ValueError(f"centroid: unsupported geometry type {geom_type!r}")


def nearest_feature(point: Sequence[float],
                    features: Sequence[dict]) -> dict[str, Any] | None:
    px, py = float(point[0]), float(point[1])
    best: tuple[float, dict[str, Any]] | None = None
    for feature in features:
        geom = feature.get("geometry") or {}
        coords = _first_coordinate(geom)
        if coords is None:
            continue
        d = math.hypot(coords[0] - px, coords[1] - py)
        if best is None or d < best[0]:
            best = (d, feature)
    if best is None:
        return None
    return best[1]


def _first_coordinate(geometry: dict) -> tuple[float, float] | None:
    coords = geometry.get("coordinates")
    while isinstance(coords, list):
        if coords and isinstance(coords[0], (int, float)):
            return float(coords[0]), float(coords[1])
        coords = coords[0] if coords else None
        if coords is None:
            return None
    return None


def topology_check(geometries: Sequence[dict]) -> TopologyReport:
    """Layer-level topology stays in TopologyService (VectorLayer flows);
    this is the geometry-level check for raw GeoJSON."""
    try:
        from shapely.geometry import shape
        from shapely.validation import explain_validity
    except ImportError as exc:
        raise RuntimeError(
            "topology_check requires shapely (or build the qgis bridge)"
        ) from exc
    issues: list[str] = []
    invalid_indices: set[int] = set()
    for index, geometry in enumerate(geometries):
        candidate = shape(geometry)
        if not candidate.is_valid:
            invalid_indices.add(index)
            issues.append(
                f"feature[{index}]: {explain_validity(candidate) or 'invalid'}")
    return TopologyReport(invalid_count=len(invalid_indices), issues=issues,
                          engine=ENGINE_SHAPELY)


def crs_transform_xy(point: Sequence[float], from_crs: str,
                     to_crs: str) -> tuple[float, float]:
    """Transform one (x, y) through the existing pyproj authority
    (:func:`make_crs_transformer`); fail-closed on unresolvable CRS."""
    import numpy as np

    from paleo_workbench.mapping.map_render_backend import (
        make_crs_transformer,
        reproject_xy,
    )

    transformer = make_crs_transformer(from_crs, to_crs)
    array = np.array([[float(point[0]), float(point[1])]])
    out = reproject_xy(array, transformer) if transformer is not None else array
    return float(out[0, 0]), float(out[0, 1])
