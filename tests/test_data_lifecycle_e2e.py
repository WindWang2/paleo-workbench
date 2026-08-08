"""End-to-end data-lifecycle acceptance tests.

These exercise the full producer→consumer→catalog integration against the
in-memory reference backend (the seam that stands in for Kimi's Core until it
lands). Each test maps to one of the acceptance stories in the integration goal.

Stories covered:
  1. RAW → Derived (managed RAW immutability after source mutation)
  2. Derived → Intermediate → Output (old versions retained across reruns)
  3. Lineage query (output → run → inputs → ancestor RAW)
  4. Tags persist across catalog rebuild (serialization round-trip)
  5. Integrity (tamper → MODIFIED, recorded checksum preserved)
  6. Legacy ResourceItem project migration on open
  7. External / unmanaged source missing → reported, no crash
  8. Real FactorMap / Prediction / Export pipeline → output provenance

These run headless (no Qt) where possible; the pipeline-level stories use the
catalog seam + domain services directly.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from paleo_workbench.catalog import (
    DataStage,
    IntegrityStatus,
    get_catalog,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.catalog.lifecycle import (
    migrate_project_resources,
    register_resource_input,
    resolve_resource_version,
)
from tests.fakes.inmemory_catalog import InMemoryCatalog, sha256_of_file


@pytest.fixture()
def catalog():
    """A fresh isolated catalog per test."""
    cat = InMemoryCatalog()
    set_catalog(cat)
    yield cat
    reset_catalog()


def _make_resource(path: Path, *, name: str = "src.las", content: bytes = b"log data"):
    """Build a minimal ResourceItem with a real on-disk file + checksum."""
    from paleo_workbench.project.models import ResourceItem

    path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    return ResourceItem(
        name=name,
        path=str(path),
        type="well_log",
        format="las",
        status="parsed",
        checksum=checksum,
        external=False,
    )


# ===================================================================== Story 1


def test_story1_raw_to_derived_managed_immutability(tmp_path: Path, catalog):
    """Import source → managed RAW v1; mutate external source; RAW unchanged."""
    src = tmp_path / "well.las"
    resource = _make_resource(src, content=b"original log curve")

    raw = register_resource_input(resource)
    assert raw.stage is DataStage.RAW
    original_checksum = raw.checksum

    # Source file on disk is later modified externally.
    src.write_bytes(b"HACKED EXTERNAL EDIT")

    # The managed RAW version is immutable: its recorded checksum is unchanged.
    registered = catalog.resolve_version(raw.version_id)
    assert registered.checksum == original_checksum
    # Integrity now flags MODIFIED (story 5 overlap, but confirms RAW tracks it).
    assert catalog.verify_integrity(raw.version_id) is IntegrityStatus.MODIFIED


# ===================================================================== Story 2


def test_story2_derived_intermediate_output_versions_retained(tmp_path: Path, catalog):
    """RAW/Derived → INTERMEDIATE v1 → rerun → INTERMEDIATE v2 → OUTPUT v1.

    Old committed versions must still resolve after a rerun (no overwrite).
    """
    src = tmp_path / "src.dat"
    resource = _make_resource(src, content=b"input")
    raw = register_resource_input(resource)

    # First processing run → INTERMEDIATE v1
    run1 = catalog.begin_run(
        operation="process", input_version_ids=[raw.version_id], generator_version="v1"
    )
    inter1 = catalog.register_intermediate(
        run_id=run1.run_id, name="grid", path=str(tmp_path / "g1.npz")
    )
    catalog.complete_run(run1.run_id)

    # Second run (rerun) → INTERMEDIATE v2 (distinct)
    run2 = catalog.begin_run(
        operation="process", input_version_ids=[raw.version_id], generator_version="v1"
    )
    inter2 = catalog.register_intermediate(
        run_id=run2.run_id, name="grid", path=str(tmp_path / "g2.npz")
    )
    catalog.complete_run(run2.run_id)

    # Final OUTPUT from the latest intermediate.
    run3 = catalog.begin_run(
        operation="finalize", input_version_ids=[inter2.version_id]
    )
    out = catalog.register_output(
        run_id=run3.run_id, name="result.png", path=str(tmp_path / "out.png")
    )
    catalog.complete_run(run3.run_id)

    assert inter1.version_id != inter2.version_id
    # Both old and new intermediate versions are retained.
    assert catalog.resolve_version(inter1.version_id) is not None
    assert catalog.resolve_version(inter2.version_id) is not None
    assert catalog.resolve_version(out.version_id) is not None
    assert catalog.resolve_version(out.version_id).stage is DataStage.OUTPUT


# ===================================================================== Story 3


def test_story3_lineage_output_to_ancestor_raw(tmp_path: Path, catalog):
    """OUTPUT → producing run → inputs → ancestor RAW is fully queryable."""
    src = tmp_path / "raw.dat"
    raw = register_resource_input(_make_resource(src))

    factor_run = catalog.begin_run(
        operation="factor_map", input_version_ids=[raw.version_id]
    )
    grid = catalog.register_intermediate(
        run_id=factor_run.run_id, name="grid", path=str(tmp_path / "g.npz")
    )
    catalog.complete_run(factor_run.run_id)

    pred_run = catalog.begin_run(
        operation="prediction", input_version_ids=[grid.version_id]
    )
    derived = catalog.register_derived(
        run_id=pred_run.run_id, name="pred", path=str(tmp_path / "p.json")
    )
    catalog.complete_run(pred_run.run_id)

    export_run = catalog.begin_run(
        operation="export", input_version_ids=[derived.version_id]
    )
    output = catalog.register_output(
        run_id=export_run.run_id, name="out.pdf", path=str(tmp_path / "o.pdf")
    )
    catalog.complete_run(export_run.run_id)

    ancestors = catalog.query_lineage(output.version_id, direction="ancestors")
    ancestor_ids = {a.version_id for a in ancestors}
    # The full chain resolves back to the original RAW input.
    assert raw.version_id in ancestor_ids
    assert grid.version_id in ancestor_ids
    assert derived.version_id in ancestor_ids


# ===================================================================== Story 4


def test_story4_tags_persist_across_rebuild(tmp_path: Path, catalog):
    """Tags survive a save → reopen → catalog rebuild (serialization round-trip)."""
    src = tmp_path / "tagged.dat"
    raw = register_resource_input(_make_resource(src))
    catalog.add_tags(raw.version_id, ["reviewed", "carbonate"])

    # Simulate close + reopen: serialize the catalog state and rebuild it.
    data = catalog.to_dict()
    rebuilt = InMemoryCatalog.from_dict(data)

    restored = rebuilt.resolve_version(raw.version_id)
    assert "reviewed" in restored.tags
    assert "carbonate" in restored.tags


# ===================================================================== Story 5


def test_story5_integrity_tamper_records_modified(tmp_path: Path, catalog):
    """Tamper a managed RAW → verify → MODIFIED; recorded checksum not overwritten."""
    src = tmp_path / "integrity.dat"
    raw = register_resource_input(_make_resource(src, content=b"pristine"))
    recorded = raw.checksum

    src.write_bytes(b"tampered")
    assert catalog.verify_integrity(raw.version_id) is IntegrityStatus.MODIFIED
    # The recorded checksum is NOT auto-overwritten — tamper stays visible.
    assert catalog.resolve_version(raw.version_id).checksum == recorded


# ===================================================================== Story 6


def test_story6_legacy_resource_project_migration(tmp_path: Path, catalog):
    """A legacy ResourceItem-only project migrates on open; workflow resolves."""
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Legacy")
    src = tmp_path / "legacy.las"
    resource = _make_resource(src, content=b"legacy data")
    project.resources.append(resource)

    # Before migration, the legacy resource id has no catalog version.
    assert resolve_resource_version(resource.id) is None

    # Migration (as called by ProjectController.open_project_path).
    versions = migrate_project_resources(project)

    assert len(versions) == 1
    # The legacy bridge now resolves.
    resolved = resolve_resource_version(resource.id)
    assert resolved is not None
    assert resolved.stage is DataStage.RAW
    assert resolved.version_id == versions[0].version_id


# ===================================================================== Story 7


def test_story7_external_unmanaged_source_missing(tmp_path: Path, catalog):
    """An external/unmanaged link whose source is missing is reported, no crash."""
    from paleo_workbench.project.models import ResourceItem

    external = ResourceItem(
        name="missing_ref.las",
        path="/nonexistent/path/missing_ref.las",
        type="well_log",
        format="las",
        status="indexed",
        external=True,
    )
    version = register_resource_input(external)

    assert version.stage is DataStage.RAW
    assert version.external is True
    # The project does not crash; integrity reports the source as missing.
    assert catalog.verify_integrity(version.version_id) is IntegrityStatus.MISSING


# ===================================================================== Story 8


def test_story8_workflow_output_has_provenance(tmp_path: Path, catalog):
    """A minimal FactorMap → Prediction → Export pipeline yields provenance.

    Exercises the real lifecycle helpers against domain task models:
      RAW input
        → factor_map run (registered by apply_interpolation_to_task's helper)
        → prediction run consuming the factor run
        → export OUTPUT with lineage back to the RAW input.
    """
    from paleo_workbench.catalog.lifecycle import (
        register_factor_map_run,
        register_prediction_run,
        register_export_output,
    )
    from paleo_workbench.project.models import FactorMapTask, PredictionTask

    # RAW input
    src = tmp_path / "wf.las"
    raw = register_resource_input(_make_resource(src))

    # Factor map task + run. The factor task consumes the RAW input resource
    # (input_resource_ids → resolved via the legacy bridge), so the run graph
    # connects through to the source data.
    factor_task = FactorMapTask(
        name="H1 砂岩含量",
        target_horizon="H1",
        factor_type="砂岩含量",
        input_resource_ids=[raw.legacy_resource_id] if raw.legacy_resource_id else [],
        method="IDW",
        status="complete",
        generator_version="factor-interp-v1",
        input_snapshot_hash="abc",
    )
    factor_run, _ = register_factor_map_run(factor_task)

    # Prediction task consuming the factor run (factor result is in-memory, so
    # lineage propagates the factor run's declared inputs through the run graph).
    pred_task = PredictionTask(
        name="pred",
        adapter_kind="mock",
        status="complete",
        generator_version="mock-prediction-v1",
        input_snapshot_hash="def",
    )
    pred_run, _ = register_prediction_run(
        pred_task, factor_task_ids=[factor_task.id]
    )

    # Export an OUTPUT file, declaring the prediction task as its source.
    out = tmp_path / "deliverable.png"
    out.write_bytes(b"PNG DATA")
    export_version = register_export_output(
        name="deliverable.png",
        output_path=str(out),
        fmt="png",
        source_version_ids=None,
        source_task_ids=[pred_task.id],
        linked_id="map_1",
    )

    assert export_version.stage is DataStage.OUTPUT
    # The export's lineage reaches back through prediction → factor → the RAW
    # ancestor input (propagated via the run graph since intermediates are
    # in-memory). This is the headline capability: connected provenance.
    ancestors = catalog.query_lineage(export_version.version_id, direction="ancestors")
    ancestor_stages = {a.stage for a in ancestors}
    assert DataStage.RAW in ancestor_stages
    runs = {r.operation for r in catalog.list_runs()}
    assert {"factor_map", "prediction", "export"} <= runs
    assert factor_run.run_id in {r.run_id for r in catalog.list_runs()}
    assert pred_run.run_id in {r.run_id for r in catalog.list_runs()}


# ======================================================== export integration


def test_record_export_registers_output_version(tmp_path: Path, catalog):
    """record_export (the export choke point) registers an OUTPUT DataVersion
    with lineage to the source resource, and ExportArtifact carries version_id."""
    from paleo_workbench.project.artifacts import record_export
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("P")
    src = tmp_path / "src.las"
    resource = _make_resource(src)
    project.resources.append(resource)
    register_resource_input(resource)  # legacy bridge

    out = tmp_path / "out.csv"
    out.write_bytes(b"csv")

    artifact = record_export(
        project,
        linked_id=resource.id,
        output_path=str(out),
        fmt="csv",
        source_task_ids=[],
        source_resource_ids=[resource.id],
    )

    assert artifact.catalog_version_id is not None
    version = catalog.resolve_version(artifact.catalog_version_id)
    assert version is not None
    assert version.stage is DataStage.OUTPUT
    # Lineage reaches back to the RAW input resource.
    ancestors = catalog.query_lineage(version.version_id, direction="ancestors")
    assert any(a.stage is DataStage.RAW for a in ancestors)


def test_record_export_backward_compat_no_catalog_resource(tmp_path: Path, catalog):
    """An export with no registered source resource still records the artifact
    (graceful degradation); catalog_version_id may be set but lineage is empty."""
    from paleo_workbench.project.artifacts import record_export
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("P")
    out = tmp_path / "view.png"
    out.write_bytes(b"PNG")

    artifact = record_export(
        project,
        linked_id="viz_view",
        output_path=str(out),
        fmt="png",
        source_task_ids=[],
    )
    # The export is recorded regardless.
    assert artifact in project.export_artifacts
    assert artifact.format == "png"


# ============================================================ Gemini UI contract


def test_ui_contract_payload_has_all_display_fields(tmp_path: Path, catalog):
    """The display payload carries everything the Data Manager needs:
    Produced by Run X, Inputs A/B/C, Stage, Version, Integrity, Path, Timestamp.
    """
    from paleo_workbench.catalog.view import version_display_payload

    src = tmp_path / "ui.las"
    raw = register_resource_input(_make_resource(src))

    run = catalog.begin_run(
        operation="export", input_version_ids=[raw.version_id], generator_version="exp-v1"
    )
    out = tmp_path / "deliverable.png"
    out.write_bytes(b"PNG")
    version = catalog.register_output(
        run_id=run.run_id,
        name="deliverable.png",
        path=str(out),
        format="png",
        checksum=sha256_of_file(out),
    )
    catalog.complete_run(run.run_id)
    catalog.add_tags(version.version_id, ["final"])

    payload = version_display_payload(version.version_id)

    # Required display fields present and correct.
    assert payload["version_id"] == version.version_id
    assert payload["stage"] == "output"
    assert payload["path"] == str(out)
    assert payload["format"] == "png"
    assert payload["name"] == "deliverable.png"
    assert payload["created_at"]  # timestamp
    assert payload["integrity"] == "verified"
    assert "final" in payload["tags"]
    # Produced by Run X.
    assert payload["producing_run_id"] == run.run_id
    assert payload["producing_operation"] == "export"
    assert payload["generator_version"] == "exp-v1"
    # Inputs A/B/C (direct ancestors).
    assert len(payload["inputs"]) == 1
    assert payload["inputs"][0]["version_id"] == raw.version_id
    assert payload["inputs"][0]["stage"] == "raw"


def test_ui_contract_unknown_version_returns_none(catalog):
    from paleo_workbench.catalog.view import version_display_payload

    assert version_display_payload("ver_does_not_exist") is None


# ============================================ reviewer-finding regression tests


def test_multi_input_run_no_duplicate_output_or_edges(tmp_path: Path, catalog):
    """A run with N inputs records each output exactly once (Review H1).

    Previously output_version_ids was appended once per input, producing
    duplicates and duplicate lineage edges.
    """
    r1 = register_resource_input(_make_resource(tmp_path / "a.dat", content=b"a"))
    r2 = register_resource_input(_make_resource(tmp_path / "b.dat", content=b"b"))
    run = catalog.begin_run(
        operation="export", input_version_ids=[r1.version_id, r2.version_id]
    )
    out = catalog.register_output(
        run_id=run.run_id, name="o", path=str(tmp_path / "o.png")
    )
    catalog.complete_run(run.run_id)
    restored = catalog.resolve_run(run.run_id)
    # Output recorded exactly once despite two inputs.
    assert restored.output_version_ids == [out.version_id]
    # Exactly two lineage edges (one per distinct input), no duplicates.
    edges = [e for e in catalog._lineage if e.target_version_id == out.version_id]
    assert len(edges) == 2


def test_import_without_checksum_computes_it(tmp_path: Path, catalog):
    """A ResourceItem with checksum=None gets hashed on registration (Review H3),
    so integrity verification and managed-input identity work for real imports."""
    from paleo_workbench.project.models import ResourceItem

    src = tmp_path / "imported.las"
    src.write_bytes(b"real import content")
    resource = ResourceItem(
        name="imported.las",
        path=str(src),
        type="well_log",
        format="las",
        status="parsed",
        checksum=None,  # import_service records None
        external=False,
    )
    version = register_resource_input(resource)
    assert version.checksum is not None  # computed from disk
    assert catalog.verify_integrity(version.version_id) is IntegrityStatus.VERIFIED
    # Content change → new managed version + MODIFIED on the old one.
    src.write_bytes(b"changed content")
    assert catalog.verify_integrity(version.version_id) is IntegrityStatus.MODIFIED


def test_external_input_dedup_on_reopen(tmp_path: Path, catalog):
    """Re-registering an EXTERNAL resource (e.g. on project reopen) does not
    accumulate duplicate versions or drift the legacy bridge (Review M2)."""
    from paleo_workbench.project.models import ResourceItem

    ext = ResourceItem(
        name="ext.las",
        path="/abs/ext.las",
        type="well_log",
        format="las",
        external=True,
    )
    v1 = register_resource_input(ext)
    v2 = register_resource_input(ext)  # reopen
    assert v1.version_id == v2.version_id
    assert len([v for v in catalog.list_versions(stage=DataStage.RAW) if v.external]) == 1


def test_export_registers_absolute_path_for_integrity(tmp_path: Path, catalog):
    """record_export with catalog_output_path stores the absolute path on the
    version so verify_integrity resolves on disk even when the artifact path
    is relativized (Review B-HIGH2)."""
    from paleo_workbench.project.artifacts import record_export
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("P")
    out = tmp_path / "exports" / "out.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"csv")

    artifact = record_export(
        project,
        linked_id="res_1",
        output_path="exports/out.csv",  # relativized (portable) artifact path
        fmt="csv",
        source_task_ids=[],
        catalog_output_path=str(out),  # absolute path for catalog hashing
    )
    version = catalog.resolve_version(artifact.catalog_version_id)
    assert version.path == str(out)  # absolute, resolvable on disk
    assert catalog.verify_integrity(version.version_id) is IntegrityStatus.VERIFIED
