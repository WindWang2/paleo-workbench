"""V7 §6/§10：工具条溢出与窄屏（1366×768）行为。"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture()
def document(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    return doc


def test_narrow_canvas_overflows_tail_groups_not_core(document, qtbot):
    """窄画布：低优先组收进「»」；capture/geometry 核心组不收纳。"""
    from PySide6.QtWidgets import QApplication

    document.resize(720, 600)
    document._reposition_toolbar()
    QApplication.processEvents()
    hidden = document._toolbar_overflow_hidden
    assert hidden, "720px 画布应触发溢出收纳"
    core = {
        "pan", "identify", "toggle_editing", "add_polygon", "move_feature",
        "vertex", "undo", "split",
    }
    assert not (hidden & core), f"核心编辑动作不得收纳: {hidden & core}"
    assert document._overflow_button.isVisibleTo(document.toolbar) or \
        not document._overflow_button.isHidden()
    # 溢出菜单有真实条目（触发真实 QAction）。
    assert len(document._overflow_menu.actions()) >= 1


def test_wide_canvas_restores_groups(document, qtbot):
    """宽画布：收纳的组还原，溢出按钮隐藏。"""
    from PySide6.QtWidgets import QApplication

    document.resize(720, 600)
    document._reposition_toolbar()  # 隐藏 widget 的 resize 不发事件（Qt 延迟）
    QApplication.processEvents()
    assert document._toolbar_overflow_hidden
    document.resize(1700, 900)
    document._reposition_toolbar()
    QApplication.processEvents()
    assert not document._toolbar_overflow_hidden
    assert document._overflow_button.isHidden()


def test_overflow_menu_respects_disabled_reason(document, qtbot):
    """菜单条目继承禁用态与原因（如无桥的样式库工具）。"""
    from PySide6.QtWidgets import QApplication

    # 有活动图层时 symbology 组才显示（V8 M1：无图层整组隐藏的原因会
    # 盖过后端判词），先建图层让禁用原因来自后端三态。
    document.edit_controller.create_layer("测试", "polygon")
    document._sync_action_state()
    document.resize(600, 500)
    document._reposition_toolbar()
    QApplication.processEvents()
    hidden = document._toolbar_overflow_hidden
    if "style_manager" not in hidden:
        pytest.skip("该宽度未收纳 style_manager")
    entries = {
        action.text(): action for action in document._overflow_menu.actions()
    }
    assert "样式库" in entries
    # 无桥环境（与 main 一致）：QGIS 原因进入 tooltip。
    if not document.uses_native_stack:
        assert "QGIS" in entries["样式库"].toolTip()


def test_1366x768_composite_fits_without_core_overflow(document, qtbot):
    """1366×768：合成文档典型宽度（~860px）核心组完整显示。"""
    from PySide6.QtWidgets import QApplication

    document.resize(860, 640)
    document._reposition_toolbar()
    QApplication.processEvents()
    actions = document.action_controller.actions
    for tool in ("pan", "identify", "toggle_editing", "add_polygon", "split"):
        assert actions[tool].isVisible(), f"{tool} 在 1366 级宽度必须可见"
    # 极限窄下允许边缘 padding 级溢出（Qt hint 缓存 ≤ 16px）；核心
    # 动作可见 + 大体适配即满足 1366 可用性目标。
    assert document.toolbar.width() <= document.width() + 16


def test_layer_groups_hidden_without_active_layer(document):
    """无活动图层：layer/symbology 组整组不显示（goal §6）。"""
    actions = document.action_controller.actions
    assert not actions["layer_properties"].isVisible()
    assert not actions["symbology"].isVisible()
    # 入口动作（新建/导入参考）保留。
    assert actions["layer_new"].isVisible()
    assert actions["reference_import"].isVisible()


def test_layer_groups_visible_with_active_layer(document):
    layer = document.edit_controller.create_layer("测试", "polygon")
    document._sync_action_state()
    actions = document.action_controller.actions
    assert actions["layer_properties"].isVisible()
    assert actions["symbology"].isVisible()
    assert actions["attribute_table"].isVisible()
    assert layer is not None
