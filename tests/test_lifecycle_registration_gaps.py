"""Lifecycle / lineage registration gap tests (E1–E9).

Every test here pins a fix for a registration gap found in review:

  E1  bulk tag application goes through service.bulk_add_tag/bulk_remove_tag
      (ONE canonical write) with legacy degradation; plus the Version-tag
      helper ``set_version_tag`` used by the version UI.
  E2  ExportArtifact delivery registers a ``delivery`` DataRun against its
      catalog OUTPUT version (previously never registered).
  E3  working-copy commit and external materialize record DataRuns whose
      output_version_ids link the new version atomically.
  E4  fault interpretation registration failure compensates: no orphan
      RUNNING run, no ghost artifact on disk.
  E5  VersionSet finalize registers a ``version_finalize`` DataRun over the
      finalized map's resolvable catalog versions.
  E6  well–seismic joint snapshot export carries the loaded seismic/well
      resources as lineage sources (previously empty).
  E7  3D mesh export carries the current modeling run's input versions as
      source lineage (previously empty).
  E8  the QC DataRun attaches the serialized report as an OUTPUT version.
  E9  import → catalog registration failures are counted and surfaced on
      ``last_registration_failures`` (never silent).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

import paleo_workbench.ui.data_lifecycle_controller as dlc
from paleo_workbench.catalog import (
    CoreCatalogAdapter,
    DataCatalogService,
    DataStage,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.lifecycle import (
    register_fault_interpretation_run,
    register_finalize_run,
    register_map_compile_run,
    register_resource_input,
)
from paleo_workbench.project.models import (
    ExportArtifact,
    PaleoMapDocument,
    ProjectDocument,
    ResourceItem,
    VersionSnapshot,
)
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.versioning import finalize_map_version
from tests.fakes.inmemory_catalog import InMemoryCatalog

# ---------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _clean_catalog_runtime():
    reset_catalog()
    yield
    reset_catalog()


@pytest.fixture
def fake():
    """In-memory CatalogPort fake wired as the active backend."""
    cat = InMemoryCatalog()
    set_catalog(cat)
    yield cat
    reset_catalog()


@pytest.fixture
def core(tmp_path: Path):
    """A real Core DataCatalogService on a tmp_path project, wired as active."""
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    yield service
    reset_catalog()
    service.close()


def _project_dir(tmp_path: Path) -> Path:
    return tmp_path / "proj"


def _make_page(qtbot) -> DataPage:
    page = DataPage(project=ProjectDocument.new("Registration Gaps"))
    qtbot.addWidget(page)
    return page


def _make_managed_resource(
    page: DataPage, tmp_path: Path, name: str = "well.las"
) -> ResourceItem:
    payload = _project_dir(tmp_path) / "data" / name
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(f"{name}-bytes".encode())
    resource = ResourceItem(
        name=name,
        path=f"data/{name}",
        type="well_log",
        format="las",
        checksum=sha256_file(payload),
        artifact_role="input",
    )
    page.project.resources.append(resource)
    page._refresh()
    return resource


def _make_external_resource(
    page: DataPage, tmp_path: Path, name: str = "ext.sgy"
) -> ResourceItem:
    payload = tmp_path / "external" / name
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(f"{name}-bytes".encode())
    resource = ResourceItem(
        name=name,
        path=payload.as_posix(),
        type="seismic",
        format="sgy",
        checksum=sha256_file(payload),
        external=True,
        artifact_role="input",
    )
    page.project.resources.append(resource)
    page._refresh()
    return resource


# ================================================================= E1 tags


def test_bulk_apply_tag_uses_one_catalog_write(qtbot, tmp_path, core, monkeypatch):
    """N selected items → ONE bulk_add_tag call (single canonical write),
    zero per-item add_tag calls, legacy tags still updated per item."""
    page = _make_page(qtbot)
    resources = [
        _make_managed_resource(page, tmp_path, name=f"w{i}.las") for i in range(3)
    ]
    core.migrate_legacy_resources(page.project.resources)

    bulk_calls: list[tuple] = []
    orig_bulk = core.bulk_add_tag

    def spy_bulk(name, **kwargs):
        bulk_calls.append((name, dict(kwargs)))
        return orig_bulk(name, **kwargs)

    singular_calls: list[str] = []
    orig_add = core.add_tag

    def spy_add(name, **kwargs):
        singular_calls.append(name)
        return orig_add(name, **kwargs)

    monkeypatch.setattr(core, "bulk_add_tag", spy_bulk)
    monkeypatch.setattr(core, "add_tag", spy_add)

    changed = page._lifecycle.bulk_apply_tag(resources, "批量", add=True)

    assert changed == 3
    assert all("批量" in r.tags for r in resources)  # legacy side updated
    assert len(bulk_calls) == 1  # ONE canonical write
    assert bulk_calls[0][0] == "批量"
    assert sorted(bulk_calls[0][1]["asset_ids"]) == sorted(r.id for r in resources)
    assert singular_calls == []  # no N-write legacy path
    assert sorted(core.find_assets_by_tag("批量")) == sorted(r.id for r in resources)


def test_bulk_apply_tag_remove_single_write(qtbot, tmp_path, core, monkeypatch):
    page = _make_page(qtbot)
    resources = [
        _make_managed_resource(page, tmp_path, name=f"w{i}.las") for i in range(2)
    ]
    core.migrate_legacy_resources(page.project.resources)
    assert page._lifecycle.bulk_apply_tag(resources, "移除我", add=True) == 2

    remove_calls: list[tuple] = []
    orig = core.bulk_remove_tag

    def spy_remove(name, **kwargs):
        remove_calls.append((name, dict(kwargs)))
        return orig(name, **kwargs)

    monkeypatch.setattr(core, "bulk_remove_tag", spy_remove)

    changed = page._lifecycle.bulk_apply_tag(resources, "移除我", add=False)

    assert changed == 2
    assert all("移除我" not in r.tags for r in resources)
    assert len(remove_calls) == 1
    assert core.find_assets_by_tag("移除我") == []


def test_bulk_apply_tag_without_catalog_updates_legacy_only(qtbot, tmp_path):
    """No catalog wired → legacy tags still updated, no error (degraded mode)."""
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)

    changed = page._lifecycle.bulk_apply_tag([resource], "离线", add=True)

    assert changed == 1
    assert "离线" in resource.tags
    changed = page._lifecycle.bulk_apply_tag([resource], "离线", add=False)
    assert changed == 1
    assert "离线" not in resource.tags


def test_bulk_apply_tag_unbridged_items_skip_catalog(qtbot, tmp_path, core):
    """Catalog wired but resources not migrated → catalog untouched, legacy OK."""
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)

    changed = page._lifecycle.bulk_apply_tag([resource], "未桥接", add=True)

    assert changed == 1
    assert "未桥接" in resource.tags
    assert core.find_assets_by_tag("未桥接") == []


def test_set_version_tag_add_and_remove(qtbot, tmp_path, core):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    core.migrate_legacy_resources(page.project.resources)
    version_id = f"ver_{resource.id}"

    assert page._lifecycle.set_version_tag(version_id, "版本级", add=True) is True
    assert version_id in core.find_versions_by_tag("版本级")
    assert page._lifecycle.set_version_tag(version_id, "版本级", add=False) is True
    assert version_id not in core.find_versions_by_tag("版本级")


def test_set_version_tag_failures_return_false(qtbot):
    page = _make_page(qtbot)

    # No catalog wired.
    assert page._lifecycle.set_version_tag("ver_x", "T", add=True) is False
    # Unknown version must not raise.
    assert page._lifecycle.set_version_tag("ver_missing", "T", add=False) is False


# ============================================================ E2 delivery


class _StubDeliveryDialog:
    """Non-modal stand-in for the delivery dialog (fixed destination)."""

    destination: Path | None = None

    def __init__(self, parent=None, *, asset_name: str = "", suggested_path: str = ""):
        pass

    def exec(self):
        return QDialog.DialogCode.Accepted

    def output_path(self) -> Path:
        assert self.destination is not None
        return self.destination

    def note(self):
        return None


def test_export_artifact_delivery_registers_delivery_run(
    qtbot, tmp_path, core, monkeypatch
):
    """An ExportArtifact with a catalog_version_id must record a ``delivery``
    DataRun (previously the branch was unreachable for artifacts)."""
    page = _make_page(qtbot)
    src = tmp_path / "out" / "map.pdf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"%PDF-1.4")
    version = core.register_result_asset(
        name="map.pdf",
        type="export",
        format="pdf",
        asset_metadata=None,
        source_path=src,
        stage=DataStage.OUTPUT,
    )
    artifact = ExportArtifact(
        linked_id="map_1",
        format="pdf",
        output_path=str(src),
        catalog_version_id=version.id,
    )
    page.project.export_artifacts.append(artifact)

    dest = tmp_path / "handoff" / "delivered.pdf"
    _StubDeliveryDialog.destination = dest
    monkeypatch.setattr(dlc, "_DeliveryDialog", _StubDeliveryDialog)

    page._deliver_asset(artifact)

    # The payload copy runs on a worker (#379); wait for the delivery run.
    qtbot.waitUntil(
        lambda: "已记录交付元数据" in page.data_toolbar.operation_status_label.text(),
        timeout=5000,
    )

    runs = [r for r in core.list_runs() if r.operation == "delivery"]
    assert len(runs) == 1
    assert runs[0].input_version_ids == [version.id]
    assert runs[0].parameters["source_version_id"] == version.id
    assert runs[0].parameters["exported_path"] == dest.as_posix()
    assert runs[0].parameters["checksum"] == sha256_file(dest)
    assert runs[0].parameters["delivery_status"] == "exported"
    assert dest.read_bytes() == b"%PDF-1.4"  # delivery itself succeeded
    assert "已记录交付元数据" in page.data_toolbar.operation_status_label.text()


# ================================================ E3 working copy / materialize


class _StubNewVersionDialog:
    """Non-modal stand-in for the 提交新版本 dialog (defaults: DERIVED)."""

    def __init__(self, parent=None, *, asset_name: str = "", default_stage: str = "derived"):
        pass

    def exec(self):
        return QDialog.DialogCode.Accepted

    def stage(self):
        return DataStage.DERIVED

    def version_name(self):
        return "edited copy"


def test_working_copy_commit_records_run_with_output(qtbot, tmp_path, core, monkeypatch):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    core.migrate_legacy_resources(page.project.resources)
    monkeypatch.setattr(dlc, "_NewVersionDialog", _StubNewVersionDialog)
    monkeypatch.setattr(dlc.QDesktopServices, "openUrl", lambda url: True)

    page._new_version_from_asset(resource)

    runs = [r for r in core.list_runs() if r.operation == "working_copy_commit"]
    assert len(runs) == 1
    assert runs[0].input_version_ids == [f"ver_{resource.id}"]
    assert runs[0].parameters["stage"] == "derived"
    assert len(runs[0].output_version_ids) == 1
    committed = core.get_version(runs[0].output_version_ids[0])
    assert committed.stage is DataStage.DERIVED
    assert committed.parent_version_ids == [f"ver_{resource.id}"]


def test_working_copy_commit_survives_run_booking_failure(
    qtbot, tmp_path, core, monkeypatch
):
    """Run-booking failure falls back to a run-less commit — the commit itself
    must never fail because of provenance bookkeeping."""
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    core.migrate_legacy_resources(page.project.resources)
    monkeypatch.setattr(dlc, "_NewVersionDialog", _StubNewVersionDialog)
    monkeypatch.setattr(dlc.QDesktopServices, "openUrl", lambda url: True)

    def boom(*args, **kwargs):
        raise RuntimeError("booking failed")

    monkeypatch.setattr(core, "register_run", boom)

    page._new_version_from_asset(resource)

    assert [r for r in core.list_runs() if r.operation == "working_copy_commit"] == []
    asset = core.get_asset(resource.id)
    assert asset.current_version_id != f"ver_{resource.id}"  # commit landed anyway
    assert "已提交新版本" in page.data_toolbar.operation_status_label.text()


def test_materialize_records_run_with_output(qtbot, tmp_path, core):
    page = _make_page(qtbot)
    resource = _make_external_resource(page, tmp_path)
    core.migrate_legacy_resources(page.project.resources)

    page._materialize_asset(resource)

    runs = [r for r in core.list_runs() if r.operation == "materialize"]
    assert len(runs) == 1
    assert runs[0].input_version_ids == [f"ver_{resource.id}"]
    assert runs[0].parameters["source"].endswith("ext.sgy")
    assert len(runs[0].output_version_ids) == 1
    managed = core.get_version(runs[0].output_version_ids[0])
    assert managed.managed is True
    assert managed.parent_version_ids == [f"ver_{resource.id}"]
    assert resource.external is False


# ============================================================== E4 fault


def test_fault_registration_failure_completes_run_failed(fake, tmp_path, monkeypatch):
    art = tmp_path / "f.fault_interp.json"
    art.write_text("{}", encoding="utf-8")

    def boom(**kwargs):
        raise RuntimeError("save failed")

    monkeypatch.setattr(fake, "register_derived", boom)

    with pytest.raises(RuntimeError):
        register_fault_interpretation_run(
            name="F", path=str(art), checksum=None, catalog=fake
        )

    runs = [r for r in fake.list_runs() if r.operation == "fault_interpretation"]
    assert len(runs) == 1
    assert runs[0].status == "failed"  # no orphan RUNNING run


def test_fault_save_reclaims_artifact_on_registration_failure(
    fake, tmp_path, monkeypatch
):
    """save_fault_draft must leave NO ghost artifact when catalog registration
    fails (same H7 contract as correlation drafts)."""
    from paleo_workbench.workflow.fault_lifecycle import save_fault_draft
    from paleo_workbench.workflow.stratigraphy_models import FaultTrace

    project = ProjectDocument.new("F")
    project.meta.project_root = str(tmp_path)
    proj_path = tmp_path / "demo.paleo.json"

    from paleo_workbench.workflow.fault_lifecycle import new_fault_draft

    draft = new_fault_draft(
        name="F1",
        traces=[FaultTrace(name="f-a", polyline=[[0.0, 0.0], [1.0, 1.0]], role="fault")],
    )

    def boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(fake, "register_derived", boom)

    with pytest.raises(RuntimeError):
        save_fault_draft(draft, project, proj_path, catalog=fake)

    assert list((tmp_path / "demo.artifacts").rglob("*.fault_interp.json")) == []
    assert project.fault_interpretations == []


# =========================================================== E5 finalize


def _map_document(project: ProjectDocument) -> PaleoMapDocument:
    doc = PaleoMapDocument(
        name="H1 图",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}
        ],
    )
    project.paleomap_documents.append(doc)
    return doc


def test_register_finalize_run_resolves_map_versions(fake, tmp_path):
    project = ProjectDocument.new("V")
    doc = _map_document(project)
    payload = tmp_path / "paleomap.json"
    payload.write_text("{}", encoding="utf-8")
    _run, map_version = register_map_compile_run(
        name=doc.name,
        domain_task_id=doc.id,
        result_path=str(payload),
        catalog=fake,
    )

    from paleo_workbench.workflow.versioning import build_snapshot

    snap = build_snapshot(project, doc, note="OK", created_by="alice")

    run_id = register_finalize_run(
        fake,
        snapshot=snap,
        operator="alice",
        note="OK",
        version_set_id="vset_1",
    )

    assert run_id is not None
    final_runs = [r for r in fake.list_runs() if r.operation == "version_finalize"]
    assert len(final_runs) == 1
    assert map_version.version_id in final_runs[0].input_version_ids
    assert final_runs[0].parameters["version_set_id"] == "vset_1"
    assert final_runs[0].parameters["operator"] == "alice"
    assert final_runs[0].parameters["snapshot_id"] == snap.id


def test_register_finalize_run_without_resolvable_inputs_returns_none(fake):
    snap = VersionSnapshot(map_document_id="map_never_registered")
    assert (
        register_finalize_run(fake, snapshot=snap, operator="a", note="") is None
    )
    assert fake.list_runs() == []  # nothing fabricated


def test_finalize_map_version_registers_finalize_run(fake, tmp_path):
    """The finalize workflow records its catalog run when lineage is traceable."""
    project = ProjectDocument.new("V")
    doc = _map_document(project)
    payload = tmp_path / "paleomap.json"
    payload.write_text("{}", encoding="utf-8")
    register_map_compile_run(
        name=doc.name, domain_task_id=doc.id, result_path=str(payload), catalog=fake
    )

    vset = finalize_map_version(project, doc.id, note="OK", operator="alice")

    runs = [r for r in fake.list_runs() if r.operation == "version_finalize"]
    assert len(runs) == 1
    assert runs[0].parameters["version_set_id"] == vset.id
    assert runs[0].status == "complete"


def test_finalize_map_version_without_catalog_still_finalizes(tmp_path):
    """No catalog → finalize succeeds, no registration attempted."""
    project = ProjectDocument.new("N")
    doc = _map_document(project)
    vset = finalize_map_version(project, doc.id, operator="bob")
    assert vset.status == "final"


# ============================================== E6 well-seismic joint snapshot


def test_joint_snapshot_export_declares_loaded_sources(qtbot, fake, tmp_path):
    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage
    from paleo_workbench.viz.joint_asset_resolver import JointAssetPaths

    project = ProjectDocument.new("J")
    segy = tmp_path / "seis.sgy"
    segy.write_bytes(b"SGY")
    well_head = tmp_path / "wellhead.dat"
    well_head.write_bytes(b"WH")
    res_seis = ResourceItem(
        name="seis.sgy", path=str(segy), type="seismic", format="sgy"
    )
    res_wh = ResourceItem(
        name="wellhead.dat", path=str(well_head), type="well_head", format="dat"
    )
    project.resources.extend([res_seis, res_wh])

    page = WellSeismicJointPage(project=project)
    qtbot.addWidget(page)
    page._host._paths = JointAssetPaths(segy=segy, well_head=well_head)

    seis_ref = fake.register_input(
        name="seis.sgy",
        path=str(segy),
        checksum=None,
        kind="seismic",
        format="sgy",
        legacy_resource_id=res_seis.id,
    )
    wh_ref = fake.register_input(
        name="wellhead.dat",
        path=str(well_head),
        checksum=None,
        kind="well_head",
        format="dat",
        legacy_resource_id=res_wh.id,
    )

    out = tmp_path / "joint.png"
    out.write_bytes(b"PNG")
    page._register_snapshot_export(str(out))

    export_runs = [r for r in fake.list_runs() if r.operation == "export"]
    assert len(export_runs) == 1
    assert {seis_ref.version_id, wh_ref.version_id} <= set(
        export_runs[0].input_version_ids
    )  # OUTPUT lineage no longer empty


def test_joint_snapshot_source_ids_helper_matches_loaded_paths(qtbot, tmp_path):
    """Unit level: the helper resolves exactly the loaded seismic/well resources."""
    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage
    from paleo_workbench.viz.joint_asset_resolver import JointAssetPaths

    project = ProjectDocument.new("J")
    segy = tmp_path / "s.sgy"
    segy.write_bytes(b"S")
    other = tmp_path / "unrelated.las"
    other.write_bytes(b"L")
    res_seis = ResourceItem(name="s.sgy", path=str(segy), type="seismic", format="sgy")
    res_other = ResourceItem(
        name="unrelated.las", path=str(other), type="well_log", format="las"
    )
    project.resources.extend([res_seis, res_other])

    page = WellSeismicJointPage(project=project)
    qtbot.addWidget(page)
    page._host._paths = JointAssetPaths(segy=segy)

    assert page._loaded_source_resource_ids() == [res_seis.id]


# ======================================================== E7 3D mesh export


def test_mesh_export_carries_modeling_run_inputs(qtbot, fake, tmp_path):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page.set_project(ProjectDocument.new("G"))
    page.combo_export_type.setCurrentIndex(0)  # FLAC3D

    raw = fake.register_input(
        name="boreholes.csv",
        path="/tmp/boreholes.csv",
        checksum="c1",
        kind="table",
        format="csv",
        legacy_resource_id="res_bh",
    )
    page._last_modeling_run_inputs = [raw.version_id]

    out = tmp_path / "model.f3grid"
    out.write_bytes(b"MESH")
    page._register_mesh_export(str(out))

    export_runs = [r for r in fake.list_runs() if r.operation == "export"]
    assert len(export_runs) == 1
    assert export_runs[0].input_version_ids == [raw.version_id]


def test_modeling_run_inputs_are_remembered(qtbot, fake, monkeypatch):
    """_register_modeling_run stores the registered run's declared inputs so a
    later mesh export can reuse them as source lineage."""
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page.set_project(ProjectDocument.new("G"))

    import paleo_workbench.catalog.lifecycle as lifecycle_mod

    captured: dict = {}
    orig = lifecycle_mod.register_modeling_run

    def spy(**kwargs):
        run, _version = orig(**kwargs)  # the page already passes catalog=fake
        captured["inputs"] = list(run.input_version_ids or [])
        return run, _version

    monkeypatch.setattr(lifecycle_mod, "register_modeling_run", spy)

    page._register_modeling_run({"algorithm": "synthetic_demo"}, is_demo=True)

    assert page._last_modeling_run_inputs == captured["inputs"]


# ============================================================== E8 qc run


def test_qc_run_attaches_report_output_version(fake):
    project = ProjectDocument.new("QC")
    doc = _map_document(project)
    report = run_basic_qc(project, doc.id)

    assert report.provenance_registered is True
    runs = [r for r in fake.list_runs() if r.operation == "qc"]
    assert len(runs) == 1
    assert runs[0].output_version_ids, "qc run must carry the report output version"
    out_version = fake.resolve_version(runs[0].output_version_ids[0])
    assert out_version is not None
    assert out_version.kind == "qc_report"
    assert out_version.checksum  # hashed from the serialized report payload


def test_qc_report_survives_without_catalog():
    project = ProjectDocument.new("QC")
    doc = _map_document(project)
    report = run_basic_qc(project, doc.id)
    # No catalog → report still produced; registration outcome visible (H14).
    assert report.provenance_registered is False
    assert len(project.quality_reports) == 1


# ======================================================= E9 import failures


def test_import_registration_failures_are_counted(qtbot, monkeypatch):
    """One failing resource must not skip the rest, and failures are recorded
    visibly on ``last_registration_failures`` (reset per call)."""
    import paleo_workbench.catalog.lifecycle as lifecycle_mod

    page = _make_page(qtbot)
    controller = page._lifecycle
    good = ResourceItem(
        name="good.las", path="/tmp/good.las", type="well_log", format="las"
    )
    bad = ResourceItem(
        name="bad.las", path="/tmp/bad.las", type="well_log", format="las"
    )

    attempts: list[str] = []
    real = register_resource_input

    def flaky(resource, **kwargs):
        attempts.append(resource.name)
        if resource.name == "bad.las":
            raise RuntimeError("boom")
        return real(resource, **kwargs)

    monkeypatch.setattr(lifecycle_mod, "register_resource_input", flaky)

    controller.register_imported_resources([bad, good])

    assert attempts == ["bad.las", "good.las"]  # failure did not skip the rest
    assert len(controller.last_registration_failures) == 1
    assert "bad.las" in controller.last_registration_failures[0]

    controller.register_imported_resources([good])
    assert controller.last_registration_failures == []  # reset per call


def test_qc_run_uses_stable_per_map_domain_key(fake):
    """The QC DataRun must be keyed by the map's linked task (falling back to
    the document id) — not the per-run report id — so re-QC after a recompile
    collapses to the latest run instead of keeping every historical QC run in
    the step aggregation (issue #373 / C15)."""
    project = ProjectDocument.new("QC")
    doc = PaleoMapDocument(
        name="H1 图",
        linked_target_horizon="H1",
        linked_prediction_task_id="task-p1",
        facies_polygons=[
            {"id": "f1", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}
        ],
    )
    project.paleomap_documents.append(doc)

    run_basic_qc(project, doc.id)
    run_basic_qc(project, doc.id)  # re-QC of the same map

    qc_runs = [r for r in fake.list_runs() if r.operation == "qc"]
    assert len(qc_runs) == 2
    keys = {r.domain_task_id for r in qc_runs}
    assert keys == {"task-p1"}, keys

    # The document id is the fallback key when no task is linked.
    project2 = ProjectDocument.new("QC2")
    doc2 = PaleoMapDocument(
        name="H2 图",
        linked_target_horizon="H2",
        facies_polygons=[
            {"id": "f1", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}
        ],
    )
    project2.paleomap_documents.append(doc2)
    run_basic_qc(project2, doc2.id)
    qc2 = [r for r in fake.list_runs() if r.operation == "qc"][-1]
    assert qc2.domain_task_id == doc2.id
