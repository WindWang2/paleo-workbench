"""ConstraintLayers adapters: break / direction lines for interpolation & mapping."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    PaleoMapDocument,
    ProjectDocument,
    _id,
)


def _as_xy_ring(coords: Sequence[Any]) -> list[tuple[float, float]]:
    """Normalize coordinate payloads to list of (x, y) floats (len >= 2)."""
    pts: list[tuple[float, float]] = []
    for p in coords or []:
        try:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append((float(p[0]), float(p[1])))
            elif isinstance(p, dict):
                if "x" in p and "y" in p:
                    pts.append((float(p["x"]), float(p["y"])))
                elif "lng" in p and "lat" in p:
                    pts.append((float(p["lng"]), float(p["lat"])))
        except (TypeError, ValueError):
            continue
    return pts


def active_lines(
    layers: ConstraintLayers | Iterable[ConstraintLayers] | None,
    *,
    role: str | None = None,
    target_horizon: str | None = None,
) -> list[ConstraintLine]:
    """Collect active lines, optionally filtered by role and horizon."""
    if layers is None:
        return []
    bag: list[ConstraintLayers]
    if isinstance(layers, ConstraintLayers):
        bag = [layers]
    else:
        bag = list(layers)
    out: list[ConstraintLine] = []
    for layer in bag:
        for line in layer.lines:
            if not line.active:
                continue
            if role is not None and line.role != role:
                continue
            if target_horizon:
                line_h = (line.target_horizon or layer.target_horizon or "").strip()
                if line_h and line_h != target_horizon:
                    continue
            out.append(line)
    return out


def break_polylines_for_idw(
    layers: ConstraintLayers | Iterable[ConstraintLayers] | None,
    *,
    target_horizon: str | None = None,
) -> list[list[tuple[float, float]]]:
    """Export active break lines as IDW ``fault_polylines`` payload."""
    polylines: list[list[tuple[float, float]]] = []
    for line in active_lines(layers, role="break", target_horizon=target_horizon):
        pts = _as_xy_ring(line.coordinates)
        if len(pts) >= 2:
            polylines.append(pts)
    return polylines


def direction_line_params(
    layers: ConstraintLayers | Iterable[ConstraintLayers] | None,
    *,
    target_horizon: str | None = None,
) -> list[dict[str, Any]]:
    """Serialize active direction lines for anisotropic trend-surface (ISS-ALG-02)."""
    params: list[dict[str, Any]] = []
    for line in active_lines(layers, role="direction", target_horizon=target_horizon):
        pts = _as_xy_ring(line.coordinates)
        az = line.azimuth_deg
        if az is None and len(pts) >= 2:
            # Bearing of first segment as default major axis.
            import math

            dx = pts[-1][0] - pts[0][0]
            dy = pts[-1][1] - pts[0][1]
            az = math.degrees(math.atan2(dx, dy)) % 360.0  # from north, clockwise-ish
        params.append(
            {
                "id": line.id,
                "name": line.name,
                "azimuth_deg": az,
                # Unset axes stay None so the engine adapter applies haiyou's
                # default anisotropy ratio (18:1). The old 1.0/0.5 placeholder
                # collapsed the ratio to 2:1 and made direction lines nearly
                # decorative (#927).
                "semi_major": line.semi_major,
                "semi_minor": line.semi_minor,
                "coordinates": [[p[0], p[1]] for p in pts],
            }
        )
    return params


def constraint_layers_for_project(
    project: ProjectDocument,
    *,
    target_horizon: str | None = None,
) -> list[ConstraintLayers]:
    if not target_horizon:
        return list(project.constraint_layers)
    return [
        layer
        for layer in project.constraint_layers
        if not layer.target_horizon or layer.target_horizon == target_horizon
    ]


def upsert_constraint_layers(
    project: ProjectDocument, layers: ConstraintLayers
) -> ConstraintLayers:
    for i, existing in enumerate(project.constraint_layers):
        if existing.id == layers.id:
            project.constraint_layers[i] = layers
            return layers
    project.constraint_layers.append(layers)
    return layers


def constraint_line_from_map_feature(feature: dict[str, Any]) -> ConstraintLine | None:
    """Interpret a map edit line feature dict as a ConstraintLine when role is set."""
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    role = str(feature.get("role") or props.get("role") or props.get("constraint_role") or "")
    if role not in {"break", "direction", "boundary", "other"}:
        # Plain map lines without role are not constraints.
        if role:
            return None
        return None
    coords = feature.get("coordinates")
    if coords is None and isinstance(feature.get("geometry"), dict):
        geom = feature["geometry"]
        if geom.get("type") == "LineString":
            coords = geom.get("coordinates")
    pts = _as_xy_ring(coords or [])
    if len(pts) < 2:
        return None
    return ConstraintLine(
        id=str(feature.get("id") or props.get("id") or _id("cline")),
        name=str(feature.get("name") or props.get("name") or ""),
        role=role,  # type: ignore[arg-type]
        coordinates=[[p[0], p[1]] for p in pts],
        azimuth_deg=_float_or_none(feature.get("azimuth_deg", props.get("azimuth_deg"))),
        semi_major=_float_or_none(feature.get("semi_major", props.get("semi_major"))),
        semi_minor=_float_or_none(feature.get("semi_minor", props.get("semi_minor"))),
        active=bool(feature.get("active", props.get("active", True))),
        target_horizon=str(
            feature.get("target_horizon") or props.get("target_horizon") or ""
        ),
        properties=dict(props),
    )


def constraints_from_map_document(
    doc: PaleoMapDocument,
    *,
    name: str | None = None,
) -> ConstraintLayers:
    """Harvest constraint-role line_features from a PaleoMapDocument."""
    lines: list[ConstraintLine] = []
    for feat in doc.line_features or []:
        cl = constraint_line_from_map_feature(feat)
        if cl is not None:
            if not cl.target_horizon:
                cl.target_horizon = doc.linked_target_horizon
            lines.append(cl)
    return ConstraintLayers(
        name=name or f"{doc.name} 约束",
        target_horizon=doc.linked_target_horizon,
        lines=lines,
    )


def line_features_from_constraints(
    layers: ConstraintLayers | Iterable[ConstraintLayers],
) -> list[dict[str, Any]]:
    """Export constraints as map-edit line_features (role stamped)."""
    if isinstance(layers, ConstraintLayers):
        bag = [layers]
    else:
        bag = list(layers)
    features: list[dict[str, Any]] = []
    for layer in bag:
        for line in layer.lines:
            pts = _as_xy_ring(line.coordinates)
            if len(pts) < 2:
                continue
            features.append(
                {
                    "id": line.id,
                    "kind": "line",
                    "name": line.name or line.role,
                    "role": line.role,
                    "coordinates": [[p[0], p[1]] for p in pts],
                    "properties": {
                        "role": line.role,
                        "constraint_role": line.role,
                        "azimuth_deg": line.azimuth_deg,
                        "semi_major": line.semi_major,
                        "semi_minor": line.semi_minor,
                        "target_horizon": line.target_horizon or layer.target_horizon,
                        **(line.properties or {}),
                    },
                }
            )
    return features


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def boundary_rings_for_engine(
    layers: ConstraintLayers | Iterable[ConstraintLayers] | None,
    *,
    target_horizon: str | None = None,
) -> list[list[tuple[float, float]]]:
    """Export active user-drawn boundary rings for the interpolation domain.

    #928: the ``boundary`` constraint role previously had no consumer — the
    constrained-IDW adapter silently replaced the user's geological intent
    with a synthesized sample hull. Rings need >= 4 points (closed polygon)
    to be a usable domain.
    """
    rings: list[list[tuple[float, float]]] = []
    for line in active_lines(layers, role="boundary", target_horizon=target_horizon):
        pts = _as_xy_ring(line.coordinates)
        # Close the ring if the drawer left it open (first != last).
        if len(pts) >= 3 and pts[0] != pts[-1]:
            pts = list(pts) + [pts[0]]
        if len(pts) >= 4:
            rings.append(pts)
    return rings
