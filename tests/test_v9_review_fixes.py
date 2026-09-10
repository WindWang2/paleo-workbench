"""V9 review 轮修复的回归测试（R1/R2 P0+P1）。

* R1-P0-1 / R2-P2-1：bool 编辑器不得把 "false" 翻转成 "true"；
* R2-P1-1：排序态差量刷新不得错行（禁排序更新 + 行映射重建）；
* R2-P1-2：拓扑计数跨会话不复活（会话身份入缓存）；
* R2-P1-3：split 触及非活动 polygon 层时该层计数也刷新；
* R1-P1-1：panel 发布路径未声明 CRS 不伪造 4326（panel_publish_crs）。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.crs_contract import panel_publish_crs
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


def _unclosed_feature(fid: str) -> VectorFeature:
    return VectorFeature(
        fid, {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]}, {})


# --------------------------------------------------------------------------- #
# R1-P0-1：bool 编辑器初始值
# --------------------------------------------------------------------------- #

def test_bool_editor_opens_on_current_value(qtbot, controller=None):
    from PySide6.QtCore import QModelIndex, QAbstractItemModel
    from PySide6.QtWidgets import QComboBox, QWidget

    from paleo_workbench.ui.workstation.composite_attribute_table import (
        _FieldEditorDelegate,
    )

    delegate = _FieldEditorDelegate(lambda: ())
    parent = QWidget()
    qtbot.addWidget(parent)
    combo = QComboBox(parent)
    combo.addItems(["true", "false"])

    class _Idx:
        def data(self, *_args):
            return "false"

    delegate.setEditorData(combo, _Idx())
    assert combo.currentText() == "false"  # 打开在当前值上（不是硬编码 true）
    combo.setCurrentIndex(combo.findText("false"))
    delegate.setEditorData(combo, _Idx())
    assert combo.currentText() == "false"


# --------------------------------------------------------------------------- #
# R2-P1-1：排序态差量刷新
# --------------------------------------------------------------------------- #

@pytest.fixture()
def controller(qtbot):
    return CompositeEditController(project_crs="EPSG:4326")


def test_delta_refresh_survives_sorted_column(controller, qtbot):
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    layer = controller.create_layer("L", "line")
    session = controller.ensure_layer_session(layer.id)[0]
    for i in range(4):
        session.add_feature(
            VectorFeature(
                f"f{i}",
                {"type": "LineString", "coordinates": [[float(i), 0], [float(i), 1]]},
                {"depth": float(10 + i * 10)},
            )
        )
    dialog = CompositeAttributeTableDialog(controller, layer.id)
    qtbot.addWidget(dialog)

    # 排序到 depth 列（降序）：f3(40) 顶行
    from PySide6.QtCore import Qt

    dialog.table.sortItems(1, Qt.SortOrder.DescendingOrder)  # fid 列排序即可触发
    # 差量更新两个要素的属性后，行内值与要素一一对应（不错行）
    session.change_attribute("f3", "depth", 5.0)
    session.change_attribute("f2", "depth", 35.0)
    dialog._on_content_changed(layer.id)
    # 找到每行 fid，校验其 depth 值
    by_fid = {}
    for row in range(dialog.table.rowCount()):
        fid_item = dialog.table.item(row, 0)
        depth_item = dialog.table.item(row, 1)
        if fid_item is None:
            continue
        # depth 列位置：schema 列从 1 起——找 fid 后第一列即 depth
        by_fid[str(fid_item.text())] = depth_item.data(Qt.ItemDataRole.DisplayRole)
    # depth 是 extra 属性（kind=text）——显示为字符串，数值语义按 float 比较
    assert float(by_fid["f3"]) == 5.0
    assert float(by_fid["f2"]) == 35.0
    assert float(by_fid["f1"]) == 20.0
    assert float(by_fid["f0"]) == 10.0


# --------------------------------------------------------------------------- #
# R2-P1-2：拓扑计数跨会话
# --------------------------------------------------------------------------- #

def test_topology_count_not_resurrected_for_new_session(controller, qtbot):
    layer = controller.create_layer("L", "polygon")
    session = controller.ensure_layer_session(layer.id)[0]
    session.add_feature(_unclosed_feature("f1"))
    assert controller._topology.refresh_error_count(layer) >= 1
    controller.rollback_edits()
    assert controller._topology.cached_error_count([layer]) == 0
    # 新会话（干净内容）不得继承旧计数——merge 门禁不假拦
    fresh = controller.ensure_layer_session(layer.id)[0]
    fresh.add_feature(
        VectorFeature(
            "g1",
            {"type": "Polygon",
             "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            {},
        )
    )
    assert controller._topology.cached_error_count([layer]) == 0


# --------------------------------------------------------------------------- #
# R2-P1-3：split 刷新触及层
# --------------------------------------------------------------------------- #

def test_split_refreshes_mutated_polygon_layer_counts(controller, qtbot):
    polygon_layer = controller.create_layer("P", "polygon")
    polygon_session = controller.ensure_layer_session(polygon_layer.id)[0]
    polygon_session.add_feature(
        VectorFeature(
            "p1",
            {"type": "Polygon",
             "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]},
            {},
        )
    )
    line_layer = controller.create_layer("C", "line")
    line_session = controller.ensure_layer_session(line_layer.id)[0]
    line_session.add_feature(
        VectorFeature(
            "c1",
            {"type": "LineString", "coordinates": [[2.0, -1.0], [2.0, 5.0]]},
            {},
        )
    )
    polygon_layer.set_selection(("p1",))
    line_layer.set_selection(("c1",))
    # 活动层 = 切割线层（典型场景：选完切割线就执行分割）
    controller.set_active_layer(line_layer.id)

    ok, message = controller.geometry_command("split")
    assert ok, message
    # split 触及的 polygon 层计数被刷新（缓存条目指向当前会话）
    entry = controller._topology._error_counts.get(polygon_layer.id)
    assert entry is not None and entry[3] is polygon_layer.edit_session
    assert controller._topology.cached_error_count(
        [polygon_layer, line_layer]) == 0  # 分割结果应有效


# --------------------------------------------------------------------------- #
# R1-P1-1：panel 发布不伪造 4326
# --------------------------------------------------------------------------- #

def test_panel_publish_crs_honest():
    assert panel_publish_crs("EPSG:4326") == "EPSG:4326"
    assert panel_publish_crs("") == ""       # 未声明 → 原坐标呈现，不伪造
    assert panel_publish_crs(None) == ""


def test_status_bar_shows_undeclared_not_fake_crs():
    """状态条 crs=controller.project_crs or "未声明" 的呈现契约（静态断言源码）。"""
    import inspect

    from paleo_workbench.ui.workstation import composite_document

    source = inspect.getsource(composite_document.CompositeDocument._sync_status_bar)
    assert 'or "EPSG:4326"' not in source
    assert "未声明" in source
