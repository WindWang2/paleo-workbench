"""Workstation V3 lifecycle / layout persistence regressions (#1120–#1127).

Offscreen coverage for the fragile polish paths called out in issue #1127:
linked map shutdown, responsive inspector persistence, layout flush ordering,
teardown re-scheduling, docked title-bar drag, float min-size, linked restore
gate and project-save edit-session flush.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QStackedWidget

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.shell import WorkstationFrame


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    project.resources.extend(
        [
            ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las"),
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
        ]
    )
    project.stratigraphy.target_horizon = "D63"
    return project


@pytest.fixture()
def workstation(qtbot, tmp_path):
    """WorkstationFrame with a per-test QSettings ini (hermetic layout state)."""
    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    frame._settings = QSettings(str(tmp_path / "workstation.ini"), QSettings.Format.IniFormat)
    frame._settings.clear()
    yield frame
    # orderly 关闭：镜像图层只随显式 shutdown 离开共享 QgsProject（与
    # 宿主契约一致），否则泄漏进后续用例的画布。
    frame.composite.shutdown()


# --- #1120: linked workspace map canvas shutdown -----------------------------


def test_linked_shutdown_stops_panels(qtbot, tmp_path):
    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    linked = frame.linked_workspace

    calls: list[str] = []

    class _FakeSeismic:
        def shutdown(self) -> None:
            calls.append("seismic")

    class _FakeWell:
        def shutdown(self) -> None:
            calls.append("well")

    linked.seismic_panel = _FakeSeismic()
    linked.well_panel = _FakeWell()

    assert linked.shutdown_workers() is True
    # seismic/well 同批 teardown，不能遗漏（平面图窗格已随编图核心化删除）。
    assert set(calls) == {"seismic", "well"}


def test_workarea_map_widget_shutdown_stops_canvas(qtbot):
    from paleo_workbench.ui.pages.workarea_map_widget import WorkAreaMapWidget

    widget = WorkAreaMapWidget(show_legend=False)
    qtbot.addWidget(widget)
    stopped: list[bool] = []
    original = widget.map_canvas.shutdown
    widget.map_canvas.shutdown = lambda: stopped.append(True)
    try:
        widget.shutdown()
    finally:
        widget.map_canvas.shutdown = original
    assert stopped == [True]


def test_workarea_map_click_survives_degenerate_extent(qtbot):
    """#1166: 退化 extent 的 map_to_screen 故障（含 ZeroDivisionError，
    属 ArithmeticError）不得从点击路径漏出。"""
    from paleo_workbench.ui.pages.workarea_map_widget import WorkAreaMapWidget

    widget = WorkAreaMapWidget(show_legend=False)
    qtbot.addWidget(widget)
    widget._snapshot = None
    widget._on_map_clicked((1.0, 2.0))  # 无快照直接返回
    from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot

    widget._snapshot = MapRenderSnapshot(project_crs="EPSG:4326", layers=())

    def _boom(_point):
        raise ZeroDivisionError("degenerate extent")

    widget.map_canvas.map_to_screen = _boom
    widget._on_map_clicked((1.0, 2.0))  # 不得抛出


# --- #1121: responsive inspector persistence ---------------------------------


def test_responsive_hide_is_not_persisted_as_user_layout(qtbot, workstation):
    workstation.resize(1180, 720)
    workstation.show()
    qtbot.waitExposed(workstation)
    # 窄屏：响应式隐藏检查器。
    workstation._apply_responsive_panels()
    assert workstation.inspector_dock.isHidden()
    assert workstation._responsive_hid_inspector

    workstation._save_layout(force=True)
    assert workstation._settings.value("layout/window_state") is not None

    # 模拟宽屏冷启动：restore 后检查器可见（blob 记录的是「可见」）。
    workstation.resize(1600, 900)
    workstation.inspector_dock.show()
    workstation._restore_layout()
    assert not workstation.inspector_dock.isHidden()


def test_restore_reapplies_responsive_policy_on_narrow_width(qtbot, workstation):
    """restore 之后必须再跑响应式：restoreState 不得在窄屏反杀自动隐藏。"""
    workstation.resize(1180, 720)
    workstation.show()
    qtbot.waitExposed(workstation)
    workstation._apply_responsive_panels()
    assert workstation.inspector_dock.isHidden()

    # restore 把检查器显示回来（blob 记录可见），随后响应式再次隐藏。
    workstation.inspector_dock.show()
    workstation._restore_layout()
    assert workstation.inspector_dock.isHidden()
    assert workstation._responsive_hid_inspector


def test_user_hide_flag_persists(qtbot, workstation):
    workstation.resize(1600, 900)  # 宽屏：排除响应式自动隐藏的干扰
    workstation.show()
    qtbot.waitExposed(workstation)
    assert not workstation.inspector_dock.isHidden()
    workstation.toggle_inspector()
    assert workstation.inspector_dock.isHidden()
    assert workstation._settings.value(
        "layout/inspector_user_hidden", False, type=bool
    ) is True


# --- #1123: float min-size only while floating -------------------------------


def test_dock_minimum_size_follows_floating_state(qtbot, workstation):
    dock = workstation.nav_dock
    assert not dock.isFloating()
    assert dock.minimumSize().width() == 0  # docked: 无强制 220px 底宽

    dock.setFloating(True)
    assert dock.minimumSize().width() >= 220
    assert dock.minimumSize().height() >= 160

    dock.setFloating(False)
    assert dock.minimumSize().width() == 0


# --- #1124: layout flush before hide; teardown must not reschedule ------------


def test_flush_layout_writes_after_hide(qtbot, workstation):
    workstation.show()
    qtbot.waitExposed(workstation)
    workstation.agent_dock.setFloating(True)
    workstation.hide()
    # hide 之后常规保存路径是 no-op；flush_layout 必须仍然落盘。
    workstation._save_layout()
    assert workstation._settings.value("layout/window_state") is None
    workstation.flush_layout()
    assert workstation._settings.value("layout/window_state") is not None


def test_teardown_freezes_state_save(qtbot, workstation):
    workstation.show()
    qtbot.waitExposed(workstation)
    workstation.shutdown_workers()
    assert workstation._layout_frozen is True
    # teardown 后任何迟到的 visibilityChanged 不得再启动保存定时器。
    workstation._schedule_state_save()
    assert workstation._save_timer.isActive() is False


def test_refresh_shell_flushes_layout_before_hide(qtbot, tmp_path, monkeypatch):
    """app._refresh_shell 必须先 flush 布局再 hide（#1124 数据路径）。"""
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    order: list[str] = []
    workstation = window.app_shell.workstation
    monkeypatch.setattr(workstation, "flush_layout", lambda: order.append("flush"))
    original_hide = window.app_shell.hide

    def _hide():
        order.append("hide")
        original_hide()

    monkeypatch.setattr(window.app_shell, "hide", _hide)
    window._refresh_shell()
    assert order.index("flush") < order.index("hide")


# --- #1125: linked restore gate ------------------------------------------------

# NOTE（编图核心化 Task 3）：嵌套 dock_area 与默认分屏比例已随平面图窗格删除；
# 宿主 QMainWindow.saveState/restoreState 覆盖全部宿主 dock，以下两例失效删除。


# --- #1126: project save flushes composite edit sessions ----------------------


def test_flush_composite_edits_commits_sessions(qtbot, tmp_path):
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.mapping.vector_layer import VectorFeature

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)

    composite = window.app_shell.workstation.composite
    controller = composite.edit_controller
    controller.create_layer("断层线", "line", template="fault")
    controller.start_editing()
    controller.active_layer.edit_session.add_feature(
        VectorFeature(
            "f-1",
            {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
        )
    )
    assert controller.editing

    committed = window._flush_composite_edits()
    assert committed == 1
    assert not controller.editing
    layers = window.project.user_vector_layers
    assert any(
        any(item.id == "f-1" for item in layer.features) for layer in layers
    ), "提交的数字化要素必须进入 project.user_vector_layers"


def test_save_project_calls_composite_flush(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.ui.project_controller import ProjectController

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    flushes: list[bool] = []
    monkeypatch.setattr(
        ProjectController,
        "_flush_composite_vector_edits",
        lambda self: flushes.append(True),
    )
    # 保存到磁盘的完整路径（无 path → save-as 对话框会阻塞：先绑 path）。
    target = tmp_path / "flush_check.paleo.json"
    monkeypatch.setattr(
        type(window),
        "project_path",
        property(lambda self: target),
    )
    window.project_controller.save_project()
    assert flushes == [True]
    assert target.exists()


# --- #1128: activity history focus --------------------------------------------


def test_activity_history_does_not_open_agent_log_dock(qtbot, workstation):
    workstation.show()
    qtbot.waitExposed(workstation)
    workstation.logs_dock.hide()
    workstation.agent_dock.hide()
    workstation._on_activity_mode("history")
    assert workstation.agent_dock.isHidden(), "「历史」不得连带显示 Agent 面板"
    assert workstation.logs_dock.isHidden(), "「历史」不得再误开「日志」面板"
