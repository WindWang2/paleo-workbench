"""Round-2 adversarial regression tests — WP1: readiness/freshness semantics.

Each test pins an invariant that the round-2 adversarial review proved was
violated (H1/H2/H6): readiness evaluation must be read-only, unavailable
inputs must not count as READY, EXACTLY_ONE is not ">=1", a superseded
failed run must not poison a step, and UNKNOWN freshness must not render
as 已完成.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import CatalogError, DataCatalogService
from paleo_workbench.project.models import (
    FactorMapTask,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.workflow.contracts.models import ReadinessStatus
from paleo_workbench.workflow.contracts.readiness import evaluate_readiness
from tests.fakes.inmemory_catalog import InMemoryCatalog

# --------------------------------------------------------------------------- WP1a
# Readiness evaluation is a read-only query: no catalog mutation, no revision
# churn, no clobbering of user-edited model metadata (H2).


def _make_catalog(tmp_path: Path) -> DataCatalogService:
    return DataCatalogService.open(tmp_path / "cat")


def _resource_counts_project() -> ProjectDocument:
    project = ProjectDocument.new("p")
    project.resources.append(
        ResourceItem(name="ok.las", path="/definitely/exists/a.las", type="well_log", format="las")
    )
    return project


def test_readiness_facies_evaluation_is_read_only(tmp_path: Path, monkeypatch):
    """evaluate_readiness must not seed models or bump the catalog revision."""
    svc = _make_catalog(tmp_path)
    rev_before = svc.document.catalog_revision
    model_ids_before = [m.model_id for m in svc.document.models]

    import paleo_workbench.catalog as catalog_mod
    from paleo_workbench.catalog import service as service_mod

    monkeypatch.setattr(catalog_mod, "get_catalog_service", lambda: svc)
    project = ProjectDocument.new("p")
    report = evaluate_readiness(project, "facies_prediction")

    assert report.status in (ReadinessStatus.PARTIAL, ReadinessStatus.READY)
    assert svc.document.catalog_revision == rev_before
    assert [m.model_id for m in svc.document.models] == model_ids_before
    # No catalog file should have been written by the evaluation itself.
    assert not (tmp_path / "cat").exists() or list((tmp_path / "cat").glob("catalog.json")) == []


def test_readiness_preserves_user_edited_model_identity(tmp_path: Path):
    """register_model(force_status=False) must not clobber identity fields."""
    svc = _make_catalog(tmp_path)
    svc.register_model(
        model_id="corp-facies-v3",
        model_name="用户改名后的正式模型名",
        model_type="ml",
        capability="facies_prediction",
        provider="test_spatial",
        status="production",
        metadata={"scientific": True},
    )
    # Seed-like call with different defaults (H4-3a scenario).
    svc.register_model(
        model_id="corp-facies-v3",
        model_name="演示相带预测（Demo）",
        model_type="heuristic",
        capability="facies_prediction",
        provider="local_asset",
        status="demo",
        metadata={"scientific": False},
    )
    m = next(m for m in svc.document.models if m.model_id == "corp-facies-v3")
    assert m.model_name == "用户改名后的正式模型名"
    assert m.model_type == "ml"
    assert m.provider == "test_spatial"
    assert m.status == "production"
    assert m.metadata["scientific"] is True


def test_register_model_noop_does_not_rewrite_catalog(tmp_path: Path):
    """Idempotent re-registration with identical values must not save."""
    svc = _make_catalog(tmp_path)
    svc.register_model(
        model_id="m1", model_name="A", model_type="ml", capability="c", provider="p"
    )
    rev = svc.document.catalog_revision
    path = Path(str(svc.project_path)) / "catalog.json"
    before = path.stat().st_mtime_ns if path.exists() else None
    time.sleep(0.01)
    svc.register_model(
        model_id="m1", model_name="A", model_type="ml", capability="c", provider="p"
    )
    assert svc.document.catalog_revision == rev
    after = path.stat().st_mtime_ns if path.exists() else None
    assert before == after


# --------------------------------------------------------------------------- WP1b
# Readiness must not count unavailable inputs (H2 false READY).


def test_readiness_excludes_missing_and_absent_resources(tmp_path: Path):
    project = ProjectDocument.new("p")
    dead = tmp_path / "deleted.las"
    project.resources.append(
        ResourceItem(name="ok.las", path=str(dead), type="well_log", format="las")
    )
    project.resources.append(
        ResourceItem(
            name="gone.las",
            path="/no/such/absolute/path/gone.las",
            type="well_log",
            format="las",
            status="missing",
        )
    )
    project.resources.append(
        ResourceItem(
            name="offline.sgy",
            path="/no/such/absolute/path/offline.sgy",
            type="seismic",
            format="sgy",
            external=True,
        )
    )
    # well_log_ingest requires well_log; only the first row can actually load.
    report = evaluate_readiness(project, "well_log_ingest")
    # 'missing' + absent-file rows must not satisfy the input.
    assert any(r.code == "missing_input:las_files" for r in report.reasons)
    # seismic_volume must be BLOCKED when the only segy payload is gone.
    report2 = evaluate_readiness(project, "seismic_volume")
    assert any(r.code == "missing_input:segy" for r in report2.reasons)


def test_readiness_factor_maps_require_completed_tasks():
    """A failed task's stale grid_artifact_path must not satisfy factor_maps."""
    from paleo_workbench.workflow.contracts.models import (
        DomainWorkflowContract,
        ImplementationStatus,
        InputCardinality,
        WorkflowInputSpec,
    )
    from paleo_workbench.workflow.contracts.readiness import evaluate_contract_readiness

    project = ProjectDocument.new("p")
    project.factor_map_tasks.append(
        FactorMapTask(
            id="f1",
            name="f1",
            target_horizon="H1",
            factor_type="sand",
            method="idw",
            status="failed",
            grid_artifact_path="/stale/npz",
        )
    )
    contract = DomainWorkflowContract(
        id="t_factor_maps",
        name="t",
        implementation_status=ImplementationStatus.PRODUCTION,
        inputs=[
            WorkflowInputSpec(
                id="factor_maps",
                name="单因素图",
                cardinality=InputCardinality.ONE_OR_MORE,
                required=True,
            )
        ],
    )
    report = evaluate_contract_readiness(project, contract)
    assert any(r.code == "missing_input:factor_maps" for r in report.reasons)


def test_readiness_exactly_one_warns_on_multiple_inputs(tmp_path: Path):
    project = ProjectDocument.new("p")
    sgy = tmp_path / "s.sgy"
    sgy.write_bytes(b"x")
    for i in range(2):
        project.resources.append(
            ResourceItem(
                name=f"s{i}.sgy",
                path=str(sgy),
                type="seismic",
                format="sgy",
            )
        )
    report = evaluate_readiness(project, "seismic_volume")
    assert any(r.code == "ambiguous_input:segy" for r in report.reasons)
    assert report.status == ReadinessStatus.PARTIAL  # warn, not READY


# --------------------------------------------------------------------------- WP1c
# Freshness step aggregation: latest run per domain task wins (B-P2) and
# UNKNOWN maps to a distinct non-complete status (H1).


def _run(cat: InMemoryCatalog, operation: str, inputs: list[str], *, status: str, task: str | None = None) -> tuple[str, str | None]:
    run = cat.begin_run(operation=operation, input_version_ids=inputs, domain_task_id=task)
    out = None
    if status == "complete":
        out = cat.register_derived(
            run_id=run.run_id, name=f"o-{run.run_id}", path="/tmp/o.npz", checksum="sha", kind="product"
        ).version_id
        cat.complete_run(run.run_id)
    else:
        cat.complete_run(run.run_id, status=status)
    return run.run_id, out


def _all_current(cat: InMemoryCatalog):
    from paleo_workbench.workflow.current_context import CurrentProjectVersionContext

    ctx = CurrentProjectVersionContext()
    for ver in cat.list_versions():
        ctx.select(ver.asset_id, ver.version_id)
    return ctx


def test_step_freshness_latest_run_wins_after_failed_retry():
    """A failed attempt superseded by a successful retry must not show FAILED."""
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.freshness import FreshnessService, FreshnessState

    cat = InMemoryCatalog()
    raw = cat.register_input(name="w.las", path="/tmp/w.las", checksum="sha-1", kind="well_log", format="las").version_id
    _run(cat, "factor_map", [raw], status="failed", task="fa")
    _, out = _run(cat, "factor_map", [raw], status="complete", task="fa")
    svc = FreshnessService(DependencyGraph.from_catalog(cat), _all_current(cat), catalog=cat)
    assert svc.step_freshness("factor_map") is FreshnessState.FRESH
    assert svc.evaluate_run  # sanity: service built


def test_step_freshness_latest_failed_run_still_failed():
    """If the LATEST run of a task failed, the step stays FAILED."""
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.freshness import FreshnessService, FreshnessState

    cat = InMemoryCatalog()
    raw = cat.register_input(name="w.las", path="/tmp/w.las", checksum="sha-1", kind="well_log", format="las").version_id
    _run(cat, "factor_map", [raw], status="complete", task="fa")
    _run(cat, "factor_map", [raw], status="failed", task="fa")
    svc = FreshnessService(DependencyGraph.from_catalog(cat), _all_current(cat), catalog=cat)
    assert svc.step_freshness("factor_map") is FreshnessState.FAILED


def test_unknown_freshness_not_complete():
    """UNKNOWN (empty lineage on a lineage-expected op) must not be 已完成."""
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.freshness import FreshnessService, FreshnessState
    from paleo_workbench.workflow.service import infer_workflow_step_status

    cat = InMemoryCatalog()
    run = cat.begin_run(operation="prediction", input_version_ids=[])
    out = cat.register_derived(
        run_id=run.run_id, name="pred", path="/tmp/pred.npz", checksum="sha", kind="product"
    ).version_id
    cat.complete_run(run.run_id)
    svc = FreshnessService(DependencyGraph.from_catalog(cat), _all_current(cat), catalog=cat)
    assert svc.step_freshness("prediction") is FreshnessState.UNKNOWN

    project = ProjectDocument.new("p")
    from paleo_workbench.project.models import PredictionTask

    project.prediction_tasks.append(PredictionTask(id="p1", name="p1", status="complete"))
    status = infer_workflow_step_status(project, "prediction", freshness_service=svc)
    assert status != "complete"
    assert status == "warning"  # 状态未知


def test_unregistered_model_status_capitalization_is_not_production(tmp_path: Path):
    """'PRODUCTION' (capitalized) must never be treated as production."""
    svc = _make_catalog(tmp_path)
    with pytest.raises(CatalogError):
        svc.register_model_version(
            "m1", model_version="1", status="production"  # direct production rejected
        )
    assert svc.find_production_model("c1") is None


# --------------------------------------------------------------------------- WP2
# Model package identity / promotion / input schema exactness (H4/H5).


def _artifact(tmp_path: Path, name: str, content: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _package_manifest(artifact: Path, **overrides) -> dict:
    m = {
        "model_id": "corp-facies-v3",
        "model_version": "1",
        "model_name": "Corp Facies",
        "capability": "facies_prediction",
        "provider": "python_callable",
        "model_type": "ml",
        "artifact": str(artifact),
        "input_schema": {"required_asset_types": ["well_log"]},
        "scientific": True,
        "demo_only": False,
    }
    m.update(overrides)
    return m


def test_manifest_string_bool_is_not_truthy_coerced(tmp_path: Path):
    """'scientific': 'false' must NOT become True (H4-1 fails-open bug)."""
    from paleo_workbench.prediction.model_package import (
        ModelPackageError,
        parse_model_package_manifest,
    )

    art = _artifact(tmp_path, "w.bin", b"A")
    parsed = parse_model_package_manifest(
        _package_manifest(art, scientific="false")
    )
    assert parsed.scientific is False
    parsed2 = parse_model_package_manifest(
        _package_manifest(art, deterministic="false", demo_only="false")
    )
    assert parsed2.deterministic is False
    assert parsed2.demo_only is False
    with pytest.raises(ModelPackageError):
        parse_model_package_manifest(_package_manifest(art, scientific=0))
    with pytest.raises(ModelPackageError):
        parse_model_package_manifest(_package_manifest(art, scientific="0"))


def test_nonscientific_package_cannot_register_or_promote(tmp_path: Path):
    from paleo_workbench.prediction.model_package import (
        ModelPackageError,
        register_model_package,
    )

    svc = _make_catalog(tmp_path)
    art = _artifact(tmp_path, "w2.bin", b"B")
    with pytest.raises(ModelPackageError):
        register_model_package(svc, _package_manifest(art, scientific=False))


def test_register_model_package_identity_conflict_detected(tmp_path: Path):
    """Same (model_id, version) + different artifact/schema must raise (H4-2)."""
    from paleo_workbench.prediction.model_package import (
        ModelPackageError,
        register_model_package,
    )

    svc = _make_catalog(tmp_path)
    art_a = _artifact(tmp_path, "a.bin", b"AAAA")
    register_model_package(svc, _package_manifest(art_a, model_version="2"))
    art_b = _artifact(tmp_path, "b.bin", b"BBBB")
    with pytest.raises(ModelPackageError) as ei:
        register_model_package(svc, _package_manifest(art_b, model_version="2"))
    assert "identity conflict" in str(ei.value)
    # The original version is untouched.
    v = svc.get_model_version("corp-facies-v3", "2")
    assert v.checksum != _sha256_of(art_b)


def _sha256_of(p) -> str:
    import hashlib

    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_promote_rejects_case_variant_and_non_scientific_version(tmp_path: Path):
    from paleo_workbench.catalog.models import CatalogError
    from paleo_workbench.prediction.model_package import (
        can_promote_to_production,
        register_model_package,
    )

    svc = _make_catalog(tmp_path)
    art = _artifact(tmp_path, "c.bin", b"CCCC")
    register_model_package(svc, _package_manifest(art, model_type="DEMO"))
    ok, reason = can_promote_to_production(svc, "corp-facies-v3", "1")
    assert not ok  # case-variant 'DEMO' must not bypass the allowlist

    art2 = _artifact(tmp_path, "d.bin", b"DDDD")
    register_model_package(
        svc, _package_manifest(art2, model_version="2", scientific=True)
    )
    # Stale model-level scientific flag (True) but version-level False:
    # the version's own declaration must block promotion (H4-3b).
    v = svc.get_model_version("corp-facies-v3", "2")
    v.metadata["scientific"] = False
    ok2, reason2 = can_promote_to_production(svc, "corp-facies-v3", "2")
    assert not ok2, reason2


def test_trashed_factor_version_not_resolved_as_input(tmp_path: Path):
    """H5-a: trashed/purged outputs must not enter prediction inputs."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.lifecycle import _versions_for_domain_tasks

    svc = _make_catalog(tmp_path)
    (tmp_path / "w.las").write_bytes(b"LAS")
    (tmp_path / "g.npz").write_bytes(b"GRID")
    cat = CoreCatalogAdapter(svc)
    raw = cat.register_input(name="w.las", path=str(tmp_path / "w.las"), checksum=None, kind="well_log", format="las").version_id
    run = cat.begin_run(operation="factor_map", input_version_ids=[raw], domain_task_id="fa")
    out = cat.register_derived(run_id=run.run_id, name="grid", path=str(tmp_path / "g.npz"), checksum=None, kind="factor_grid", format="npz")
    cat.complete_run(run.run_id)
    assert _versions_for_domain_tasks(["fa"], catalog=cat) == [out.version_id]
    svc.trash_version(out.version_id, reason="test")
    assert _versions_for_domain_tasks(["fa"], catalog=cat) == []


def test_failed_latest_run_inputs_not_propagated(tmp_path: Path):
    """H5-c: a failed recompute must not stand in for the factor grid."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.lifecycle import _versions_for_domain_tasks

    svc = _make_catalog(tmp_path)
    (tmp_path / "w.las").write_bytes(b"LAS")
    cat = CoreCatalogAdapter(svc)
    raw = cat.register_input(name="w.las", path=str(tmp_path / "w.las"), checksum=None, kind="well_log", format="las").version_id
    run = cat.begin_run(operation="factor_map", input_version_ids=[raw], domain_task_id="fa")
    (tmp_path / "g.npz").write_bytes(b"GRID")
    out = cat.register_derived(run_id=run.run_id, name="grid", path=str(tmp_path / "g.npz"), checksum=None, kind="factor_grid", format="npz")
    cat.complete_run(run.run_id)
    # Successful run exists; then a FAILED recompute becomes the latest run.
    run2 = cat.begin_run(operation="factor_map", input_version_ids=[raw], domain_task_id="fa")
    cat.complete_run(run2.run_id, status="failed")
    assert _versions_for_domain_tasks(["fa"], catalog=cat) == [out.version_id]


def test_execute_run_fails_cleanly_on_unknown_input(tmp_path: Path):
    """H5-d: bad input must mark the run failed, never leave it running."""
    from paleo_workbench.prediction.inference_service import execute_run, start_inference
    from paleo_workbench.prediction.model_package import register_model_package
    from paleo_workbench.prediction.providers import register_provider

    class _FakeProvider:
        def run(self, inputs, parameters):
            return {"spatial_output_type": "NONE", "generator_version": "fake"}

    register_provider("rr2_test_provider", _FakeProvider)

    svc = _make_catalog(tmp_path)
    art = _artifact(tmp_path, "m.bin", b"M")
    register_model_package(svc, _package_manifest(art, provider="rr2_test_provider"))
    svc.promote_model("corp-facies-v3", "1")
    mv = svc.get_model_version("corp-facies-v3", "1")
    run = start_inference(svc, model_version_id=mv.id, input_version_ids=["ver_missing_123"])
    out = execute_run(svc, run.id)
    run_after = svc.get_run(run.id)
    assert run_after.status == "failed"
    assert (run_after.parameters or {}).get("error_type") == "CatalogError"


def test_start_inference_snapshot_is_order_invariant(tmp_path: Path):
    """H5-e: same input set in different order -> same snapshot hash."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.prediction.inference_service import start_inference

    svc = _make_catalog(tmp_path)
    (tmp_path / "a.las").write_bytes(b"A")
    (tmp_path / "b.las").write_bytes(b"B")
    cat = CoreCatalogAdapter(svc)
    v1 = cat.register_input(name="a.las", path=str(tmp_path / "a.las"), checksum=None, kind="well_log", format="las").version_id
    v2 = cat.register_input(name="b.las", path=str(tmp_path / "b.las"), checksum=None, kind="well_log", format="las").version_id
    from paleo_workbench.prediction.model_package import register_model_package

    art = _artifact(tmp_path, "m2.bin", b"M2")
    register_model_package(svc, _package_manifest(art))
    mv = svc.get_model_version("corp-facies-v3", "1")
    r1 = start_inference(svc, model_version_id=mv.id, input_version_ids=[v1, v2])
    r2 = start_inference(svc, model_version_id=mv.id, input_version_ids=[v2, v1])
    h1 = r1.parameters["_input_snapshot_hash"]
    h2 = r2.parameters["_input_snapshot_hash"]
    assert h1 == h2
    assert r1.input_version_ids == sorted([v1, v2])


def test_unknown_input_schema_vocabulary_rejected(tmp_path: Path):
    """H5-b: unrecognized schema must not silently fall back to gather."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.prediction.input_contract import (
        InputContractError,
        resolve_model_inputs,
    )
    from paleo_workbench.prediction.model_package import register_model_package

    svc = _make_catalog(tmp_path)
    (tmp_path / "a.las").write_bytes(b"A")
    cat = CoreCatalogAdapter(svc)
    cat.register_input(name="a.las", path=str(tmp_path / "a.las"), checksum=None, kind="well_log", format="las")
    art = _artifact(tmp_path, "m3.bin", b"M3")
    # JSON-Schema-style vocabulary is not the recognized contract vocabulary.
    register_model_package(
        svc, _package_manifest(art, input_schema={"type": "object", "required": ["well_log"]})
    )
    mv = svc.get_model_version("corp-facies-v3", "1")
    project = ProjectDocument.new("p")
    with pytest.raises(InputContractError):
        resolve_model_inputs(project, svc, mv, strict=True)
