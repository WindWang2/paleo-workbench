"""V11 Model/View 迁移（MAP/VERSION 侧表面，goal §8 / 01-ui-audit D2）。

结构契约断言（不做墙钟断言）：

* MapAttributeTable 要素选择器：10 万要素图层下可见条目 ≤ _MAX_VISIBLE，
  不再存在“每要素一条”的 QComboBox（D2 ②）；
* CorrelationLinkEditor 顶点表：5 万行零 QTableWidgetItem（D2 ⑥）；
* VersionWorkbenchDialog 时间线：reload_versions 行内容变化时按版本 id
  恢复选择（StableSelection，D2 ④）；
* InspectorPanel 版本表：模型化 + 选择信号驱动版本标签控件（D2 ⑦）；
* MapLayerTree / MapDocumentPanel / MapReferencePanel：键差分重建保
  项身份与展开态（D2 ⑮）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QComboBox, QTableWidgetItem, QTableView

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.project.models import (
    MapReferenceLayer,
    PaleoMapDocument,
)
from paleo_workbench.ui.modelview.object_table import ObjectTableModel
from paleo_workbench.ui.pages.correlation_link_editor import CorrelationLinkEditor
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.map_attribute_table import (
    _MAX_VISIBLE,
    MapAttributeTable,
)
from paleo_workbench.ui.pages.map_document_panel import MapDocumentPanel
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.map_reference_panel import MapReferencePanel
from paleo_workbench.ui.pages.version_workbench_dialog import VersionWorkbenchDialog
from paleo_workbench.workflow.correlation_lifecycle import new_correlation_draft
from paleo_workbench.workflow.stratigraphy_models import FormationTop


# --- MapAttributeTable：有界要素选择器（D2 ②）--------------------------------


def _record(fid: str, name: str) -> dict:
    return {
        "id": fid,
        "kind": "facies",
        "name": name,
        "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
        "properties": {"facies_name": "浅湖"},
    }


def test_feature_selector_bounded_at_100k_features(qtbot):
    table = MapAttributeTable()
    qtbot.addWidget(table)
    records = [_record(f"f{i:06d}", f"F{i}") for i in range(100_000)]
    table.set_layer_features(records)

    # 结构性上限：占位行 + 至多 _MAX_VISIBLE 个匹配要素——任何时刻都不
    # 物化 10 万条下拉字符串。
    assert table.feature_combo.count() <= _MAX_VISIBLE + 1
    # 形态：每要素一条的 QComboBox 已不存在。
    assert table.findChildren(QComboBox) == []
    # 截断时计数脚注可见并提示总数。
    table.show()
    assert table._feature_count_label.isVisibleTo(table)
    assert "共 100000 个要素" in table._feature_count_label.text()
    assert f"显示前 {_MAX_VISIBLE}" in table._feature_count_label.text()


def test_feature_selector_search_narrows_and_surfaces_offwindow_feature(qtbot):
    table = MapAttributeTable()
    qtbot.addWidget(table)
    records = [_record(f"f{i:06d}", f"F{i}") for i in range(100_000)]
    table.set_layer_features(records)

    # 窗口外的要素（f099999）默认没有条目；输入过滤后回到窗口内。
    assert table.feature_combo.findData("f099999") < 0
    table.feature_search.setText("f099999")
    # V11（P1-1 搜索防抖 200ms）：等待过滤生效。
    qtbot.waitUntil(
        lambda: table.feature_combo.count() == 2, timeout=3000
    )
    assert table.feature_combo.count() == 2  # 占位行 + 唯一匹配
    assert table.feature_combo.findData("f099999") == 1
    assert table.feature_combo.itemText(1) == "F99999"
    assert not table._feature_count_label.isVisibleTo(table)


def test_feature_selector_selection_preserved_across_update_layer_features(qtbot):
    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_layer_features(
        [_record(f"f{i:05d}", f"F{i}") for i in range(300)],
        selected_ids={"f00042"},
    )
    assert table.feature_combo.currentData() == "f00042"

    table.update_layer_features(
        [_record("f00042", "renamed-42")], selected_ids={"f00042"}
    )

    # 同键差量：选择保持，选中要素置顶，标签原地刷新。
    assert table.feature_combo.currentData() == "f00042"
    assert table.feature_combo.findData("f00042") == 1
    assert table.feature_combo.itemText(1) == "renamed-42"
    assert table.table.item(
        next(
            row for row in range(table.table.rowCount())
            if table.table.item(row, 0).text() == "name"
        ),
        1,
    ).text() == "renamed-42"


def test_feature_selector_selection_signal_wiring(qtbot):
    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_layer_features([_record("f1", "W1"), _record("f2", "W2")])

    requested: list[str] = []
    table.feature_selection_requested.connect(requested.append)

    # 用户在列表里选中 f2 → 发出权威要素 id（宿主据此 set_feature）。
    table.feature_combo.setCurrentRow(table.feature_combo.findData("f2"))
    assert requested == ["f2"]
    table.feature_combo.setCurrentRow(0)  # 占位行 = 清选
    assert requested == ["f2", ""]


# --- CorrelationLinkEditor：5 万顶点零 item（D2 ⑥）---------------------------


@pytest.fixture
def counting_table_items(monkeypatch):
    """统计 QTableWidgetItem 构造数（全量重建的结构性代理指标）。"""
    created = {"n": 0}
    real = QTableWidgetItem

    class CountingItem(real):
        def __init__(self, *args):
            super().__init__(*args)
            created["n"] += 1

    monkeypatch.setattr("PySide6.QtWidgets.QTableWidgetItem", CountingItem)
    return created


def test_correlation_editor_50k_tops_are_model_rows_not_items(qtbot, counting_table_items):
    well_ids = [f"r{i:04d}" for i in range(500)]
    tops = [
        FormationTop(
            well_name=f"W{i % 500:04d}",
            well_id=well_ids[i % 500],
            marker=f"M{i // 500:04d}",
            depth=1000.0 + i,
        )
        for i in range(50_000)
    ]
    draft = new_correlation_draft(name="t", well_resource_ids=well_ids, tops=tops)

    editor = CorrelationLinkEditor(draft)
    qtbot.addWidget(editor)

    assert editor.top_table.rowCount() == 50_000
    assert isinstance(editor.top_table, QTableView)
    assert isinstance(editor.top_table.model(), ObjectTableModel)
    # 虚拟模型：5 万行 × 5 列 = 25 万个单元格，零 QTableWidgetItem。
    assert counting_table_items["n"] == 0
    # 首行内容按井/层位/深度排序可见（模型侧取值）。
    assert editor.top_table.model().data(editor.top_table.model().index(0, 0)) == "W0000"


def test_correlation_editor_selection_survives_rebuild(qtbot):
    tops = [
        FormationTop(well_name=f"W{i}", well_id=f"r{i}", marker="M1", depth=1000.0 + i)
        for i in range(3)
    ]
    draft = new_correlation_draft(name="t", well_resource_ids=["r0", "r1", "r2"], tops=tops)
    editor = CorrelationLinkEditor(draft)
    qtbot.addWidget(editor)

    editor.top_table.selectRow(1)
    assert editor._selected_top_id() == tops[1].id

    # 编辑顶点属性（同键集合）→ 整表 set_rows → 选择按顶点 id 恢复。
    tops[1].confidence = "高"
    editor._rebuild_tables()
    assert editor.top_table.currentRow() == 1
    assert editor._selected_top_id() == tops[1].id


# --- VersionWorkbenchDialog：reload 后按版本 id 恢复选择（D2 ④）---------------


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def catalog_service(tmp_path):
    from paleo_workbench.catalog.service import DataCatalogService

    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


def _asset_with_versions(service, tmp_path):
    v1 = service.import_raw(
        _source(tmp_path, "core.las", b"raw-bytes"),
        name="岩心数据",
        type="well_log",
        format="las",
    )
    v2 = service.register_version(
        v1.asset_id,
        _source(tmp_path, "filtered.csv", b"derived-bytes"),
        DataStage.DERIVED,
        parent_version_ids=[v1.id],
    )
    v3 = service.register_version(
        v1.asset_id,
        _source(tmp_path, "final.csv", b"output-bytes"),
        DataStage.OUTPUT,
        parent_version_ids=[v2.id],
    )
    return v1, v2, v3


def test_version_workbench_reload_preserves_selected_version_id(
    qtbot, catalog_service, tmp_path
):
    v1, v2, v3 = _asset_with_versions(catalog_service, tmp_path)
    dialog = VersionWorkbenchDialog(
        service_provider=lambda: catalog_service, asset_id=v1.asset_id
    )
    qtbot.addWidget(dialog)
    assert isinstance(dialog.versions_table, QTableView)
    assert isinstance(dialog.versions_table.model(), ObjectTableModel)

    # 时间线最新在前：v3 / v2 / v1 → 选中 v2（row 1）。
    dialog.versions_table.selectRow(1)
    assert dialog._single_selection().id == v2.id

    # 行内容变化（v3 入回收站，行仍可见）→ reload 后同一版本仍被选中。
    catalog_service.trash_version(v3.id, reason="test")
    dialog.reload_versions()
    assert dialog.versions_table.rowCount() == 3
    assert dialog._single_selection() is not None
    assert dialog._single_selection().id == v2.id
    assert dialog.versions_table.currentRow() == 1
    # 已删除行经前景 token 置灰（模型侧取色，非硬编码 gray）。
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor

    from paleo_workbench.ui import style

    stage_index = dialog.versions_table.model().index(0, 1)
    fg = dialog.versions_table.model().data(
        stage_index, Qt.ItemDataRole.ForegroundRole
    )
    assert isinstance(fg, QColor)
    assert fg == QColor(style.palette()["TEXT_SECONDARY"])


def test_version_workbench_reload_drops_selection_when_key_gone(
    qtbot, catalog_service, tmp_path
):
    v1, v2, v3 = _asset_with_versions(catalog_service, tmp_path)
    dialog = VersionWorkbenchDialog(
        service_provider=lambda: catalog_service, asset_id=v1.asset_id
    )
    qtbot.addWidget(dialog)
    dialog.versions_table.selectRow(0)
    selected_id = dialog._single_selection().id

    # 新增版本 → 键集变化 + 原选中仍在；删除当前选中版本所在行不可行
    #（版本不可物理删除），改用换资产：键全换 → 选择自然清空。
    other = catalog_service.import_raw(
        _source(tmp_path, "other.las", b"other"),
        name="其他资产",
        type="well_log",
        format="las",
    )
    assert selected_id
    dialog._asset_id = other.asset_id
    dialog.reload_versions()
    assert dialog._single_selection() is None


# --- InspectorPanel 版本表（D2 ⑦）---------------------------------------------


def _version_view(version_id: str, *, tags=None, is_current=False):
    from paleo_workbench.ui.pages.data_view_models import VersionView

    return VersionView(
        version_id=version_id,
        is_current=is_current,
        tags=list(tags or []),
    )


def _asset_view(versions):
    from paleo_workbench.ui.pages.data_view_models import (
        AssetView,
        IntegrityState,
        LineageView,
    )

    return AssetView(
        id="res_1",
        name="well.las",
        type="well_log",
        type_label="测井",
        format="las",
        stage=DataStage.RAW,
        current_version=versions[0].version_id if versions else "v1",
        versions=versions,
        tags=[],
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


def test_inspector_versions_table_is_model_based_with_signals(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(_asset_view([
        _version_view("ver_1", tags=["v1 标签"], is_current=True),
        _version_view("ver_2"),
    ]))

    table = panel.versions_table
    assert isinstance(table, QTableView)
    assert isinstance(table.model(), ObjectTableModel)
    assert table.rowCount() == 2
    assert table.columnCount() == 5
    assert table.horizontalHeaderItem(4).text() == "标签"
    assert table.item(0, 0).text() == "★ ver_1"
    assert table.item(0, 4).text() == "v1 标签"
    assert table.item(1, 4).text() == "—"

    # 选择信号驱动版本标签控件（选择 → _selected_version → 门控）。
    panel.set_version_tags_enabled(True)
    assert not panel.version_tag_add_btn.isEnabled()
    table.selectRow(1)
    assert panel._selected_version is not None
    assert panel._selected_version.version_id == "ver_2"
    assert panel.version_tag_add_btn.isEnabled()
    assert not panel.version_tag_remove_btn.isEnabled()  # ver_2 无标签


def test_inspector_versions_selection_preserved_across_refresh(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    view = _asset_view([_version_view("ver_1"), _version_view("ver_2")])
    panel.update_asset(view)
    panel.versions_table.selectRow(1)
    assert panel._selected_version.version_id == "ver_2"

    # 同资产刷新（如版本标签写回后的 update_asset 流）→ 同键恢复选择。
    panel.update_asset(_asset_view([
        _version_view("ver_1"),
        _version_view("ver_2", tags=["新标签"]),
    ]))
    assert panel.versions_table.currentRow() == 1
    assert panel._selected_version.version_id == "ver_2"
    assert panel.versions_table.item(1, 4).text() == "新标签"


# --- MapLayerTree / 面板 reconcile：身份与展开态（D2 ⑮）----------------------


def test_map_layer_tree_item_identity_and_expansion_preserved(qtbot):
    docs = [
        PaleoMapDocument(name="Map A", linked_target_horizon="H1"),
        PaleoMapDocument(name="Map B", linked_target_horizon="H2"),
    ]
    tree = MapLayerTree()
    qtbot.addWidget(tree)
    tree.set_documents(docs)
    tree.set_active_document(docs[0])

    root = tree.tree.topLevelItem(0)
    doc_a, doc_b = root.child(0), root.child(1)
    facies_before = doc_a.child(0)
    tree.tree.setCurrentItem(facies_before)

    # 同键重建（文档列表不变）：项身份 + 选中行 + 展开态原样保留。
    doc_b.setExpanded(True)
    doc_a.setExpanded(False)  # 用户手动收起活动文档
    tree.set_documents(docs)

    assert root.child(0) is doc_a  # 身份未变（未 clear+rebuild）
    assert root.child(1) is doc_b
    assert tree.tree.currentItem() is facies_before
    assert root.child(0).child(0) is facies_before
    assert not doc_a.isExpanded()  # 手动收起的状态未被重建吞掉
    assert doc_b.isExpanded()

    # 切换活动文档 → 图层子树迁移到新文档，回切后原键重新填充并展开。
    tree.set_active_document(docs[1])
    assert root.child(1).childCount() == 4
    tree.set_active_document(docs[0])
    assert root.child(0).childCount() == 4
    assert root.child(0).isExpanded()


def test_map_document_panel_list_item_identity_preserved(qtbot):
    panel = MapDocumentPanel()
    qtbot.addWidget(panel)
    docs = [
        PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2"),
        PaleoMapDocument(name="T1 Map", linked_target_horizon="T1"),
    ]
    panel.update_state(docs)
    first = panel.document_list.item(0)
    panel.document_list.setCurrentRow(1)

    # 同键刷新：项身份与选中保持，标签原地更新。
    docs[0].name = "ZJ2 Map (revised)"
    panel.update_state(docs)
    assert panel.document_list.item(0) is first
    assert panel.document_list.currentRow() == 1
    assert "ZJ2 Map (revised)" in panel.document_list.item(0).text()

    # 键集变化：消失键移除、新增键追加。
    panel.update_state([docs[1]])
    assert panel.document_list.count() == 1
    assert panel.document_list.item(0).text().startswith("T1 Map")


def test_map_reference_panel_list_item_identity_preserved(qtbot):
    panel = MapReferencePanel()
    qtbot.addWidget(panel)
    layer = MapReferenceLayer(
        id="ref_1",
        name="构造参考",
        source_path="/tmp/ref.geojson",
        source_kind="vector",
        source_crs="EPSG:4326",
        project_crs="EPSG:3857",
        status="ready",
    )
    panel.set_layers([layer])
    first = panel.layer_list.item(0)

    # 同键刷新：身份保持，状态标签/勾选态原地更新。
    layer.status = "offline"
    layer.error_message = "参考图源文件不可用"
    panel.set_layers([layer])
    assert panel.layer_list.item(0) is first
    assert "离线" in first.text()
    assert first.toolTip() == "参考图源文件不可用"
