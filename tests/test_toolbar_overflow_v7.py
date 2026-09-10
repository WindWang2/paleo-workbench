"""V7 §6/§10：地图工具条宿主行布局（两行顶栏，画布无悬浮条）。

新布局语义（2026-09 两行布局）：
* 第 1 行：``WorkstationAppBarToolbar`` + ``MappingStageToolbar`` 同行；
* 第 2 行：两条地图工具条（核心组 / 扩展组 + 视图开关与面板菜单）；
* 画布上不再悬浮任何应用工具条；窄窗口溢出交给 Qt 原生工具条扩展按钮。
"""
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


def _window(qtbot, tmp_path):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    window.show()
    return window


def _toolbar_action_ids(bar) -> set:
    return {
        action.objectName().split(":", 1)[1]
        for action in bar.actions()
        if action.objectName().startswith("MapAction:")
    }


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


def test_action_enablement_survives_rehost(document):
    """动作使能求值仍工作（托管重构只改父级与布局，不改求值语义）。"""
    actions = document.action_controller.actions
    document._sync_action_state()
    assert not actions["toggle_editing"].isEnabled()
    layer = document.edit_controller.create_layer("测试", "point")
    # 显式置活动层（图层树重载回路可能清空新建层的隐式活动态）。
    document.edit_controller.set_active_layer(layer.id)
    document._sync_action_state()
    assert actions["toggle_editing"].isEnabled()
    assert not actions["toggle_editing"].isChecked()


def test_map_toolbars_cover_all_tool_groups(document):
    """两条宿主工具条覆盖全部 TOOL_GROUPS，无遗漏无重叠（孤立构造）。"""
    from PySide6.QtWidgets import QToolBar

    from paleo_workbench.mapping.tool_availability import TOOL_GROUPS

    top, bottom = document.host_map_toolbars()
    assert isinstance(top, QToolBar)
    assert isinstance(bottom, QToolBar)
    assert top.objectName() == "WorkstationMapToolsToolbarTop"
    assert bottom.objectName() == "WorkstationMapToolsToolbarBottom"
    # 孤立构造（无 shell 宿主）：条暂挂 document 名下，随其析构。
    assert top.parent() is document
    assert bottom.parent() is document
    assert document._toolbar_top_groups == (
        "navigate", "selection", "inspection", "edit_session",
        "capture", "geometry",
    )
    assert document._toolbar_bottom_groups == (
        "snapping", "layer", "symbology", "factor", "qa",
        "layout_export",
    )
    top_ids = _toolbar_action_ids(top)
    bottom_ids = _toolbar_action_ids(bottom)
    assert top_ids == {
        tool for group in document._toolbar_top_groups for tool in TOOL_GROUPS[group]
    }
    assert bottom_ids == {
        tool for group in document._toolbar_bottom_groups
        for tool in TOOL_GROUPS[group]
    }
    assert not (top_ids & bottom_ids)
    assert top_ids | bottom_ids == {
        tool for members in TOOL_GROUPS.values() for tool in members
    }
    for button in (
        document.well_track_button,
        document.seismic_section_button,
        document.link_button,
        document.panels_button,
    ):
        assert button.parentWidget() is bottom


def test_map_toolbars_host_chrome(document):
    """宿主行统一样式：不可移动/浮动、屏蔽右键菜单（与全局栏/阶段条对齐）。"""
    from PySide6.QtCore import Qt

    for bar in document.host_map_toolbars():
        assert not bar.isMovable()
        assert not bar.isFloatable()
        assert (
            bar.contextMenuPolicy()
            is Qt.ContextMenuPolicy.PreventContextMenu
        )


def test_host_rows_app_stage_row1_map_row2(qtbot, tmp_path):
    """宿主顶栏：第 1 行含全局栏与阶段条，第 2 行含两条地图工具条。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    window = _window(qtbot, tmp_path)
    ws = window.app_shell.workstation
    host = ws._dock_host
    # 构造期 restore 定时器可能先恢复出持久化几何：等它落定后再定尺寸，
    # 行归位后断言（旧 QSettings 存的是旧布局，归位逻辑必须收敛到新行）。
    qtbot.wait(200)
    window.resize(1440, 900)
    ws._enforce_toolbar_rows()
    QApplication.processEvents()
    QApplication.processEvents()

    app_bar, stage = ws.app_bar_toolbar, ws.stage_toolbar
    map_top, map_bottom = ws.composite.host_map_toolbars()
    for bar in (app_bar, stage, map_top, map_bottom):
        assert host.toolBarArea(bar) is Qt.ToolBarArea.TopToolBarArea
        assert not bar.isHidden()
    # 同行：y 相等；分行：行先后（几何断言，不依赖内部换行 API）。
    assert app_bar.y() == stage.y()
    assert map_top.y() == map_bottom.y()
    assert map_top.y() > app_bar.y()
    assert stage.x() > app_bar.x()
    assert map_bottom.x() > map_top.x()
    # 1440px 下完整可见：实际宽不被压进 hint 之下（无挤压/无原生溢出）。
    for bar in (app_bar, stage, map_top, map_bottom):
        assert bar.width() >= bar.sizeHint().width(), bar.objectName()


def test_canvas_has_no_overlay_toolbar(qtbot, tmp_path):
    """画布 subtree 内无应用工具条（QGIS 原生 CAD 停靠条 mToolbar 除外）。"""
    from PySide6.QtWidgets import QToolBar, QWidget

    window = _window(qtbot, tmp_path)
    ws = window.app_shell.workstation
    names = {
        bar.objectName()
        for bar in ws.composite.canvas.findChildren(QToolBar)
    }
    assert "WorkstationOverlayToolbar" not in names
    assert not (
        names
        & {"WorkstationMapToolsToolbarTop", "WorkstationMapToolsToolbarBottom"}
    )
    assert names <= {"mToolbar"}, f"画布上出现应用工具条: {names}"
    # 全窗无悬浮条残留（含 resize/布局时机闪现的游离实例）。
    assert window.findChildren(QWidget, "WorkstationOverlayToolbar") == []


def test_shell_rebuild_retires_old_toolbars(qtbot, tmp_path):
    """壳重建（工程切换）：旧顶栏退役改名，宿主上同名只剩本壳一条。

    回归：旧壳拆除只 remove/hide 不改名，C++ 对象在 deleteLater 落定前
    仍以原名存活，新壳 restoreState 按名复活旧条 → 同名双条挤占顶栏
    （真机：地图条跑到第 1 行左侧、App bar 被挤右）。
    """
    from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QToolBar

    from paleo_workbench.ui.workstation.shell import WorkstationFrame

    names = (
        "WorkstationAppBarToolbar",
        "MappingStageToolbar",
        "WorkstationMapToolsToolbarTop",
        "WorkstationMapToolsToolbarBottom",
    )
    host = QMainWindow()
    qtbot.addWidget(host)
    first = WorkstationFrame(_project(tmp_path), QStackedWidget(), dock_host=host)
    qtbot.addWidget(first)
    assert [bar.objectName() for bar in first._own_toolbar_rows()] == list(names)
    first.shutdown_workers()
    QApplication.processEvents()
    # 旧条全部改名退役：宿主上无原名残留，restoreState 按名查找必然落空。
    for name in names:
        assert host.findChildren(QToolBar, name) == [], name
    retired = [
        bar.objectName()
        for bar in host.findChildren(QToolBar)
        if bar.objectName().endswith("_retired")
    ]
    assert sorted(retired) == sorted(f"{name}_retired" for name in names)
    # 新壳建好后：同名各一条且都是本壳的条，无复活。
    second = WorkstationFrame(_project(tmp_path), QStackedWidget(), dock_host=host)
    qtbot.addWidget(second)
    QApplication.processEvents()
    own = set(second._own_toolbar_rows())
    for name in names:
        found = host.findChildren(QToolBar, name)
        assert len(found) == 1, (name, [str(b.objectName()) for b in found])
        assert found[0] in own, name


def _assert_no_orphan_separators(document) -> None:
    """可见分隔符两侧必须都是可见动作（首/尾/连续分隔符即孤儿）。"""
    for bar in document.host_map_toolbars():
        visible = [action for action in bar.actions() if action.isVisible()]
        for index, action in enumerate(visible):
            if not action.isSeparator():
                continue
            assert 0 < index < len(visible) - 1, (
                f"{bar.objectName()} 分隔符在首/尾成孤儿"
            )
            assert not visible[index - 1].isSeparator(), (
                f"{bar.objectName()} 连续分隔符成孤儿"
            )
            assert not visible[index + 1].isSeparator(), (
                f"{bar.objectName()} 连续分隔符成孤儿"
            )


def test_no_orphan_separators_without_active_layer(document):
    """无活动图层：隐藏组两侧分隔符同步隐藏，无孤立「|」条带。

    回归：求值器隐藏整组动作时 Qt 不联动分隔符，mapBottom 出现孤立
    分隔符（默认工程冷启动即无活动层，直接命中）。同步规则必须是
    不动点：连续调用两次结果一致（曾出现显隐震荡，单次调用恰好干净）。
    """
    document._sync_action_state()
    document._sync_action_state()
    actions = document.action_controller.actions
    assert not actions["layer_properties"].isVisible()
    _assert_no_orphan_separators(document)


def test_no_orphan_separators_with_active_layer(document):
    """有活动图层：全组可见时分隔符不变量同样成立（双向不断言反方向）。"""
    layer = document.edit_controller.create_layer("测试", "polygon")
    # 显式置活动层（图层树重载回路可能清空新建层的隐式活动态，
    # 与 test_action_enablement_survives_rehost 同一约定）。
    document.edit_controller.set_active_layer(layer.id)
    document._sync_action_state()
    document._sync_action_state()
    assert document.action_controller.actions["layer_properties"].isVisible()
    _assert_no_orphan_separators(document)
    # 非退化保证：全组可见时组间分隔符必须留一条（防「全藏」式修法）。
    bottom = document.host_map_toolbars()[1]
    assert any(
        action.isSeparator() and action.isVisible()
        for action in bottom.actions()
    )
