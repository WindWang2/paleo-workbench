"""18c: deterministic demo-grade PaleoMapDocument compiler.

Always produces an editable draft (placeholder polygon when inputs are empty).
Same seed + same region list → same geometry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.project.models import (
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
)

_GENERATOR = "deterministic-map-draft-v1"
_COLS = 2
_SIDE = 0.04
_CELL = 0.05
_BASE_Y = 22.5


def compile_map_draft(
    project: ProjectDocument,
    *,
    target_horizon: str | None = None,
    prediction_task_id: str | None = None,
    seed: int = 0,
) -> PaleoMapDocument:
    """Build a deterministic demo paleomap draft and append it to the project.

    Always returns a draft — never raises for empty inputs. Prefer a placeholder
    polygon over dead-ending the UI.
    """
    horizon = _resolve_horizon(project, target_horizon)
    task = _resolve_prediction_task(project, prediction_task_id)
    regions = _extract_regions(task)

    facies_polygons = _polygons_from_regions(regions, seed=seed)
    well_overlays = _wells_from_project(project)
    legend_facies = _unique_facies(facies_polygons)

    name = f"{horizon} 相带草稿"
    doc = PaleoMapDocument(
        name=name,
        linked_target_horizon=horizon,
        linked_prediction_task_id=task.id if task is not None else None,
        facies_polygons=facies_polygons,
        well_overlays=well_overlays,
        map_chrome={"title": name, "legend_facies": legend_facies},
        view_state={
            "generator": _GENERATOR,
            "is_demo_draft": True,
            "seed": seed,
        },
    )
    project.paleomap_documents.append(doc)
    if project.compilation_runs:
        project.compilation_runs[-1].active_paleomap_document_id = doc.id
    return doc


def _resolve_horizon(project: ProjectDocument, target_horizon: str | None) -> str:
    if target_horizon:
        return target_horizon
    if project.compilation_runs:
        th = project.compilation_runs[-1].target_horizon
        if th:
            return th
    th = project.stratigraphy.target_horizon
    if th:
        return th
    return "未指定层位"


def _resolve_prediction_task(
    project: ProjectDocument,
    prediction_task_id: str | None,
) -> PredictionTask | None:
    if prediction_task_id:
        for task in project.prediction_tasks:
            if task.id == prediction_task_id:
                return task
        return None
    if project.prediction_tasks:
        return project.prediction_tasks[-1]
    return None


def _extract_regions(task: PredictionTask | None) -> list[dict[str, Any]]:
    if task is None:
        return []
    summary = task.result_summary or {}
    raw = summary.get("predicted_regions") or []
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


def _polygons_from_regions(
    regions: list[dict[str, Any]],
    *,
    seed: int,
) -> list[dict[str, Any]]:
    base_x = 114.0 + (seed % 10) * 0.001
    base_y = _BASE_Y
    if not regions:
        return [
            _square_feature(
                facies="未分类",
                x0=base_x,
                y0=base_y,
                side=_SIDE,
                probability=None,
                region_id=None,
            )
        ]
    features: list[dict[str, Any]] = []
    for i, region in enumerate(regions):
        facies = str(region.get("facies") or "未分类")
        x0 = base_x + (i % _COLS) * _CELL
        y0 = base_y + (i // _COLS) * _CELL
        features.append(
            _square_feature(
                facies=facies,
                x0=x0,
                y0=y0,
                side=_SIDE,
                probability=region.get("probability"),
                region_id=region.get("region_id"),
            )
        )
    return features


def _square_feature(
    *,
    facies: str,
    x0: float,
    y0: float,
    side: float,
    probability: Any,
    region_id: Any,
) -> dict[str, Any]:
    ring = [
        [x0, y0],
        [x0 + side, y0],
        [x0 + side, y0 + side],
        [x0, y0 + side],
        [x0, y0],
    ]
    props: dict[str, Any] = {
        "name": facies,
        "facies": facies,
        "probability": probability,
        "region_id": region_id,
    }
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {
            "type": "Polygon",
            "coordinates": [ring],
        },
    }


def _wells_from_project(project: ProjectDocument) -> list[dict[str, Any]]:
    """Prefer factor sample_points; else synthetic from applicable wells / well_log stems."""
    from_factors = _wells_from_factor_tasks(project)
    if from_factors:
        return from_factors
    names = list(project.stratigraphy.applicable_wells or [])
    if not names:
        names = sorted(
            {
                Path(r.name).stem
                for r in project.resources
                if r.type == "well_log" and r.name
            }
        )
    return [
        {
            "name": well_name,
            "lng": round(114.0 + i * 0.02, 6),
            "lat": round(22.6 + (i % 3) * 0.01, 6),
        }
        for i, well_name in enumerate(names)
    ]


def _wells_from_factor_tasks(project: ProjectDocument) -> list[dict[str, Any]]:
    wells: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in project.factor_map_tasks:
        params = task.parameters or {}
        points = params.get("sample_points") or []
        if not isinstance(points, list):
            continue
        for pt in points:
            if not isinstance(pt, dict):
                continue
            name = str(pt.get("well") or pt.get("name") or pt.get("well_name") or "")
            if "x" in pt and "y" in pt:
                lng = float(pt["x"])
                lat = float(pt["y"])
            elif "lng" in pt and "lat" in pt:
                lng = float(pt["lng"])
                lat = float(pt["lat"])
            else:
                continue
            key = f"{name}:{lng}:{lat}"
            if key in seen:
                continue
            seen.add(key)
            wells.append({"name": name, "lng": lng, "lat": lat})
    return wells


def _unique_facies(features: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for feat in features:
        props = feat.get("properties") or {}
        facies = str(props.get("facies") or props.get("name") or "")
        if facies and facies not in seen:
            seen.add(facies)
            ordered.append(facies)
    return ordered
