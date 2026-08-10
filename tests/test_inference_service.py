"""P2 Inference job layer E2E: ModelRegistry → InferenceService → catalog.

Covers: demo run (complete + DERIVED output + lineage), failed run (status
failed, NO output version), no-production-model → None, honest demo marking,
and heuristic-run failure on missing inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataRun, DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.prediction.inference_service import (
    execute_run,
    link_run_to_domain_task,
    materialize_prediction_task,
    resolve_prediction_inputs,
    start_inference,
)
from paleo_workbench.prediction.providers import (
    CAPABILITY_FACIES,
    MODEL_ID_DEMO,
    ensure_default_models,
)
from paleo_workbench.project.models import ProjectDocument, ResourceItem


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _write_gr_las(path: Path) -> None:
    lines = [
        "~VERSION INFORMATION",
        " VERS. 2.0:",
        " WRAP. NO:",
        "~WELL INFORMATION",
        " STRT.M 1000.0:",
        " STOP.M 1100.0:",
        " STEP.M 10.0:",
        " NULL. -999.25:",
        " WELL. A1:",
        "~CURVE INFORMATION",
        " DEPT.M :",
        " GR.GAPI :",
        "~ASCII",
    ]
    for i, d in enumerate(range(1000, 1101, 10)):
        gr = 30.0 + (i * 8.0 if i < 6 else 20.0)
        lines.append(f"{d:.1f} {gr:.1f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- default registry ------------------------------------------------------


def test_ensure_default_models_registers_demo_and_heuristic(service):
    demo_m, heur_m, demo_v, heur_v = ensure_default_models(service)
    assert demo_m.status == "demo"
    assert heur_m.status == "demo"
    assert demo_v.demo_only is True
    assert heur_v.demo_only is False
    # No production model → honest unavailable state.
    assert service.find_production_model(CAPABILITY_FACIES) is None
    # Idempotent.
    again = ensure_default_models(service)
    assert again[0].model_id == demo_m.model_id
    assert len(service.list_model_versions(MODEL_ID_DEMO)) == 1


# --- demo run --------------------------------------------------------------


def test_demo_inference_run_complete_with_output_and_lineage(service):
    _demo_m, _heur_m, demo_v, _heur_v = ensure_default_models(service)
    run = start_inference(
        service,
        model_version_id=demo_v.id,
        parameters={"seed": 7, "workflow": "seismic_facies", "name_prefix": "地震相预测"},
    )
    assert isinstance(run, DataRun)
    assert run.status == "running"
    assert run.model_ref["model_id"] == MODEL_ID_DEMO
    assert run.parameters["seed"] == 7
    assert run.parameters["_input_snapshot_hash"]

    out = execute_run(service, run.id)
    finished = out["run"]
    assert finished.status == "complete"
    assert len(finished.output_version_ids) == 1
    assert finished.parameters["_finished_at"]
    assert finished.parameters["output_version_id"] == finished.output_version_ids[0]

    # DERIVED output version with run linkage + honest metadata.
    version = service.get_version(finished.output_version_ids[0])
    assert version.stage == DataStage.DERIVED
    assert version.run_id == finished.id
    assert version.metadata["source"] == "synthetic/demo"
    assert version.metadata["demo"] is True
    payload = json.loads(service.resolve_path(version).read_text(encoding="utf-8"))
    assert payload["demo"] is True
    assert payload["model"]["model_id"] == MODEL_ID_DEMO
    assert payload["result_summary"]["is_mock"] is True
    assert payload["result_summary"]["final_scientific_prediction"] is False
    assert payload["result_summary"]["demo"] is True

    # Lineage: run consumed by output version.
    lineage = service.get_lineage(version.id)
    assert lineage["run"] is not None
    assert lineage["run"].id == finished.id


def test_failed_inference_run_has_no_output(service):
    _demo_m, _heur_m, _demo_v, heur_v = ensure_default_models(service)
    run = start_inference(
        service, model_version_id=heur_v.id, parameters={"seed": 1}
    )
    out = execute_run(service, run.id)
    failed = out["run"]
    assert failed.status == "failed"
    assert failed.output_version_ids == []
    assert "error" in failed.parameters
    assert "error_type" in failed.parameters
    # No DERIVED version was created for the failed run.
    assert service.list_versions(failed.id) == []


def test_execute_run_rejects_unknown_run(service):
    with pytest.raises(Exception):
        execute_run(service, "run_does_not_exist")


def test_start_inference_rejects_unknown_model_version(service):
    with pytest.raises(Exception):
        start_inference(service, model_version_id="mver_does_not_exist")


# --- heuristic run with real LAS -------------------------------------------


def test_heuristic_run_uses_las_and_records_heuristic_labels(service, tmp_path):
    las = tmp_path / "A1.las"
    _write_gr_las(las)
    project = ProjectDocument.new("LAS")
    project.meta.project_root = str(tmp_path)
    project.resources.append(
        ResourceItem(name="A1.las", path=str(las), type="well_log", format="las")
    )
    # Migrate the resource into the catalog so it resolves to a version.
    service.migrate_legacy_resources(project.resources)
    input_ids = resolve_prediction_inputs(project, service)
    assert len(input_ids) == 1

    _demo_m, _heur_m, _demo_v, heur_v = ensure_default_models(service)
    run = start_inference(
        service,
        model_version_id=heur_v.id,
        input_version_ids=input_ids,
        parameters={"seed": 2},
    )
    out = execute_run(service, run.id)
    assert out["run"].status == "complete"
    result = out["result"]
    summary = result["result_summary"]
    assert summary["is_mock"] is False
    assert summary["final_scientific_prediction"] is False
    assert summary["model_type"] == "heuristic"
    assert summary["probabilities_uncalibrated"] is True
    assert summary["source_kind"] in {"las_curve", "las_and_seismic"}
    assert summary.get("well_meta", {}).get("curve")


# --- domain task materialization -------------------------------------------


def test_materialize_prediction_task_carries_honest_flags():
    project = ProjectDocument.new("X")
    payload = {
        "schema_version": "1.0",
        "adapter_kind": "mock",
        "generator_version": "demo-facies-v1",
        "demo": True,
        "source": "synthetic/demo",
        "parameters": {"workflow": "seismic_facies", "name_prefix": "地震相预测"},
        "model": {"model_id": MODEL_ID_DEMO, "model_version": "1",
                  "model_name": "演示", "demo_only": True},
        "result_summary": {
            "predicted_regions": [{"region_id": "r1", "facies": "砂", "probability": 0.8}],
            "is_mock": True,
            "final_scientific_prediction": False,
            "demo": True,
            "source": "synthetic/demo",
            "model_type": "demo",
        },
        "probability_summary": {"mean_probability": 0.8},
        "evidence_contribution": [],
        "review_areas": [],
        "seed": 7,
    }
    task = materialize_prediction_task(
        project, payload, name_prefix="地震相预测", workflow="seismic_facies"
    )
    assert task.model_metadata["model_id"] == MODEL_ID_DEMO
    assert task.model_metadata["demo_only"] is True
    assert task.model_metadata["demo"] is True
    assert task.result_summary["is_mock"] is True
    assert task.result_summary["final_scientific_prediction"] is False
    assert task.seed == 7


def test_link_run_to_domain_task(service):
    _demo_m, _heur_m, demo_v, _heur_v = ensure_default_models(service)
    run = start_inference(service, model_version_id=demo_v.id)
    linked = link_run_to_domain_task(service, run.id, "pred_abc")
    assert linked.parameters["_domain_task_id"] == "pred_abc"


# ------------------------------------------------------ thread-safe result asset (finding #4)


def test_register_result_asset_creates_asset_and_version_atomically(service, tmp_path):
    """Worker-facing result registration goes through ONE locked operation:
    asset + version committed together, run output linkage set."""
    src = tmp_path / "result.json"
    src.write_text(json.dumps({"source": "inference", "demo": True}), encoding="utf-8")

    run = service.register_run(
        operation="prediction",
        input_version_ids=[],
        parameters={"adapter_kind": "demo"},
    )
    run_id = run.id
    version = service.register_result_asset(
        name="Demo 模型 结果",
        type="prediction_result",
        format="json",
        asset_metadata={"kind": "prediction_result"},
        source_path=src,
        stage=DataStage.DERIVED,
        run_id=run_id,
        version_metadata={"demo": True, "kind": "prediction_result"},
    )

    assert version.stage == DataStage.DERIVED
    assert service.get_asset(version.asset_id).name == "Demo 模型 结果"
    # Run output linkage updated in the same save.
    run = service.get_run(run_id)
    assert version.id in run.output_version_ids
    # Payload managed & readable.
    payload = service.resolve_path(version)
    assert payload.is_file()
    assert json.loads(payload.read_text(encoding="utf-8"))["demo"] is True


def test_register_result_asset_failure_leaves_no_half_asset(service, tmp_path):
    """A failing registration (missing source) rolls back the freshly created
    asset — no orphan asset, no stray document entries (worker crash safety)."""
    before_assets = len(service.document.assets)
    missing = tmp_path / "does_not_exist.json"

    with pytest.raises(Exception):
        service.register_result_asset(
            name="失败 结果",
            type="prediction_result",
            format="json",
            asset_metadata={"kind": "prediction_result"},
            source_path=missing,
            stage=DataStage.DERIVED,
        )

    assert len(service.document.assets) == before_assets
    assert len(service.document.versions) == 0


# ------------------------------------------- production promotion durability (C2)


def test_promote_model_survives_ensure_default_models(service):
    """An explicitly promoted production model must NOT be silently reset to
    demo by ensure_default_models on the next run (review finding C2)."""
    from paleo_workbench.prediction.providers import (
        CAPABILITY_FACIES,
        MODEL_ID_HEURISTIC,
        ensure_default_models,
    )

    ensure_default_models(service)
    # No production model initially (honest unavailable state).
    assert service.find_production_model(CAPABILITY_FACIES) is None

    # Explicit promotion (the sanctioned act).
    promoted = service.promote_model(MODEL_ID_HEURISTIC, "1")
    assert promoted.status == "production"
    assert service.find_production_model(CAPABILITY_FACIES) is not None

    # ensure_default_models runs again (as on every run click) — must preserve.
    ensure_default_models(service)
    found = service.find_production_model(CAPABILITY_FACIES)
    assert found is not None
    assert found.model_id == MODEL_ID_HEURISTIC
    assert found.status == "production"
    assert service.get_model(MODEL_ID_HEURISTIC).status == "production"


def test_register_model_force_status_controls_existing_model(service):
    """register_model with force_status=False preserves an existing model's
    status/metadata; force_status=True deliberately changes them."""
    from paleo_workbench.prediction.providers import (
        MODEL_ID_DEMO,
        ensure_default_models,
    )

    ensure_default_models(service)
    service.promote_model(MODEL_ID_DEMO, "1")

    # Seed-style re-registration (force_status=False) does not downgrade.
    service.register_model(
        model_id=MODEL_ID_DEMO,
        model_name="演示相带预测（Demo）",
        model_type="demo",
        capability="facies",
        provider="demo",
        status="demo",
        metadata={"source": "synthetic/demo"},
    )
    assert service.get_model(MODEL_ID_DEMO).status == "production"

    # Explicit force_status=True updates it.
    service.register_model(
        model_id=MODEL_ID_DEMO,
        model_name="演示相带预测（Demo）",
        model_type="demo",
        capability="facies",
        provider="demo",
        status="demo",
        metadata={"source": "synthetic/demo"},
        force_status=True,
    )
    assert service.get_model(MODEL_ID_DEMO).status == "demo"
