"""Geological topology service — control-line polygonization (geotopo Ticket 1).

ONE host entry point per geological-topology operation
(``docs/development/geotopo-editor/02-interface-contracts.md`` §4.1).
Preferred engine is the bridge ``qgis_render_bridge.geotopo`` submodule
(native DCEL core); without the bridge the same contract runs on shapely
(``unary_union`` noding + ``polygonize``).  Results disclose the engine via
``.engine`` — degradation is visible, never silent.

Error contract: every failure raises :class:`GeoTopoError` carrying the
contract error code (``PWB-GT-001`` …), identical on both engines.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Sequence

from paleo_workbench.mapping.qgis_style import qgis_bridge_available

__all__ = [
    "ENGINE_QGIS",
    "ENGINE_SHAPELY",
    "GeoTopoError",
    "GeoTopoPolygon",
    "GeoTopoResult",
    "ReshapePair",
    "SharedArc",
    "find_shared_arcs",
    "polygonize_control_lines",
    "reshape_shared_arc",
    "smooth_curve",
]

ENGINE_QGIS = "qgis"
ENGINE_SHAPELY = "shapely-fallback"

_BRIDGE_PROBE: bool | None = None


class GeoTopoError(RuntimeError):
    """Contract error with a machine-readable ``PWB-GT-xxx`` code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GeoTopoPolygon:
    geometry: dict[str, Any]
    area: float
    centroid: tuple[float, float]
    source_lines: tuple[str, ...]
    ring_closed: bool = True


@dataclass(frozen=True)
class GeoTopoResult:
    engine: str
    polygons: list[GeoTopoPolygon]
    dropped_dangles: int
    node_count: int
    edge_count: int
    elapsed_ms: float


def _bridge_geotopo():
    """Return the bridge geotopo submodule (or None when unavailable)."""
    global _BRIDGE_PROBE
    if _BRIDGE_PROBE is None:
        _BRIDGE_PROBE = qgis_bridge_available()
    if not _BRIDGE_PROBE:
        return None
    import qgis_render_bridge as native

    return getattr(native, "geotopo", None)


def _validate_lines(lines: Sequence[dict]) -> list[dict]:
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)):
        raise GeoTopoError("PWB-GT-001", "lines must be a sequence of control-line records")
    validated: list[dict] = []
    for record in lines:
        if not isinstance(record, dict) or "id" not in record or "path" not in record:
            raise GeoTopoError("PWB-GT-001", "each line needs 'id' and 'path'")
        path = record["path"]
        if len(path) < 2:
            raise GeoTopoError("PWB-GT-001", f"line {record['id']!r} has fewer than 2 vertices")
        for point in path:
            if len(point) != 2:
                raise GeoTopoError("PWB-GT-001", f"line {record['id']!r} has a non-2D vertex")
            x, y = float(point[0]), float(point[1])
            if not (math.isfinite(x) and math.isfinite(y)):
                raise GeoTopoError("PWB-GT-001", f"line {record['id']!r} has a non-finite vertex")
        validated.append({"id": str(record["id"]), "path": [[float(p[0]), float(p[1])] for p in path]})
    return validated


def _validate_options(tolerance: float, clip_envelope: Sequence[float] | None) -> tuple[float, list[float] | None]:
    if not (isinstance(tolerance, (int, float)) and math.isfinite(tolerance) and tolerance > 0):
        raise GeoTopoError("PWB-GT-002", "tolerance must be a positive finite number")
    envelope: list[float] | None = None
    if clip_envelope is not None:
        if len(clip_envelope) != 4:
            raise GeoTopoError("PWB-GT-001", "clip_envelope must be [xmin, ymin, xmax, ymax]")
        envelope = [float(v) for v in clip_envelope]
        if envelope[0] > envelope[2] or envelope[1] > envelope[3]:
            raise GeoTopoError("PWB-GT-001", "clip_envelope is inverted")
    return float(tolerance), envelope


def polygonize_control_lines(
    lines: Sequence[dict],
    *,
    tolerance: float = 1e-6,
    clip_envelope: Sequence[float] | None = None,
    min_ring_area: float = 0.0,
) -> GeoTopoResult:
    """Polygonize a control-line network (shorelines, facies boundaries, faults).

    Returns every bounded face of the planar subdivision as an OGC polygon
    (CCW exterior ring) with its parent control-line provenance; the unbounded
    outer face is excluded, optional ``clip_envelope`` drops faces not fully
    inside it.  Raises :class:`GeoTopoError` on contract violations.
    """
    validated = _validate_lines(lines)
    tolerance, envelope = _validate_options(tolerance, clip_envelope)
    if not validated:
        return GeoTopoResult(_current_engine_name(), [], 0, 0, 0, 0.0)

    options: dict[str, Any] = {"tolerance": tolerance, "min_ring_area": min_ring_area}
    if envelope is not None:
        options["clip_envelope"] = envelope

    bridge = _bridge_geotopo()
    started = time.perf_counter()
    if bridge is not None:
        return _polygonize_via_bridge(bridge, validated, options, started)
    return _polygonize_via_shapely(validated, tolerance, envelope, min_ring_area, started)


def _current_engine_name() -> str:
    return ENGINE_QGIS if _bridge_geotopo() is not None else ENGINE_SHAPELY


def _polygonize_via_bridge(bridge, lines: list[dict], options: dict, started: float) -> GeoTopoResult:
    try:
        envelope_json = bridge.polygonize_control_lines(
            json.dumps({"lines": lines}), json.dumps(options))
    except Exception as exc:  # bridge contract wraps everything in the envelope
        raise GeoTopoError("PWB-GT-001", f"bridge call failed: {exc}") from exc
    try:
        payload = json.loads(envelope_json)
    except (TypeError, ValueError) as exc:
        raise GeoTopoError("PWB-GT-001", f"bridge returned malformed json: {exc}") from exc
    if payload.get("status") != "ok":
        raise GeoTopoError(payload.get("code", "PWB-GT-001"), payload.get("message", "unknown error"))
    polygons = [
        GeoTopoPolygon(
            geometry=item["geometry"],
            area=float(item["area"]),
            centroid=(float(item["centroid"][0]), float(item["centroid"][1])),
            source_lines=tuple(item.get("source_lines", ())),
            ring_closed=bool(item.get("ring_closed", True)),
        )
        for item in payload["polygons"]
    ]
    return GeoTopoResult(
        engine=ENGINE_QGIS,
        polygons=polygons,
        dropped_dangles=int(payload.get("dropped_dangles", 0)),
        node_count=int(payload.get("node_count", 0)),
        edge_count=int(payload.get("edge_count", 0)),
        elapsed_ms=float(payload.get("elapsed_ms", (time.perf_counter() - started) * 1000.0)),
    )


def _polygonize_via_shapely(
    lines: list[dict],
    tolerance: float,
    envelope: list[float] | None,
    min_ring_area: float,
    started: float,
) -> GeoTopoResult:
    import shapely
    from shapely.geometry import LineString, MultiLineString, box
    from shapely.geometry.polygon import orient
    from shapely.ops import polygonize, unary_union

    geoms = []
    for record in lines:
        geometry = LineString(record["path"])
        if tolerance > 0:
            geometry = shapely.set_precision(geometry, tolerance)
        geoms.append(geometry)
    noded = unary_union(geoms)
    if noded.is_empty:
        return GeoTopoResult(ENGINE_SHAPELY, [], 0, 0, 0,
                             (time.perf_counter() - started) * 1000.0)

    pieces = list(noded.geoms) if isinstance(noded, MultiLineString) else [noded]
    faces = [orient(polygon, sign=1.0) for polygon in polygonize(pieces)]
    faces = [polygon for polygon in faces if polygon.area > max(min_ring_area, 0.0)]
    if envelope is not None:
        clip_box = box(envelope[0], envelope[1], envelope[2], envelope[3])
        faces = [polygon for polygon in faces if polygon.within(clip_box)]

    merged_boundary = unary_union([polygon.boundary for polygon in faces])
    dangling = noded.difference(merged_boundary)
    if dangling.is_empty:
        dropped = 0
    elif isinstance(dangling, MultiLineString):
        dropped = len(dangling.geoms)
    else:
        dropped = 1

    pieces = list(noded.geoms) if isinstance(noded, MultiLineString) else [noded]
    edge_count = len(pieces)  # pieces are also the polygonizer input above
    node_count = len({coordinate for piece in pieces for coordinate in piece.coords})

    polygons_out: list[GeoTopoPolygon] = []
    for polygon in faces:
        ring = polygon.exterior.coords
        parents = tuple(
            record["id"]
            for record, geometry in zip(lines, geoms)
            if geometry.intersects(polygon.boundary)
        )
        centroid = polygon.centroid
        polygons_out.append(GeoTopoPolygon(
            geometry=_polygon_geometry(polygon),
            area=float(polygon.area),
            centroid=(float(centroid.x), float(centroid.y)),
            source_lines=parents,
        ))
    return GeoTopoResult(
        engine=ENGINE_SHAPELY,
        polygons=polygons_out,
        dropped_dangles=dropped,
        node_count=node_count,
        edge_count=edge_count,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )


def _polygon_geometry(polygon) -> dict[str, Any]:
    from shapely.geometry import mapping

    geometry = mapping(polygon)
    coordinates = [
        [[float(x), float(y)] for x, y in ring]
        for ring in geometry["coordinates"]
    ]
    return {"type": "Polygon", "coordinates": coordinates}


# ---------------------------------------------------------------------------
# geotopo Ticket 3：共边查找与联动重塑（契约 §1.2/§1.3）。


@dataclass(frozen=True)
class SharedArc:
    arc: tuple[tuple[float, float], ...]
    length: float
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True)
class ReshapePair:
    polygon_a: dict[str, Any]
    polygon_b: dict[str, Any]
    area_before: float
    area_after: float
    area_residual: float


def _open_ring(geometry: dict[str, Any]) -> list[list[float]]:
    if geometry.get("type") != "Polygon":
        raise GeoTopoError("PWB-GT-001", "polygon geometry required")
    ring = [[float(x), float(y)] for x, y in geometry["coordinates"][0]]
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        raise GeoTopoError("PWB-GT-001", "polygon ring needs >= 3 distinct vertices")
    return ring


def _chain_points(value: Sequence[Sequence[float]], what: str) -> list[list[float]]:
    points = [[float(p[0]), float(p[1])] for p in value]
    if len(points) >= 2 and points[0] == points[-1]:
        points.pop()
    if len(points) < 2:
        raise GeoTopoError("PWB-GT-001", f"{what} needs >= 2 distinct points")
    return points


def _interned_sequence(points: list[list[float]], tolerance: float) -> list[tuple[int, int]]:
    return [(int(round(p[0] / tolerance)), int(round(p[1] / tolerance))) for p in points]


def find_shared_arcs(
    polygon_a: dict[str, Any],
    polygon_b: dict[str, Any],
    *,
    tolerance: float = 1e-6,
) -> list[SharedArc]:
    """两多边形外环在容差内的全部共享弧（≥2 节点；角点触碰不算）。"""
    tolerance, _unused = _validate_options(tolerance, None)
    ring_a = _open_ring(polygon_a)
    ring_b = _open_ring(polygon_b)
    seq_a = _interned_sequence(ring_a, tolerance)
    seq_b = _interned_sequence(ring_b, tolerance)
    n, m = len(seq_a), len(seq_b)
    pos_b: dict[tuple[int, int], list[int]] = {}
    for j, node in enumerate(seq_b):
        pos_b.setdefault(node, []).append(j)

    claimed = [False] * n
    arcs: list[SharedArc] = []
    recorded: set[tuple[int, int]] = set()
    for i in range(n):
        if claimed[i]:
            continue
        for j0 in pos_b.get(seq_a[i], ()):
            for step in (1, -1):
                bi = i
                bj = j0
                for _guard in range(n):
                    pi = (bi - 1) % n
                    pj = (bj - step) % m
                    if seq_a[pi] != seq_b[pj] or (pi + 1) % n == i:
                        break
                    bi, bj = pi, pj
                ei, ej = bi, bj
                for _guard in range(n):
                    ni = (ei + 1) % n
                    nj = (ej + step) % m
                    if seq_a[ni] != seq_b[nj] or ni == bi:
                        break
                    ei, ej = ni, nj
                if ei == bi or (bi, ei) in recorded:
                    continue
                recorded.add((bi, ei))
                chain = []
                k = bi
                while True:
                    chain.append(ring_a[k])
                    claimed[k] = True
                    if k == ei:
                        break
                    k = (k + 1) % n
                length = sum(
                    math.hypot(chain[q + 1][0] - chain[q][0],
                               chain[q + 1][1] - chain[q][1])
                    for q in range(len(chain) - 1))
                arcs.append(SharedArc(
                    arc=tuple((p[0], p[1]) for p in chain),
                    length=length,
                    start=(chain[0][0], chain[0][1]),
                    end=(chain[-1][0], chain[-1][1])))
                break
            if claimed[i]:
                break
    return arcs


def _ring_signed_area(ring: list[list[float]]) -> float:
    return sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1]
        - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring))) / 2.0


def _locate_arc(ring: list[list[float]], seq: list[tuple[int, int]],
                arc_ids: list[tuple[int, int]]) -> tuple[int, int] | None:
    """返回 (起始下标, 方向)：弧节点链在环内唯一子序列匹配。"""
    count = len(seq)
    arc_len = len(arc_ids)
    if arc_len >= count:
        return None
    for i in range(count):
        for direction in (1, -1):
            wanted = arc_ids if direction == 1 else list(reversed(arc_ids))
            if all(seq[(i + k) % count] == wanted[k] for k in range(arc_len)):
                return i, direction
    return None


def reshape_shared_arc(
    polygon_a: dict[str, Any],
    polygon_b: dict[str, Any],
    arc: Sequence[Sequence[float]],
    curve: Sequence[Sequence[float]],
    *,
    tolerance: float = 1e-6,
) -> ReshapePair:
    """共边联动重塑（契约 §1.3）：同一 curve 替换两侧共享弧，拒绝式守恒。"""
    bridge = _bridge_geotopo()
    if bridge is not None:
        return _reshape_via_bridge(bridge, polygon_a, polygon_b, arc, curve, tolerance)
    return _reshape_via_shapely(polygon_a, polygon_b, arc, curve, tolerance)


def _reshape_via_bridge(bridge, polygon_a, polygon_b, arc, curve, tolerance) -> ReshapePair:
    payload = json.loads(bridge.reshape_shared_arc(
        json.dumps(polygon_a), json.dumps(polygon_b),
        json.dumps([list(p) for p in arc]), json.dumps([list(p) for p in curve]),
        tolerance))
    if payload.get("status") != "ok":
        raise GeoTopoError(payload.get("code", "PWB-GT-201"),
                           payload.get("message", "reshape failed"))
    return ReshapePair(
        polygon_a=payload["polygon_a"],
        polygon_b=payload["polygon_b"],
        area_before=float(payload["area_before"]),
        area_after=float(payload["area_after"]),
        area_residual=float(payload["area_residual"]),
    )


def _reshape_via_shapely(polygon_a, polygon_b, arc, curve, tolerance) -> ReshapePair:
    from shapely.geometry import Polygon, mapping, shape

    tolerance, _unused = _validate_options(tolerance, None)
    ring_a = _open_ring(polygon_a)
    ring_b = _open_ring(polygon_b)
    arc_points = _chain_points(arc, "arc")
    curve_points = _chain_points(curve, "curve")

    area_before = abs(_ring_signed_area(ring_a)) + abs(_ring_signed_area(ring_b))
    arc_ids_full = _interned_sequence(arc_points, tolerance)
    arc_ids: list[tuple[int, int]] = []
    for node in arc_ids_full:
        if not arc_ids or arc_ids[-1] != node:
            arc_ids.append(node)
    if len(arc_ids) < 2:
        raise GeoTopoError("PWB-GT-201", "arc degenerates under tolerance")

    seq_a = _interned_sequence(ring_a, tolerance)
    seq_b = _interned_sequence(ring_b, tolerance)
    hit_a = _locate_arc(ring_a, seq_a, arc_ids)
    hit_b = _locate_arc(ring_b, seq_b, arc_ids)
    if hit_a is None or hit_b is None:
        raise GeoTopoError("PWB-GT-201", "shared arc not found within tolerance")

    def build_ring(ring: list[list[float]], hit: tuple[int, int]) -> list[list[float]]:
        start, direction = hit
        rotated = [ring[(start + k) % len(ring)] for k in range(len(ring))]
        insert = curve_points if direction == 1 else list(reversed(curve_points))
        return insert + rotated[len(arc_ids):]

    new_a = build_ring(ring_a, hit_a)
    new_b = build_ring(ring_b, hit_b)

    geom_a = Polygon(new_a)
    geom_b = Polygon(new_b)
    if not geom_a.is_valid or not geom_b.is_valid:
        raise GeoTopoError("PWB-GT-202", "reshaped ring invalid: self-intersection")
    if geom_a.intersection(geom_b).area > tolerance * max(
            1.0, _chain_length(curve_points)):
        raise GeoTopoError("PWB-GT-203", "reshaped rings overlap each other")
    area_after = geom_a.area + geom_b.area
    residual = abs(area_after - area_before)
    if residual > tolerance * max(1.0, _chain_length(curve_points)):
        raise GeoTopoError("PWB-GT-204",
                           f"area conservation failed (residual={residual})")
    union_area = geom_a.union(geom_b).area
    if abs(union_area - area_before) > tolerance * max(1.0, _chain_length(curve_points)):
        raise GeoTopoError("PWB-GT-203", "reshape opens a gap between the polygons")
    return ReshapePair(
        polygon_a=_polygon_json(geom_a),
        polygon_b=_polygon_json(geom_b),
        area_before=area_before,
        area_after=area_after,
        area_residual=residual,
    )


def _chain_length(points: list[list[float]]) -> float:
    return sum(math.hypot(points[i + 1][0] - points[i][0],
                          points[i + 1][1] - points[i][1])
               for i in range(len(points) - 1))


def _polygon_json(polygon) -> dict[str, Any]:
    from shapely.geometry import mapping

    coordinates = [
        [[float(x), float(y)] for x, y in ring]
        for ring in mapping(polygon)["coordinates"]
    ]
    return {"type": "Polygon", "coordinates": coordinates}


def smooth_curve(curve: Sequence[Sequence[float]], *, subdivisions: int = 8) -> list[list[float]]:
    """Catmull-Rom 过采样（端点保持）；重塑前可选的样条平滑。"""
    points = [list(map(float, p)) for p in curve]
    if len(points) < 3 or subdivisions <= 0:
        return points
    padded = [points[0]] + points + [points[-1]]
    smooth: list[list[float]] = []  # 每段 t∈[0,1) 生成，末点单独补——零重复
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        for step in range(subdivisions):
            t = step / subdivisions
            t2, t3 = t * t, t * t * t
            smooth.append([
                0.5 * ((2 * p1[0])
                       + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
                0.5 * ((2 * p1[1])
                       + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
            ])
    smooth.append(points[-1])
    return smooth
 
