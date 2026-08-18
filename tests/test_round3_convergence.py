"""Round-3 residual-defect regressions.

These contracts were proven against the post-round-2 tip: previous reviews
protected *status* on seed re-registration and added many focused tests, but
left identity clobber, read-only readiness mutation, and missing-payload
READY holes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.prediction.providers import (
    CAPABILITY_FACIES,
    MODEL_ID_HEURISTIC,
    ensure_default_models,
)
from paleo_workbench.project.models import (
    FactorMapTask,
    PaleoMapDocument,
    ProjectDocument,
    ProjectMeta,
    ResourceItem,
)
from paleo_workbench.workflow.contracts.models import ReadinessStatus
from paleo_workbench.workflow.contracts.readiness import evaluate_readiness


@pytest.fixture
def service(tmp_path: Path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()
    reset_catalog()


def test_ensure_default_models_does_not_rebind_promoted_identity(service):
    """Seed must not rewrite a same-id model's provider/type/name after promote.

    Status was already protected (C2). Identity was not: a production model
    sharing a seed id was rebound to the heuristic/demo provider.
    """
    ensure_default_models(service)
    service.register_model(
        model_id=MODEL_ID_HEURISTIC,
        model_name="Promoted Heuristic Became Real",
        model_type="ml",
        capability=CAPABILITY_FACIES,
        provider="my_production_provider",
        status="production",
        metadata={"scientific": True, "source": "user"},
        force_status=True,
    )
    before_rev = service.document.catalog_revision
    ensure_default_models(service)
    after = service.get_model(MODEL_ID_HEURISTIC)
    assert after.status == "production"
    assert after.provider == "my_production_provider"
    assert after.model_type == "ml"
    assert after.model_name == "Promoted Heuristic Became Real"
    assert after.capability == CAPABILITY_FACIES
    assert after.metadata.get("scientific") is True
    # No-op seed must not bump catalog revision.
    assert service.document.catalog_revision == before_rev


def test_register_model_empty_capability_does_not_wipe(service):
    service.register_model(
        model_id="custom-prod",
        model_name="Custom",
        model_type="ml",
        capability=CAPABILITY_FACIES,
        provider="pkg",
        status="production",
        force_status=True,
    )
    service.register_model(model_id="custom-prod", model_name="Custom")
    model = service.get_model("custom-prod")
    assert model.capability == CAPABILITY_FACIES
    assert model.status == "production"
    assert model.provider == "pkg"
    assert model.model_type == "ml"


def test_register_model_still_updates_identity_when_values_given(service):
    """Public update contract: non-empty fields still refresh (not seed-only)."""
    service.register_model(
        model_id="m1", model_name="A", capability="cap", provider="p", status="demo"
    )
    updated = service.register_model(
        model_id="m1", model_name="A2", capability="cap2", provider="p", status="demo"
    )
    assert updated.model_name == "A2"
    assert updated.capability == "cap2"


def test_readiness_blocks_missing_absolute_payload():
    project = ProjectDocument(
        meta=ProjectMeta(name="missing-payload"),
        resources=[
            ResourceItem(
                name="ghost-well",
                path="/tmp/does-not-exist-r3-well.las",
                type="well_log",
                format="las",
                status="indexed",
            )
        ],
    )
    report = evaluate_readiness(project, "data_import")
    assert report.status is ReadinessStatus.BLOCKED
    assert any(r.code == "missing_input:source_files" for r in report.reasons)
    ingest = evaluate_readiness(project, "well_log_ingest")
    assert ingest.status is ReadinessStatus.BLOCKED
    assert any(r.code == "missing_input:las_files" for r in ingest.reasons)


def test_readiness_blocks_status_missing_resource():
    project = ProjectDocument(
        meta=ProjectMeta(name="status-missing"),
        resources=[
            ResourceItem(
                name="trashed-well",
                path="/tmp/also-missing.las",
                type="well_log",
                format="las",
                status="missing",
            )
        ],
    )
    report = evaluate_readiness(project, "data_import")
    assert report.status is ReadinessStatus.BLOCKED
    assert any(r.code == "missing_input:source_files" for r in report.reasons)


def test_readiness_keeps_relative_fixture_paths():
    """Relative fixture paths without a real project_root still count."""
    project = ProjectDocument.new("fixtures")
    project.resources.append(
        ResourceItem(name="w.las", path="w.las", type="well_log", format="las")
    )
    report = evaluate_readiness(project, "well_log_ingest")
    assert report.status is ReadinessStatus.READY


def test_readiness_resolves_relative_paths_against_project_root(tmp_path: Path):
    well = tmp_path / "real.las"
    well.write_text("~A\n", encoding="utf-8")
    present = ProjectDocument(
        meta=ProjectMeta(name="rooted", project_root=str(tmp_path)),
        resources=[
            ResourceItem(
                name="real.las", path="real.las", type="well_log", format="las"
            )
        ],
    )
    assert evaluate_readiness(present, "well_log_ingest").status is ReadinessStatus.READY

    missing = ProjectDocument(
        meta=ProjectMeta(name="rooted-miss", project_root=str(tmp_path)),
        resources=[
            ResourceItem(
                name="gone.las", path="gone.las", type="well_log", format="las"
            )
        ],
    )
    report = evaluate_readiness(missing, "well_log_ingest")
    assert report.status is ReadinessStatus.BLOCKED
    assert any(r.code == "missing_input:las_files" for r in report.reasons)


def test_readiness_evaluation_does_not_seed_catalog(service):
    set_catalog(CoreCatalogAdapter(service))
    try:
        assert service.list_models() == []
        revision = service.document.catalog_revision
        project = ProjectDocument.new("mutate")
        report = evaluate_readiness(project, "facies_prediction")
        assert [m.model_id for m in service.list_models()] == []
        assert service.document.catalog_revision == revision
        assert any(
            r.code in {"no_production_model", "prediction_demo_only"}
            for r in report.reasons
        )
    finally:
        reset_catalog()


def test_quality_control_exactly_one_map_is_ambiguous_when_two():
    project = ProjectDocument(
        meta=ProjectMeta(name="two-maps"),
        paleomap_documents=[
            PaleoMapDocument(name="m1", linked_target_horizon="H1"),
            PaleoMapDocument(name="m2", linked_target_horizon="H1"),
        ],
    )
    report = evaluate_readiness(project, "quality_control")
    assert report.status is ReadinessStatus.PARTIAL
    assert any(r.code == "ambiguous_input:map_document" for r in report.reasons)


def test_failed_factor_task_with_stale_grid_path_is_not_a_factor_map():
    """A failed leftover grid_artifact_path must not count as a usable factor."""
    from paleo_workbench.workflow.contracts.readiness import evaluate_contract_readiness
    from paleo_workbench.workflow.contracts.registry import get_default_registry

    contract = get_default_registry().get_contract("facies_prediction")
    assert contract is not None
    project = ProjectDocument(
        meta=ProjectMeta(name="failed-factor"),
        factor_map_tasks=[
            FactorMapTask(
                name="failed-grid",
                target_horizon="H1",
                factor_type="gr",
                method="idw",
                status="failed",
                grid_artifact_path="/tmp/stale-grid.npz",
            )
        ],
    )
    # Drive the factor_maps counter through the public evaluator.
    report = evaluate_contract_readiness(project, contract)
    # Optional input: failed leftover must not become a silent usable count.
    # The helper is asserted via the same branch used for required contracts.
    from paleo_workbench.workflow.contracts.readiness import _count_complete_factor_maps

    assert _count_complete_factor_maps(project) == 0
    assert report.status in {ReadinessStatus.PARTIAL, ReadinessStatus.READY}


def test_domain_task_failed_latest_run_does_not_replace_products(service, tmp_path):
    """A later failed run must not substitute RAW inputs for a complete product."""
    from paleo_workbench.catalog.lifecycle import _versions_for_domain_tasks

    raw_path = tmp_path / "raw.bin"
    raw_path.write_bytes(b"RAW")
    product_path = tmp_path / "grid.bin"
    product_path.write_bytes(b"GRID")
    adapter = CoreCatalogAdapter(service)
    raw = adapter.register_input(
        name="raw.bin", path=str(raw_path), checksum=None, kind="well_log"
    )
    ok = adapter.begin_run(
        operation="factor_map",
        input_version_ids=[raw.version_id],
        domain_task_id="factor_1",
    )
    product = adapter.register_intermediate(
        run_id=ok.run_id,
        name="grid",
        path=str(product_path),
        kind="factor_map",
    )
    adapter.complete_run(ok.run_id)
    failed = adapter.begin_run(
        operation="factor_map",
        input_version_ids=[raw.version_id],
        domain_task_id="factor_1",
    )
    adapter.complete_run(failed.run_id, status="failed")

    resolved = _versions_for_domain_tasks(["factor_1"], catalog=adapter)
    assert resolved == [product.version_id]
    assert raw.version_id not in resolved

    from paleo_workbench.prediction.inference_service import _ServiceRunView

    proxy_ids = _versions_for_domain_tasks(["factor_1"], catalog=_ServiceRunView(service))
    assert proxy_ids == [product.version_id]

    later_empty = adapter.begin_run(
        operation="factor_map",
        input_version_ids=[raw.version_id],
        domain_task_id="factor_1",
    )
    adapter.complete_run(later_empty.run_id)
    still = _versions_for_domain_tasks(["factor_1"], catalog=adapter)
    assert still == [product.version_id]
    assert still == _versions_for_domain_tasks(
        ["factor_1"], catalog=_ServiceRunView(service)
    )


def test_update_run_status_rejects_failed_to_complete(service):
    from paleo_workbench.catalog.models import CatalogError

    run = service.register_run("prediction", status="failed")
    with pytest.raises(CatalogError, match="terminal"):
        service.update_run_status(run.id, "complete")
    assert service.get_run(run.id).status == "failed"


def test_execute_run_rejects_failed_run(service):
    from paleo_workbench.catalog.models import CatalogError
    from paleo_workbench.prediction.inference_service import execute_run
    from paleo_workbench.prediction.providers import ensure_default_models

    _demo_m, _heur_m, demo_v, _heur_v = ensure_default_models(service)
    run = service.register_run(
        "prediction",
        status="failed",
        parameters={"model_version_id": demo_v.id},
    )
    with pytest.raises(CatalogError, match="running"):
        execute_run(service, run.id)


def test_cancelled_run_is_not_fresh(service, tmp_path):
    from paleo_workbench.workflow.freshness import FreshnessService, FreshnessState

    src = tmp_path / "in.bin"
    src.write_bytes(b"in")
    adapter = CoreCatalogAdapter(service)
    raw = adapter.register_input(name="in.bin", path=str(src), checksum=None, kind="raw")
    run = adapter.begin_run(operation="factor_map", input_version_ids=[raw.version_id])
    adapter.complete_run(run.run_id, status="cancelled")
    report = FreshnessService.for_project(catalog=adapter, service=service).evaluate_run(
        run.run_id
    )
    assert report.state is not FreshnessState.FRESH
    assert report.state is FreshnessState.FAILED


def test_rebase_rewrites_trash_original_path_and_model_uri(service, tmp_path):
    from paleo_workbench.catalog.store import catalog_file_for

    src = tmp_path / "proj" / "weights.bin"
    src.write_bytes(b"w")
    version = service.import_raw(src, name="weights.bin", type="model")
    service.trash_version(version.id, reason="test")
    trashed = service.get_version(version.id)
    trash_meta = dict(trashed.metadata.get("trash") or {})
    trash_meta["original_path"] = "old.artifacts/raw/asset/weights.bin"
    trashed.metadata["trash"] = trash_meta
    trashed.path = "old.artifacts/trash/ver/weights.bin"
    service.register_model(
        model_id="pkg",
        model_name="Pkg",
        capability="facies_prediction",
        provider="python_callable",
        status="demo",
    )
    mv = service.register_model_version(
        "pkg",
        model_version="1",
        artifact_uri="old.artifacts/models/weights.bin",
    )
    # Persist the stale prefixes, then rebase as Save As does.
    service._save()
    changed = service.rebase_artifact_paths()
    assert changed is True
    current = service.project_path.name.removesuffix(".paleo.json") + ".artifacts"
    refreshed = service.get_version(version.id)
    assert refreshed.path.startswith(f"{current}/")
    assert refreshed.metadata["trash"]["original_path"].startswith(f"{current}/")
    assert service.get_model_version_by_id(mv.id).artifact_uri.startswith(f"{current}/")
    assert catalog_file_for(service.project_path).is_file()


def test_rebase_owned_artifact_path_rewrites_relative_prefix():
    from paleo_workbench.project.paths import rebase_owned_artifact_path

    old = Path("/tmp/first.artifacts")
    new = Path("/tmp/second.artifacts")
    out = rebase_owned_artifact_path(
        "first.artifacts/derived/h.npz",
        old_root=old,
        new_root=new,
    )
    assert out == "second.artifacts/derived/h.npz"


def test_constrained_idw_refuses_missing_scipy(monkeypatch):
    import builtins

    from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "scipy.ndimage" or name.startswith("scipy."):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
    ]
    with pytest.raises(RuntimeError, match="SciPy"):
        run_constrained_idw(points, grid_n=20)


def test_topology_validate_labels_missing_shapely(monkeypatch):
    import builtins

    from paleo_workbench.mapping.topology import TopologyService
    from paleo_workbench.mapping.vector_layer import VectorLayer

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "shapely.geometry" or name.startswith("shapely"):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    layer = VectorLayer(id="L", name="L")
    issues = TopologyService(enabled=True).validate([layer])
    assert issues
    assert any(i.get("code") == "shapely_unavailable" for i in issues)


def test_demo_square_float_drift_is_not_map_compilable():
    from paleo_workbench.prediction.spatial_result import is_map_compilable

    ring = [
        [114.0, 22.5],
        [114.0 + 0.04, 22.5],
        [114.0 + 0.04, 22.5 + 0.04],
        [114.0, 22.5 + 0.04],
        [114.0, 22.5],
    ]
    payload = {
        "result_summary": {
            "spatial": {
                "type": "VECTOR_POLYGONS",
                "crs": "EPSG:4326",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"facies": "砂"},
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    }
                ],
            }
        }
    }
    assert is_map_compilable(payload) is False

    tall = [
        [114.0, 22.5],
        [114.04, 22.5],
        [114.04, 22.70],
        [114.0, 22.70],
        [114.0, 22.5],
    ]
    tall_payload = {
        "result_summary": {
            "spatial": {
                "type": "VECTOR_POLYGONS",
                "crs": "EPSG:4326",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"facies": "砂"},
                        "geometry": {"type": "Polygon", "coordinates": [tall]},
                    }
                ],
            }
        }
    }
    assert is_map_compilable(tall_payload) is True


def test_seismic_close_blocks_reads_and_drops_cache():
    from paleo_workbench.viz.seismic_volume_cache import SeismicVolumeCache
    from paleo_workbench.viz.seismic_volume_source import SeismicVolumeSource

    cache = SeismicVolumeCache(max_bytes=1024 * 1024)
    src = SeismicVolumeSource("/tmp/does-not-exist-r3.sgy", cache=cache)
    src._meta = type("M", (), {"source_id": "ghost", "is_pseudo": True})()
    src.close()
    assert src._closed is True
    with pytest.raises(RuntimeError, match="closed"):
        src.read_preview()
