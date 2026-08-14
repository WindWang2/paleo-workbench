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

    Raises :class:`ProductionMapError` when geometry is missing, demo-only
    (without ``allow_demo_task``), untrusted, or when catalog lineage cannot
    be registered. Production provenance is part of the compile contract
    (H3): a document is never appended to the project while the catalog holds
    no lineage for it.
    """
    task = _resolve_task(project, prediction_task_id)
    payload = prediction_payload
    if payload is None:
        if task is None:
            raise ProductionMapError("无预测任务，无法进行生产编图")
        payload = _payload_from_task(task)

    summary = payload.get("result_summary") or {}
    demo_marked = bool(
        summary.get("demo")
        or summary.get("is_mock")
        or payload.get("demo")
        or (payload.get("model") or {}).get("demo_only")
    )
    if demo_marked:
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

    # Scientific validation gate: finite rings, closure, CRS, and the
    # demo-square anti-laundering check must ALL pass (D-P0).
    from paleo_workbench.prediction.spatial_result import validate_spatial_result

    validation_errors = validate_spatial_result(
        payload,
        require_scientific=not bool(summary.get("allow_map_compile")),
    )
    if validation_errors:
        raise ProductionMapError("预测几何未通过生产校验: " + "; ".join(validation_errors))

    # Model trust: when the payload declares a model version, it must resolve
    # to a promoted production version (D-P2). Fail closed when a catalog is
    # present but the claim cannot be verified; with NO catalog the document
    # cannot claim production at all, so the unverifiable claim is moot.
    model_meta = payload.get("model") or {}
    declared_mv_id = str(
        model_meta.get("model_version_id") or model_meta.get("version_id") or ""
    ).strip()
    if declared_mv_id:
        trust_catalog = catalog_service
        if trust_catalog is None:
            try:
                from paleo_workbench.catalog import get_catalog

                trust_catalog = get_catalog()
            except Exception:
                trust_catalog = None
        if trust_catalog is not None:
            verifier = (
                trust_catalog
                if hasattr(trust_catalog, "get_model_version_by_id")
                else None
            )
            if verifier is None:
                raise ProductionMapError("声明了模型版本但无法验证其生产状态")
            try:
                declared_mv = verifier.get_model_version_by_id(declared_mv_id)
            except Exception as exc:
                raise ProductionMapError(
                    f"声明的模型版本不存在: {declared_mv_id} ({exc})"
                ) from exc
            if declared_mv.status != "production" or declared_mv.demo_only:
                raise ProductionMapError(
                    "声明的模型版本未处于生产状态，不能用于生产编图"
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

    # Only link the task when the payload actually came from it: a
    # caller-supplied payload with a default task resolution is unverified.
    linked_task = task if (prediction_task_id is not None or prediction_payload is None) else None

    doc = PaleoMapDocument(
        name=name,
        linked_target_horizon=horizon,
        linked_prediction_task_id=linked_task.id if linked_task is not None else None,
        facies_polygons=features,
        well_overlays=well_overlays,
        map_chrome={"title": name, "legend_facies": legend},
        map_crs=str(crs or ""),
        view_state={
            "generator": PRODUCTION_MAP_GENERATOR,
            "is_demo_draft": demo_marked,
            "spatial_output_type": SPATIAL_VECTOR_POLYGONS,
            # Production is granted only after lineage registration below.
            "production": False,
        },
    )

    if demo_marked:
        # Explicit demo path: never pretend provenance is complete.
        doc.view_state["production"] = False
        doc.view_state["lineage"] = "untracked"
        project.paleomap_documents.append(doc)
        if project.compilation_runs:
            project.compilation_runs[-1].active_paleomap_document_id = doc.id
        return doc

    catalog = catalog_service
    if catalog is None:
        try:
            from paleo_workbench.catalog import get_catalog

            catalog = get_catalog()
        except Exception:
            catalog = None
    if catalog is None:
        # No-catalog mode must degrade explicitly, not fake provenance (H3).
        doc.view_state["production"] = False
        doc.view_state["lineage"] = "untracked"
    else:
        # Lineage FIRST: a production document is only committed to the
        # project once its DataRun + DERIVED version are durably registered.
        _register_lineage(
            catalog,
            doc=doc,
            task=linked_task,
            prediction_version_id=prediction_version_id,
            horizon=horizon,
        )
        doc.view_state["production"] = True
        doc.view_state["lineage"] = "registered"

    project.paleomap_documents.append(doc)
    if project.compilation_runs:
        project.compilation_runs[-1].active_paleomap_document_id = doc.id
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


def _resolve_map_input_ids(
    service,
    task: PredictionTask | None,
    prediction_version_id: str | None,
) -> list[str]:
    """Resolve the prediction input version ids for the map_compile run.

    Prefers the explicit ``prediction_version_id``; otherwise resolves the
    task's latest prediction output through the run graph so lineage never
    registers with an empty input list (H3).
    """
    if prediction_version_id:
        return [str(prediction_version_id)]
    if task is None:
        return []
    try:
        from paleo_workbench.catalog.lifecycle import _versions_for_domain_tasks

        if service is not None and hasattr(service, "document"):
            # DataCatalogService: expose runs through the service view.
            from paleo_workbench.prediction.inference_service import _ServiceRunView

            return _versions_for_domain_tasks(
                [task.id], catalog=_ServiceRunView(service)
            )
        # Pure CatalogPort (InMemoryCatalog / PALEO_DATA_CATALOG backends):
        # it already IS the port the lifecycle helper expects.
        return _versions_for_domain_tasks([task.id], catalog=service)
    except Exception:
        return []


def _register_lineage(
    service,
    *,
    doc: PaleoMapDocument,
    task: PredictionTask | None,
    prediction_version_id: str | None,
    horizon: str,
) -> None:
    """Register map_compile DataRun + optional DERIVED paleomap version.

    Uses:
    1. explicit *service* when it is a DataCatalogService (tests/production),
    2. otherwise CatalogPort via get_catalog() / register_map_compile_run.

    Any provenance failure raises :class:`ProductionMapError` — the caller
    must not commit a production document with partial lineage (H3). A run
    that already started is marked ``failed`` before the error propagates so
    no RUNNING orphan survives.
    """
    input_ids = _resolve_map_input_ids(service, task, prediction_version_id)
    if not input_ids:
        raise ProductionMapError(
            "生产编图需要可解析的预测结果版本（未找到 lineage 输入）"
        )
    source_task_ids = [task.id] if task is not None else []
    params = {
        "generator_version": PRODUCTION_MAP_GENERATOR,
        "target_horizon": horizon,
        "linked_prediction_task_id": doc.linked_prediction_task_id,
        "_domain_task_id": doc.id,
        "source_task_ids": source_task_ids,
    }

    payload = {
        "id": doc.id,
        "name": doc.name,
        "linked_target_horizon": doc.linked_target_horizon,
        "linked_prediction_task_id": doc.linked_prediction_task_id,
        "facies_polygons": doc.facies_polygons,
        "map_crs": doc.map_crs,
        "view_state": doc.view_state,
    }

    # Path 1: DataCatalogService (has register_run + register_result_asset).
    if service is not None and hasattr(service, "register_run") and hasattr(
        service, "register_result_asset"
    ):
        tmp: Path | None = None
        run = None
        try:
            from paleo_workbench.catalog.models import DataStage

            fd, tmp_name = tempfile.mkstemp(prefix="paleomap_", suffix=".json")
            tmp = Path(tmp_name)
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            run = service.register_run(
                operation="map_compile",
                input_version_ids=input_ids,
                parameters=params,
                generator=PRODUCTION_MAP_GENERATOR,
                status="running",
            )
            run_id = run.id
            out = service.register_result_asset(
                name=doc.name,
                type="paleomap",
                format="json",
                asset_metadata={"kind": "paleomap", "production": True},
                source_path=str(tmp),
                stage=DataStage.DERIVED,
                run_id=run.id,
                version_metadata={
                    "kind": "paleomap",
                    "generator": PRODUCTION_MAP_GENERATOR,
                    "production": True,
                },
            )
            service.update_run_status(
                run.id,
                "complete",
                extra_parameters={"output_version_id": out.id},
            )
            return
        except Exception as exc:
            # No orphan RUNNING run: mark it failed before propagating.
            if run is not None:
                try:
                    service.update_run_status(
                        run.id,
                        "failed",
                        extra_parameters={
                            "error": f"{exc.__class__.__name__}: {exc}"
                        },
                    )
                except Exception:
                    pass
            raise ProductionMapError(
                f"目录 lineage 登记失败（生产编图已中止）: {exc}"
            ) from exc
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # Path 2: CatalogPort lifecycle helper (no duplicate fallback — Path 1
    # either succeeds or raises, so this runs only when the caller passed a
    # port adapter rather than a DataCatalogService).
    try:
        from paleo_workbench.catalog.lifecycle import register_map_compile_run
    except Exception as exc:
        raise ProductionMapError(f"catalog lifecycle 不可用: {exc}") from exc

    tmp2: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix="paleomap_", suffix=".json")
        tmp2 = Path(tmp_name)
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        register_map_compile_run(
            name=doc.name,
            input_version_ids=input_ids,
            source_task_ids=source_task_ids or None,
            domain_task_id=doc.id,
            parameters=params,
            result_path=str(tmp2),
            catalog=service,
        )
    except Exception as exc:
        raise ProductionMapError(
            f"目录 lineage 登记失败（生产编图已中止）: {exc}"
        ) from exc
    finally:
        if tmp2 is not None:
            try:
                tmp2.unlink()
            except OSError:
                pass
