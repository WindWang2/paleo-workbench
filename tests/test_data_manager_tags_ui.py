"""Data Manager Tags UI tests (Agent F: F1-F7).

Covers: multi-tag FilterQuery AND/OR matching + normalization, the toolbar
tag-filter panel pipeline, the TagManagerDialog governance flows, the bulk
add/remove tag dialogs, the project_root table/navigation fix, the seven
default columns, inspector version tags, and the relaxed stage gating.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog

from paleo_workbench.catalog import DataCatalogService, reset_catalog
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages import data_page as dp
from paleo_workbench.ui.pages import inspector_panel as ip
from paleo_workbench.ui.pages import tag_widgets as tw
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu
from paleo_workbench.ui.pages.data_asset_table import (
    DEFAULT_COLUMN_KEYS,
    DataAssetTable,
)
from paleo_workbench.ui.pages.data_table_columns import COLUMN_BY_KEY
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    DataStage,
    IntegrityState,
    LineageView,
    VersionView,
)
from paleo_workbench.ui.pages.filter_index import FilterIndex, FilterQuery
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.tag_widgets import (
    BulkAddTagDialog,
    BulkRemoveTagDialog,
    TagManagerDialog,
    parse_multi_tag_input,
)


# --- helpers ------------------------------------------------------------------


def _res(name: str, *, tags=None, role=None, path=None, rtype="well_log"):
    return ResourceItem(
        name=name,
        path=path or f"/{name}",
        type=rtype,
        format="las",
        tags=list(tags or []),
        artifact_role=role,
    )


def _make_project_file(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def catalog(tmp_path: Path):
    """A real Core DataCatalogService (not wired as runtime active)."""
    service = DataCatalogService.open(_make_project_file(tmp_path))
    yield service
    service.close()


def _seed_catalog(service: DataCatalogService, tmp_path: Path) -> ResourceItem:
    payload = tmp_path / "proj" / "well.las"
    payload.write_bytes(b"well-bytes")
    resource = ResourceItem(
        name="well.las",
        path=payload.as_posix(),
        type="well_log",
        format="las",
        artifact_role="input",
    )
    service.migrate_legacy_resources([resource])
    service.add_tag("重点井", asset_id=resource.id)
    service.add_tag("版本标", version_id=f"ver_{resource.id}")
    # Standalone (zero-usage) tag entities: associate then disassociate —
    # the catalog only creates tags through an association.
    for name in ("探井", "unused"):
        service.bulk_add_tag(name, asset_ids=[resource.id])
        service.bulk_remove_tag(name, asset_ids=[resource.id])
    return resource


# --- F1: multi-tag FilterQuery ---------------------------------------------------


def test_filter_query_multi_tag_and_or_matrix():
    idx = FilterIndex()
    assets = [
        _res("a.las", tags=["重点井", "探井"]),
        _res("b.las", tags=["探井"]),
        _res("c.las", tags=["区域"]),
    ]
    idx.rebuild(assets)

    # AND: asset must carry every listed tag.
    assert idx.filter_query(FilterQuery(tags=["重点井", "探井"], tag_operator="and")) == [0]
    assert idx.filter_query(FilterQuery(tags=["探井", "不存在"], tag_operator="and")) == []
    # OR: any listed tag.
    assert idx.filter_query(FilterQuery(tags=["重点井", "区域"], tag_operator="or")) == [0, 2]
    assert idx.filter_query(FilterQuery(tags=["不存在"], tag_operator="or")) == []


def test_filter_query_tags_combine_with_stage_and_keyword():
    idx = FilterIndex()
    assets = [
        _res("a.las", tags=["重点"], role="input"),
        _res("b.las", tags=["重点"], role="derived"),
        _res("c.las", tags=["普通"], role="input"),
    ]
    idx.rebuild(assets)

    query = FilterQuery(
        node_type="stage", node_value=DataStage.RAW.value, tags=["重点"]
    )
    assert idx.filter_query(query) == [0]

    query = FilterQuery(tags=["重点"], search_text="b")
    assert idx.filter_query(query) == [1]

    query = FilterQuery(
        node_type="stage", node_value=DataStage.DERIVED.value,
        tags=["重点", "普通"], tag_operator="or", search_text="zzz-no-match",
    )
    assert idx.filter_query(query) == []


def test_filter_query_singular_tag_still_supported_and_unions_into_tags():
    idx = FilterIndex()
    assets = [
        _res("a.las", tags=["重点井", "探井"]),
        _res("b.las", tags=["探井"]),
    ]
    idx.rebuild(assets)

    # Legacy singular field on its own.
    assert idx.filter_query(FilterQuery(tag="探井")) == [0, 1]
    # Singular tag is unioned into the tags list for AND judgement.
    assert idx.filter_query(FilterQuery(tag="重点井", tags=["探井"])) == [0]
    assert idx.filter_query(FilterQuery(tag="重点井", tags=["探井"], tag_operator="or")) == [0, 1]


def test_tag_normalization_collapses_whitespace_and_case():
    idx = FilterIndex()
    idx.rebuild([_res("a.las", tags=["A B"])])

    assert idx.filter_query(FilterQuery(tags=["a  b"])) == [0]  # double space folds
    assert idx.filter_query(FilterQuery(tag="a b")) == [0]
    assert idx.filter_query(FilterQuery(node_type="tag", node_value="A  B")) == [0]
    assert idx.filter_query(FilterQuery(node_type="tag", node_value="a-b")) == []


def test_navigation_tag_node_matches_catalog_normalized_names():
    idx = FilterIndex()
    idx.rebuild([_res("a.las", tags=["Sand Box"])])
    # NavigationTree tag leaves carry display names; matching is normalized.
    assert idx.filter_query(FilterQuery(node_type="tag", node_value="sand  box")) == [0]


# --- F1: toolbar tag filter panel pipeline -----------------------------------------


def test_tag_filter_panel_signal_filters_asset_table(qtbot):
    page = DataPage(project=ProjectDocument.new("Tags UI"))
    qtbot.addWidget(page)
    res_a = _res("a.las", tags=["重点井"])
    res_b = _res("b.las", tags=["探井"])
    page.project.resources.extend([res_a, res_b])
    page._refresh()
    assert page.asset_table.visible_asset_count() == 2

    page.data_toolbar.set_tag_candidates(["重点井", "探井"])
    assert page.data_toolbar.tag_candidates() == sorted(["重点井", "探井"])

    # Select one tag (AND default).
    page.data_toolbar._on_tag_toggled("重点井", True)
    assert page.asset_table.visible_asset_count() == 1
    assert page.asset_table.asset_at(0).name == "a.las"

    # AND with a second tag the asset lacks → no rows.
    page.data_toolbar._on_tag_toggled("探井", True)
    assert page.asset_table.visible_asset_count() == 0

    # Switching to OR matches either tag.
    page.data_toolbar._on_operator_changed("or", True)
    assert page.asset_table.visible_asset_count() == 2

    # Clearing restores the unfiltered view.
    page.data_toolbar.clear_tag_filter()
    assert page.asset_table.visible_asset_count() == 2
    assert page.data_toolbar.current_tag_selection() == []
    assert page.data_toolbar.current_tag_operator() == "or"


def test_tag_filter_menu_builds_checkable_actions(qtbot):
    toolbar = dp.DataToolbar()
    qtbot.addWidget(toolbar)
    toolbar.set_tag_candidates(["t1", "t2"])
    toolbar._rebuild_tag_filter_menu()
    texts = [a.text() for a in toolbar._tag_filter_menu.actions()]
    assert "t1" in texts and "t2" in texts
    assert any("AND" in t for t in texts) and any("OR" in t for t in texts)
    assert any("清除" in t for t in texts)


def test_tag_filter_menu_empty_candidates_hint(qtbot):
    toolbar = dp.DataToolbar()
    qtbot.addWidget(toolbar)
    toolbar._rebuild_tag_filter_menu()
    assert toolbar._tag_filter_menu.actions()[0].isEnabled() is False


# --- F5: default columns -----------------------------------------------------------


def test_default_column_keys_include_lineage():
    assert DEFAULT_COLUMN_KEYS == [
        "name", "type", "stage", "version", "lineage", "tags", "integrity", "modified",
    ]
    assert [COLUMN_BY_KEY[k].label for k in DEFAULT_COLUMN_KEYS] == [
        "文件名", "类型", "生命周期", "版本", "血缘", "标签", "完整性", "修改时间",
    ]


# --- F4: project_root resolution ----------------------------------------------------


def test_asset_table_project_root_avoids_missing_false_positive(qtbot, tmp_path):
    payload = tmp_path / "data" / "rel.las"
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(b"relative")
    res = ResourceItem(
        name="rel.las", path="data/rel.las", type="well_log", format="las"
    )

    with_root = DataAssetTable()
    qtbot.addWidget(with_root)
    with_root.update_assets([res], [], project_root=tmp_path)
    assert with_root.view_at(0).integrity_state != IntegrityState.MISSING

    without_root = DataAssetTable()
    qtbot.addWidget(without_root)
    without_root.update_assets([res], [])
    assert without_root.view_at(0).integrity_state == IntegrityState.MISSING


def test_asset_table_project_root_forwarded_to_model_and_index(qtbot, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.las").write_bytes(b"x")
    res = ResourceItem(name="x.las", path="data/x.las", type="well_log", format="las")
    table = DataAssetTable()
    qtbot.addWidget(table)
    table.update_assets([res], [], project_root=tmp_path)
    assert table.model._project_root == tmp_path
    # FilterIndex views resolved against the same root.
    assert table.view_at(0).integrity_state != IntegrityState.MISSING


def test_navigation_tree_counts_resolve_project_relative_paths(qtbot, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "y.las").write_bytes(b"y")
    res = ResourceItem(name="y.las", path="data/y.las", type="well_log", format="las")

    from paleo_workbench.ui.pages.navigation_tree import NavigationTree

    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([res], [], project_root=tmp_path)
    missing = tree.find_category_item("❌ 缺失")
    assert missing.text(0).rsplit(" ", 1)[-1] == "0"

    tree2 = NavigationTree()
    qtbot.addWidget(tree2)
    tree2.update_counts([res], [])
    missing2 = tree2.find_category_item("❌ 缺失")
    assert missing2.text(0).rsplit(" ", 1)[-1] == "1"


# --- F2: TagManagerDialog ------------------------------------------------------------


def test_tag_manager_renders_usage_table(qtbot, tmp_path, catalog):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)

    assert dlg.hint_label.isHidden() is True  # hidden while a catalog is wired
    assert dlg.table.columnCount() == 3
    assert dlg.table.rowCount() == 4  # 重点井 / 版本标 / 探井 / unused

    def row_for(tag: str) -> int:
        for r in range(dlg.table.rowCount()):
            if dlg.table.item(r, 0).text() == tag:
                return r
        raise AssertionError(f"tag {tag} not rendered")

    r = row_for("重点井")
    assert dlg.table.item(r, 1).text() == "1"  # asset usage
    assert dlg.table.item(r, 2).text() == "0"  # version usage
    rv = row_for("版本标")
    assert dlg.table.item(rv, 1).text() == "0"
    assert dlg.table.item(rv, 2).text() == "1"


def test_tag_manager_search_filters_table(qtbot, tmp_path, catalog):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)
    dlg.search_input.setText("重点")
    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 0).text() == "重点井"


def test_tag_manager_without_catalog_disables_operations(qtbot):
    dlg = TagManagerDialog(service_provider=lambda: None)
    qtbot.addWidget(dlg)
    assert dlg.hint_label.isHidden() is False  # visible once shown
    assert dlg.table.rowCount() == 0
    assert dlg.create_btn.isEnabled() is False
    assert dlg.prune_btn.isEnabled() is False


class _FakeTagInput:
    """Replaces TagInputDialog inside tag_widgets for scripted flows."""
    next_name = "新名"

    def __init__(self, existing_tags=None, parent=None):
        self.label = type("L", (), {"setText": lambda self, t: None})()

    def setWindowTitle(self, _title):
        pass

    def exec(self):  # noqa: A003 - Qt API name
        return QDialog.DialogCode.Accepted

    def get_tag_name(self) -> str:
        return type(self).next_name


class _FakeMessageBox:
    # Attributes referenced by the production call sites.
    StandardButton = type(
        "StandardButton", (), {"Yes": 0x4000, "No": 0x10000}
    )
    calls: list[tuple[str, str]] = []
    question_answer = StandardButton.Yes

    @classmethod
    def question(cls, parent, title, text, *args, **kwargs):
        cls.calls.append(("question", title))
        return cls.question_answer

    @classmethod
    def information(cls, parent, title, text, *args, **kwargs):
        cls.calls.append(("information", title))
        return QDialog.DialogCode.Accepted

    @classmethod
    def critical(cls, parent, title, text, *args, **kwargs):
        cls.calls.append(("critical", title))
        return QDialog.DialogCode.Accepted

    @classmethod
    def warning(cls, parent, title, text, *args, **kwargs):
        cls.calls.append(("warning", title))
        return QDialog.DialogCode.Accepted


def test_tag_manager_rename_collision_merge_confirmed(qtbot, tmp_path, catalog, monkeypatch):
    resource = _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)

    # Select 重点井 and rename it onto the existing 探井 → collision → merge.
    row = next(
        r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).text() == "重点井"
    )
    dlg.table.selectRow(row)
    _FakeTagInput.next_name = "探井"
    _FakeMessageBox.calls = []
    monkeypatch.setattr(tw, "TagInputDialog", _FakeTagInput)
    monkeypatch.setattr(tw, "QMessageBox", _FakeMessageBox)

    dlg._on_rename()

    assert ("question", "标签冲突") in _FakeMessageBox.calls
    # Merge semantics: associations re-pointed at 探井, source dropped.
    assert catalog.find_assets_by_tag("探井") == [resource.id]
    names = {t.name for t in catalog.list_tags()}
    assert "重点井" not in names
    assert "探井" in names


def test_tag_manager_rename_collision_declined_keeps_tags(qtbot, tmp_path, catalog, monkeypatch):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)

    row = next(
        r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).text() == "探井"
    )
    dlg.table.selectRow(row)
    _FakeTagInput.next_name = "重点井"
    _FakeMessageBox.calls = []
    _FakeMessageBox.question_answer = _FakeMessageBox.StandardButton.No  # "No"
    monkeypatch.setattr(tw, "TagInputDialog", _FakeTagInput)
    monkeypatch.setattr(tw, "QMessageBox", _FakeMessageBox)

    dlg._on_rename()

    names = {t.name for t in catalog.list_tags()}
    assert names == {"重点井", "探井", "unused", "版本标"}
    _FakeMessageBox.question_answer = _FakeMessageBox.StandardButton.Yes


def test_tag_manager_delete_unused_refused_when_in_use(qtbot, tmp_path, catalog, monkeypatch):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)

    row = next(
        r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).text() == "重点井"
    )
    dlg.table.selectRow(row)
    _FakeMessageBox.calls = []
    monkeypatch.setattr(tw, "QMessageBox", _FakeMessageBox)

    dlg._on_delete_unused()

    # Refused with a usage-count prompt; tag untouched.
    assert ("information", "标签在使用中") in _FakeMessageBox.calls
    assert "重点井" in {t.name for t in catalog.list_tags()}


def test_tag_manager_delete_unused_succeeds_for_zero_usage(qtbot, tmp_path, catalog):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)

    row = next(
        r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).text() == "unused"
    )
    dlg.table.selectRow(row)
    assert dlg.delete_btn.isEnabled() is True

    dlg._on_delete_unused()

    assert "unused" not in {t.name for t in catalog.list_tags()}
    assert dlg.table.rowCount() == 3


def test_tag_manager_prune_removes_all_unused(qtbot, tmp_path, catalog, monkeypatch):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)
    _FakeMessageBox.calls = []
    monkeypatch.setattr(tw, "QMessageBox", _FakeMessageBox)

    dlg._on_prune_unused()

    assert ("question", "清理全部无用标签") in _FakeMessageBox.calls
    remaining = {t.name for t in catalog.list_tags()}
    assert remaining == {"重点井", "版本标"}  # 探井 + unused pruned
    assert dlg.table.rowCount() == 2


def test_tag_manager_merge_via_target_choice(qtbot, tmp_path, catalog, monkeypatch):
    resource = _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)

    row = next(
        r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).text() == "重点井"
    )
    dlg.table.selectRow(row)

    def fake_get_item(parent, title, label, items, *args, **kwargs):
        assert "重点井" in label
        assert "探井" in items
        return "探井", True

    monkeypatch.setattr(tw.QInputDialog, "getItem", staticmethod(fake_get_item))
    dlg._on_merge()

    assert catalog.find_assets_by_tag("探井") == [resource.id]
    assert "重点井" not in {t.name for t in catalog.list_tags()}


def test_tag_manager_double_click_emits_tag_selected(qtbot, tmp_path, catalog):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)
    received: list[str] = []
    dlg.tag_selected.connect(received.append)

    row = next(
        r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 0).text() == "重点井"
    )
    dlg.table.cellDoubleClicked.emit(row, 0)

    assert received == ["重点井"]


def test_tag_manager_create_adds_tag(qtbot, tmp_path, catalog, monkeypatch):
    _seed_catalog(catalog, tmp_path)
    dlg = TagManagerDialog(service_provider=lambda: catalog)
    qtbot.addWidget(dlg)
    _FakeTagInput.next_name = "新标签"
    monkeypatch.setattr(tw, "TagInputDialog", _FakeTagInput)

    changed: list[bool] = []
    dlg.tags_changed.connect(lambda: changed.append(True))
    dlg._on_create()

    assert "新标签" in {t.name for t in catalog.list_tags()}
    assert changed == [True]


# --- F2: Tag Manager entry wiring ----------------------------------------------------


def test_toolbar_tag_manager_button_emits_signal(qtbot):
    toolbar = dp.DataToolbar()
    qtbot.addWidget(toolbar)
    assert toolbar.tag_manager_btn.text() == "标签管理"
    received: list[bool] = []
    toolbar.tag_manager_requested.connect(lambda: received.append(True))
    toolbar.tag_manager_btn.click()
    assert received == [True]


def test_navigation_tree_manage_tags_signal_wired_to_page(qtbot, monkeypatch):
    page = DataPage(project=ProjectDocument.new("Entry"))
    qtbot.addWidget(page)
    opened: list[bool] = []
    monkeypatch.setattr(page, "_open_tag_manager", lambda: opened.append(True))
    page.navigation_tree.manage_tags_requested.emit()
    assert opened == [True]


def test_data_page_open_tag_manager_filters_on_tag_selected(qtbot, monkeypatch):
    page = DataPage(project=ProjectDocument.new("Manager"))
    qtbot.addWidget(page)
    res_a = _res("a.las", tags=["重点井"])
    res_b = _res("b.las", tags=["探井"])
    page.project.resources.extend([res_a, res_b])
    page._refresh()

    class FakeManager(QObject):
        tag_selected = Signal(str)
        tags_changed = Signal()
        instances: list["FakeManager"] = []

        def __init__(self, service_provider=None, parent=None):
            super().__init__()
            FakeManager.instances.append(self)

        def exec(self):  # noqa: A003 - Qt API name
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(dp, "TagManagerDialog", FakeManager)
    page._open_tag_manager()
    dlg = FakeManager.instances[-1]

    dlg.tag_selected.emit("重点井")
    assert page.asset_table.visible_asset_count() == 1
    assert page.asset_table.asset_at(0).name == "a.las"


# --- F3: bulk tag dialogs --------------------------------------------------------------


def test_parse_multi_tag_input():
    assert parse_multi_tag_input("a, b；c；d, d") == ["a", "b", "c", "d"]
    assert parse_multi_tag_input("#重点井, 探井;") == ["重点井", "探井"]
    assert parse_multi_tag_input("  , ;; ") == []
    assert parse_multi_tag_input("x\ny") == ["x", "y"]


def test_bulk_add_dialog_parses_input(qtbot):
    dlg = BulkAddTagDialog()
    qtbot.addWidget(dlg)
    dlg.input.setText("甲, 乙；丙")
    assert dlg.tag_names() == ["甲", "乙", "丙"]


def test_bulk_remove_dialog_checkbox_list(qtbot):
    dlg = BulkRemoveTagDialog(["探井", "重点井"])
    qtbot.addWidget(dlg)
    assert [cb.text() for cb in dlg.checkboxes] == ["探井", "重点井"]
    assert dlg.selected_tags() == []
    dlg.checkboxes[0].setChecked(True)
    assert dlg.selected_tags() == ["探井"]


class _FakeAddDialog:
    names: list[str] = ["甲", "乙"]

    def __init__(self, parent=None):
        pass

    def exec(self):  # noqa: A003 - Qt API name
        return QDialog.DialogCode.Accepted

    def tag_names(self) -> list[str]:
        return list(type(self).names)


class _FakeRemoveDialog:
    captured: dict = {}
    selected: list[str] = ["探井"]

    def __init__(self, candidate_tags=None, parent=None):
        type(self).captured["candidates"] = list(candidate_tags or [])

    def exec(self):  # noqa: A003 - Qt API name
        return QDialog.DialogCode.Accepted

    def selected_tags(self) -> list[str]:
        return list(type(self).selected)


def test_bulk_add_tag_calls_controller_per_tag(qtbot, monkeypatch):
    page = DataPage(project=ProjectDocument.new("Bulk"))
    qtbot.addWidget(page)
    res1 = _res("r1.las", tags=[])
    res2 = _res("r2.las", tags=[])
    page.project.resources.extend([res1, res2])
    page._refresh()

    calls: list[tuple[int, str, bool]] = []

    def fake_bulk(items, tag_name, *, add):
        calls.append((len(items), tag_name, add))
        return len(items)

    monkeypatch.setattr(page._lifecycle, "bulk_apply_tag", fake_bulk)
    monkeypatch.setattr(dp, "BulkAddTagDialog", _FakeAddDialog)

    page._prompt_add_tag_to_assets([res1, res2])

    assert calls == [(2, "甲", True), (2, "乙", True)]
    assert "已为 4 项数据添加 2 个标签" in page.data_toolbar.operation_status_label.text()


def test_bulk_remove_tag_candidates_from_union_and_calls_controller(qtbot, monkeypatch):
    page = DataPage(project=ProjectDocument.new("BulkR"))
    qtbot.addWidget(page)
    res1 = _res("r1.las", tags=["探井", "重点"])
    res2 = _res("r2.las", tags=["重点"])
    page.project.resources.extend([res1, res2])
    page._refresh()

    calls: list[tuple[int, str, bool]] = []

    def fake_bulk(items, tag_name, *, add):
        calls.append((len(items), tag_name, add))
        return len(items)

    monkeypatch.setattr(page._lifecycle, "bulk_apply_tag", fake_bulk)
    monkeypatch.setattr(dp, "BulkRemoveTagDialog", _FakeRemoveDialog)

    page._prompt_remove_tag_from_assets([res1, res2])

    # Checkbox list built from the selected assets' tag union (sorted).
    assert _FakeRemoveDialog.captured["candidates"] == sorted({"探井", "重点"})
    assert calls == [(2, "探井", False)]


def test_bulk_remove_tag_no_tags_reports_status(qtbot):
    page = DataPage(project=ProjectDocument.new("BulkEmpty"))
    qtbot.addWidget(page)
    res = _res("r.las", tags=[])
    page._prompt_remove_tag_from_assets([res])
    assert "无可用标签" in page.data_toolbar.operation_status_label.text()


def test_bulk_tag_legacy_fallback_without_controller_contract(qtbot, monkeypatch):
    """bulk_apply_tag missing (E not landed) → legacy per-resource loop."""
    page = DataPage(project=ProjectDocument.new("Fallback"))
    qtbot.addWidget(page)
    res1 = _res("f1.las", tags=[])
    res2 = _res("f2.las", tags=["既有"])
    page.project.resources.extend([res1, res2])
    page._refresh()

    monkeypatch.setattr(page._lifecycle, "bulk_apply_tag", None)
    _FakeAddDialog.names = ["新tag"]
    monkeypatch.setattr(dp, "BulkAddTagDialog", _FakeAddDialog)

    page._prompt_add_tag_to_assets([res1, res2])

    assert "新tag" in res1.tags
    assert "新tag" in res2.tags


# --- F6: Inspector version tags ----------------------------------------------------------


def _asset_view(versions: list[VersionView]) -> AssetView:
    return AssetView(
        id="res_1",
        name="well.las",
        type="well_log",
        type_label="测井",
        format="las",
        stage=DataStage.RAW,
        current_version=versions[0].version_id if versions else "v1",
        versions=versions,
        tags=["资产标签"],
        managed=True,
        integrity_state=IntegrityState.VERIFIED,
        checksum="abc",
        path="/well.las",
        size_bytes=10,
        size_formatted="10 B",
        created_at="—",
        modified_at="—",
        source="test",
        lineage=LineageView(),
    )


def test_inspector_versions_table_has_tag_column(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    view = _asset_view(
        [
            VersionView(version_id="ver_1", tags=["v1 标签"]),
            VersionView(version_id="ver_2", tags=[]),
        ]
    )
    panel.update_asset(view)

    assert panel.versions_table.columnCount() == 5
    assert panel.versions_table.horizontalHeaderItem(4).text() == "标签"
    assert panel.versions_table.item(0, 4).text() == "v1 标签"
    assert panel.versions_table.item(1, 4).text() == "—"


def test_inspector_version_tag_controls_gating(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    view = _asset_view([VersionView(version_id="ver_1", tags=["已有"])])
    panel.update_asset(view)

    # Disabled (no catalog) by default: hidden controls.
    assert panel.version_tags_enabled() is False
    assert panel.version_tags_bar.isVisible() is False

    panel.set_version_tags_enabled(True)
    assert panel.version_tags_enabled() is True
    # No version row selected yet → buttons disabled.
    assert panel.version_tag_add_btn.isEnabled() is False
    assert panel.version_tag_remove_btn.isEnabled() is False

    panel.versions_table.selectRow(0)
    assert panel.version_tag_add_btn.isEnabled() is True
    assert panel.version_tag_remove_btn.isEnabled() is True


class _FakeTagInput2:
    next_name = "版本新增"

    def __init__(self, existing_tags=None, parent=None):
        pass

    def setWindowTitle(self, _t):
        pass

    def exec(self):  # noqa: A003 - Qt API name
        return QDialog.DialogCode.Accepted

    def get_tag_name(self) -> str:
        return type(self).next_name


def test_inspector_version_tag_add_emits_signal(qtbot, monkeypatch):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    view = _asset_view([VersionView(version_id="ver_9", tags=[])])
    panel.update_asset(view)
    panel.set_version_tags_enabled(True)
    panel.versions_table.selectRow(0)

    received: list[tuple[str, str]] = []
    panel.version_tag_added.connect(lambda vid, name: received.append((vid, name)))
    monkeypatch.setattr(ip, "TagInputDialog", _FakeTagInput2)

    panel.version_tag_add_btn.click()

    assert received == [("ver_9", "版本新增")]


def test_inspector_version_tag_remove_emits_signal(qtbot, monkeypatch):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    view = _asset_view([VersionView(version_id="ver_9", tags=["要移除"])])
    panel.update_asset(view)
    panel.set_version_tags_enabled(True)
    panel.versions_table.selectRow(0)

    received: list[tuple[str, str]] = []
    panel.version_tag_removed.connect(lambda vid, name: received.append((vid, name)))

    class _FakeMenu:
        def __init__(self, parent=None):
            self._actions = []

        def addAction(self, label):
            self._actions.append(label)

        def exec(self, pos):  # noqa: A003 - Qt API name
            return type("A", (), {"text": lambda self: "要移除"})()

    monkeypatch.setattr(ip, "QMenu", _FakeMenu)
    panel.version_tag_remove_btn.click()

    assert received == [("ver_9", "要移除")]


def test_data_page_version_tag_wiring_calls_controller(qtbot, monkeypatch):
    page = DataPage(project=ProjectDocument.new("VTag"))
    qtbot.addWidget(page)
    calls: list[tuple[str, str, bool]] = []

    def fake_set(version_id, tag_name, *, add):
        calls.append((version_id, tag_name, add))
        return True

    monkeypatch.setattr(page._lifecycle, "set_version_tag", fake_set)

    page.inspector_panel.version_tag_added.emit("ver_a", "标签1")
    assert calls == [("ver_a", "标签1", True)]

    page.inspector_panel.version_tag_removed.emit("ver_b", "标签2")
    assert calls[-1] == ("ver_b", "标签2", False)
    assert "已从版本移除标签" in page.data_toolbar.operation_status_label.text()


def test_data_page_version_tags_disabled_without_catalog(qtbot):
    page = DataPage(project=ProjectDocument.new("NoCatalog"))
    qtbot.addWidget(page)
    res = _res("nc.las", tags=["t"])
    page._update_inspector(res)
    assert page.inspector_panel.version_tags_enabled() is False


def test_data_page_version_tags_enabled_for_bridged_asset(qtbot, tmp_path, catalog):
    resource = _seed_catalog(catalog, tmp_path)
    from paleo_workbench.catalog import CoreCatalogAdapter, set_catalog

    set_catalog(CoreCatalogAdapter(catalog))
    try:
        page = DataPage(project=ProjectDocument.new("Bridged"))
        qtbot.addWidget(page)
        page._update_inspector(resource)
        assert page.inspector_panel.version_tags_enabled() is True
        # Version rows enriched from the catalog expose version tags.
        view = page.inspector_panel._current_view
        assert any(v.tags == ["版本标"] for v in view.versions)
    finally:
        reset_catalog()


# --- F7: stage gating relaxation -------------------------------------------------------


def _res_with_role(role: str):
    return ResourceItem(
        name="x.las", path="/x.las", type="well_log", format="las",
        status="parsed", artifact_role=role,
    )


def test_menu_new_version_and_promote_on_derived_and_intermediate(qtbot):
    for role in ("derived", "intermediate"):
        menu = AssetContextMenu()
        menu.build(_res_with_role(role), viz_supported=False)
        new_ver = menu.find_action("ctx_new_version")
        promote = menu.find_action("ctx_promote")
        assert new_ver is not None and new_ver.isEnabled() is True, role
        assert promote is not None and promote.isEnabled() is True, role


def test_menu_raw_and_output_gates_unchanged(qtbot):
    raw_menu = AssetContextMenu()
    raw_menu.build(_res_with_role("input"), viz_supported=False)
    assert raw_menu.find_action("ctx_create_derived") is not None
    assert raw_menu.find_action("ctx_new_version") is None
    assert raw_menu.find_action("ctx_promote") is None

    out_menu = AssetContextMenu()
    out_menu.build(_res_with_role("export"), viz_supported=False)
    assert out_menu.find_action("ctx_export_open") is not None
    assert out_menu.find_action("ctx_new_version") is None
    assert out_menu.find_action("ctx_promote") is None
