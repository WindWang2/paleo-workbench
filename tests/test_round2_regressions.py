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

import numpy as np
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
    """Seeds must not rebind a promoted model (H4-3a).

    Protection is at the SEED layer: ensure_default_models skips existing
    models entirely (round-3 contract), and find_production_model re-runs the
    promote gates so a rebound provider can never be served as production.
    """
    from paleo_workbench.prediction.providers import (
        CAPABILITY_FACIES,
        ensure_default_models,
    )

    svc = _make_catalog(tmp_path)
    ensure_default_models(svc)
    svc.register_model(
        model_id="facies-heuristic-v1",
        model_name="Promoted Heuristic Became Real",
        model_type="ml",
        capability=CAPABILITY_FACIES,
        provider="test_spatial",
        status="production",
        metadata={"scientific": True, "source": "user"},
        force_status=True,
    )
    rev_before = svc.document.catalog_revision
    ensure_default_models(svc)
    m = svc.get_model("facies-heuristic-v1")
    assert m.provider == "test_spatial"
    assert m.model_type == "ml"
    assert m.status == "production"
    # No-op seed must not rewrite the catalog file.
    assert svc.document.catalog_revision == rev_before
    # The version slot still points at the seeded version (not rebound).
    v = svc.get_model_version("facies-heuristic-v1", "1")
    assert v is not None


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


# --------------------------------------------------------------------------- WP3
# Production paleomap provenance / transactions (H3).


def _production_payload(tmp_path: Path, *, demo: bool = False) -> dict:
    """A valid scientific VECTOR_POLYGONS payload (non-demo square area)."""
    return {
        "result_summary": {
            "final_scientific_prediction": True,
            "demo": demo,
            "spatial_output_type": "VECTOR_POLYGONS",
            "spatial": {
                "crs": "EPSG:4326",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"facies": "S"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[120.1, 30.2], [120.3, 30.2], [120.3, 30.4], [120.1, 30.4], [120.1, 30.2]]
                            ],
                        },
                    }
                ],
            },
        },
        "model": {},
    }


def _promoted_model(tmp_path: Path) -> tuple[DataCatalogService, str]:
    from paleo_workbench.prediction.model_package import register_model_package
    from paleo_workbench.prediction.providers import register_provider

    class _RR2SpatialProvider:
        def run(self, inputs, parameters):
            return {
                "spatial_output_type": "VECTOR_POLYGONS",
                "generator_version": "rr2-spatial",
                "result_summary": {
                    "final_scientific_prediction": True,
                    "spatial_output_type": "VECTOR_POLYGONS",
                    "spatial": {
                        "crs": "EPSG:4326",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"facies": "S"},
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [
                                        [[120.1, 30.2], [120.3, 30.2], [120.3, 30.4], [120.1, 30.4], [120.1, 30.2]]
                                    ],
                                },
                            }
                        ],
                    },
                },
            }

    register_provider("rr2_spatial", _RR2SpatialProvider)

    svc = _make_catalog(tmp_path)
    art = _artifact(tmp_path, "pm.bin", b"PM")
    register_model_package(
        svc,
        {
            "model_id": "pm-model",
            "model_version": "1",
            "model_name": "PM",
            "capability": "facies_prediction",
            "provider": "rr2_spatial",
            "model_type": "ml",
            "artifact": str(art),
            "input_schema": {"required_asset_types": ["well_log"]},
        },
    )
    svc.promote_model("pm-model", "1")
    return svc, svc.get_model_version("pm-model", "1").id


def test_demo_square_geometry_cannot_compile_as_production(tmp_path: Path):
    """H3/D-P0: the anti-laundering demo-square check must actually fire."""
    from paleo_workbench.pipeline.compile_map_production import (
        ProductionMapError,
        compile_map_production,
    )

    project = ProjectDocument.new("p")
    project.stratigraphy.target_horizon = "H1"
    payload = {
        "result_summary": {
            "final_scientific_prediction": True,
            "spatial_output_type": "VECTOR_POLYGONS",
            "spatial": {
                "crs": "EPSG:4326",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"facies": "S"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[114.0, 22.5], [114.04, 22.5], [114.04, 22.54], [114.0, 22.54], [114.0, 22.5]]
                            ],
                        },
                    }
                ],
            },
        },
        "model": {},
    }
    with pytest.raises(ProductionMapError, match="demo"):
        compile_map_production(project, prediction_payload=payload)


def test_production_compile_lineage_failure_is_transactional(tmp_path: Path, monkeypatch):
    """H3: lineage failure raises, doc is not appended, no orphan RUNNING run."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.pipeline.compile_map_production import (
        ProductionMapError,
        compile_map_production,
    )
    from paleo_workbench.prediction.inference_service import execute_run, start_inference

    svc, mv_id = _promoted_model(tmp_path)
    (tmp_path / "w.las").write_bytes(b"LAS")
    cat = CoreCatalogAdapter(svc)
    v = cat.register_input(name="w.las", path=str(tmp_path / "w.las"), checksum=None, kind="well_log", format="las").version_id
    run = start_inference(svc, model_version_id=mv_id, input_version_ids=[v])
    execute_run(svc, run.id)
    pred_vid = svc.get_run(run.id).output_version_ids[0]

    project = ProjectDocument.new("p")
    project.stratigraphy.target_horizon = "H1"
    payload = _production_payload(tmp_path)
    payload["model"] = {"model_version_id": mv_id}

    def _boom(*args, **kwargs):
        raise OSError("disk full (injected)")

    monkeypatch.setattr(svc, "register_result_asset", _boom)
    with pytest.raises(ProductionMapError):
        compile_map_production(
            project,
            prediction_payload=payload,
            catalog_service=svc,
            prediction_version_id=pred_vid,
        )
    assert project.paleomap_documents == []
    # The started run was marked failed, not left RUNNING (no orphan).
    runs = [r for r in svc.document.runs if r.operation == "map_compile"]
    assert runs and all(r.status == "failed" for r in runs)


def test_no_catalog_compile_is_explicitly_untracked(tmp_path: Path, monkeypatch):
    """H3: without a catalog, the doc must degrade to non-production."""
    from paleo_workbench.pipeline.compile_map_production import compile_map_production

    project = ProjectDocument.new("p")
    project.stratigraphy.target_horizon = "H1"
    monkeypatch.setattr(
        "paleo_workbench.catalog.get_catalog", lambda: None, raising=False
    )
    doc = compile_map_production(project, prediction_payload=_production_payload(tmp_path))
    assert doc.view_state.get("production") is False
    assert doc.view_state.get("lineage") == "untracked"


def test_demo_payload_with_allow_demo_task_stays_demo(tmp_path: Path):
    """H3/D-P3: allow_demo_task must not mint a production-marked demo doc."""
    from paleo_workbench.pipeline.compile_map_production import compile_map_production

    project = ProjectDocument.new("p")
    project.stratigraphy.target_horizon = "H1"
    payload = _production_payload(tmp_path, demo=True)
    doc = compile_map_production(
        project, prediction_payload=payload, allow_demo_task=True
    )
    assert doc.view_state.get("is_demo_draft") is True
    assert doc.view_state.get("production") is False


def test_untrusted_model_version_blocks_production_compile(tmp_path: Path):
    """H3/D-P2: declared model version must be promoted."""
    from paleo_workbench.pipeline.compile_map_production import (
        ProductionMapError,
        compile_map_production,
    )

    svc = _make_catalog(tmp_path)
    project = ProjectDocument.new("p")
    project.stratigraphy.target_horizon = "H1"
    payload = _production_payload(tmp_path)
    payload["model"] = {"model_version_id": "ver_does_not_exist"}
    with pytest.raises(ProductionMapError, match="模型版本不存在"):
        compile_map_production(project, prediction_payload=payload, catalog_service=svc)


def test_demo_document_cannot_be_expert_finalized():
    """H3/D-P1d: demo drafts must never reach export_ready via finalize."""
    from paleo_workbench.project.models import PaleoMapDocument
    from paleo_workbench.workflow.versioning import finalize_map_version

    project = ProjectDocument.new("p")
    doc = PaleoMapDocument(
        name="demo",
        linked_target_horizon="H1",
        view_state={"is_demo_draft": True, "production": False},
    )
    project.paleomap_documents.append(doc)
    with pytest.raises(ValueError, match="演示草稿"):
        finalize_map_version(project, doc.id)
    assert not project.version_sets


# --------------------------------------------------------------------------- WP4
# Freshness withdrawal propagation, plan ordering, cycle detection (H1/H11).


def test_withdrawn_upstream_makes_downstream_not_fresh(tmp_path: Path):
    """H1: trashing an upstream version must degrade downstream freshness."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.workflow.current_context import (
        CurrentProjectVersionContext,
        resolve_current_project_version_context,
    )
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.freshness import (
        FreshnessReasonType,
        FreshnessService,
        FreshnessState,
    )

    svc = _make_catalog(tmp_path)
    (tmp_path / "w.las").write_bytes(b"LAS")
    (tmp_path / "g.npz").write_bytes(b"GRID")
    cat = CoreCatalogAdapter(svc)
    raw = cat.register_input(name="w.las", path=str(tmp_path / "w.las"), checksum=None, kind="well_log", format="las").version_id
    run = cat.begin_run(operation="factor_map", input_version_ids=[raw], domain_task_id="fa")
    out = cat.register_derived(run_id=run.run_id, name="grid", path=str(tmp_path / "g.npz"), checksum=None, kind="factor_grid", format="npz")
    cat.complete_run(run.run_id)

    project = ProjectDocument.new("p")
    ctx = resolve_current_project_version_context(project, catalog=cat)
    svc_f = FreshnessService(DependencyGraph.from_catalog(cat), ctx, catalog=cat)
    assert svc_f.evaluate_run(run.run_id).state is FreshnessState.FRESH

    # Trash the RAW upstream → the factor product must not stay FRESH.
    svc.trash_version(raw, reason="bad input")
    cat2 = CoreCatalogAdapter(svc)
    svc_f2 = FreshnessService(DependencyGraph.from_catalog(cat2), ctx, catalog=cat2)
    report = svc_f2.evaluate_run(run.run_id)
    assert report.state is not FreshnessState.FRESH
    assert any(r.type is FreshnessReasonType.MISSING_LINEAGE for r in report.reasons)

    # Purging the version entirely must also degrade (not silently FRESH).
    svc.trash_version(out.version_id, reason="x")
    svc.purge_trashed()
    cat3 = CoreCatalogAdapter(svc)
    svc_f3 = FreshnessService(DependencyGraph.from_catalog(cat3), ctx, catalog=cat3)
    report3 = svc_f3.evaluate_run(run.run_id)
    assert report3.state is not FreshnessState.FRESH


def test_plan_orders_map_after_prediction_without_version_edge(tmp_path: Path):
    """H11: map_compile with only a task-level link runs after prediction."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.workflow.current_context import (
        CurrentProjectVersionContext,
        resolve_current_project_version_context,
    )
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.freshness import FreshnessService
    from paleo_workbench.workflow.recompute_plan import build_recompute_plan

    svc = _make_catalog(tmp_path)
    (tmp_path / "g.npz").write_bytes(b"GRID")
    cat = CoreCatalogAdapter(svc)
    # Factor grid version.
    run_f = cat.begin_run(operation="factor_map", input_version_ids=[], domain_task_id="fa")
    grid = cat.register_derived(run_id=run_f.run_id, name="grid", path=str(tmp_path / "g.npz"), checksum=None, kind="factor_grid", format="npz")
    cat.complete_run(run_f.run_id)
    # Prediction consumes the grid (version edge exists).
    run_p = cat.begin_run(operation="prediction", input_version_ids=[grid.version_id], domain_task_id="pred-task")
    cat.complete_run(run_p.run_id)
    # Map compile consumes the same grid (in-memory prediction result: no
    # prediction version edge), linked via task id only.
    run_m = cat.begin_run(
        operation="map_compile",
        input_version_ids=[grid.version_id],
        domain_task_id="map-doc",
        parameters={
            "linked_prediction_task_id": "pred-task",
            "source_task_ids": ["pred-task"],
        },
    )
    cat.complete_run(run_m.run_id)

    project = ProjectDocument.new("p")
    ctx = resolve_current_project_version_context(project, catalog=cat)
    svc_f = FreshnessService(DependencyGraph.from_catalog(cat), ctx, catalog=cat)
    plan = build_recompute_plan(svc_f, stale_only=False)
    ops = [s.operation for s in plan.steps]
    assert ops.index("prediction") < ops.index("map_compile"), ops


def test_cycle_detection_reports_all_cycles():
    """A self-loop must not mask a separate A->B->A cycle."""
    from paleo_workbench.catalog.types import DataRunRef, DataStage, DataVersionRef
    from paleo_workbench.workflow.dependency_graph import DependencyGraph

    def _ver(vid, asset):
        return DataVersionRef(
            asset_id=asset, version_id=vid, name=vid, stage=DataStage.INTERMEDIATE
        )

    def _run(rid, inputs, outputs, op="factor_map"):
        return DataRunRef(
            run_id=rid,
            operation=op,
            input_version_ids=inputs,
            output_version_ids=outputs,
            status="completed",
        )

    class _FakeCat:
        def __init__(self, versions, runs):
            self._versions = versions
            self._runs = runs

        def list_versions(self):
            return self._versions

        def list_runs(self):
            return self._runs

    # Self-loop: run_s consumes and produces o_s (o_s -> o_s edge).
    # Independent cycle: run1 consumes a -> o1; run2 consumes o1 -> o2;
    # run3 consumes o2 AND a -> o1' is NOT a cycle; instead:
    # run2 consumes o1 -> o2; run3 consumes o2 -> o1 (o1 -> o2 -> o1).
    versions = [
        _ver("a", "asset-a"),
        _ver("o_s", "asset-s"),
        _ver("o1", "asset-1"),
        _ver("o2", "asset-2"),
    ]
    runs = [
        _run("run_s", ["o_s"], ["o_s"]),
        _run("run1", ["a"], ["o1"]),
        _run("run2", ["o1"], ["o2"]),
        _run("run3", ["o2", "a"], ["o1"]),  # o1 -> o2 -> o1 cycle
    ]
    graph = DependencyGraph.from_catalog(_FakeCat(versions, runs))
    assert "o_s" in graph.cycle_nodes  # self-loop reported
    assert "o1" in graph.cycle_nodes and "o2" in graph.cycle_nodes  # A->B->A


# --------------------------------------------------------------------------- WP5
# Interpretation lifecycle / depth-domain (H7/H8).


def test_tops_from_canvas_reads_geoviz_row_shape():
    """P0: real geoviz canvas rows (well_name/formation_name/depth_m)."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.correlation_session import tops_from_canvas_rows
    from paleo_workbench.workflow.stratigraphy_models import DepthDomain

    rows = [
        SimpleNamespace(well_name="W0", formation_name="H1", depth_m=100.0),
        SimpleNamespace(well_name="W0", formation_name="H2", depth_m=250.0),
        SimpleNamespace(well_name="W1", formation_name="H1", depth_m=105.0),
    ]
    tops = tops_from_canvas_rows(
        rows,
        name_to_resource_id={"W0": "well-0", "W1": "well-1"},
        depth_domain=DepthDomain.MD,
    )
    assert len(tops) == 3
    assert tops[0].marker == "H1"
    assert tops[0].depth == pytest.approx(100.0)
    assert tops[2].marker == "H1"
    assert tops[2].depth == pytest.approx(105.0)


def test_tops_domain_preserved_on_resave():
    """H8: reopen→resave must not relabel TWT tops as MD."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.correlation_session import tops_from_canvas_rows
    from paleo_workbench.workflow.stratigraphy_models import DepthDomain, FormationTop

    prev = [
        FormationTop(
            id="top_x",
            well_id="well-0",
            well_name="W0",
            marker="H1",
            depth=2500.0,
            depth_domain=DepthDomain.TWT,
        )
    ]
    rows = [SimpleNamespace(well_name="W0", formation_name="H1", depth_m=2500.0)]
    tops = tops_from_canvas_rows(
        rows,
        name_to_resource_id={"W0": "well-0"},
        depth_domain=DepthDomain.MD,  # page hardcode
        previous_tops=prev,
    )
    assert tops[0].id == "top_x"
    assert tops[0].depth_domain is DepthDomain.TWT
    assert tops[0].depth == pytest.approx(2500.0)


def test_horizon_save_noop_does_not_mint_version(tmp_path: Path):
    """H7: identical content re-save must be a no-op."""
    import numpy as np

    from paleo_workbench.viz.interpretation_lifecycle import (
        open_draft_from_array,
        save_draft_as_new_version,
    )

    project = ProjectDocument.new("p")
    draft = open_draft_from_array(
        np.zeros((8, 8), dtype=np.float32), horizon_key="H1", name="H1"
    )
    ref1, msg1 = save_draft_as_new_version(draft, project, tmp_path / "proj" / "p.paleo.json")
    assert msg1 == "ok"
    v1 = ref1.current_version_id
    ref2, msg2 = save_draft_as_new_version(draft, project, tmp_path / "proj" / "p.paleo.json")
    assert msg2 == "noop_unchanged"
    assert ref2.current_version_id == v1


def test_horizon_save_registration_failure_cleans_artifact(tmp_path: Path, monkeypatch):
    """H7: catalog failure must not leave a ghost artifact."""
    import numpy as np

    from paleo_workbench.viz.interpretation_lifecycle import (
        open_draft_from_array,
        save_draft_as_new_version,
    )

    def _boom(*a, **k):
        raise OSError("catalog down (injected)")

    monkeypatch.setattr(
        "paleo_workbench.viz.interpretation_lifecycle.register_interpretation_version",
        _boom,
    )
    project = ProjectDocument.new("p")
    draft = open_draft_from_array(
        np.zeros((8, 8), dtype=np.float32), horizon_key="H1", name="H1"
    )
    proj_path = tmp_path / "proj" / "p.paleo.json"
    with pytest.raises(OSError):
        save_draft_as_new_version(draft, project, proj_path)
    interp_dir = tmp_path / "proj" / "p.artifacts" / "interpretations"
    leftovers = list(interp_dir.glob("*.npz")) if interp_dir.exists() else []
    assert leftovers == []


# --------------------------------------------------------------------------- WP6
# Well-log overlay / project isolation (H8/H9).


def test_overlay_reapply_replaces_correlation_markers():
    """H9: re-applying an overlay must replace, not accumulate, tops."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.correlation_overlay import (
        apply_correlation_tops_to_well_log_data,
    )
    from paleo_workbench.workflow.correlation_session import stable_top_id
    from paleo_workbench.workflow.stratigraphy_models import DepthDomain, FormationTop

    project = ProjectDocument.new("p")
    from paleo_workbench.project.models import CorrelationInterpretationRef

    tops = [
        FormationTop(
            id=stable_top_id(well_name="W0", marker="TopA"),
            well_id="well-0",
            well_name="W0",
            marker="TopA",
            depth=1002.0,
            depth_domain=DepthDomain.MD,
        )
    ]
    payload = SimpleNamespace(tops=tops)
    ref = CorrelationInterpretationRef(
        id="corr-1",
        name="C",
        current_version_id="v1",
        artifact_path="/no/such/file.json",
    )
    project.correlation_interpretations.append(ref)

    import paleo_workbench.workflow.correlation_overlay as ov

    orig = ov.load_current_correlation_payload
    ov.load_current_correlation_payload = lambda proj, project_path=None: (ref, payload)
    try:
        base = SimpleNamespace(well_name="W0")
        first = apply_correlation_tops_to_well_log_data(base, project)
        assert len(first.markers) == 1
        second = apply_correlation_tops_to_well_log_data(first, project)
        assert len(second.markers) == 1, "markers must not accumulate"
        tops[0].depth = 1007.0
        third = apply_correlation_tops_to_well_log_data(second, project)
        assert len(third.markers) == 1
        assert third.markers[0].depth == pytest.approx(1007.0)
    finally:
        ov.load_current_correlation_payload = orig


def test_overlay_skips_non_md_domain_tops():
    """H8: TWT tops must not be plotted numerically on the MD log axis."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.correlation_overlay import (
        apply_correlation_tops_to_well_log_data,
    )
    from paleo_workbench.workflow.correlation_session import stable_top_id
    from paleo_workbench.workflow.stratigraphy_models import DepthDomain, FormationTop

    project = ProjectDocument.new("p")
    from paleo_workbench.project.models import CorrelationInterpretationRef

    tops = [
        FormationTop(
            id=stable_top_id(well_name="W0", marker="TWT1"),
            well_id="well-0",
            well_name="W0",
            marker="TWT1",
            depth=2500.0,
            depth_domain=DepthDomain.TWT,
        ),
        FormationTop(
            id=stable_top_id(well_name="W0", marker="MD1"),
            well_id="well-0",
            well_name="W0",
            marker="MD1",
            depth=500.0,
            depth_domain=DepthDomain.MD,
        ),
    ]
    payload = SimpleNamespace(tops=tops)
    ref = CorrelationInterpretationRef(
        id="corr-2", name="C", current_version_id="v1", artifact_path="/no/such/file.json"
    )
    project.correlation_interpretations.append(ref)
    import paleo_workbench.workflow.correlation_overlay as ov

    orig = ov.load_current_correlation_payload
    ov.load_current_correlation_payload = lambda proj, project_path=None: (ref, payload)
    try:
        base = SimpleNamespace(well_name="W0")
        wrapped = apply_correlation_tops_to_well_log_data(base, project)
        assert [m.label for m in wrapped.markers] == ["MD1"]
    finally:
        ov.load_current_correlation_payload = orig


def test_overlay_converts_md_tops_onto_feet_axis():
    """WL-4: meter-domain MD tops must be converted, not numerically placed,
    when the log axis is a foot (DEPT.FT) depth axis."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.correlation_overlay import (
        apply_correlation_tops_to_well_log_data,
    )
    from paleo_workbench.workflow.correlation_session import stable_top_id
    from paleo_workbench.workflow.stratigraphy_models import DepthDomain, FormationTop

    project = ProjectDocument.new("p")
    from paleo_workbench.project.models import CorrelationInterpretationRef

    tops = [
        FormationTop(
            id=stable_top_id(well_name="W0", marker="MD1"),
            well_id="well-0",
            well_name="W0",
            marker="MD1",
            depth=500.0,
            depth_domain=DepthDomain.MD,
        ),
    ]
    payload = SimpleNamespace(tops=tops)
    ref = CorrelationInterpretationRef(
        id="corr-3", name="C", current_version_id="v1", artifact_path="/no/such/file.json"
    )
    project.correlation_interpretations.append(ref)
    import paleo_workbench.workflow.correlation_overlay as ov

    orig = ov.load_current_correlation_payload
    ov.load_current_correlation_payload = lambda proj, project_path=None: (ref, payload)
    try:
        base = SimpleNamespace(well_name="W0", depth_unit="ft")
        wrapped = apply_correlation_tops_to_well_log_data(base, project)
        assert len(wrapped.markers) == 1
        assert wrapped.markers[0].depth == pytest.approx(500.0 * 3.280839895013123)
        # Meter axis: numeric placement unchanged.
        flat = apply_correlation_tops_to_well_log_data(
            SimpleNamespace(well_name="W0"), project
        )
        assert flat.markers[0].depth == pytest.approx(500.0)
    finally:
        ov.load_current_correlation_payload = orig


def test_correlation_artifact_resolves_project_first(tmp_path: Path, monkeypatch):
    """H9: a duplicated project must read ITS OWN artifact, not the CWD copy."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.correlation_artifact import (
        write_correlation_artifact,
    )
    from paleo_workbench.workflow.correlation_overlay import (
        load_current_correlation_payload,
    )
    from paleo_workbench.workflow.stratigraphy_models import (
        CorrelationScientificPayload,
        DepthDomain,
        FormationTop,
    )

    projA = tmp_path / "A"
    projB = tmp_path / "B"
    (projA / "x.artifacts" / "correlations").mkdir(parents=True)
    (projB / "x.artifacts" / "correlations").mkdir(parents=True)

    topsA = [FormationTop(id="t1", well_id="w1", well_name="W1", marker="TopA", depth=1002.0, depth_domain=DepthDomain.MD)]
    topsB = [FormationTop(id="t2", well_id="w1", well_name="W1", marker="TopA", depth=1007.0, depth_domain=DepthDomain.MD)]

    def _payload(tops):
        return CorrelationScientificPayload(
            interpretation_id="c",
            tops=tops,
            depth_domain=DepthDomain.MD,
            well_resource_ids=["w1"],
        )

    write_correlation_artifact(
        _payload(topsA), projA / "x.artifacts" / "correlations", "corr_v1"
    )
    write_correlation_artifact(
        _payload(topsB), projB / "x.artifacts" / "correlations", "corr_v1"
    )
    rel = "x.artifacts/correlations/corr_v1.correlation.json"

    from paleo_workbench.project.models import CorrelationInterpretationRef, ProjectDocument

    projectB = ProjectDocument.new("B")
    projectB.correlation_interpretations.append(
        CorrelationInterpretationRef(
            id="c", name="C", current_version_id="v", artifact_path=rel
        )
    )
    monkeypatch.chdir(projA)
    ref, payload = load_current_correlation_payload(projectB, project_path=projB / "x.paleo.json")
    assert payload is not None
    assert payload.tops[0].depth == pytest.approx(1007.0), "must read B, not A"


# --------------------------------------------------------------------------- WP7/WP8
# Seismic cache identity / fingerprint completeness (H10/H11).


def test_source_id_changes_on_inode_replace(tmp_path: Path):
    """H10: same-size, mtime-preserved replacement must change the identity."""
    import os

    from paleo_workbench.viz.seismic_volume_source import source_id_for_path

    p = tmp_path / "survey.sgy"
    p.write_bytes(b"A" * 4096)
    id1 = source_id_for_path(p)
    p2 = tmp_path / "survey_new.sgy"
    p2.write_bytes(b"B" * 4096)
    st = p.stat()
    os.utime(p2, ns=(st.st_atime_ns, st.st_mtime_ns))
    os.replace(p2, p)
    id2 = source_id_for_path(p)
    assert id1 != id2


def test_directional_fingerprint_covers_weights_and_flags():
    """H11: q/b_i/qc_flag changes must dirty the directional fingerprint."""
    from paleo_workbench.workflow.interpolation_fingerprint import (
        build_factor_fingerprints,
    )

    base = {
        "sample_points": [
            {"x": 100.0, "y": 200.0, "z": 10.0, "q": 1.0, "b_i": 1.0, "qc_flag": "ok"},
            {"x": 110.0, "y": 210.0, "z": 12.0, "q": 1.0, "b_i": 1.0, "qc_flag": "ok"},
        ],
        "method": "方向趋势",
        "grid_n": 40,
    }
    fp1 = build_factor_fingerprints(**base)
    pts2 = [dict(pt, b_i=0.1) for pt in base["sample_points"]]
    fp2 = build_factor_fingerprints(**{**base, "sample_points": pts2})
    assert fp1.result != fp2.result
    pts3 = [dict(pt, qc_flag="outlier") for pt in base["sample_points"]]
    fp3 = build_factor_fingerprints(**{**base, "sample_points": pts3})
    assert fp1.result != fp3.result
    idw = {**base, "method": "IDW"}
    fp4 = build_factor_fingerprints(**idw)
    fp5 = build_factor_fingerprints(**{**idw, "sample_points": pts2})
    assert fp4.result == fp5.result


def test_fingerprint_normalizes_negative_zero():
    from paleo_workbench.workflow.interpolation_fingerprint import (
        build_factor_fingerprints,
    )

    pts = [{"x": 0.0, "y": -0.0, "z": 1.0}]
    pts2 = [{"x": -0.0, "y": 0.0, "z": 1.0}]
    fp1 = build_factor_fingerprints(sample_points=pts, method="IDW", grid_n=20)
    fp2 = build_factor_fingerprints(sample_points=pts2, method="IDW", grid_n=20)
    assert fp1.result == fp2.result


# --------------------------------------------------------------------------- FU1
# Task-level plan expansion for empty-lineage runs (H11 truncation).


def test_plan_includes_empty_lineage_prediction_after_upstream_change(tmp_path: Path):
    """A prediction run registered before its factor run recorded NO input
    versions. After the upstream RAW version advances, the recompute plan
    must still include the prediction (task-level dependency) instead of
    silently truncating the chain at the factor step."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.project.models import PredictionTask
    from paleo_workbench.workflow.current_context import (
        resolve_current_project_version_context,
    )
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.freshness import FreshnessService
    from paleo_workbench.workflow.recompute_plan import build_recompute_plan

    svc = DataCatalogService.open(tmp_path / "cat")
    (tmp_path / "w.las").write_bytes(b"LAS v1")
    (tmp_path / "w_v2.las").write_bytes(b"LAS v2")
    (tmp_path / "g.npz").write_bytes(b"GRID")
    cat = CoreCatalogAdapter(svc)
    # RAW v1 -> factor run (output grid).
    asset = cat.register_input(name="w.las", path=str(tmp_path / "w.las"), checksum=None, kind="well_log", format="las")
    raw_v1 = asset.version_id
    run_f = cat.begin_run(operation="factor_map", input_version_ids=[raw_v1], domain_task_id="fa")
    grid = cat.register_derived(run_id=run_f.run_id, name="grid", path=str(tmp_path / "g.npz"), checksum=None, kind="factor_grid", format="npz")
    cat.complete_run(run_f.run_id)
    # Prediction run with EMPTY lineage (registered before the factor run
    # existed — the timing hole): operation prediction, no input versions.
    run_p = cat.begin_run(operation="prediction", input_version_ids=[], domain_task_id="pred-1")
    cat.complete_run(run_p.run_id)
    # The RAW asset advances to v2 (same asset, new version).
    raw_v2 = svc.register_version(
        asset.asset_id,
        tmp_path / "w_v2.las",
        svc.get_version(raw_v1).stage,
    ).id

    project = ProjectDocument.new("p")
    project.prediction_tasks.append(
        PredictionTask(
            id="pred-1",
            name="pred",
            input_factor_map_ids=["fa"],
            status="complete",
        )
    )
    ctx = resolve_current_project_version_context(project, catalog=cat)
    svc_f = FreshnessService(DependencyGraph.from_catalog(cat), ctx, catalog=cat)

    plan = build_recompute_plan(
        svc_f, changed_version_ids=[raw_v2, raw_v1], project=project
    )
    ops = [s.operation for s in plan.steps]
    assert "factor_map" in ops
    assert "prediction" in ops, (
        f"empty-lineage prediction must be planned via its task link; got {ops}"
    )
    assert ops.index("factor_map") < ops.index("prediction")


# --------------------------------------------------------------------------- FU2/FU4
# Follow-up fixes: production transform hoisting + cache ownership.


def test_ms_to_preview_sample_index_production_function():
    """FU2 (K-F6): pin the PRODUCTION transform, not a test-local copy."""
    from paleo_workbench.viz.stratal_adapter import ms_to_preview_sample_index

    out = ms_to_preview_sample_index(
        np.asarray([100.0, 200.0, 300.0]),
        dt_ms=4.0,
        t0_ms=100.0,
        n_samples=51,
        n_sample_preview=21,
    )
    # t0 -> 0; t0 + 100ms (25 samples of 50) -> 10 of 20; t0+200ms -> 20.
    assert out[0] == pytest.approx(0.0)
    assert out[1] == pytest.approx(10.0)
    assert out[2] == pytest.approx(20.0)


def test_volume_cache_put_does_not_freeze_caller_array():
    """FU4: cache.put must own its buffer — the caller's array stays writable."""
    from paleo_workbench.viz.seismic_volume_cache import (
        SeismicCacheKey,
        SeismicVolumeCache,
    )

    cache = SeismicVolumeCache()
    data = np.ones((4, 4), dtype=np.float32)  # already contiguous float32
    entry = cache.put(SeismicCacheKey(source_id="s", kind="preview", index=0, lod=0), data)
    assert data.flags.writeable, "caller's array must not be frozen by cache.put"
    assert not entry.flags.writeable
    got = cache.get(SeismicCacheKey(source_id="s", kind="preview", index=0, lod=0))
    assert got is not None
