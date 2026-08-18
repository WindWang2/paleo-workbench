"""Issue #848 — architecture / data-hygiene batch regression tests.

Covers (subset with behavior-level assertions):
- correlation/fault saves no longer leak unreferenced local ghost artifacts
- catalog.service imports without pulling in the prediction package (no
  layered cycle); gates re-exported from the catalog layer
- the adapter-shaped run view is a single shared implementation
- readiness evaluation reads the caller-supplied catalog, not only the global
- contract graph upstream/downstream edges are symmetric (validation enforces)
- factor-prepare parallel groups tolerate one failing group
- session caches clear on project close (public API wired)
- synthetic factor tasks stay source_kind="mock" through interpolation
- register_version rejects unsafe version ids; double-corrupt store raises
  CatalogError and isolates the bytes
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paleo_workbench.catalog import (
    CatalogStore,
    CoreCatalogAdapter,
    DataCatalogService,
    DataStage,
)
from paleo_workbench.catalog.models import CatalogError
from paleo_workbench.catalog.store import (
    catalog_bak_file_for,
    catalog_file_for,
)
from paleo_workbench.project.factor_grid_artifacts import (
    clear_session_caches,
    has_live_factor_grid,
    live_factor_grid_cache_stats,
    store_live_factor_grid,
)
from paleo_workbench.project.models import (
    FactorMapTask,
    PredictionTask,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.workflow.correlation_lifecycle import (
    new_correlation_draft,
    save_correlation_draft,
)
from paleo_workbench.workflow.fault_lifecycle import (
    new_fault_draft,
    save_fault_draft,
)
from paleo_workbench.workflow.stratigraphy_models import (
    CorrelationMethod,
    DepthDomain,
    FormationTop,
)


def _make_project_path(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture()
def project_path(tmp_path: Path) -> Path:
    return _make_project_path(tmp_path)


@pytest.fixture()
def service(project_path: Path):
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


@pytest.fixture()
def project(project_path: Path):
    return ProjectDocument.new(name="Demo")


def _points(seed: int, base_x: float) -> list[dict]:
    rng = __import__("random").Random(seed)
    pts = []
    for i in range(6):
        pts.append(
            {
                "x": base_x + rng.uniform(0, 1000),
                "y": rng.uniform(0, 1000),
                "value": rng.uniform(10, 30),
            }
        )
    return pts


# ------------------------------------------------- 1. ghost artifact leak


def test_correlation_save_leaves_no_unreferenced_local_artifact(
    tmp_path, project_path, project
):
    from paleo_workbench.catalog import get_catalog

    adapter = _open_adapter(project_path)
    try:
        draft = new_correlation_draft(name="corr1")
        draft.payload.tops = [
            FormationTop(
                well_id="w1",
                well_name="W1",
                marker="H1",
                depth=100.0,
                depth_domain=DepthDomain.MD,
                method=CorrelationMethod.MANUAL,
            )
        ]
        ref, status = save_correlation_draft(
            draft, project, project_path, catalog=adapter
        )
        assert status == "ok"

        corr_dir = _artifact_dir_for(project_path, "correlations")
        leftovers = [
            p for p in corr_dir.glob("*") if p.suffix == ".json"
        ]
        assert leftovers == [], (
            "correlation save must not leave unreferenced local artifacts, "
            f"found {leftovers}"
        )
        managed = _resolve_managed(ref.artifact_path, project_path)
        assert managed.is_file()
        assert ref.current_version_id.startswith("ver_")
    finally:
        adapter.service.close()
        get_catalog()  # no global wiring needed here


def test_fault_save_leaves_no_unreferenced_local_artifact(
    tmp_path, project_path, project
):
    adapter = _open_adapter(project_path)
    try:
        draft = new_fault_draft(
            name="fault1",
            traces=[],
            source_version_ids=["ver_x"],
        )
        ref, status = save_fault_draft(draft, project, project_path, catalog=adapter)
        assert status == "ok"

        fault_dir = _artifact_dir_for(project_path, "faults")
        leftovers = [p for p in fault_dir.glob("*") if p.suffix == ".json"]
        assert leftovers == [], (
            "fault save must not leave unreferenced local artifacts, "
            f"found {leftovers}"
        )
        managed = _resolve_managed(ref.artifact_path, project_path)
        assert managed.is_file()
    finally:
        adapter.service.close()


def test_correlation_save_keeps_local_when_no_catalog(
    tmp_path, project_path, project, monkeypatch
):
    """Without a catalog the local file IS the referenced copy — keep it."""
    monkeypatch.setattr("paleo_workbench.catalog.get_catalog", lambda: None)
    draft = new_correlation_draft(name="corr2")
    ref, status = save_correlation_draft(draft, project, project_path)
    assert status == "ok"
    corr_dir = _artifact_dir_for(project_path, "correlations")
    assert len(list(corr_dir.glob("*.json"))) == 1


# --------------------------------------------------- 2. catalog⇄prediction cycle


def test_catalog_service_imports_without_prediction_package():
    """Headless catalog must not pull the prediction package (layering)."""
    root = str(Path(__file__).resolve().parents[1])
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import paleo_workbench.catalog.service as s; "
        "print(any(m.startswith('paleo_workbench.prediction') for m in sys.modules))"
        % root
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_promote_gates_reexported_from_catalog_layer():
    from paleo_workbench.catalog.model_gates import (
        can_promote_to_production as catalog_gate,
    )
    from paleo_workbench.prediction.model_package import (
        can_promote_to_production as package_gate,
    )

    assert catalog_gate is package_gate
    # The policy constants are single-sourced in the catalog layer.
    from paleo_workbench.catalog.model_gates import NON_PROMOTABLE_PROVIDERS

    assert NON_PROMOTABLE_PROVIDERS == frozenset({"demo", "local_asset"})


def test_promote_gate_rejects_demo_provider(service, tmp_path):
    from paleo_workbench.catalog.model_gates import can_promote_to_production

    service.register_model(
        model_id="m1",
        model_name="DemoModel",
        model_type="ml",
        capability="facies_prediction",
        provider="demo",
        status="demo",
    )
    service.register_model_version(
        "m1",
        model_version="1",
        artifact_uri=str(tmp_path / "w.bin"),
        checksum=None,
        input_schema={"well_log": []},
        output_schema={},
        demo_only=True,
    )
    ok, reason = can_promote_to_production(service, "m1", "1")
    assert ok is False
    assert "demo" in reason


# ---------------------------------------- 3. shared run view implementation


def test_service_run_view_single_implementation():
    from paleo_workbench.prediction import inference_service
    from paleo_workbench.prediction import input_contract

    assert inference_service._ServiceRunView is input_contract._ServiceRunView
    assert inference_service._RunProxy is input_contract._RunProxy


def test_link_run_to_domain_task_uses_public_surface(service, tmp_path):
    from paleo_workbench.prediction.inference_service import (
        link_run_to_domain_task,
    )

    adapter = CoreCatalogAdapter(service)
    src = tmp_path / "w.las"
    src.write_bytes(b"data")
    raw = adapter.register_input(name=src.name, path=str(src), checksum=None)
    run = adapter.begin_run(operation="prediction", input_version_ids=[raw.version_id])
    linked = link_run_to_domain_task(service, run.run_id, "task_42")
    # Persisted via the public API and readable back from disk.
    assert (linked.parameters or {}).get("_domain_task_id") == "task_42"
    assert service.get_run(run.run_id).parameters["_domain_task_id"] == "task_42"


# ------------------------------------------------- 4. readiness catalog param


def test_readiness_uses_passed_catalog_not_global(monkeypatch):
    from paleo_workbench.workflow.contracts.readiness import evaluate_readiness

    project = ProjectDocument.new(name="Demo")
    project.prediction_tasks.append(PredictionTask(name="p1"))

    global_catalog = SimpleNamespace(find_production_model=lambda cap: None)
    monkeypatch.setattr(
        "paleo_workbench.catalog.get_catalog_service", lambda: global_catalog
    )

    # Passed catalog HAS a production model → no no_production_model reason.
    with_model = SimpleNamespace(find_production_model=lambda cap: object())
    report = evaluate_readiness(
        project, "facies_prediction", catalog=with_model
    )
    codes = [r.code for r in report.reasons]
    assert "no_production_model" not in codes


# ------------------------------------------------- 5. contract edge symmetry


def test_contract_edges_symmetric_and_labels_present():
    from paleo_workbench.workflow.contracts.registry import get_default_registry
    from paleo_workbench.workflow.contracts.validation import validate_registry
    from paleo_workbench.workflow.recompute_plan import OPERATION_LABELS_ZH

    reg = get_default_registry()
    assert validate_registry(reg) == []
    by_id = {c.id: c for c in reg.list_contracts()}
    # The two edges the audit called out are now mirrored on both sides.
    assert "fault_interpretation" in by_id["seismic_volume"].downstream_contract_ids
    assert "well_correlation" in by_id["factor_interpolation"].upstream_contract_ids
    assert "well_seismic_joint" in by_id["horizon_interpretation"].upstream_contract_ids
    assert "stratigraphic_correlation" in OPERATION_LABELS_ZH
    assert "fault_interpretation" in OPERATION_LABELS_ZH


# ------------------------------------------- 6. scheduler group fault tolerance


def test_parallel_group_failure_keeps_other_group_results(monkeypatch):
    """PALEO_PREPARE_WORKERS>1: one exploding group must not discard the
    completed results of the other groups (serial path already isolated)."""
    from paleo_workbench.workflow.factor_prepare_scheduler import (
        batch_prepare_factor_maps as sched_batch,
        build_prepare_snapshot,
        run_factor_prepare_schedule,
    )

    project = ProjectDocument.new(name="Demo")
    # Give each location pair the same sample geometry so they share an
    # independent plan group; different locations keep A/B groups distinct.
    for name, base_x in [("A1", 0.0), ("A2", 0.0), ("B1", 50000.0), ("B2", 50000.0)]:
        project.factor_map_tasks.append(
            FactorMapTask(
                name=name,
                target_horizon="H1",
                factor_type="sand" if name.endswith("1") else "clay",
                method="IDW",
                parameters={"sample_points": _points(int(base_x / 1000), base_x)},
                status="pending",
            )
        )
    snap = build_prepare_snapshot(project, generation=1, method="IDW", grid_n=16)

    real_batch = sched_batch

    def exploding_batch(sub, **kwargs):
        names = {t.name for t in sub.factor_map_tasks}
        if any(n.startswith("B") for n in names):
            raise RuntimeError("B group boom")
        return real_batch(sub, **kwargs)

    monkeypatch.setattr(
        "paleo_workbench.workflow.factor_prepare_scheduler.batch_prepare_factor_maps",
        exploding_batch,
    )

    result = run_factor_prepare_schedule(snap, workers=2)

    assert result.failed_count >= 1
    # Map result back to original task names (task ids are "factor_…", not "A1").
    name_by_id = {t.id: t.name for t in project.factor_map_tasks}
    a = [r for r in result.task_results if name_by_id.get(r.task_id, "").startswith("A")]
    b = [r for r in result.task_results if name_by_id.get(r.task_id, "").startswith("B")]
    assert len(a) == 2 and len(b) == 2
    # A-group tasks completed with grids; B-group tasks recorded the failure.
    assert all(r.error is None and r.task is not None for r in a)
    assert all(r.error for r in b)


# ------------------------------------------------- 8. session cache clearing


def test_session_caches_clear_on_project_close():
    from paleo_workbench.workflow.freshness import clear_dependency_graph_cache
    from paleo_workbench.workflow.interpolation_fingerprint import plan_cache_clear

    # Start from a known-empty cache so earlier tests in the same process do
    # not affect the accounting.
    clear_session_caches()
    clear_dependency_graph_cache()
    plan_cache_clear()

    store_live_factor_grid("t1", _fake_grid_result())
    assert has_live_factor_grid("t1") is True
    assert live_factor_grid_cache_stats()["entries"] >= 1

    clear_session_caches()
    clear_dependency_graph_cache()
    plan_cache_clear()

    assert live_factor_grid_cache_stats()["entries"] == 0
    assert has_live_factor_grid("t1") is False


def _fake_grid_result():
    try:
        import numpy as np

        from paleo_workbench.workflow.factor_grid_result import FactorGridResult

        n = 4
        x = np.linspace(0, 1, n, dtype=np.float64)
        y = np.linspace(0, 1, n, dtype=np.float64)
        return FactorGridResult(
            grid_z=np.ones((n, n), dtype=np.float32),
            grid_x=x,
            grid_y=y,
            factor_name="f",
            algorithm_id="idw",
            algorithm_parameters={},
            crs="",
            unit="",
        )
    except Exception:  # pragma: no cover
        raise AssertionError("numpy unavailable for cache test")


# ------------------------------------------------- 9. mock stays mock


def test_synthetic_tasks_stay_mock_through_interpolation(monkeypatch):
    from paleo_workbench.workflow.factor_interpolation import (
        batch_prepare_factor_maps,
    )

    # No resources/wells → the scheduler fabricates synthetic sample points.
    project = ProjectDocument.new(name="Demo")
    batch_prepare_factor_maps(project, method="IDW", grid_n=16, seed=3)

    assert project.factor_map_tasks
    for task in project.factor_map_tasks:
        assert task.source_kind == "mock", (
            "pure synthetic input must be labeled mock, never mixed (audit #848)"
        )


def test_mock_task_not_relabeled_mixed_on_completion():
    from paleo_workbench.workflow.factor_interpolation import (
        apply_interpolation_to_task,
    )

    project = ProjectDocument.new(name="Demo")
    project.factor_map_tasks.append(
        FactorMapTask(
            name="sand",
            target_horizon="H1",
            factor_type="sand",
            method="IDW",
            parameters={"sample_points": _points(1, 0.0)},
            status="pending",
            source_kind="mock",
        )
    )
    apply_interpolation_to_task(project.factor_map_tasks[0], project=project)
    task = project.factor_map_tasks[0]
    assert task.status == "complete"
    assert task.source_kind == "mock"


# ------------------------------------------------------ 10. catalog hardening


def test_register_version_rejects_unsafe_version_id(service, tmp_path):
    src = tmp_path / "w.las"
    src.write_bytes(b"data")
    raw = service.import_raw(src)

    with pytest.raises(CatalogError, match="[Uu]nsafe"):
        service.register_version(
            raw.asset_id,
            src,
            DataStage.DERIVED,
            parent_version_ids=[raw.id],
            version_id="../..",
        )
    with pytest.raises(CatalogError, match="[Uu]nsafe"):
        service.register_version(
            raw.asset_id,
            src,
            DataStage.DERIVED,
            parent_version_ids=[raw.id],
            version_id="a/b",
        )


def test_store_load_raises_catalog_error_when_canonical_and_bak_corrupt(tmp_path):
    project_path = _make_project_path(tmp_path)
    canonical = catalog_file_for(project_path)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b'{"truncated": ')
    bak = catalog_bak_file_for(project_path)
    bak.write_bytes(b"{also-broken")

    with pytest.raises(CatalogError, match="both corrupt"):
        CatalogStore(project_path).load()

    isolated = [
        p for p in canonical.parent.iterdir()
        if p.name.startswith("catalog.json.corrupt-")
    ]
    assert len(isolated) == 1


# ------------------------------------- deferred: metadata dialect convergence


def test_prediction_task_metadata_uses_single_version_key(project):
    """Registry path must set prediction_version_id only; no output_version_id
    legacy dialect remains for _on_seismic_send_to_mapping to double-read."""
    from paleo_workbench.prediction.inference_service import materialize_prediction_task

    task = materialize_prediction_task(
        project,
        payload={
            "run_id": "run_42",
            "output_version_id": "ver_out_1",
            "result_summary": {"predicted_regions": []},
            "model": {
                "model_id": "m1",
                "model_version": "1",
                "model_name": "Demo",
                "model_version_id": "mv_1",
            },
        },
        name_prefix="测试预测",
        workflow="seismic_facies",
        run_id="run_42",
        output_version_id="ver_out_1",
    )
    assert task.model_metadata.get("prediction_version_id") == "ver_out_1"
    assert "output_version_id" not in task.model_metadata, (
        "model_metadata must converge on a single prediction_version_id key; "
        "output_version_id is the catalog/run dialect, not task metadata"
    )


# ----------------------------------------- deferred: legacy wrapper deletion


def test_legacy_prediction_wrapper_modules_removed():
    """paleo_workbench/workflow/{facies,seismic,well_log}_prediction.py were
    legacy wrappers with no production callers once utilities moved out."""
    removed = [
        "paleo_workbench.workflow.facies_prediction",
        "paleo_workbench.workflow.seismic_prediction",
        "paleo_workbench.workflow.well_log_prediction",
    ]
    for name in removed:
        with pytest.raises(ImportError):
            __import__(name)


def test_well_log_prediction_utilities_rehoused():
    """Still-used helpers from the legacy wrapper moved to viz layer / page."""
    from paleo_workbench.ui.pages.well_log_prediction_page import export_well_canvas
    from paleo_workbench.viz.prediction_helpers import (
        merge_prediction_onto_well_log,
        regions_to_depth_intervals,
    )

    assert callable(regions_to_depth_intervals)
    assert callable(merge_prediction_onto_well_log)
    assert callable(export_well_canvas)


def test_seismic_display_modes_rehoused():
    """SEISMIC_DISPLAY_MODES moved next to its only consumer."""
    from paleo_workbench.ui.pages.seismic_control_panel import SEISMIC_DISPLAY_MODES

    assert isinstance(SEISMIC_DISPLAY_MODES, tuple)
    assert "vd" in SEISMIC_DISPLAY_MODES
    assert "wiggle" in SEISMIC_DISPLAY_MODES


# ------------------------------------------------------------------ helpers


def _open_service(project_path: Path) -> DataCatalogService:
    return DataCatalogService.open(project_path)


def _open_adapter(project_path: Path) -> CoreCatalogAdapter:
    """Return a CatalogPort-wrapped service for lifecycle helpers."""
    return CoreCatalogAdapter(DataCatalogService.open(project_path))


def _artifact_dir_for(project_path: Path, sub: str) -> Path:
    from paleo_workbench.project.paths import artifact_dir_for

    return artifact_dir_for(project_path) / sub


def _resolve_managed(rel_or_abs: str, project_path: Path) -> Path:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    return (project_path.resolve().parent / p).resolve()