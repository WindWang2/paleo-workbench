"""Layer-descriptor builders for the staged factor-map workflow (goal §10-12).

A Stage-2 factor group must carry SIX children per ``FACTOR_CHILD_ORDER``
(input points → scalar grid → contours → classification polygons →
uncertainty surface → QC overlay).  This module builds plain layer
*descriptors* — dicts with ``layer_id / role / title / geometry_kind /
features-or-payload / metadata`` — with **no Qt dependency**, so the stage
action layer stays a thin orchestrator while scientific truth (live
``FactorGridResult`` vs task metadata) is decided by the caller.

Honesty rules (mirroring the ``FactorGridResult`` design contract):

* **No invented data.**  The uncertainty child exists only when the
  algorithm produced a ``variance_grid`` (kriging); its absence is reported
  as an info QC point on the QC child instead of a fabricated layer.
* **Scalar children are descriptors only.**  The grid / uncertainty children
  carry the ``FactorGridResult``-derived metadata the scalar publish path
  needs (extent, statistics, artifact version, run ref) under ``payload``.
  Rendering them requires the canvas snapshot path, which may be absent
  (no QGIS bridge); the descriptor is still produced so the factor group is
  complete in domain state.  Grid arrays never cross into descriptors.
* **Derived vector children come from the live grid only** — contours reuse
  ``geological_pipeline.contouring``, classifications reuse
  ``geological_pipeline.polygonization``; without a live grid those children
  are empty with an explicit ``absent_reason`` (no silent recompute).
* Contour features are capped (``contour_limit``); truncation is reported
  in metadata, never silent.

Prediction confidence overlays and integrated-boundary ring extraction
live here too, so Phase-1/Phase-3 stage actions consume the same pure
descriptor vocabulary (``confidence_overlay_layers``,
``integrated_boundary_action_helpers``).
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

import numpy as np

from paleo_workbench.mapping_workspace.layer_groups import factor_group_title
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = [
    "SCALAR_GRID_LAYER_TYPE",
    "classify_prediction_task",
    "confidence_overlay_layers",
    "factor_group_layers",
    "integrated_boundary_action_helpers",
    "boundary_features_from_polygons",
]

#: Runtime layer type for scalar-grid semantics (``mapping.layers.LayerType``).
SCALAR_GRID_LAYER_TYPE = "scalar_grid"

#: Feature property keys that carry a prediction probability / confidence.
_PROBABILITY_FIELDS: tuple[str, ...] = (
    "probability",
    "confidence",
    "confidence_probability",
    "mean_probability",
)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _task_parameters(task: Any) -> dict:
    params = getattr(task, "parameters", None)
    return dict(params) if isinstance(params, Mapping) else {}


def _task_quality_metrics(task: Any) -> dict:
    metrics = getattr(task, "quality_metrics", None)
    return dict(metrics) if isinstance(metrics, Mapping) else {}


def _task_grid_metadata(task: Any) -> dict:
    meta = getattr(task, "grid_metadata", None)
    return dict(meta) if isinstance(meta, Mapping) else {}


def _sample_points(task: Any) -> list[dict]:
    points = _task_parameters(task).get("sample_points")
    if isinstance(points, list):
        return [dict(p) for p in points if isinstance(p, Mapping)]
    return []


def _well_table(document: Any, task: Any):
    """Resolve the task's WellTable (existing overlay authority)."""
    table_id = str(getattr(task, "well_table_id", "") or "")
    if not table_id or document is None:
        return None
    for candidate in getattr(document, "well_tables", None) or []:
        if str(getattr(candidate, "id", "") or "") == table_id:
            return candidate
    return None


def _anchor_xy(grid: FactorGridResult | None, task: Any) -> tuple[float, float] | None:
    """A defensible anchor position for point-carried QC markers."""
    if grid is not None:
        xmin, ymin, xmax, ymax = grid.extent
        return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
    points = _sample_points(task)
    finite = [
        (_finite(p.get("x")), _finite(p.get("y")))
        for p in points
    ]
    finite = [(x, y) for x, y in finite if x is not None and y is not None]
    if not finite:
        return None
    return (
        sum(x for x, _ in finite) / len(finite),
        sum(y for _, y in finite) / len(finite),
    )


# ---------------------------------------------------------------------------
# Child builders
# ---------------------------------------------------------------------------


def _input_child(document: Any, task: Any, task_id: str, title: str) -> dict:
    """Input well points: WellTable rows first (existing overlay path),
    task ``parameters.sample_points`` as fallback."""
    features: list[tuple[dict, dict]] = []
    source = ""
    table = _well_table(document, task)
    if table is not None and getattr(table, "rows", None):
        source = "well_table"
        for row in table.rows:
            x = _finite(getattr(row, "x", None))
            y = _finite(getattr(row, "y", None))
            if x is None or y is None:
                continue
            value = _finite(getattr(row, "value", None))
            if value is None:
                value = _finite((getattr(row, "attributes", None) or {}).get("value"))
            features.append((
                {"type": "Point", "coordinates": [x, y]},
                {
                    "well_id": str(getattr(row, "well_id", "") or ""),
                    "well": str(getattr(row, "name", "") or ""),
                    "value": value,
                    "qc_flag": str(getattr(row, "qc_flag", "ok") or "ok"),
                },
            ))
    if not features:
        points = _sample_points(task)
        if points:
            source = "task_parameters"
            for index, point in enumerate(points, start=1):
                x = _finite(point.get("x"))
                y = _finite(point.get("y"))
                if x is None or y is None:
                    continue
                features.append((
                    {"type": "Point", "coordinates": [x, y]},
                    {
                        "well_id": str(
                            point.get("well_id") or point.get("well")
                            or f"sample_{index}"),
                        "well": str(point.get("well") or point.get("well_name") or ""),
                        "value": _finite(point.get("value")),
                        "qc_flag": str(point.get("qc_flag") or "ok"),
                    },
                ))
    return {
        "layer_id": f"factor_input:{task_id}",
        "role": LayerRole.FACTOR_INPUT,
        "title": f"{title}·井点",
        "geometry_kind": "point",
        "features": features,
        "metadata": {
            "factor_task_id": task_id,
            "well_source": source,
            "feature_count": len(features),
        },
    }


def _scalar_payload(
    task: Any,
    grid: FactorGridResult | None,
    task_id: str,
    *,
    quantity: str,
    extra_metadata: dict | None = None,
) -> dict:
    """Scalar-grid descriptor payload: the FactorGridResult-derived info the
    scalar publish path needs.  Grid arrays never enter the payload."""
    if grid is not None:
        source = "live_grid"
        descriptor = grid.to_descriptor()
        algorithm_id = grid.algorithm_id
        extent = list(grid.extent)
        statistics = grid.statistics.to_dict()
        width, height = grid.width, grid.height
        crs = grid.crs
        unit = grid.unit
        run_ref = grid.run_ref
    else:
        meta = _task_grid_metadata(task)
        source = "task_grid_metadata" if meta else "absent"
        descriptor = dict(meta)
        algorithm_id = str(meta.get("algorithm_id") or "")
        extent = list(meta.get("extent") or [])
        statistics = dict(meta.get("statistics") or {})
        width = int(meta.get("width") or 0)
        height = int(meta.get("height") or 0)
        crs = meta.get("crs")
        unit = meta.get("unit")
        run_ref = meta.get("run_ref")
    payload = {
        "layer_type": SCALAR_GRID_LAYER_TYPE,
        "factor_task_id": task_id,
        "quantity": quantity,
        "source": source,
        "descriptor": descriptor,
    }
    metadata = {
        "factor_task_id": task_id,
        "layer_type": SCALAR_GRID_LAYER_TYPE,
        "quantity": quantity,
        "source": source,
        "algorithm_id": algorithm_id,
        "crs": crs,
        "unit": unit,
        "extent": [float(v) for v in extent] if len(extent) == 4 else [],
        "width": width,
        "height": height,
        "statistics": statistics,
        "artifact_version_id": str(getattr(task, "grid_artifact_version_id", "") or ""),
        "artifact_path": str(getattr(task, "grid_artifact_path", "") or ""),
        "run_ref": run_ref,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    if quantity == "stddev" and "stddev_statistics" in metadata:
        # R1-F4: the uncertainty descriptor's `statistics` must describe the
        # stddev quantity it carries — not the factor-value statistics of the
        # parent grid.  The parent stats stay available as `factor_statistics`.
        metadata["factor_statistics"] = statistics
        metadata["statistics"] = dict(metadata["stddev_statistics"])
    payload["metadata"] = metadata
    return payload


def _grid_child(task: Any, grid: FactorGridResult | None, task_id: str, title: str) -> dict:
    payload = _scalar_payload(task, grid, task_id, quantity="factor_value")
    payload["metadata"]["has_variance_grid"] = bool(
        grid is not None and grid.variance_grid is not None
    )
    return {
        "layer_id": f"factor_grid:{task_id}",
        "role": LayerRole.FACTOR_GRID,
        "title": f"{title}·栅格",
        "geometry_kind": "raster",
        "payload": payload,
        "metadata": payload["metadata"],
    }


def _contour_child(
    grid: FactorGridResult | None,
    task_id: str,
    title: str,
    contour_limit: int,
) -> dict:
    """Contours from the live grid (marching squares); honest emptiness when
    the grid is not resident."""
    absent_reason = ""
    features: list[tuple[dict, dict]] = []
    metadata: dict[str, Any] = {"factor_task_id": task_id}
    if grid is None:
        absent_reason = "no live factor grid (open the preparation page to load)"
    else:
        from paleo_workbench.mapping.geological_pipeline.contouring import (
            calculate_nice_contour_levels,
            generate_contour_layer,
        )

        vmin = grid.statistics.min
        vmax = grid.statistics.max
        levels = calculate_nice_contour_levels(vmin, vmax) or None
        try:
            contour = generate_contour_layer(
                grid, levels=levels, name=f"{title}·等值线")
            snapshot = contour.to_snapshot()
            records = [
                (dict(record.get("geometry") or {}), dict(record.get("properties") or {}))
                for record in snapshot.features
            ]
            contour_qc = dict((contour.metadata or {}).get("contour_qc") or {})
        except Exception as exc:  # honest failure, never a fabricated layer
            absent_reason = f"contour extraction failed: {exc}"
            records = []
            contour_qc = {}
        total = len(records)
        limit = max(0, int(contour_limit))
        features = records[:limit] if limit else records
        metadata.update({
            "feature_count_total": total,
            "truncated": total > len(features),
            "contour_qc": contour_qc,
        })
    if absent_reason:
        metadata["absent_reason"] = absent_reason
    metadata["feature_count"] = len(features)
    return {
        "layer_id": f"factor_contour:{task_id}",
        "role": LayerRole.FACTOR_CONTOUR,
        "title": f"{title}·等值线",
        "geometry_kind": "line",
        "features": features,
        "metadata": metadata,
    }


def _classification_child(
    grid: FactorGridResult | None,
    task_id: str,
    title: str,
) -> dict:
    """Threshold classification polygons from the live grid."""
    absent_reason = ""
    features: list[tuple[dict, dict]] = []
    metadata: dict[str, Any] = {"factor_task_id": task_id}
    if grid is None:
        absent_reason = "no live factor grid (open the preparation page to load)"
    else:
        from paleo_workbench.mapping.geological_pipeline.polygonization import (
            generate_facies_polygon_layer,
        )

        try:
            polygon_layer = generate_facies_polygon_layer(
                grid, name=f"{title}·分级")
            snapshot = polygon_layer.to_snapshot()
            features = [
                (dict(record.get("geometry") or {}), dict(record.get("properties") or {}))
                for record in snapshot.features
            ]
            metadata["polygon_qc"] = dict(
                (polygon_layer.metadata or {}).get("polygon_qc") or {})
        except Exception as exc:  # honest failure, never fabricated polygons
            absent_reason = f"polygonization failed: {exc}"
    if absent_reason:
        metadata["absent_reason"] = absent_reason
    metadata["feature_count"] = len(features)
    return {
        "layer_id": f"factor_classification:{task_id}",
        "role": LayerRole.FACTOR_CLASSIFICATION,
        "title": f"{title}·分级",
        "geometry_kind": "polygon",
        "features": features,
        "metadata": metadata,
    }


def _uncertainty_child(
    grid: FactorGridResult | None,
    task_id: str,
    title: str,
) -> dict | None:
    """Stddev surface descriptor from ``variance_grid`` — ``None`` (honest
    absence) when the algorithm produced no variance grid."""
    if grid is None or grid.variance_grid is None:
        return None
    variance = np.asarray(grid.variance_grid, dtype=np.float64)
    finite = variance[np.isfinite(variance) & (variance >= 0.0)]
    stddev_stats: dict[str, Any] = {
        "min": None, "max": None, "mean": None, "std": None,
        "valid_count": int(finite.size), "total_count": int(variance.size),
    }
    if finite.size:
        stddev = np.sqrt(finite)
        stddev_stats.update({
            "min": float(stddev.min()),
            "max": float(stddev.max()),
            "mean": float(stddev.mean()),
            "std": float(stddev.std()),
        })
    parameters = grid.algorithm_parameters or {}
    extra = {
        "derivation": "stddev = sqrt(variance_grid)",
        "has_variance_grid": True,
        "variance_min": parameters.get("variance_min"),
        "variance_max": parameters.get("variance_max"),
        "stddev_statistics": stddev_stats,
    }
    payload = _scalar_payload(None, grid, task_id, quantity="stddev", extra_metadata=extra)
    return {
        "layer_id": f"factor_uncertainty:{task_id}",
        "role": LayerRole.FACTOR_UNCERTAINTY,
        "title": f"{title}·不确定性",
        "geometry_kind": "raster",
        "payload": payload,
        "metadata": payload["metadata"],
    }


def _constraint_diagnostics(task: Any, grid: FactorGridResult | None) -> dict:
    """Merged requested/applied/ignored record (task parameters carry the
    engine-merged copy; the grid carries the raw evaluation)."""
    merged: dict[str, Any] = {}
    if grid is not None:
        raw = (grid.algorithm_parameters or {}).get("constraint_diagnostics")
        if isinstance(raw, Mapping):
            merged.update(raw)
    task_side = _task_parameters(task).get("constraint_diagnostics")
    if isinstance(task_side, Mapping):
        merged.update(task_side)
    return merged


def _qc_markers(task: Any, grid: FactorGridResult | None, uncertainty_present: bool) -> list[dict]:
    """Known quality markers (FACTOR_QC spec fields: rule / severity / reason)."""
    markers: list[dict] = []
    diagnostics = _constraint_diagnostics(task, grid)
    for kind in diagnostics.get("ignored_constraints") or []:
        markers.append({
            "rule": f"constraint_ignored:{kind}",
            "severity": "warning",
            "reason": f"requested constraint {kind} was dropped silently by the backend",
        })
    for kind in diagnostics.get("unsupported_constraints") or []:
        markers.append({
            "rule": f"constraint_unsupported:{kind}",
            "severity": "warning",
            "reason": f"interpolation method cannot honor requested constraint {kind}",
        })
    for kind in diagnostics.get("partial_constraints") or []:
        markers.append({
            "rule": f"constraint_partial:{kind}",
            "severity": "info",
            "reason": f"requested constraint {kind} applied only partially",
        })
    quality = _task_quality_metrics(task)
    parameters = (grid.algorithm_parameters or {}) if grid is not None else {}
    duplicates = quality.get("duplicate_wells_dropped", parameters.get("duplicate_wells_dropped"))
    duplicates = int(duplicates) if _finite(duplicates) else 0
    if duplicates > 0:
        markers.append({
            "rule": "duplicate_wells_dropped",
            "severity": "warning",
            "reason": f"{duplicates} duplicate wells were dropped before interpolation",
        })
    if grid is None:
        markers.append({
            "rule": "grid_unavailable",
            "severity": "info",
            "reason": "no live factor grid resident — grid/contour/classification "
                      "children are empty (open the preparation page to load)",
        })
    elif not uncertainty_present:
        markers.append({
            "rule": "uncertainty_missing",
            "severity": "info",
            "reason": "algorithm produced no variance grid (kriging-only output) — "
                      "uncertainty child not created",
        })
    return markers


def _qc_child(
    task: Any,
    grid: FactorGridResult | None,
    task_id: str,
    title: str,
    uncertainty_present: bool,
) -> dict:
    markers = _qc_markers(task, grid, uncertainty_present)
    anchor = _anchor_xy(grid, task)
    features: list[tuple[dict, dict]] = []
    if anchor is not None:
        for marker in markers:
            features.append((
                {"type": "Point", "coordinates": [anchor[0], anchor[1]]},
                {
                    "rule": str(marker["rule"]),
                    "severity": str(marker["severity"]),
                    "reason": str(marker["reason"]),
                    "factor_task_id": task_id,
                },
            ))
    return {
        "layer_id": f"factor_qc:{task_id}",
        "role": LayerRole.FACTOR_QC,
        "title": f"{title}·QC",
        "geometry_kind": "point",
        "features": features,
        "metadata": {
            "factor_task_id": task_id,
            "markers": markers,
            "feature_count": len(features),
            "anchor_available": anchor is not None,
        },
    }


def factor_group_layers(
    document: Any,
    task: Any,
    *,
    grid: FactorGridResult | None = None,
    contour_limit: int = 200,
) -> list[dict]:
    """Build descriptors for ALL SIX factor-group children of ``task``.

    ``grid`` is the caller-resolved live ``FactorGridResult`` (peek pattern
    stays in the action).  The returned list follows ``FACTOR_CHILD_ORDER``:
    input → grid → contour → classification → uncertainty → QC.  The
    uncertainty child is omitted when no ``varariance_grid`` exists (honest
    absence; the QC child reports it).
    """
    task_id = str(getattr(task, "id", "") or "")
    title = factor_group_title(
        getattr(task, "name", ""), getattr(task, "factor_type", ""))
    descriptors: list[dict] = [
        _input_child(document, task, task_id, title),
        _grid_child(task, grid, task_id, title),
        _contour_child(grid, task_id, title, contour_limit),
        _classification_child(grid, task_id, title),
    ]
    uncertainty = _uncertainty_child(grid, task_id, title)
    if uncertainty is not None:
        descriptors.append(uncertainty)
    descriptors.append(
        _qc_child(task, grid, task_id, title, uncertainty is not None))
    return descriptors


# ---------------------------------------------------------------------------
# Phase 1 — prediction confidence overlays
# ---------------------------------------------------------------------------


def classify_prediction_task(task: Any) -> str:
    """Classify a prediction task as well/seismic/unknown from
    machine-readable signals (mirrors the stage-action heuristics)."""
    refs = getattr(task, "input_refs", None) or {}
    keys = (
        " ".join(str(key).lower() for key, value in refs.items() if value)
        if isinstance(refs, Mapping)
        else ""
    )
    if "seis" in keys:
        return "seismic"
    if "well" in keys or "log" in keys:
        return "well"
    name = str(getattr(task, "name", "") or "").lower()
    if "seis" in name or "地震" in name:
        return "seismic"
    if "well" in name or "测井" in name or "井" in name:
        return "well"
    return "unknown"


def _probability_of(properties: Mapping) -> float | None:
    for field in _PROBABILITY_FIELDS:
        value = _finite(properties.get(field))
        if value is not None:
            return max(0.0, min(1.0, value))
    return None


def _prediction_polygon_features(task: Any) -> list[dict]:
    """Mirror of the stage-action VECTOR_POLYGONS extraction (spatial
    features preferred, ``extract_polygon_features`` fallback)."""
    summary = dict(getattr(task, "result_summary", None) or {})
    spatial = summary.get("spatial") or {}
    raw = spatial.get("features") if isinstance(spatial, Mapping) else None
    if isinstance(raw, list) and raw:
        return [f for f in raw if isinstance(f, dict)]
    from paleo_workbench.prediction.spatial_result import extract_polygon_features

    try:
        return extract_polygon_features({"result_summary": summary})
    except Exception:
        return []


def confidence_overlay_layers(document: Any, prediction_task: Any) -> list[dict]:
    """Probability/confidence polygon descriptors for a prediction task.

    Produces one descriptor per task carrying polygon features whose
    properties include a probability/confidence field — the geometry is the
    predicted polygon, the attributes become the confidence overlay.
    Tasks without probability-bearing polygon results yield an honest empty
    list (never a fabricated confidence surface).
    """
    del document  # spatial results travel on the task; kept for call symmetry
    category = classify_prediction_task(prediction_task)
    role = {
        "well": LayerRole.WELL_FACIES_CONFIDENCE,
        "seismic": LayerRole.SEISMIC_FACIES_CONFIDENCE,
    }.get(category)
    if role is None:
        return []
    task_id = str(getattr(prediction_task, "id", "") or "")
    name = str(getattr(prediction_task, "name", "") or "")
    features: list[tuple[dict, dict]] = []
    probabilities: list[float] = []
    for record in _prediction_polygon_features(prediction_task):
        geometry = record.get("geometry")
        if not isinstance(geometry, dict) or str(geometry.get("type")) not in {
            "Polygon", "MultiPolygon",
        }:
            continue
        properties = dict(record.get("properties") or {})
        probability = _probability_of(properties)
        if probability is None:
            continue  # no confidence field → not a confidence overlay feature
        probabilities.append(probability)
        attributes = {
            "probability": probability,
            "facies": str(properties.get("facies") or ""),
            "region_id": str(properties.get("region_id") or record.get("id") or ""),
            "prediction_task_id": task_id,
        }
        for field in ("confidence", "merged_sample_count", "stratigraphic_unit"):
            value = properties.get(field)
            if value is not None:
                attributes[field] = value
        features.append((dict(geometry), attributes))
    if not features:
        return []
    label = "测井" if role is LayerRole.WELL_FACIES_CONFIDENCE else "地震"
    return [{
        "layer_id": f"prediction_confidence:{task_id}",
        "role": role,
        "title": f"{name}（{label}预测置信度）",
        "geometry_kind": "polygon",
        "features": features,
        "metadata": {
            "prediction_task_id": task_id,
            "category": category,
            "feature_count": len(features),
            "probability_min": min(probabilities),
            "probability_max": max(probabilities),
            "probability_mean": sum(probabilities) / len(probabilities),
        },
    }]


# ---------------------------------------------------------------------------
# Phase 3 — integrated boundary rings
# ---------------------------------------------------------------------------


def _iter_polygon_rings(geometry: Mapping) -> Iterable[list]:
    """Yield [x, y] rings (exterior first, then holes) of a Polygon /
    MultiPolygon geometry."""
    gtype = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")
    if not coordinates:
        return
    if gtype == "Polygon":
        rings: list[Any] = list(coordinates)
    elif gtype == "MultiPolygon":
        rings = [ring for poly in coordinates for ring in poly]
    else:
        return
    for ring in rings:
        if isinstance(ring, (list, tuple)) and len(ring) >= 3:
            yield ring


def boundary_features_from_polygons(
    features: Iterable[tuple[Mapping, Mapping]],
    *,
    source_layer_id: str = "",
) -> list[tuple[dict, dict]]:
    """Extract facies-polygon rings as boundary LineString features."""
    out: list[tuple[dict, dict]] = []
    for geometry, properties in features:
        if not isinstance(geometry, Mapping):
            continue
        ring_index = 0
        for ring in _iter_polygon_rings(geometry):
            # Rings are kept open (QGIS line semantics); closure is implied
            # by first/last vertex proximity for closed input rings.
            points: list[list[float]] = []
            for point in ring:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                x = _finite(point[0])
                y = _finite(point[1])
                if x is None or y is None:
                    continue
                points.append([x, y])
            if len(points) < 3:
                continue
            attributes = {
                "facies": str((properties or {}).get("facies")
                              or (properties or {}).get("facies_name") or ""),
                "ring": "exterior" if ring_index == 0 else f"hole_{ring_index}",
                "source_layer_id": str(source_layer_id),
            }
            out.append((
                {"type": "LineString", "coordinates": points},
                attributes,
            ))
            ring_index += 1
    return out


def integrated_boundary_action_helpers(document: Any, source_layer_id: str) -> dict | None:
    """Descriptor for an ``INTEGRATED_BOUNDARY`` layer from a draft's facies
    polygons (document-side lookup by layer id).

    Returns ``None`` when the draft has no polygon rings — the caller
    reports honestly instead of creating an empty boundary layer.
    """
    layer = None
    for candidate in getattr(document, "user_vector_layers", None) or []:
        if str(getattr(candidate, "id", "") or "") == str(source_layer_id):
            layer = candidate
            break
    if layer is None:
        return None
    features = [
        (feature.geometry, feature.properties)
        for feature in getattr(layer, "features", None) or []
        if isinstance(getattr(feature, "geometry", None), Mapping)
    ]
    boundary = boundary_features_from_polygons(
        features, source_layer_id=str(source_layer_id))
    if not boundary:
        return None
    return {
        "layer_id": f"integrated_boundary:{source_layer_id}",
        "role": LayerRole.INTEGRATED_BOUNDARY,
        "title": "综合相带边界",
        "geometry_kind": "line",
        "features": boundary,
        "metadata": {
            "source_layer_id": str(source_layer_id),
            "feature_count": len(boundary),
        },
    }
