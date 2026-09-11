"""属性表差量刷新（workstation V6 Phase 5，baseline C-P0-3）。

三处 P0 热点（5k 要素下每次单元格编辑都全量重建，超出 <50ms 例行编辑
预算 10-30 倍）：

1. ``MappingPage._sync_attribute_table_from_authoring`` —— 修订前进即对
   全部要素跑 ``feature_to_record`` 并整体重灌要素下拉；
2. ``MapAttributeTable.set_layer_features`` —— 无条件 clear + N 次 addItem；
3. ``CompositeAttributeTableDialog.refresh`` —— ``content_changed`` 每次
   全量重建所有行 × 列的 QTableWidgetItem。

V6 差量语义：会话内单要素属性变更只更新受影响行 / 下拉条目；要素 id
集、schema/列、图层切换等结构变化仍走全量重建。断言差量性质（重建
调用数有界、不随要素数增长），不依赖墙钟。
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QSettings

import paleo_workbench.ui.pages.mapping_page as mapping_page_module
import paleo_workbench.ui.workstation.composite_attribute_table as composite_table_module
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.workstation.composite_attribute_table import (
    CompositeAttributeTableDialog,
)
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


@pytest.fixture(autouse=True)
def _hermetic_layout_store(monkeypatch, tmp_path):
    """与 test_mapping_page 相同的布局存储隔离：不触碰开发者真实设置。"""
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(
        mapping_page_module,
        "LayoutPersistence",
        lambda: LayoutPersistence(settings),
    )


class ComboSpy:
    """经 combo model 信号统计下拉重建：clear+重灌 = 批量行增删事件。"""

    def __init__(self, combo) -> None:
        self.inserts = 0
        self.removes = 0
        combo.model().rowsInserted.connect(lambda *args: self._bump("inserts"))
        combo.model().rowsRemoved.connect(lambda *args: self._bump("removes"))

    def _bump(self, name: str) -> None:
        setattr(self, name, getattr(self, name) + 1)


def _record(fid: str, name: str) -> dict:
    return {
        "id": fid,
        "kind": "facies",
        "name": name,
        "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
        "properties": {"facies_name": "浅湖"},
    }


def _facies_document(count: int, *, wells: int = 0, doc_id: str = "map-diff"):
    return PaleoMapDocument(
        id=doc_id,
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[
            {
                "id": f"f{i:05d}",
                "name": f"F{i:05d}",
                "coordinates": [[0, 0], [4, 0], [0, 4]],
            }
            for i in range(count)
        ],
        well_overlays=[
            {
                "id": f"w{i:05d}",
                "name": f"W{i:05d}",
                "coordinates": [float(i), float(i)],
            }
            for i in range(wells)
        ],
    )


def _polygon_feature(fid: str, name: str, facies: str = "三角洲") -> VectorFeature:
    return VectorFeature(
        feature_id=fid,
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
        },
        attributes={"facies": facies, "horizon": "H1", "name": name},
    )


def _composite_dialog(qtbot, feature_count: int):
    """已开始编辑会话的属性表（稳态：例行单元格编辑走差量路径）。"""
    controller = CompositeEditController()
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.import_layer_features(
        layer.id, [_polygon_feature(f"f{i:05d}", f"F{i:05d}") for i in range(feature_count)]
    )
    layer.start_editing()
    dialog = CompositeAttributeTableDialog(controller, layer.id)
    qtbot.addWidget(dialog)
    return controller, layer, dialog


def _column_of(dialog: CompositeAttributeTableDialog, header: str) -> int:
    for column in range(dialog.table.columnCount()):
        if dialog.table.horizontalHeaderItem(column).text() == header:
            return column
    raise AssertionError(f"column {header!r} not found")


def _row_of(dialog: CompositeAttributeTableDialog, fid: str) -> int:
    for row in range(dialog.table.rowCount()):
        item = dialog.table.item(row, 0)
        if item is not None and item.text() == fid:
            return row
    raise AssertionError(f"row {fid!r} not found")


# --- MapAttributeTable：下拉差量 ------------------------------------------------


def test_set_layer_features_same_id_set_updates_labels_without_combo_refill(qtbot):
    """id 集不变（纯属性编辑）时下拉不得 clear+重灌，只原地改标签。"""
    table = MapAttributeTable()
    qtbot.addWidget(table)
    records = [_record(f"f{i:05d}", f"F{i:05d}") for i in range(300)]
    table.set_layer_features(records, selected_ids={"f00007"})
    assert table.feature_combo.count() == 301  # placeholder + 300

    spy = ComboSpy(table.feature_combo)
    renamed = [dict(record) for record in records]
    renamed[150]["name"] = "renamed-150"
    table.set_layer_features(renamed, selected_ids={"f00007"})

    assert spy.inserts == 0, "id 集未变时下拉被整体重灌"
    assert spy.removes == 0, "id 集未变时下拉被清空"
    assert table.feature_combo.count() == 301
    index = table.feature_combo.findData("f00150")
    assert index >= 0
    assert table.feature_combo.itemText(index) == "renamed-150"
    assert table.feature_combo.currentData() == "f00007"
    assert table._layer_features["f00150"]["name"] == "renamed-150"


def test_set_layer_features_refills_combo_when_id_set_changes(qtbot):
    """要素 id 集变化（图层切换 / 增删要素）仍走全量重灌。"""
    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_layer_features([_record(f"a{i:05d}", f"A{i}") for i in range(50)])
    spy = ComboSpy(table.feature_combo)

    table.set_layer_features([_record(f"b{i:05d}", f"B{i}") for i in range(40)])

    assert spy.inserts > 0 and spy.removes > 0  # 全量重灌发生
    assert table.feature_combo.count() == 41  # placeholder + 40


def test_update_layer_features_touches_only_changed_records(qtbot):
    """宿主差量入口：只更新给定要素的绑定记录/下拉标签/属性格。"""
    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_layer_features(
        [_record(f"f{i:05d}", f"F{i:05d}") for i in range(400)],
        selected_ids={"f00007"},
    )
    spy = ComboSpy(table.feature_combo)

    table.update_layer_features(
        [_record("f00007", "renamed-7")], selected_ids={"f00007"}
    )

    assert spy.inserts == 0 and spy.removes == 0
    assert table.feature_combo.itemText(table.feature_combo.findData("f00007")) == "renamed-7"
    # 属性格跟随选中要素的新记录
    value_cells = [
        table.table.item(row, 1)
        for row in range(table.table.rowCount())
        if table.table.item(row, 0).text() == "name"
    ]
    assert value_cells and value_cells[0].text() == "renamed-7"
    # 未触及要素的绑定记录不被改动
    assert table._layer_features["f00123"]["name"] == "F00123"


# --- MappingPage：记录重建差量 --------------------------------------------------


def test_mapping_page_single_attribute_edit_rebuilds_only_one_record(qtbot, monkeypatch):
    """单要素属性编辑：feature_to_record 调用数 == 1，不随要素数增长。"""
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([_facies_document(250)])
    authoring = page._authoring_document
    authoring.active_layer.start_editing()
    # 会话开启后的一次全量同步（预热缓存基线）。
    page._sync_attribute_table_from_authoring()

    calls = {"n": 0}
    real = mapping_page_module.feature_to_record

    def counting(feature, *, kind):
        calls["n"] += 1
        return real(feature, kind=kind)

    monkeypatch.setattr(mapping_page_module, "feature_to_record", counting)
    spy = ComboSpy(page.attribute_table.feature_combo)

    page._on_property_changed("f00123", "name", "renamed-123")

    assert calls["n"] == 1, "单要素编辑不得重建全部要素记录"
    assert spy.inserts == 0 and spy.removes == 0
    index = page.attribute_table.feature_combo.findData("f00123")
    assert index >= 0
    assert page.attribute_table.feature_combo.itemText(index) == "renamed-123"
    assert page._attribute_table_records[2][123]["name"] == "renamed-123"
    # 编辑后的属性值真实进入权威会话
    session = authoring.active_layer.edit_session
    assert session.feature("f00123").attributes["name"] == "renamed-123"


def test_mapping_page_full_rebuild_on_layer_switch(qtbot, monkeypatch):
    """结构变化（切换活动图层）仍全量重建：每要素一次记录转换。"""
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([_facies_document(120, wells=30)])
    authoring = page._authoring_document
    authoring.set_active_kind("well")
    authoring.active_layer.start_editing()
    page._sync_attribute_table_from_authoring()

    calls = {"n": 0}
    real = mapping_page_module.feature_to_record

    def counting(feature, *, kind):
        calls["n"] += 1
        return real(feature, kind=kind)

    monkeypatch.setattr(mapping_page_module, "feature_to_record", counting)

    authoring.set_active_kind("facies")
    page._sync_attribute_table_from_authoring()

    assert calls["n"] == 120  # facies 图层全量重建
    assert page.attribute_table.feature_combo.count() == 121


# --- 综合编修属性表：行级差量 ----------------------------------------------------


@pytest.fixture
def item_factory(monkeypatch):
    """统计 QTableWidgetItem 创建数（全量重建的代理指标）。"""
    created = {"n": 0}
    real = composite_table_module.QTableWidgetItem

    class CountingItem(real):
        def __init__(self, *args):
            super().__init__(*args)
            created["n"] += 1

    monkeypatch.setattr(composite_table_module, "QTableWidgetItem", CountingItem)
    return created


def test_composite_single_attribute_change_updates_one_row_in_place(qtbot, item_factory):
    controller, layer, dialog = _composite_dialog(qtbot, 300)
    facies_column = _column_of(dialog, "相带类型")
    row = _row_of(dialog, "f00007")
    untouched = dialog.table.item(_row_of(dialog, "f00008"), facies_column).text()

    item_factory["n"] = 0  # 只统计编辑之后的创建
    layer.edit_session.change_attribute("f00007", "facies", "深湖")
    controller.content_changed.emit(layer.id)

    assert item_factory["n"] == 0, "单要素属性变更不得重建任何单元格 item"
    assert dialog.table.item(row, facies_column).text() == "深湖"
    assert dialog.table.item(_row_of(dialog, "f00008"), facies_column).text() == untouched
    assert dialog.table.rowCount() == 300
    # 权威数据一致
    assert layer.edit_session.feature("f00007").attributes["facies"] == "深湖"


def test_composite_differential_cost_is_independent_of_feature_count(qtbot, item_factory):
    """差量代价有界：一次编辑的 item 创建数与要素总数无关。"""
    counts = []
    for feature_count in (120, 480):
        controller, layer, dialog = _composite_dialog(qtbot, feature_count)
        facies_column = _column_of(dialog, "相带类型")
        item_factory["n"] = 0
        layer.edit_session.change_attribute("f00007", "facies", "深湖")
        controller.content_changed.emit(layer.id)
        assert dialog.table.item(_row_of(dialog, "f00007"), facies_column).text() == "深湖"
        counts.append(item_factory["n"])
        dialog.close()

    assert counts[0] == counts[1] == 0


def test_composite_full_rebuild_on_structure_changes(qtbot, item_factory):
    controller, layer, dialog = _composite_dialog(qtbot, 80)
    facies_column = _column_of(dialog, "相带类型")
    assert dialog.table.rowCount() == 80

    # 新增要素 → 行结构变化 → 全量重建
    item_factory["n"] = 0
    layer.edit_session.add_feature(_polygon_feature("brand-new", "New"))
    controller.content_changed.emit(layer.id)
    assert dialog.table.rowCount() == 81
    assert item_factory["n"] == 0  # virtual model: no QTableWidgetItem

    # 新属性字段 → 列结构变化 → 全量重建
    item_factory["n"] = 0
    layer.edit_session.change_attribute("f00007", "brand_new_key", "x")
    controller.content_changed.emit(layer.id)
    assert dialog.table.columnCount() > facies_column + 1
    assert item_factory["n"] == 0

    # 提交（保存编辑）→ 会话更替 → 全量重建
    item_factory["n"] = 0
    layer.edit_session.commit_changes()
    controller.content_changed.emit(layer.id)
    assert item_factory["n"] == 0
    assert dialog.table.rowCount() == 81


# --- 性能回归（宽时限 + 差量性质双断言）-------------------------------------------


def test_composite_single_edit_at_2000_features_under_bound(qtbot, item_factory):
    controller, layer, dialog = _composite_dialog(qtbot, 2000)
    facies_column = _column_of(dialog, "相带类型")

    item_factory["n"] = 0
    started = time.perf_counter()
    layer.edit_session.change_attribute("f01000", "facies", "深湖")
    controller.content_changed.emit(layer.id)
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"2000 要素下单要素编辑耗时 {elapsed:.3f}s"
    assert item_factory["n"] == 0  # 只有一行更新，零 item 重建
    assert dialog.table.item(_row_of(dialog, "f01000"), facies_column).text() == "深湖"


def test_mapping_page_single_edit_at_2000_features_under_bound(qtbot, monkeypatch):
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([_facies_document(2000, doc_id="map-perf")])
    authoring = page._authoring_document
    authoring.active_layer.start_editing()
    page._sync_attribute_table_from_authoring()  # 会话开启后的全量基线

    calls = {"n": 0}
    real = mapping_page_module.feature_to_record

    def counting(feature, *, kind):
        calls["n"] += 1
        return real(feature, kind=kind)

    monkeypatch.setattr(mapping_page_module, "feature_to_record", counting)
    spy = ComboSpy(page.attribute_table.feature_combo)

    started = time.perf_counter()
    authoring.active_layer.edit_session.change_attribute("f01500", "name", "renamed")
    page._sync_attribute_table_from_authoring()
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"2000 要素下单要素同步耗时 {elapsed:.3f}s"
    assert calls["n"] == 1
    assert spy.inserts == 0 and spy.removes == 0
    assert (
        page.attribute_table.feature_combo.itemText(
            page.attribute_table.feature_combo.findData("f01500")
        )
        == "renamed"
    )
