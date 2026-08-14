"""Data Manager governance UI tests (data-governance v2).

Covers: full lineage tree in the inspector, lineage column values, catalog-only
result rows surfacing in the table, review-status filtering, governance
metadata editing flow, the Catalog Health dialog, and workflow-refresh wiring.
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
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.catalog_health_dialog import CatalogHealthDialog
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.filter_index import FilterIndex, FilterQuery
from paleo_workbench.ui.pages.governance_dialog import GovernanceMetadataDialog


@pytest.fixture(autouse=True)
def _clean_catalog_runtime():
    reset_catalog()
    yield
    reset_catalog()


@pytest.fixture
def catalog(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    yield service
    reset_catalog()
    service.close()


def _page(qtbot, catalog) -> DataPage:
    page = DataPage(project=ProjectDocument.new("Governance UI"))
    qtbot.addWidget(page)
    page.set_project_path(catalog.project_path)
    return page


def _seed_chain(tmp_path: Path, catalog: DataCatalogService, page: DataPage):
    """seismic RAW (bridged resource) → factor INTERMEDIATE → paleomap DERIVED."""
    project_dir = catalog.project_path.parent
    (project_dir / "raw.sgy").write_bytes(b"seismic")
    raw = catalog.import_raw(
        project_dir / "raw.sgy", name="raw.sgy", type="seismic"
    )
    resource = ResourceItem(
        id=raw.asset_id,
        name="raw.sgy",
        path=str(project_dir / "raw.sgy"),
        type="seismic",
        format="sgy",
        artifact_role="input",
    )
    page.project.resources.append(resource)
    (project_dir / "g.npz").write_bytes(b"grid")
    (project_dir / "m.json").write_bytes(b"map")
    inter = catalog.create_derived(
        project_dir / "g.npz",
        parent_version_ids=[raw.id],
        name="factor_grid",
        operation="factor_map",
        type="factor_map",
    )
    out = catalog.create_derived(
        project_dir / "m.json",
        parent_version_ids=[inter.id],
        name="paleomap",
        operation="map_compile",
        type="paleomap",
    )
    catalog.update_asset_metadata(out.asset_id, {"review_status": "pending"})
    page._refresh()
    return raw, inter, out


# --- lineage tree --------------------------------------------------------------


def test_inspector_lineage_tree_shows_full_chain(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    resource = page.project.resources[0]
    page._set_selected_asset(resource)
    page._update_inspector(resource)

    tree = page.inspector_panel.lineage_tree.tree
    texts = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert any("上游追溯" in t for t in texts)
    flat = []

    def walk(item):
        flat.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    joined = "\n".join(flat)
    assert "paleomap" in joined
    assert "factor_grid" in joined
    assert "raw.sgy" in joined
    assert "map_compile" in joined  # producing run interleaved
    assert "prediction" not in joined


def test_lineage_node_double_click_emits_activation(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    page._set_selected_asset(page.project.resources[0])
    page._update_inspector(page.project.resources[0])

    tree = page.inspector_panel.lineage_tree.tree
    with qtbot.waitSignal(
        page.inspector_panel.lineage_version_activated, timeout=2000
    ) as blocker:
        # Double-click the current version node (root of the upstream tree).
        root_holder = tree.topLevelItem(0)
        version_item = root_holder.child(0)
        tree.itemDoubleClicked.emit(version_item, 0)
    version_id, asset_id = blocker.args
    assert version_id == raw.id
    assert asset_id == raw.asset_id


# --- table columns / catalog-only rows ------------------------------------------


def test_lineage_column_shows_depth_to_raw(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    page._refresh()
    model = page.asset_table.model
    column = page.asset_table.visible_column_keys().index("lineage")
    statuses = {
        model.view_at(row).name: model.view_at(row).lineage_status
        for row in range(model.rowCount())
    }
    assert statuses["raw.sgy"] == "源头"
    assert statuses["factor_grid"] == "1 级至源头"
    assert statuses["paleomap"] == "2 级至源头"


def test_catalog_only_results_appear_in_table(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    names = {
        page.asset_table.model.view_at(row).name
        for row in range(page.asset_table.model.rowCount())
    }
    # The bridged resource AND the two catalog-only products are listed.
    assert {"raw.sgy", "factor_grid", "paleomap"} <= names


def test_catalog_only_row_selection_enriches_inspector(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    target = None
    for row in range(page.asset_table.model.rowCount()):
        view = page.asset_table.model.view_at(row)
        if view is not None and view.name == "paleomap":
            target = page.asset_table.model.asset_at(row)
            break
    assert target is not None
    page._set_selected_asset(target)
    page._update_inspector(target)
    assert page.inspector_panel._current_view is not None
    assert page.inspector_panel._current_view.name == "paleomap"


def test_removing_catalog_only_row_trashes_asset(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    catalog_only = [
        page.asset_table.model.asset_at(row)
        for row in range(page.asset_table.model.rowCount())
        if (page.asset_table.model.view_at(row) or AssetViewNone).name == "paleomap"
    ]
    assert catalog_only
    assert page.remove_assets(catalog_only) is True
    assert catalog.get_asset(out.asset_id).trashed is True


class _NilView:
    name = ""


AssetViewNone = _NilView()


# --- governance metadata ---------------------------------------------------------


def test_governance_dialog_patch_is_normalized():
    dlg = GovernanceMetadataDialog(
        None, asset_name="x", current={"region": "塔里木", "confidence": "high"}
    )
    dlg.review_combo.setCurrentIndex(
        dlg.review_combo.findData("pending_review")
    )
    dlg.confidence_combo.setCurrentIndex(dlg.confidence_combo.findData("low"))
    patch = dlg.patch()
    assert patch["confidence"] == "low"
    assert patch["review_status"] == "pending_review"
    assert patch["region"] == "塔里木"
    assert patch["discipline"] == ""  # unset


def test_governance_edit_flow_persists(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    page._set_selected_asset(page.project.resources[0])
    page._update_inspector(page.project.resources[0])
    assert page.inspector_panel.governance_table.rowCount() >= 1

    ok = page._lifecycle.update_governance_metadata(
        raw.asset_id, {"region": "塔里木", "review_status": "已通过"}
    )
    assert ok is True
    meta = catalog.get_asset(raw.asset_id).metadata
    assert meta["region"] == "塔里木"
    assert meta["review_status"] == "approved"
    # The refreshed inspector shows the display label.
    page._set_selected_asset(page.project.resources[0])
    page._update_inspector(page.project.resources[0])
    body = []
    table = page.inspector_panel.governance_table
    for row in range(table.rowCount()):
        body.append(table.item(row, 0).text() + table.item(row, 1).text())
    assert any("已通过" in cell for cell in body)


# --- review-status filtering ------------------------------------------------------


def test_review_status_filter_matches_governed_rows(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    from paleo_workbench.ui.pages.data_view_models import (
        asset_view_from_object,
        make_catalog_enricher,
    )

    enrich = make_catalog_enricher(catalog)
    assets = page.asset_table.model.assets()
    views = [enrich(asset_view_from_object(a)) for a in assets]
    index = FilterIndex()
    index.rebuild(assets, enricher=enrich)
    rows = index.filter_query(
        FilterQuery(node_type="review_status", node_value="pending_review")
    )
    matched = {views[i].name for i in rows}
    assert matched == {"paleomap"}


def test_navigation_tree_review_group_counts(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    group = page.navigation_tree.review_parent_item
    labels = [
        group.child(i).text(0) for i in range(group.childCount())
    ]
    assert any("待审核" in label for label in labels)


# --- catalog health --------------------------------------------------------------


def test_health_dialog_renders_report(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    dialog = CatalogHealthDialog(page, service_provider=lambda: catalog)
    report = catalog.audit()
    dialog.update_report(report)
    text = dialog.summary_label.text()
    assert "资产 3" in text
    assert "版本 3" in text
    assert "运行 2" in text


def test_health_dialog_reports_missing_payload(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    payload = catalog.resolve_path(raw)
    payload.chmod(payload.stat().st_mode | 0o200)
    payload.unlink()
    dialog = CatalogHealthDialog(page, service_provider=lambda: catalog)
    dialog.update_report(catalog.audit())
    kinds = {
        dialog.issues_table.item(row, 1).text()
        for row in range(dialog.issues_table.rowCount())
    }
    assert "payload_missing" in kinds
    assert "高" in dialog.summary_label.text() or "⚠️" in dialog.summary_label.text()


# --- workflow refresh -------------------------------------------------------------


def test_workflow_controller_refreshes_data_page_after_updates(qtbot, tmp_path, catalog):
    from paleo_workbench.ui.workflow_controller import WorkflowController

    page = _page(qtbot, catalog)
    calls = []

    class _FakeShell:
        @staticmethod
        def data_page_widget():
            return page

        def update_data_page(self, state, resources, artifacts):
            calls.append((resources, artifacts))

        def update_home_page(self, *args, **kwargs):
            pass

        def update_seismic_prediction_page(self, *args, **kwargs):
            pass

        def update_well_log_prediction_page(self, *args, **kwargs):
            pass

        def update_visualization_page(self, *args, **kwargs):
            pass

        def update_preparation_page(self, *args, **kwargs):
            pass

        def update_mapping_page(self, *args, **kwargs):
            pass

        def update_review_export_page(self, *args, **kwargs):
            pass

    class _FakeWindow:
        app_shell = _FakeShell()
        project = page.project

    controller = WorkflowController(_FakeWindow())
    controller._on_factor_maps_updated()
    controller._on_seismic_prediction_updated()
    controller._on_qc_reports_updated()
    assert len(calls) == 3


# --- review-fix regressions ------------------------------------------------------


def test_enricher_resolves_production_import_bridge(qtbot, tmp_path, catalog):
    """Production imports bridge resource id -> asset via legacy_resource_id
    (asset id != resource id); the lineage column must still light up."""
    from paleo_workbench.catalog.lifecycle import register_resource_input

    page = _page(qtbot, catalog)
    project_dir = catalog.project_path.parent
    (project_dir / "prod.las").write_bytes(b"las-bytes")
    resource = ResourceItem(
        name="prod.las",
        path="prod.las",
        type="well_log",
        format="las",
        artifact_role="input",
    )
    page.project.resources.append(resource)
    register_resource_input(resource)
    page._refresh()

    model = page.asset_table.model
    statuses = {
        model.view_at(row).name: model.view_at(row).lineage_status
        for row in range(model.rowCount())
    }
    assert statuses.get("prod.las") == "源头"


def test_registered_export_not_duplicated_in_table(qtbot, tmp_path, catalog):
    """A catalog OUTPUT behind an ExportArtifact row must not ALSO appear as
    a catalog-only row (the deliverable would be listed twice."""
    from paleo_workbench.project.artifacts import record_export

    page = _page(qtbot, catalog)
    project_dir = catalog.project_path.parent
    (project_dir / "deliver.png").write_bytes(b"png")
    artifact = record_export(
        page.project,
        linked_id="raw",
        output_path=str(project_dir / "deliver.png"),
        fmt="png",
        source_task_ids=[],
    )
    assert artifact.catalog_version_id
    page._refresh()

    names = [
        page.asset_table.model.view_at(row).name
        for row in range(page.asset_table.model.rowCount())
    ]
    assert names.count("deliver.png") == 1


def test_catalog_only_row_preview_path_is_absolute(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    for row in range(page.asset_table.model.rowCount()):
        view = page.asset_table.model.view_at(row)
        if view is not None and view.name == "paleomap":
            assert view.path.startswith("/")
            break
    else:
        raise AssertionError("paleomap row not found")


def test_governance_save_refreshes_catalog_only_row_inspector(qtbot, tmp_path, catalog):
    page = _page(qtbot, catalog)
    raw, inter, out = _seed_chain(tmp_path, catalog, page)
    target = None
    for row in range(page.asset_table.model.rowCount()):
        view = page.asset_table.model.view_at(row)
        if view is not None and view.name == "paleomap":
            target = page.asset_table.model.asset_at(row)
            break
    page._set_selected_asset(target)
    page._update_inspector(target)

    ok = page._lifecycle.update_governance_metadata(
        out.asset_id, {"review_status": "approved"}
    )
    assert ok is True
    # _refresh re-points the selection at the rebuilt row; the inspector now
    # driven from it shows the NEW value, not the stale pre-edit view.
    body = []
    table = page.inspector_panel.governance_table
    for row in range(table.rowCount()):
        body.append(table.item(row, 1).text())
    assert any("已通过" in cell for cell in body)
