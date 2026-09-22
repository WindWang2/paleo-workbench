"""测井相预测：井点提取与点到面（最近邻分类面）。

测井预测任务通常是 ``WELL_INTERVALS``（曲线域），不能直接当平面相图。
本模块把区间结果接到井位 XY，再按最近邻生成分类相面。点到面必须由
明确动作触发，阶段切换绝不重算。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from paleo_workbench.mapping.factor_layer_products import classify_prediction_task

#: 井点叠加 / 点到面成果在成员资格里的稳定 task 标记（与单井多边形叠加区分）。
POINTS_LAYER_TASK_ID = "well_facies_points"
SURFACE_LAYER_TASK_ID = "well_facies_point_to_surface"

_DEFAULT_GRID_N = 80


@dataclass(frozen=True)
class WellFaciesPoint:
    """一张测井预测相井点（平面位置 + 代表相）。"""

    x: float
    y: float
    facies: str
    well_id: str = ""
    well_name: str = ""
    probability: float | None = None
    task_id: str = ""
    thickness: float | None = None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def well_xy(well: Any, project: Any | None = None) -> tuple[float, float] | None:
    """工程 CRS 坐标优先，源坐标其次；井表行列作最后回退。"""
    x = getattr(well, "project_x", None)
    y = getattr(well, "project_y", None)
    if x is None or y is None:
        x = getattr(well, "surface_x", None)
        y = getattr(well, "surface_y", None)
    xf, yf = _finite(x), _finite(y)
    if xf is not None and yf is not None:
        return xf, yf
    if project is None or well is None:
        return None
    well_id = str(getattr(well, "id", "") or "")
    well_name = str(getattr(well, "name", "") or "")
    from paleo_workbench.project.domain import normalize_well_name

    want = {normalize_well_name(well_id), normalize_well_name(well_name)}
    want.discard("")
    for table in getattr(project, "well_tables", None) or []:
        for row in getattr(table, "rows", None) or []:
            keys = {
                normalize_well_name(str(getattr(row, "well_id", "") or "")),
                normalize_well_name(str(getattr(row, "name", "") or "")),
            }
            if want & keys:
                rx, ry = _finite(getattr(row, "x", None)), _finite(getattr(row, "y", None))
                if rx is not None and ry is not None:
                    return rx, ry
    return None


def representative_facies(
    regions: Sequence[Any] | None,
    *,
    horizon: str = "",
) -> tuple[str, float | None, float] | None:
    """区间 → 代表相：按累计厚度（再比概率）取众数。无厚度则只比概率。"""
    items = [record for record in (regions or ()) if isinstance(record, dict)]
    horizon_text = str(horizon or "").strip()
    if horizon_text:
        matched = [
            record for record in items
            if horizon_text in str(
                record.get("stratigraphic_unit")
                or record.get("horizon")
                or ""
            )
        ]
        if matched:
            items = matched
    # facies → (thickness, probability mass, probability weight)
    totals: dict[str, tuple[float, float, float]] = {}
    for record in items:
        facies = str(
            record.get("facies") or record.get("label") or record.get("name") or ""
        ).strip()
        if not facies:
            continue
        top, bottom = _finite(record.get("top")), _finite(record.get("bottom"))
        thickness = abs(bottom - top) if top is not None and bottom is not None else 0.0
        probability = _finite(record.get("probability") or record.get("confidence"))
        total_t, mass, weight = totals.get(facies, (0.0, 0.0, 0.0))
        total_t += thickness
        if probability is not None:
            sample_weight = thickness if thickness > 0.0 else 1.0
            mass += probability * sample_weight
            weight += sample_weight
        totals[facies] = (total_t, mass, weight)
    if not totals:
        return None
    facies, (thickness, mass, weight) = max(
        totals.items(),
        key=lambda item: (item[1][0], (item[1][1] / item[1][2]) if item[1][2] else 0.0),
    )
    mean_p = (mass / weight) if weight else None
    return facies, mean_p, thickness


def _task_regions(task: Any) -> list[dict]:
    summary = dict(getattr(task, "result_summary", None) or {})
    spatial = summary.get("spatial") if isinstance(summary.get("spatial"), dict) else {}
    intervals = spatial.get("intervals") or spatial.get("well_intervals") or []
    if isinstance(intervals, list) and intervals:
        return [item for item in intervals if isinstance(item, dict)]
    regions = summary.get("predicted_regions") or []
    return [item for item in regions if isinstance(item, dict)]


def _spatial_point_features(task: Any) -> list[WellFaciesPoint]:
    summary = dict(getattr(task, "result_summary", None) or {})
    spatial = summary.get("spatial") if isinstance(summary.get("spatial"), dict) else {}
    raw = spatial.get("features") or []
    if not isinstance(raw, list):
        return []
    task_id = str(getattr(task, "id", "") or "")
    points: list[WellFaciesPoint] = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        geometry = record.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates") or []
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        x, y = _finite(coords[0]), _finite(coords[1])
        if x is None or y is None:
            continue
        properties = dict(record.get("properties") or {})
        facies = str(
            properties.get("facies") or properties.get("label")
            or properties.get("name") or ""
        ).strip()
        if not facies:
            continue
        points.append(WellFaciesPoint(
            x=x, y=y, facies=facies,
            well_id=str(properties.get("well_id") or ""),
            well_name=str(properties.get("well_name") or properties.get("well") or ""),
            probability=_finite(properties.get("probability") or properties.get("confidence")),
            task_id=task_id,
        ))
    return points


def _wells_for_task(project: Any, task: Any) -> list[Any]:
    from paleo_workbench.project.domain import entity_ids_for_asset, well_registry

    registry = well_registry(project)
    found: list[Any] = []
    seen: set[str] = set()

    def _add(well: Any) -> None:
        well_id = str(getattr(well, "id", "") or "") if well is not None else ""
        if well is None or not well_id or well_id in seen:
            return
        seen.add(well_id)
        found.append(well)

    refs = getattr(task, "input_refs", None) or {}
    resource_ids: list[str] = []
    for key in ("well_log_resource_ids", "well_logs", "well", "wells"):
        values = refs.get(key) if isinstance(refs, dict) else None
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            resource_ids.extend(str(item) for item in values if item)
    for resource_id in resource_ids:
        for _etype, entity_id in entity_ids_for_asset(project, resource_id, "well"):
            _add(registry.by_id(entity_id))
        for resource in getattr(project, "resources", None) or []:
            if str(getattr(resource, "id", "") or "") != resource_id:
                continue
            _add(registry.by_key(str(getattr(resource, "name", "") or "")))
            break
    return found


def _points_from_intervals(
    project: Any, task: Any, *, horizon: str
) -> list[WellFaciesPoint]:
    from paleo_workbench.project.domain import well_registry

    regions = _task_regions(task)
    if not regions:
        return []
    wells = _wells_for_task(project, task)
    registry = well_registry(project)
    task_id = str(getattr(task, "id", "") or "")
    grouped: dict[str, list[dict]] = {}
    for record in regions:
        key = str(
            record.get("well_id") or record.get("well_name") or record.get("well") or ""
        ).strip()
        grouped.setdefault(key, []).append(record)

    points: list[WellFaciesPoint] = []

    def _emit(well: Any, records: list[dict]) -> None:
        xy = well_xy(well, project)
        picked = representative_facies(records, horizon=horizon)
        if xy is None or picked is None:
            return
        facies, probability, thickness = picked
        points.append(WellFaciesPoint(
            x=xy[0], y=xy[1], facies=facies,
            well_id=str(getattr(well, "id", "") or ""),
            well_name=str(getattr(well, "name", "") or ""),
            probability=probability, task_id=task_id,
            thickness=thickness if thickness else None,
        ))

    if list(grouped.keys()) == [""] and len(wells) == 1:
        _emit(wells[0], grouped[""])
        return points

    for key, records in grouped.items():
        well = registry.by_id(key) or registry.by_key(key) if key else None
        if well is None and len(wells) == 1:
            well = wells[0]
        if well is not None:
            _emit(well, records)
    return points


def well_prediction_tasks(project: Any) -> list[Any]:
    """工程中可识别为测井相预测的任务。"""
    return [
        task for task in (getattr(project, "prediction_tasks", None) or [])
        if classify_prediction_task(task) == "well"
    ]


def well_facies_points(project: Any, *, horizon: str = "") -> list[WellFaciesPoint]:
    """全部测井预测任务的平面井点（空间 Point 优先，否则区间 + 井位）。"""
    target = horizon or str(
        getattr(getattr(project, "stratigraphy", None), "target_horizon", "") or ""
    )
    points: list[WellFaciesPoint] = []
    for task in well_prediction_tasks(project):
        spatial = _spatial_point_features(task)
        if spatial:
            points.extend(spatial)
            continue
        points.extend(_points_from_intervals(project, task, horizon=target))
    return points


def point_features(points: Iterable[WellFaciesPoint]) -> list[tuple[dict, dict]]:
    """井点 → ``_create_role_layer`` 可用的 (geometry, properties)。"""
    features: list[tuple[dict, dict]] = []
    for point in points:
        properties: dict[str, Any] = {
            "facies": point.facies,
            "well_id": point.well_id,
            "well_name": point.well_name,
            "prediction_task_id": point.task_id,
        }
        if point.probability is not None:
            properties["probability"] = point.probability
        if point.thickness is not None:
            properties["thickness"] = point.thickness
        features.append((
            {"type": "Point", "coordinates": [point.x, point.y]},
            properties,
        ))
    return features


def _extent_from_workarea(project: Any) -> tuple[float, float, float, float] | None:
    workarea = getattr(project, "workarea", None)
    ring = list(getattr(workarea, "boundary", None) or []) if workarea is not None else []
    xs, ys = [], []
    for vertex in ring:
        try:
            x, y = float(vertex[0]), float(vertex[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            xs.append(x)
            ys.append(y)
    if len(xs) < 3:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _extent_from_points(
    points: Sequence[WellFaciesPoint],
) -> tuple[float, float, float, float]:
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    span_x = max(xmax - xmin, 1.0)
    span_y = max(ymax - ymin, 1.0)
    pad_x, pad_y = span_x * 0.1, span_y * 0.1
    return xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y


def _clip_ring(project: Any) -> list[list[float]] | None:
    workarea = getattr(project, "workarea", None)
    ring = list(getattr(workarea, "boundary", None) or []) if workarea is not None else []
    cleaned: list[list[float]] = []
    for vertex in ring:
        try:
            x, y = float(vertex[0]), float(vertex[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            cleaned.append([x, y])
    return cleaned if len(cleaned) >= 4 else None


def nearest_neighbor_class_grid(
    points: Sequence[WellFaciesPoint],
    *,
    extent: tuple[float, float, float, float],
    grid_n: int = _DEFAULT_GRID_N,
    clip_ring: Sequence[Sequence[float]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[str, ...]]:
    """最近邻分类栅格：每个格子取最近井点的相。返回 (grid_z, grid_x, grid_y, facies_names)。"""
    if not points:
        raise ValueError("point-to-surface needs at least one well facies point")
    names: list[str] = []
    index_of: dict[str, int] = {}
    xs = np.empty(len(points), dtype=np.float64)
    ys = np.empty(len(points), dtype=np.float64)
    classes = np.empty(len(points), dtype=np.int16)
    for i, point in enumerate(points):
        if point.facies not in index_of:
            index_of[point.facies] = len(names)
            names.append(point.facies)
        xs[i] = point.x
        ys[i] = point.y
        classes[i] = index_of[point.facies]
    xmin, ymin, xmax, ymax = extent
    nx = ny = max(2, int(grid_n))
    grid_x = np.linspace(xmin, xmax, nx, dtype=np.float64)
    grid_y = np.linspace(ymin, ymax, ny, dtype=np.float64)
    dx = grid_x[None, :, None] - xs[None, None, :]
    dy = grid_y[:, None, None] - ys[None, None, :]
    nearest = np.argmin(dx * dx + dy * dy, axis=-1)
    grid_z = classes[nearest].astype(np.float32)
    if clip_ring:
        from paleo_workbench.mapping.geometry_planar import (
            point_in_ring_scalar_inclusive,
        )

        ring = [(float(x), float(y)) for x, y in clip_ring]
        mask = np.ones(grid_z.shape, dtype=bool)
        for row, y in enumerate(grid_y):
            for col, x in enumerate(grid_x):
                if not point_in_ring_scalar_inclusive(float(x), float(y), ring):
                    mask[row, col] = False
        grid_z = np.where(mask, grid_z, np.float32(np.nan))
    return grid_z, grid_x, grid_y, tuple(names)


def point_to_surface_features(
    points: Sequence[WellFaciesPoint],
    *,
    project: Any | None = None,
    grid_n: int = _DEFAULT_GRID_N,
) -> list[tuple[dict, dict]]:
    """井点 → 相面多边形 (geometry, properties)。点数不足时返回空表。"""
    if len(points) < 1:
        return []
    extent = _extent_from_workarea(project) or _extent_from_points(points)
    ring = _clip_ring(project)
    grid_z, grid_x, grid_y, facies_names = nearest_neighbor_class_grid(
        points, extent=extent, grid_n=grid_n, clip_ring=ring,
    )
    crs = str(
        getattr(getattr(project, "coordinate", None), "project_crs", "") or ""
    ) or None
    from paleo_workbench.mapping.geological_pipeline.polygonization import (
        generate_facies_polygon_layer,
    )
    from paleo_workbench.workflow.factor_grid_result import FactorGridResult

    n_class = len(facies_names)
    thresholds = (
        [0.0] if n_class == 1
        else [i + 0.5 for i in range(n_class - 1)]
    )
    grid = FactorGridResult(
        grid_z=grid_z,
        grid_x=grid_x,
        grid_y=grid_y,
        factor_name="测井预测相",
        algorithm_id="nearest_neighbor",
        algorithm_parameters={
            "method": "nearest_neighbor",
            "n_points": len(points),
            "grid_n": int(grid_n),
        },
        crs=crs,
    )
    layer = generate_facies_polygon_layer(
        grid,
        thresholds=thresholds,
        facies_names=list(facies_names),
        clip_ring=ring,
        name="测井预测相（点到面）",
    )
    features: list[tuple[dict, dict]] = []
    for record in layer.features or ():
        if not isinstance(record, dict):
            continue
        geometry = record.get("geometry")
        if not isinstance(geometry, dict):
            continue
        properties = dict(record.get("properties") or {})
        properties.setdefault("facies", properties.get("facies_name") or "")
        properties["source"] = "well_point_to_surface"
        features.append((geometry, properties))
    return features
