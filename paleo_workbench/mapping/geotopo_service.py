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
    "polygonize_control_lines",
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
