"""Constraint geometry sync-back (goal §11, audit P0-3).

``create_constraint`` (ui/workstation/stage_actions.py) registers an editable
``UserVectorLayer`` plus a ``ConstraintLine`` whose ``coordinates`` are EMPTY —
geometry is digitized into the vector layer, and the engine-side line used by
interpolation could silently diverge.  This module harvests the digitized
features back into the linked ``ConstraintLine`` entries and stamps a content
fingerprint so downstream freshness evaluation has a comparison baseline
(``constraints:current``).

Matching rule (conservative, machine-readable signals only):

1. primary — ``ConstraintLine.properties["layer_id"] == layer_id`` (the stamp
   ``create_constraint`` writes);
2. fallback — same ``constraint_kind`` AND the line name equals the layer
   name AND the line still has empty coordinates (legacy layers created
   before the ``layer_id`` stamp existed).

Harvest semantics:

* line-kind layers — one coordinate sequence per feature (MultiLineString
  parts are joined, dropping duplicated joint vertices);
* polygon kinds (mask / exclusion area) — the exterior ring of each feature,
  **closed** (first vertex appended when the digitizer left it open; the
  interpolation ring consumer requires closed rings);
* a layer with multiple features syncs one ``ConstraintLine`` per feature
  (the first matched line keeps its identity; extras are appended with the
  same ``layer_id`` stamp); stale extra lines from a previous sync are
  replaced, never accumulated;
* every synced line's ``properties`` gains ``{"content_fingerprint":
  sha256(coordinates)}``.

Wiring: called from ``StageActionDispatcher.stage_save`` (after
``flush_edit_sessions`` has committed the vector layers into
``ProjectDocument.user_vector_layers``).  It is deliberately a pure document
transform — no Qt — so readiness/overlay paths can also call it directly.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from paleo_workbench.mapping_workspace.layer_roles import (
    constraint_kind_from_value,
)

__all__ = [
    "constraint_content_fingerprint",
    "sync_constraint_geometry",
]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _vertex(point: Any) -> list[float] | None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    x = _finite(point[0])
    y = _finite(point[1])
    if x is None or y is None:
        return None
    return [x, y]


def constraint_content_fingerprint(coordinates: Iterable[Iterable[float]]) -> str:
    """sha256 over a canonical encoding of the coordinate sequence.

    Same coordinates → same hash (floats are rounded to 9 decimals so trivial
    representation noise does not churn the fingerprint).
    """
    canonical = [
        [round(float(point[0]), 9), round(float(point[1]), 9)]
        for point in coordinates
        if _vertex(point) is not None
    ]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _line_kind_of(layer: Any) -> bool:
    kind = constraint_kind_from_value(str(getattr(layer, "template", "") or ""))
    if kind is not None:
        return kind.geometry_kind != "polygon"
    return str(getattr(layer, "geometry_kind", "line") or "line") != "polygon"


def _harvest_coordinates(layer: Any) -> tuple[list[list[list[float]]], int]:
    """Feature geometries → coordinate sequences (closed rings for polygons).

    Returns ``(sequences, holes_seen)`` where holes_seen counts interior
    rings skipped by polygon harvesting (the interpolation ring consumer
    uses exterior domains only).
    """
    is_line = _line_kind_of(layer)
    sequences: list[list[list[float]]] = []
    holes = 0
    for feature in getattr(layer, "features", None) or []:
        geometry = getattr(feature, "geometry", None)
        if not isinstance(geometry, Mapping):
            continue
        gtype = str(geometry.get("type") or "")
        coordinates = geometry.get("coordinates")
        if not coordinates:
            continue
        if is_line:
            parts: list[Any] = []
            if gtype == "LineString":
                parts = [coordinates]
            elif gtype == "MultiLineString":
                parts = list(coordinates)
            else:
                continue
            merged: list[list[float]] = []
            for part in parts:
                for point in part or []:
                    vertex = _vertex(point)
                    if vertex is None:
                        continue
                    if merged and merged[-1] == vertex:
                        continue  # drop duplicated joints between parts
                    merged.append(vertex)
            if len(merged) >= 2:
                sequences.append(merged)
        else:
            if gtype == "Polygon":
                rings = list(coordinates)
            elif gtype == "MultiPolygon":
                rings = [ring for poly in coordinates for ring in poly]
            else:
                continue
            for index, ring in enumerate(rings):
                points: list[list[float]] = []
                for point in ring or []:
                    vertex = _vertex(point)
                    if vertex is not None:
                        points.append(vertex)
                if len(points) < 3:
                    continue
                if index == 0:
                    # Ring closure for polygon kinds (mask / exclusion):
                    # the boundary-ring consumer requires first == last.
                    if points[0] != points[-1]:
                        points.append(list(points[0]))
                    sequences.append(points)
                else:
                    holes += 1
    return sequences, holes


def _linked_lines(document: Any, layer: Any, layer_id: str) -> tuple[list, str]:
    """Find the ConstraintLine entries linked to this vector layer."""
    kind_value = str(getattr(layer, "template", "") or "")
    layer_name = str(getattr(layer, "name", "") or "")
    by_layer_id: list = []
    by_kind: list = []
    for group in getattr(document, "constraint_layers", None) or []:
        for line in group.lines:
            properties = line.properties or {}
            if str(properties.get("layer_id") or "") == layer_id:
                by_layer_id.append(line)
            elif (
                kind_value
                and str(properties.get("constraint_kind") or "") == kind_value
                and str(line.name or "") == layer_name
                and not line.coordinates
            ):
                by_kind.append(line)
    if by_layer_id:
        return by_layer_id, "layer_id"
    if by_kind:
        return by_kind, "constraint_kind+name"
    return [], ""


def _target_group(document: Any, matched: list):
    for group in getattr(document, "constraint_layers", None) or []:
        if any(line in group.lines for line in matched):
            return group
    groups = getattr(document, "constraint_layers", None)
    if groups is None:
        return None
    if groups:
        return groups[0]
    from paleo_workbench.project.models import ConstraintLayers

    group = ConstraintLayers(name="约束层")
    document.constraint_layers.append(group)
    return group


def sync_constraint_geometry(document: Any, layer_id: str) -> dict:
    """Harvest a constraint ``UserVectorLayer``'s features into the linked
    ``ConstraintLine.coordinates`` (+ content fingerprint).

    Returns a report dict; ``ok`` is False with a ``reason`` when nothing
    was synced (unknown layer / not a constraint layer / empty layer).
    """
    layer_id = str(layer_id or "")
    layer = None
    for candidate in getattr(document, "user_vector_layers", None) or []:
        if str(getattr(candidate, "id", "") or "") == layer_id:
            layer = candidate
            break
    if layer is None:
        return {"ok": False, "reason": "layer_not_found", "layer_id": layer_id}
    kind = constraint_kind_from_value(str(getattr(layer, "template", "") or ""))
    if kind is None:
        return {
            "ok": False,
            "reason": "not_a_constraint_layer",
            "layer_id": layer_id,
        }
    sequences, holes = _harvest_coordinates(layer)
    if not sequences:
        # Never wipe previously synced geometry based on an empty transient
        # state (digitizing may still be in progress).
        return {
            "ok": False,
            "reason": "layer_empty",
            "layer_id": layer_id,
            "constraint_kind": kind.value,
        }

    matched, matched_by = _linked_lines(document, layer, layer_id)
    group = _target_group(document, matched)
    if group is None:
        return {"ok": False, "reason": "no_constraint_group", "layer_id": layer_id}

    template_line = matched[0] if matched else None
    # Replace semantics: stale extra lines from a previous sync are dropped
    # (never accumulated), then one line per harvested sequence is appended.
    stale = set(id(line) for line in matched)
    group.lines = [line for line in group.lines if id(line) not in stale]

    from paleo_workbench.project.models import ConstraintLine

    synced: list[ConstraintLine] = []
    for index, coordinates in enumerate(sequences):
        fingerprint = constraint_content_fingerprint(coordinates)
        if index == 0 and template_line is not None:
            line = template_line
            line.coordinates = coordinates
        else:
            line = ConstraintLine(
                name=str(getattr(layer, "name", "") or kind.label),
                role=template_line.role if template_line is not None
                else kind.interpolation_role,
                target_horizon=(
                    template_line.target_horizon if template_line is not None
                    else str(getattr(group, "target_horizon", "") or "")
                ),
                properties={
                    "layer_id": layer_id,
                    "constraint_kind": kind.value,
                    "feature_index": index,
                },
            )
            line.coordinates = coordinates
        group.lines.append(line)
        properties = dict(line.properties or {})
        properties["layer_id"] = layer_id
        properties["constraint_kind"] = kind.value
        properties["content_fingerprint"] = fingerprint
        line.properties = properties
        synced.append(line)

    aggregate = constraint_content_fingerprint(
        [point for coordinates in sequences for point in coordinates])
    return {
        "ok": True,
        "layer_id": layer_id,
        "constraint_kind": kind.value,
        "matched_by": matched_by or "created_new_line",
        "lines_synced": len(synced),
        "features_harvested": len(sequences),
        "interior_rings_skipped": holes,
        "coordinates_total": sum(len(seq) for seq in sequences),
        "content_fingerprint": aggregate,
    }
