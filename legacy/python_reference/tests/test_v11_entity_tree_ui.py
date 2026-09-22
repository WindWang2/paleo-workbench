"""V11 Data Manager entity view: role-grouped tree + well detail panel."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import (
    EntityAssetLink,
    WellEntity,
    upsert_entity_asset_link,
)
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.navigation_tree import (
    ENTITY_NODE,
    NavigationTree,
)


@pytest.fixture()
def catalog_env(tmp_path: Path):
    project_file = tmp_path / "demo.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    yield service, tmp_path
    service.close()


def _well_doc_multi_role():
    doc = ProjectDocument.new("W")
    well = WellEntity(name="A1")
    doc.wells.append(well)
    for asset_id, role in (
        ("asset_head", "well_head"),
        ("asset_las1", "well_log"),
        ("asset_las2", "well_log"),
        ("asset_tops", "tops"),
    ):
        doc.entity_asset_links.append(
            EntityAssetLink(
                entity_type="well",
                entity_id=well.id,
                asset_id=asset_id,
                role=role,
            )
        )
    return doc, well


def test_well_leaves_group_by_role(qtbot):
    doc, well = _well_doc_multi_role()
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(doc)

    group = tree._well_group_item
    well_item = group.child(0)
    # three role groups: 井身/井位, 测井曲线 (2), 分层顶
    role_texts = [
        well_item.child(i).text(0) for i in range(well_item.childCount())
    ]
    assert any(t.startswith("◧ 井身/井位 (1)") for t in role_texts)
    assert any(t.startswith("◧ 测井曲线 (2)") for t in role_texts)
    assert any(t.startswith("◧ 分层顶 (1)") for t in role_texts)
    # well_log group holds both LAS leaves
    log_group = next(
        well_item.child(i)
        for i in range(well_item.childCount())
        if "测井曲线" in well_item.child(i).text(0)
    )
    assert log_group.childCount() == 2
    leaf = log_group.child(0)
    query = leaf.data(0, Qt.ItemDataRole.UserRole)
    assert query.node_type == ENTITY_NODE
    assert query.node_value == well.id


def test_entity_activated_signal_on_double_click(qtbot):
    doc, well = _well_doc_multi_role()
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(doc)
    emitted: list[str] = []
    tree.entity_activated.connect(emitted.append)

    group = tree._well_group_item
    well_item = group.child(0)
    tree._on_item_activated(well_item, 0)
    assert emitted == [well.id]

    # file leaves do NOT re-emit entity activation
    log_group = next(
        well_item.child(i)
        for i in range(well_item.childCount())
        if "测井曲线" in well_item.child(i).text(0)
    )
    tree._on_item_activated(log_group.child(0), 0)
    assert emitted == [well.id]


def test_well_detail_panel_renders_view(qtbot, catalog_env, tmp_path):
    from paleo_workbench.catalog.entity_views import EntityViewService
    from paleo_workbench.ui.pages.well_detail_panel import WellDetailPanel

    service, tmp_path = catalog_env
    doc = ProjectDocument.new("W")
    well = WellEntity(name="A1", uwi="UWI-9")
    doc.wells.append(well)
    las1 = tmp_path / "a1.las"
    las1.write_text("las-1", encoding="utf-8")
    v1 = service.import_raw(las1, name="a1.las", type="well_log")
    asset1 = service.get_asset(service.get_version(v1.id).asset_id)
    las2 = tmp_path / "a2.las"
    las2.write_text("las-2", encoding="utf-8")
    v2 = service.import_raw(las2, name="a2.las", type="well_log")
    asset2 = service.get_asset(service.get_version(v2.id).asset_id)
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset1.id,
        role="well_log", is_primary=True,
    )
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset2.id,
        role="well_log",
    )

    view = EntityViewService(service, doc).well_view(well.id)
    panel = WellDetailPanel()
    qtbot.addWidget(panel)
    panel.set_view(view)

    assert panel._title.text() == "A1"
    assert "UWI-9" in panel._subtitle.text()
    # roles table: only filled slots appear as rows
    assert panel._roles_table.rowCount() == 1
    assert "a1.las" in panel._roles_table.item(0, 1).text() or "a2.las" in panel._roles_table.item(0, 1).text()
    panel.set_view(None)
    assert panel._roles_table.rowCount() == 0


def test_workspace_well_detail_stack(qtbot):
    from paleo_workbench.ui.pages.data_workspace import DataWorkspace

    workspace = DataWorkspace()
    qtbot.addWidget(workspace)
    assert not workspace.well_detail_visible()
    workspace.show_well_detail(True)
    assert workspace.well_detail_visible()
    workspace.show_well_detail(False)
    assert not workspace.well_detail_visible()
    # overview swap still works after the V11 index was added
    workspace.show_overview(True)
    assert workspace.overview_visible()
    workspace.show_overview(False)
    assert not workspace.overview_visible()
