"""Production paleomap compilation from real spatial prediction artifacts.

Unlike :func:`compile_map_draft` (demo squares near 114/22.5), this path:

- requires VECTOR_POLYGONS geometry from the prediction payload
- never invents placeholder / 未分类 squares
- refuses WELL_INTERVALS-only and non-spatial results
- marks documents as non-demo
- optionally registers map_compile DataRun lineage
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from paleo_workbench.project.models import PaleoMapDocument, PredictionTask, ProjectDocument
from paleo_workbench.prediction.spatial_result import (
    SPATIAL_VECTOR_POLYGONS,
    SpatialResultError,
    extract_polygon_features,
    is_map_compilable,
    spatial_type_of,
)

PRODUCTION_MAP_GENERATOR = "production-map-from-spatial-v1"


class ProductionMapError(ValueError):
    """Cannot compile a production paleomap from the given prediction."""


def _resolve_task(
    project: ProjectDocument, prediction_task_id: str | None
) -> PredictionTask | None:
    if prediction_task_id:
        for task in project.prediction_tasks:
            if task.id == prediction_task_id:
                return task
        return None
    if project.prediction_tasks:
        return project.prediction_tasks[-1]
    return None


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
    return ""


def _payload_from_task(task: PredictionTask) -> dict[str, Any]:
    """Rebuild a minimal payload view from the domain task."""
    summary = dict(task.result_summary or {})
    return {
        "result_summary": summary,
        "spatial": summary.get("spatial"),
        "demo": bool(summary.get("demo")),
        "model": task.model_metadata or {},
    }


def _normalize_feature(feat: dict[str, Any]) -> dict[str, Any]:
    props = dict(feat.get("properties") or {})
    facies = str(
        props.get("facies")
        or props.get("name")
        or feat.get("facies")
        or feat.get("name")
        or ""
    )
    if not facies:
        facies = "unspecified"
    props.setdefault("facies", facies)
    props.setdefault("name", facies)
    return {
        "type": "Feature",
        "name": facies,
        "facies": facies,
        "properties": props,
        "geometry": feat["geometry"],
    }


def compile_map_production(
    project: ProjectDocument,
    *,
    target_horizon: str | None = None,
    prediction_task_id: str | None = None,
    prediction_payload: dict[str, Any] | None = None,
    map_crs: str | None = None,
    catalog_service=None,
    prediction_version_id: str | None = None,
    allow_demo_task: bool = False,
) -> PaleoMapDocument:
    """Compile a production PaleoMapDocument from spatial prediction geometry.

    Raises :class:`ProductionMapError` when geometry is missing or demo-only
    without ``allow_demo_task``.
    """
    task = _resolve_task(project, prediction_task_id)
    payload = prediction_payload
    if payload is None:
        if task is None:
            raise ProductionMapError("无预测任务，无法进行生产编图")
        payload = _payload_from_task(task)

    summary = payload.get("result_summary") or {}
    if summary.get("demo") or summary.get("is_mock") or payload.get("demo"):
        if not allow_demo_task:
            raise ProductionMapError(
                "演示/mock 预测结果不能用于生产古地理编图；请使用「生成演示草稿」"
            )
    if summary.get("final_scientific_prediction") is False and not allow_demo_task:
        # Heuristic / non-scientific: still may have geometry in tests; block by default.
        if not summary.get("allow_map_compile"):
            raise ProductionMapError(
                "非科学预测结果（final_scientific_prediction=False）不能用于生产编图"
            )

    stype = spatial_type_of(payload)
    if stype == "WELL_INTERVALS":
        raise ProductionMapError(
            "井深区间预测（WELL_INTERVALS）不能直接编绘平面古地理图；"
            "需要平面空间几何或分类栅格"
        )
    if not is_map_compilable(payload):
        raise ProductionMapError(
            "预测结果缺少可编绘的平面多边形几何（VECTOR_POLYGONS）；"
            "不会生成占位方块或「未分类」假几何"
        )

    features = [_normalize_feature(f) for f in extract_polygon_features(payload)]
    # Double-check: no empty rings
    if not features:
        raise ProductionMapError("空间特征列表为空")

    horizon = _resolve_horizon(project, target_horizon)
    if not horizon:
        raise ProductionMapError("生产编图需要明确的目标层位")

    spatial = summary.get("spatial") or payload.get("spatial") or {}
    crs = map_crs or spatial.get("crs") or getattr(
        getattr(project, "coordinate", None), "project_crs", ""
    ) or ""

    name = f"{horizon} 相带图"
    legend = []
    seen: set[str] = set()
    for feat in features:
        f = str(feat.get("facies") or "")
        if f and f not in seen:
            seen.add(f)
            legend.append(f)

    # Wells: only real sample points (no synthetic 114/22.x placement).
    well_overlays = _wells_real_only(project)

    doc = PaleoMapDocument(
        name=name,
        linked_target_horizon=horizon,
        linked_prediction_task_id=task.id if task is not None else None,
        facies_polygons=features,
        well_overlays=well_overlays,
        map_chrome={"title": name, "legend_facies": legend},
        map_crs=str(crs or ""),
        view_state={
            "generator": PRODUCTION_MAP_GENERATOR,
            "is_demo_draft": False,
            "spatial_output_type": SPATIAL_VECTOR_POLYGONS,
            "production": True,
        },
    )
    project.paleomap_documents.append(doc)
    if project.compilation_runs:
        project.compilation_runs[-1].active_paleomap_document_id = doc.id

    if catalog_service is not None:
        _register_lineage(
            catalog_service,
            doc=doc,
            task=task,
            prediction_version_id=prediction_version_id,
            horizon=horizon,
        )
    return doc


def _wells_real_only(project: ProjectDocument) -> list[dict[str, Any]]:
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
            try:
                if "x" in pt and "y" in pt:
                    lng = float(pt["x"])
                    lat = float(pt["y"])
                elif "lng" in pt and "lat" in pt:
                    lng = float(pt["lng"])
                    lat = float(pt["lat"])
                else:
                    continue
            except (TypeError, ValueError):
                continue
            key = f"{name}:{lng}:{lat}"
            if key in seen:
                continue
            seen.add(key)
            wells.append({"name": name, "lng": lng, "lat": lat, "x": lng, "y": lat})
    return wells


def _register_lineage(
    service,
    *,
    doc: PaleoMapDocument,
    task: PredictionTask | None,
    prediction_version_id: str | None,
    horizon: str,
) -> None:
    """Best-effort map_compile DataRun via lifecycle when a catalog port exists."""
    try:
        from paleo_workbench.catalog.lifecycle import register_map_compile_run
        from paleo_workbench.catalog import get_catalog
    except Exception:
        return

    input_ids: list[str] = []
    if prediction_version_id:
        input_ids.append(prediction_version_id)
    source_task_ids = [task.id] if task is not None else []

    # Prefer catalog port if bound; DataCatalogService is not always the port.
    cat = get_catalog()
    fd = None
    tmp: Path | None = None
    try:
        payload = {
            "id": doc.id,
            "name": doc.name,
            "linked_target_horizon": doc.linked_target_horizon,
            "linked_prediction_task_id": doc.linked_prediction_task_id,
            "facies_polygons": doc.facies_polygons,
            "map_crs": doc.map_crs,
            "view_state": doc.view_state,
        }
        fd, tmp_name = tempfile.mkstemp(prefix="paleomap_", suffix=".json")
        tmp = Path(tmp_name)
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        register_map_compile_run(
            name=doc.name,
            input_version_ids=input_ids,
            source_task_ids=source_task_ids or None,
            domain_task_id=doc.id,
            parameters={
                "generator_version": PRODUCTION_MAP_GENERATOR,
                "target_horizon": horizon,
                "linked_prediction_task_id": doc.linked_prediction_task_id,
            },
            result_path=str(tmp),
            catalog=cat,
        )
    except Exception:
        pass
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
