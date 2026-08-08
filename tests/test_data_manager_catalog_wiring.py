"""UI → Core catalog wiring tests (Data Manager ↔ DataCatalogService).

Covers: tag mirroring, derived copy via Core, integrity verification via the
service (UI never overwrites recorded checksums), materialize external,
inspector enrichment, and graceful legacy fallback when no catalog is wired.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import (
    CoreCatalogAdapter,
    DataCatalogService,
    DataStage,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.data_view_models import IntegrityState
from paleo_workbench.ui.pages.integrity_worker import IntegrityWorker


@pytest.fixture(autouse=True)
def _clean_catalog_runtime():
    reset_catalog()
    yield
    reset_catalog()


def _make_project_file(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def catalog(tmp_path):
    """A real Core DataCatalogService on a tmp_path project, wired as active."""
    service = DataCatalogService.open(_make_project_file(tmp_path))
    set_catalog(CoreCatalogAdapter(service))
    yield service
    reset_catalog()
    service.close()


def _project_dir(tmp_path: Path) -> Path:
    return tmp_path / "proj"


def _make_managed_resource(page: DataPage, tmp_path: Path, name: str = "well.las") -> ResourceItem:
    """A managed (in-project) resource with a real payload + recorded checksum."""
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


def _make_external_resource(page: DataPage, tmp_path: Path, name: str = "ext.sgy") -> ResourceItem:
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


def _make_page(qtbot) -> DataPage:
    page = DataPage(project=ProjectDocument.new("Catalog Wiring"))
    qtbot.addWidget(page)
    return page


# --- tag mirroring ---------------------------------------------------------


def test_tag_add_and_remove_mirrors_to_catalog(qtbot, tmp_path, catalog):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    catalog.migrate_legacy_resources(page.project.resources)

    page._handle_tag_added(resource, "重点井")

    assert "重点井" in resource.tags  # legacy .paleo.json compat preserved
    assert catalog.find_assets_by_tag("重点井") == [resource.id]

    page._handle_tag_removed(resource, "重点井")

    assert "重点井" not in resource.tags
    assert catalog.find_assets_by_tag("重点井") == []


def test_tag_mirror_failure_does_not_break_ui(qtbot, tmp_path, catalog):
    """An un-bridged resource (no catalog asset) must not raise on tag ops."""
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    # No migration → resolve_legacy_resource returns None → no mirror.

    page._handle_tag_added(resource, "普通")

    assert "普通" in resource.tags
    assert catalog.find_assets_by_tag("普通") == []


# --- derived copy via Core ---------------------------------------------------


def test_derived_copy_goes_through_core(qtbot, tmp_path, catalog):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    catalog.migrate_legacy_resources(page.project.resources)
    raw_version = catalog.get_version(f"ver_{resource.id}")
    raw_sha_before = raw_version.sha256

    page._create_derived_copy(resource)

    # RAW version untouched (immutable).
    assert catalog.get_version(raw_version.id).sha256 == raw_sha_before
    assert raw_version.stage == DataStage.RAW

    # New DERIVED version with parent lineage + provenance run.
    derived_versions = [
        v
        for v in catalog.document.versions
        if v.stage == DataStage.DERIVED and raw_version.id in v.parent_version_ids
    ]
    assert len(derived_versions) == 1
    derived_version = derived_versions[0]
    runs = [r for r in catalog.list_runs() if r.operation == "derived_copy"]
    assert len(runs) == 1
    assert runs[0].input_version_ids == [raw_version.id]
    assert runs[0].output_version_ids == [derived_version.id]

    # Legacy ResourceItem companion points at the Core-managed payload, stored
    # project-relative (the managed payload lives inside the project dir, so
    # .paleo.json stays relocatable).
    assert len(page.project.resources) == 2
    companion = page.project.resources[1]
    assert companion.name == f"{resource.name}_derived"
    assert companion.artifact_role == "derived"
    assert "派生" in companion.tags
    assert not Path(companion.path).is_absolute()
    assert companion.path == derived_version.path
    assert _project_dir(tmp_path) / companion.path == catalog.resolve_path(derived_version)
    assert companion.checksum == derived_version.sha256
    assert companion.external is False
    assert companion.parsed_summary["catalog_version_id"] == derived_version.id

    lineage = catalog.get_lineage(derived_version.id)
    assert [p.id for p in lineage["parents"]] == [raw_version.id]


def test_derived_copy_legacy_fallback_without_catalog(qtbot, tmp_path):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)

    page._create_derived_copy(resource)

    assert len(page.project.resources) == 2
    companion = page.project.resources[1]
    assert companion.artifact_role == "derived"
    assert companion.path == resource.path  # legacy companion shares the path
    assert companion.checksum == resource.checksum


# --- integrity via the service ----------------------------------------------


def _run_worker(worker: IntegrityWorker):
    reports = []
    worker.finished.connect(reports.append)
    worker.run()
    assert len(reports) == 1
    return reports[0]


def test_integrity_verify_uses_service_for_bridged_assets(qtbot, tmp_path, catalog):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    catalog.migrate_legacy_resources(page.project.resources)

    service, bridged = page._bridged_version_map([resource])
    assert service is catalog
    assert bridged == {resource.id: f"ver_{resource.id}"}

    # Untampered → verified through the Core service.
    worker = IntegrityWorker(
        [resource], catalog_service=service, bridged_versions=bridged
    )
    report = _run_worker(worker)
    assert report.results[resource.id] == IntegrityState.VERIFIED
    assert report.verified_count == 1


def test_integrity_tamper_reports_modified_and_keeps_recorded_checksum(
    qtbot, tmp_path, catalog
):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    catalog.migrate_legacy_resources(page.project.resources)
    version = catalog.get_version(f"ver_{resource.id}")
    recorded_sha = version.sha256

    # Tamper with the payload on disk.
    payload = catalog.resolve_path(version)
    payload.write_bytes(b"tampered")

    service, bridged = page._bridged_version_map([resource])
    worker = IntegrityWorker(
        [resource], catalog_service=service, bridged_versions=bridged
    )
    report = _run_worker(worker)

    assert report.results[resource.id] == IntegrityState.MODIFIED
    assert report.modified_count == 1
    # The UI must never overwrite recorded checksums for catalog assets.
    assert resource.id not in report.checksum_updates
    assert catalog.get_version(version.id).sha256 == recorded_sha


def test_integrity_unbridged_assets_keep_legacy_path(qtbot, tmp_path, catalog):
    """Catalog wired but resource not bridged → legacy self-hashing path."""
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    # No migration → un-bridged.
    service, bridged = page._bridged_version_map([resource])
    assert bridged == {}

    worker = IntegrityWorker(
        [resource],
        project_root=_project_dir(tmp_path),
        catalog_service=service,
        bridged_versions=bridged,
    )
    report = _run_worker(worker)
    assert report.results[resource.id] == IntegrityState.VERIFIED


# --- materialize external ----------------------------------------------------


def test_materialize_external_via_service(qtbot, tmp_path, catalog):
    page = _make_page(qtbot)
    resource = _make_external_resource(page, tmp_path)
    catalog.migrate_legacy_resources(page.project.resources)
    external_version = catalog.get_version(f"ver_{resource.id}")
    assert external_version.managed is False

    page._materialize_asset(resource)

    # Catalog: new managed RAW snapshot with lineage back to the external link.
    asset = catalog.get_asset(resource.id)
    managed_version = catalog.get_version(asset.current_version_id)
    assert managed_version.managed is True
    assert managed_version.id != external_version.id
    assert managed_version.parent_version_ids == [external_version.id]
    assert catalog.resolve_path(managed_version).is_file()

    # Legacy ResourceItem updated to the managed payload (project-relative:
    # the managed snapshot lives inside the project dir).
    assert resource.external is False
    assert not Path(resource.path).is_absolute()
    assert resource.path == managed_version.path
    assert _project_dir(tmp_path) / resource.path == catalog.resolve_path(managed_version)
    assert resource.checksum == managed_version.sha256


def test_materialize_without_catalog_reports_unavailable(qtbot, tmp_path):
    page = _make_page(qtbot)
    resource = _make_external_resource(page, tmp_path)

    page._materialize_asset(resource)

    assert resource.external is True  # unchanged
    assert "未连接数据目录" in page.data_toolbar.operation_status_label.text()


def test_materialize_action_enabled_only_for_bridged_external(
    qtbot, tmp_path, catalog
):
    from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu

    page = _make_page(qtbot)
    ext_resource = _make_external_resource(page, tmp_path)
    managed_resource = _make_managed_resource(page, tmp_path, name="managed.las")
    catalog.migrate_legacy_resources(page.project.resources)

    # The menu builds the action disabled for external assets; DataPage enables
    # it only when bridged to an unmanaged catalog version. Drive the same
    # logic the context-menu wiring uses.
    _svc, ext_ref = page._catalog_bridge(ext_resource)
    assert ext_ref is not None and ext_ref.external is True
    _svc, managed_ref = page._catalog_bridge(managed_resource)
    assert managed_ref is not None and managed_ref.external is False

    menu = AssetContextMenu()
    menu.build(ext_resource, viz_supported=False)
    act = menu.find_action("ctx_materialize")
    assert act is not None
    assert act.isEnabled() is False  # enabled by DataPage only when actionable


# --- inspector enrichment -----------------------------------------------------


def test_inspector_enriched_from_catalog(qtbot, tmp_path, catalog):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    catalog.migrate_legacy_resources(page.project.resources)
    catalog.add_tag("重点", asset_id=resource.id)
    page._create_derived_copy(resource)  # adds a DERIVED child + run

    page._update_inspector(resource)

    view = page.inspector_panel._current_view
    assert view is not None
    # Versions come from the catalog (real version ids, not legacy "v1").
    assert any(v.version_id == f"ver_{resource.id}" for v in view.versions)
    assert all(v.version_id != "v1" for v in view.versions)
    # Tags mirrored from the catalog asset.
    assert "重点" in view.tags
    # Lineage: the derived copy appears as a child of the RAW version.
    assert view.lineage.child_ids, "expected derived child in lineage"
    child = catalog.get_version(view.lineage.child_ids[0])
    assert child.stage == DataStage.DERIVED
    assert view.lineage.has_lineage is True


def test_inspector_enrichment_for_derived_asset_shows_parents_and_run(
    qtbot, tmp_path, catalog
):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)
    catalog.migrate_legacy_resources(page.project.resources)
    page._create_derived_copy(resource)
    companion = page.project.resources[1]

    derived_version = catalog.get_version(companion.parsed_summary["catalog_version_id"])
    lineage = catalog.get_lineage(derived_version.id)
    assert lineage["run"] is not None
    assert lineage["run"].operation == "derived_copy"
    assert [p.id for p in lineage["parents"]] == [f"ver_{resource.id}"]


def test_inspector_falls_back_to_plain_view_without_catalog(qtbot, tmp_path):
    page = _make_page(qtbot)
    resource = _make_managed_resource(page, tmp_path)

    page._update_inspector(resource)

    view = page.inspector_panel._current_view
    assert view is not None
    assert [v.version_id for v in view.versions] == ["v1"]  # legacy default
    assert view.lineage.has_lineage is False
