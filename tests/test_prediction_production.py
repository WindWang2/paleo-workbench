"""Stage 13: production prediction package + real paleomap pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import CatalogError, DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.pipeline.compile_map import compile_map_draft
from paleo_workbench.pipeline.compile_map_production import (
    ProductionMapError,
    compile_map_production,
)
from paleo_workbench.prediction.inference_service import (
    execute_run,
    materialize_prediction_task,
    resolve_inputs_for_model,
    start_inference,
)
from paleo_workbench.prediction.model_package import (
    ModelPackageError,
    can_promote_to_production,
    register_model_package,
)
from paleo_workbench.prediction.providers import (
    CAPABILITY_FACIES,
    MODEL_ID_DEMO,
    MODEL_ID_HEURISTIC,
    ensure_default_models,
    register_provider,
)
from paleo_workbench.prediction.spatial_result import extract_polygon_features
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.workflow.contracts.readiness import evaluate_readiness
from paleo_workbench.workflow.contracts.registry import WorkflowContractRegistry
from tests.fakes.spatial_model_provider import (
    PROVIDER_TEST_SPATIAL,
    PROVIDER_TEST_SPATIAL_FAIL,
    PROVIDER_TEST_SPATIAL_MALFORMED,
    TestSpatialFailProvider,
    TestSpatialMalformedProvider,
    TestSpatialModelProvider,
)


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _register_well(service, tmp_path: Path, name: str = "W0.las") -> tuple[str, ProjectDocument]:
    """Write a LAS, migrate into catalog, return (version_id, project)."""
    las = tmp_path / name
    las.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 1000.0:",
                " STOP.M 1010.0:",
                " STEP.M 10.0:",
                " NULL. -999.25:",
                " WELL. A1:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "1000.0 40.0",
                "1010.0 50.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    project = ProjectDocument.new("Wells")
    project.meta.project_root = str(tmp_path)
    project.resources.append(
        ResourceItem(
            id="well-0",
            name=name,
            path=str(las),
            type="well_log",
            format="las",
        )
    )
    service.migrate_legacy_resources(project.resources)
    from paleo_workbench.prediction.inference_service import resolve_prediction_inputs

    ids = resolve_prediction_inputs(project, service)
    assert ids, "well version must resolve after migrate"
    return ids[0], project


def _package_manifest(artifact: Path, **overrides) -> dict:
    base = {
        "model_id": "test-spatial-pkg-v1",
        "model_version": "1",
        "model_name": "Test Spatial Package",
        "capability": CAPABILITY_FACIES,
        "provider": PROVIDER_TEST_SPATIAL,
        "artifact": str(artifact),
        "model_type": "ml",
        "input_schema": {"required_asset_types": ["well_log"], "min_wells": 1},
        "output_schema": {"spatial_output_type": "VECTOR_POLYGONS"},
        "spatial_output_type": "VECTOR_POLYGONS",
        "scientific": True,
        "demo_only": False,
        "runtime": "python_callable",
        "preprocessing_version": "prep-v1",
    }
    base.update(overrides)
    return base


def _install_test_provider(service, tmp_path, provider_cls=TestSpatialModelProvider, **kw):
    register_provider(PROVIDER_TEST_SPATIAL, provider_cls)
    if provider_cls is TestSpatialFailProvider:
        register_provider(PROVIDER_TEST_SPATIAL_FAIL, provider_cls)
    if provider_cls is TestSpatialMalformedProvider:
        register_provider(PROVIDER_TEST_SPATIAL_MALFORMED, provider_cls)
    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"spatial-weights-v1")
    manifest = _package_manifest(artifact, **kw)
    if provider_cls is TestSpatialFailProvider:
        manifest["model_id"] = "test-spatial-fail-v1"
        manifest["provider"] = PROVIDER_TEST_SPATIAL_FAIL
    if provider_cls is TestSpatialMalformedProvider:
        manifest["model_id"] = "test-spatial-malformed-v1"
        manifest["provider"] = PROVIDER_TEST_SPATIAL_MALFORMED
    model, version = register_model_package(service, manifest, require_artifact=True)
    service.promote_model(manifest["model_id"], manifest["model_version"])
    return model, service.get_model_version(manifest["model_id"], manifest["model_version"])


# --- no production model honesty -------------------------------------------------


def test_no_production_model_blocks_scientific_path(service):
    ensure_default_models(service)
    assert service.find_production_model(CAPABILITY_FACIES) is None
    # Promote demo/heuristic must fail.
    with pytest.raises(CatalogError):
        service.promote_model(MODEL_ID_DEMO, "1")
    with pytest.raises(CatalogError):
        service.promote_model(MODEL_ID_HEURISTIC, "1")
    assert service.find_production_model(CAPABILITY_FACIES) is None


def test_demo_compile_still_isolated_from_production_map(tmp_path, service):
    ensure_default_models(service)
    project = ProjectDocument.new("NoModel")
    project.stratigraphy.target_horizon = "H1"
    # Demo draft path still works but is marked is_demo_draft.
    doc = compile_map_draft(project, target_horizon="H1", seed=0)
    assert doc.view_state.get("is_demo_draft") is True
    # Production compiler refuses empty/non-spatial.
    with pytest.raises(ProductionMapError):
        compile_map_production(project, target_horizon="H1")


# --- package register + inference lifecycle --------------------------------------


def test_register_package_and_run_spatial_inference(tmp_path, service):
    well_vid, project = _register_well(service, tmp_path)
    project.stratigraphy.target_horizon = "H1"
    _model, mver = _install_test_provider(service, tmp_path)

    input_ids = resolve_inputs_for_model(project, service, mver.id, strict=True)
    assert well_vid in input_ids
    # Must not over-declare: only well (schema requires well_log).
    assert all(
        service.get_version(vid) is not None for vid in input_ids
    )

    run = start_inference(
        service,
        model_version_id=mver.id,
        input_version_ids=input_ids,
        parameters={"seed": 3, "workflow": "facies", "name_prefix": "test"},
    )
    assert run.input_version_ids == input_ids
    out = execute_run(service, run.id)
    finished = out["run"]
    assert finished.status == "complete"
    assert len(finished.output_version_ids) == 1
    version = service.get_version(finished.output_version_ids[0])
    assert version.stage == DataStage.DERIVED
    payload = out["result"]
    assert payload["result_summary"]["final_scientific_prediction"] is True
    feats = extract_polygon_features(payload)
    assert len(feats) == 2
    # Real coordinates — not demo square origin.
    ring = feats[0]["geometry"]["coordinates"][0]
    xs = [p[0] for p in ring]
    assert min(xs) == pytest.approx(120.10)
    assert 114.0 not in xs

    task = materialize_prediction_task(
        project, payload, name_prefix="test", workflow="facies", target_horizon="H1"
    )
    project.prediction_tasks.append(task)
    # Summary is bounded (no giant grids).
    assert "grid" not in (task.result_summary.get("spatial") or {})


def test_fail_provider_no_derived_output(tmp_path, service):
    _register_well(service, tmp_path)
    register_provider(PROVIDER_TEST_SPATIAL_FAIL, TestSpatialFailProvider)
    artifact = tmp_path / "w.bin"
    artifact.write_bytes(b"x")
    register_model_package(
        service,
        _package_manifest(
            artifact,
            model_id="test-spatial-fail-v1",
            provider=PROVIDER_TEST_SPATIAL_FAIL,
        ),
    )
    service.promote_model("test-spatial-fail-v1", "1")
    mver = service.get_model_version("test-spatial-fail-v1", "1")
    run = start_inference(service, model_version_id=mver.id, input_version_ids=[])
    out = execute_run(service, run.id)
    assert out["run"].status == "failed"
    assert out["run"].output_version_ids == []
    assert out["result"] is None


def test_malformed_spatial_output_fails_run(tmp_path, service):
    _register_well(service, tmp_path)
    register_provider(PROVIDER_TEST_SPATIAL_MALFORMED, TestSpatialMalformedProvider)
    artifact = tmp_path / "w.bin"
    artifact.write_bytes(b"x")
    register_model_package(
        service,
        _package_manifest(
            artifact,
            model_id="test-spatial-malformed-v1",
            provider=PROVIDER_TEST_SPATIAL_MALFORMED,
        ),
    )
    service.promote_model("test-spatial-malformed-v1", "1")
    mver = service.get_model_version("test-spatial-malformed-v1", "1")
    run = start_inference(service, model_version_id=mver.id, input_version_ids=[])
    out = execute_run(service, run.id)
    assert out["run"].status == "failed"
    assert out["run"].output_version_ids == []


def test_package_rejects_demo_provider_as_production(tmp_path, service):
    artifact = tmp_path / "w.bin"
    artifact.write_bytes(b"x")
    with pytest.raises(ModelPackageError):
        register_model_package(
            service,
            {
                "model_id": "evil-demo",
                "model_version": "1",
                "model_name": "Evil",
                "capability": CAPABILITY_FACIES,
                "provider": "demo",
                "artifact": str(artifact),
                "input_schema": {"required_asset_types": ["well_log"]},
                "model_type": "demo",
            },
        )


# --- paleomap production ---------------------------------------------------------


def test_production_map_preserves_real_coordinates(tmp_path, service):
    _well_vid, project = _register_well(service, tmp_path)
    project.stratigraphy.target_horizon = "ZJ2"
    _model, mver = _install_test_provider(service, tmp_path)
    input_ids = resolve_inputs_for_model(project, service, mver.id, strict=True)
    run = start_inference(
        service, model_version_id=mver.id, input_version_ids=input_ids
    )
    out = execute_run(service, run.id)
    assert out["run"].status == "complete"
    task = materialize_prediction_task(
        project, out["result"], name_prefix="p", workflow="f", target_horizon="ZJ2"
    )
    project.prediction_tasks.append(task)

    doc = compile_map_production(
        project,
        target_horizon="ZJ2",
        prediction_task_id=task.id,
        prediction_payload=out["result"],
        prediction_version_id=out["run"].output_version_ids[0],
        catalog_service=service,
    )
    assert doc.view_state.get("is_demo_draft") is False
    assert doc.view_state.get("production") is True
    # H3: lineage must be durably registered with the prediction input.
    assert any(
        r.operation == "map_compile"
        and out["run"].output_version_ids[0] in r.input_version_ids
        for r in service.document.runs
    )
    assert len(doc.facies_polygons) == 2
    ring = doc.facies_polygons[0]["geometry"]["coordinates"][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    assert min(xs) == pytest.approx(120.10)
    assert min(ys) == pytest.approx(30.20)
    # Must not be the demo fixed square origin.
    assert not (min(xs) == 114.0 and min(ys) == 22.5)


def test_production_map_blocks_nonspatial_and_well_intervals():
    project = ProjectDocument.new("Block")
    project.stratigraphy.target_horizon = "H1"
    from paleo_workbench.project.models import PredictionTask

    task = PredictionTask(
        name="intervals",
        result_summary={
            "final_scientific_prediction": True,
            "spatial_output_type": "WELL_INTERVALS",
            "spatial": {
                "type": "WELL_INTERVALS",
                "intervals": [{"well": "W0", "top": 10, "bottom": 20}],
            },
            "predicted_regions": [{"facies": "S", "top": 10, "bottom": 20}],
        },
    )
    project.prediction_tasks.append(task)
    with pytest.raises(ProductionMapError, match="WELL_INTERVALS"):
        compile_map_production(project, target_horizon="H1")

    task2 = PredictionTask(
        name="labels-only",
        result_summary={
            "final_scientific_prediction": True,
            "predicted_regions": [{"facies": "S", "probability": 0.9}],
        },
    )
    project.prediction_tasks.append(task2)
    with pytest.raises(ProductionMapError):
        compile_map_production(project, prediction_task_id=task2.id)


def test_prediction_v2_marks_map_stale_via_freshness(tmp_path, service):
    """Stage-9: after link_run_to_domain_task, prediction is FRESH; after a
    relevant well tip change, Prediction V1 and map_compile are STALE.

    Drives shipped FreshnessService.evaluate_run (not a re-implementation).
    """
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.models import DataStage
    from paleo_workbench.prediction.inference_service import link_run_to_domain_task
    from paleo_workbench.workflow.current_context import (
        resolve_current_project_version_context,
    )
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.freshness import (
        FreshnessService,
        FreshnessState,
    )

    well_vid, project = _register_well(service, tmp_path)
    project.stratigraphy.target_horizon = "H1"
    _model, mver = _install_test_provider(service, tmp_path)
    input_ids = resolve_inputs_for_model(project, service, mver.id, strict=True)
    assert well_vid in input_ids

    # --- Prediction V1 + link (UI production path) ---
    run1 = start_inference(
        service,
        model_version_id=mver.id,
        input_version_ids=input_ids,
        parameters={"seed": 1},
    )
    out1 = execute_run(service, run1.id)
    assert out1["run"].status == "complete"
    pred_v1 = out1["run"].output_version_ids[0]
    # Critical Stage-13 identity: run.generator == task generator_version.
    assert out1["run"].generator == out1["result"].get("generator_version")
    assert out1["run"].generator  # non-empty provider identity

    task = materialize_prediction_task(
        project,
        out1["result"],
        name_prefix="p",
        workflow="f",
        target_horizon="H1",
        run_id=out1["run"].id,
        output_version_id=pred_v1,
    )
    project.prediction_tasks.append(task)
    link_run_to_domain_task(service, out1["run"].id, task.id)
    assert task.generator_version == out1["run"].generator

    cat = CoreCatalogAdapter(service)
    graph = DependencyGraph.from_catalog(cat)
    ctx = resolve_current_project_version_context(project, catalog=cat)
    fresh_svc = FreshnessService(graph, ctx, catalog=cat)

    pred_rep = fresh_svc.evaluate_run(out1["run"].id)
    assert pred_rep.state is FreshnessState.FRESH, (
        f"fresh linked prediction must be FRESH, got {pred_rep.state}: "
        f"{pred_rep.reasons}"
    )

    # --- Map compile lineage from Prediction V1 ---
    doc = compile_map_production(
        project,
        target_horizon="H1",
        prediction_payload=out1["result"],
        prediction_version_id=pred_v1,
        catalog_service=service,
    )
    map_runs = [r for r in service.document.runs if r.operation == "map_compile"]
    assert map_runs, "map_compile DataRun required for Stage-9 map freshness"
    map_run = map_runs[-1]
    assert pred_v1 in map_run.input_version_ids
    assert (map_run.parameters or {}).get("_domain_task_id") == doc.id

    graph = DependencyGraph.from_catalog(cat)
    ctx = resolve_current_project_version_context(project, catalog=cat)
    fresh_svc = FreshnessService(graph, ctx, catalog=cat)
    map_rep = fresh_svc.evaluate_run(map_run.id)
    assert map_rep.state is FreshnessState.FRESH, (
        f"map from current prediction tip must be FRESH, got {map_rep.state}: "
        f"{map_rep.reasons}"
    )

    # --- Relevant upstream tip change on the SAME well asset ---
    well_asset = next(a for a in service.document.assets if a.type == "well_log")
    las2 = tmp_path / "W0b.las"
    las2.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 1000.0:",
                " STOP.M 1010.0:",
                " STEP.M 10.0:",
                " NULL. -999.25:",
                " WELL. A1:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "1000.0 99.0",
                "1010.0 88.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    well_v2 = service.register_version(well_asset.id, las2, DataStage.RAW)
    assert well_asset.current_version_id == well_v2.id
    assert well_v2.id != well_vid

    # Prediction V2 on the new tip (proves new DERIVED + FRESH current path).
    run2 = start_inference(
        service,
        model_version_id=mver.id,
        input_version_ids=[well_v2.id],
        parameters={"seed": 2},
    )
    out2 = execute_run(service, run2.id)
    pred_v2 = out2["run"].output_version_ids[0]
    assert pred_v1 != pred_v2
    task_v2 = materialize_prediction_task(
        project,
        out2["result"],
        name_prefix="p",
        workflow="f",
        target_horizon="H1",
        run_id=out2["run"].id,
        output_version_id=pred_v2,
    )
    project.prediction_tasks = [task_v2]
    link_run_to_domain_task(service, out2["run"].id, task_v2.id)

    graph = DependencyGraph.from_catalog(cat)
    ctx = resolve_current_project_version_context(project, catalog=cat)
    ctx.select(well_asset.id, well_v2.id)
    fresh_svc = FreshnessService(graph, ctx, catalog=cat)

    pred_v1_rep = fresh_svc.evaluate_run(out1["run"].id)
    assert pred_v1_rep.state is FreshnessState.STALE, (
        f"Prediction V1 must be STALE after well tip change, "
        f"got {pred_v1_rep.state}: {pred_v1_rep.reasons}"
    )

    map_stale = fresh_svc.evaluate_run(map_run.id)
    assert map_stale.state is FreshnessState.STALE, (
        f"map from Prediction V1 must be STALE after tip change, "
        f"got {map_stale.state}: {map_stale.reasons}"
    )

    pred_v2_rep = fresh_svc.evaluate_run(out2["run"].id)
    assert pred_v2_rep.state is FreshnessState.FRESH, (
        f"Prediction V2 must be FRESH, got {pred_v2_rep.state}: {pred_v2_rep.reasons}"
    )


# --- readiness / contracts -------------------------------------------------------


def test_facies_prediction_readiness_warns_without_production_model(service):
    ensure_default_models(service)
    project = ProjectDocument.new("Ready")
    from paleo_workbench.workflow.contracts.registry import get_default_registry
    from paleo_workbench.workflow.contracts.readiness import evaluate_contract_readiness

    reg = get_default_registry()
    contract = reg.get_contract("facies_prediction")
    assert contract is not None
    report = evaluate_contract_readiness(project, contract)
    codes = {r.code for r in report.reasons}
    assert "no_production_model" in codes or "prediction_demo_only" in codes


def test_send_to_mapping_logic_blocks_nonspatial_non_demo():
    """Production non-spatial prediction must not compile demo squares.

    Mirrors workflow_controller branching without Qt.
    """
    from paleo_workbench.pipeline.compile_map import compile_map_draft
    from paleo_workbench.pipeline.compile_map_production import compile_map_production
    from paleo_workbench.prediction.spatial_result import is_map_compilable
    from paleo_workbench.project.models import PredictionTask

    project = ProjectDocument.new("SendMap")
    project.stratigraphy.target_horizon = "H1"
    scientific = PredictionTask(
        name="sci",
        adapter_kind="local",
        result_summary={
            "final_scientific_prediction": True,
            "demo": False,
            "is_mock": False,
            "predicted_regions": [{"facies": "S", "probability": 0.9}],
        },
        model_metadata={"demo": False, "demo_only": False},
    )
    project.prediction_tasks.append(scientific)
    payload = {"result_summary": scientific.result_summary}
    assert not is_map_compilable(payload)
    # Controller must block: production compile raises; demo must not be invoked.
    with pytest.raises(ProductionMapError):
        compile_map_production(
            project, prediction_task_id=scientific.id, prediction_payload=payload
        )
    assert not any(
        (d.view_state or {}).get("is_demo_draft") for d in project.paleomap_documents
    )

    # Explicit demo task may use demo compiler.
    demo_task = PredictionTask(
        name="demo",
        adapter_kind="mock",
        result_summary={
            "demo": True,
            "is_mock": True,
            "final_scientific_prediction": False,
            "predicted_regions": [{"facies": "A", "probability": 0.5}],
        },
        model_metadata={"demo": True},
    )
    project.prediction_tasks.append(demo_task)
    compile_map_draft(project, prediction_task_id=demo_task.id, seed=0)
    assert any((d.view_state or {}).get("is_demo_draft") for d in project.paleomap_documents)


def test_map_compile_registers_lineage_on_catalog_service(tmp_path, service):
    _well_vid, project = _register_well(service, tmp_path)
    project.stratigraphy.target_horizon = "H1"
    _model, mver = _install_test_provider(service, tmp_path)
    input_ids = resolve_inputs_for_model(project, service, mver.id, strict=True)
    run = start_inference(service, model_version_id=mver.id, input_version_ids=input_ids)
    out = execute_run(service, run.id)
    task = materialize_prediction_task(
        project, out["result"], name_prefix="p", workflow="f", target_horizon="H1"
    )
    project.prediction_tasks.append(task)
    pred_vid = out["run"].output_version_ids[0]
    doc = compile_map_production(
        project,
        target_horizon="H1",
        prediction_payload=out["result"],
        prediction_version_id=pred_vid,
        catalog_service=service,
    )
    map_runs = [r for r in service.document.runs if r.operation == "map_compile"]
    assert map_runs, "map_compile DataRun must be registered via DataCatalogService"
    assert pred_vid in map_runs[-1].input_version_ids
    assert map_runs[-1].status == "complete"
    assert map_runs[-1].output_version_ids
    assert doc.view_state.get("is_demo_draft") is False


def test_schema_driven_inputs_exclude_unrelated_seismic(tmp_path, service):
    well_vid, project = _register_well(service, tmp_path)
    seis = tmp_path / "s.segy"
    seis.write_bytes(b"SEGY")
    project.resources.append(
        ResourceItem(
            id="seis-0",
            name="s.segy",
            path=str(seis),
            type="seismic",
            format="segy",
        )
    )
    service.migrate_legacy_resources(project.resources)
    _model, mver = _install_test_provider(service, tmp_path)
    input_ids = resolve_inputs_for_model(project, service, mver.id, strict=True)
    assert well_vid in input_ids
    # Seismic must not be included when schema only requires well_log.
    for vid in input_ids:
        asset_type = None
        version = service.get_version(vid)
        for a in service.document.assets:
            if a.id == version.asset_id:
                asset_type = a.type
                break
        assert asset_type != "seismic"
