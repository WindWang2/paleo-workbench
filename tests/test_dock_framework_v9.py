"""Dock Framework V9 — resize-authority and descriptor contracts.

Regression tests for the V9 audit P0 fixes:
- B-1: hub dock content must not impose the current page's layout minimum
  (HubScrollArea + AdaptivePageStack).
- B-2: relaxed constraint stack (window/inspector/explorer floors).
- B-3: presets change visibility only; action affordances resize grow-only.
- B-5: GL-bearing docks are not floatable.
- C-4: every shell dock is wired to layout save scheduling.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.project.domain import WellEntity
from paleo_workbench.ui.app_shell import AdaptivePageStack, AppShell
from paleo_workbench.ui.dock_framework import (
    DockImportance,
    classify_viewport,
    ensure_dock_usable,
    workstation_dock_registry,
    ViewportClass,
)
from paleo_workbench.ui.workstation.shell import HubScrollArea


@pytest.fixture(autouse=True)
def _hermetic_global_layout_settings():
    """清空（并事后恢复清空）工作站全局布局 QSettings。

    本模块多个用例构造真实 AppShell 并 show——未替换 settings 的路径
    （归因 handler、save 定时器）会写「PaleoWorkbench/Workstation」全局
    ini，把 inspector 偏好泄漏给同会话后续文件（workstation fixture 在
    构造期同步读该键）。测试环境的全局布局状态必须无菌。
    """
    from PySide6.QtCore import QSettings

    settings = QSettings("PaleoWorkbench", "Workstation")
    settings.clear()
    settings.sync()
    yield
    settings.clear()
    settings.sync()


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


# --- descriptor registry ------------------------------------------------


def test_registry_describes_all_workstation_docks():
    ids = workstation_dock_registry.ids()
    assert set(ids) == {
        "nav", "mapping_stage", "inspector", "composite_layer", "hub",
        "composite_input", "agent", "tasks", "logs", "console",
        "composite_linked", "well", "seismic",
    }
    for dock_id in ids:
        descriptor = workstation_dock_registry.require(dock_id)
        # objectName 保持历史方案：持久化 saveState 字节跨 V8→V9 可解析。
        assert descriptor.object_name == f"WorkstationDock_{descriptor.title}"
        assert descriptor.preferred_area in ("left", "right", "top", "bottom")
        assert isinstance(descriptor.importance, DockImportance)


def test_gl_bearing_docks_are_not_floatable():
    for dock_id in ("well", "seismic", "hub"):
        assert workstation_dock_registry.require(dock_id).can_float is False, dock_id
    # 普通 dock 仍可浮动。
    assert workstation_dock_registry.require("inspector").can_float is True


def test_viewport_classification():
    assert classify_viewport(1093) is ViewportClass.COMPACT  # 1366 @125%
    assert classify_viewport(1366) is ViewportClass.NORMAL
    assert classify_viewport(1920) is ViewportClass.WIDE
    assert classify_viewport(2560) is ViewportClass.ULTRAWIDE


# --- resize authority (B-3) ---------------------------------------------


def test_ensure_dock_usable_is_grow_only(qtbot):
    window = QMainWindow()
    window.resize(1600, 900)
    qtbot.addWidget(window)
    content = QWidget()
    dock = QDockWidget("agent", window)
    dock.setWidget(content)
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    window.show()

    issued = []
    window.resizeDocks = lambda docks, sizes, orient: issued.append(list(sizes))

    # 情形一：底行已被用户调高（经 resizeDocks 语义无法回读，直接以
    # resize 模拟高度）→ 低于地板才增长；高于地板零调用。
    dock.resize(dock.width(), 420)
    assert ensure_dock_usable(window, dock, minimum=245, vertical=True) is False
    assert issued == []

    # 情形二：高度低于地板 → 发出一次增长请求（尺寸即地板值）。
    dock.resize(dock.width(), 100)
    assert ensure_dock_usable(window, dock, minimum=245, vertical=True) is True
    assert issued == [[245]]


def test_preset_apply_never_calls_programmatic_sizing(qtbot, tmp_path, monkeypatch):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation

    called = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.shell.apply_first_run_sizes",
        lambda *a, **k: called.append(a),
    )
    for preset_id in ws.preset_ids():
        ws.apply_layout_preset(preset_id)
    qtbot.wait(60)  # 捕获 deferred singleShot 形态的回卷（旧缺陷形状）
    assert called == [], "presets must be visibility-only (audit B-3)"


def test_show_agent_grows_only(qtbot, tmp_path, monkeypatch):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation

    issued = []
    monkeypatch.setattr(
        ws._dock_host, "resizeDocks",
        lambda docks, sizes, orient: issued.append(list(sizes)),
    )
    # 用户把 Agent 底行调得很高 → 打开 Agent 不得压回 245。
    ws.agent_dock.show()
    ws.agent_dock.resize(ws.agent_dock.width(), 400)
    ws.show_agent()
    for sizes in issued:
        assert sizes[0] >= 400, "agent affordance must never shrink the row"


# --- hub content: scroll degradation, per-page minimum (B-1) -------------


def test_hub_dock_content_is_scroll_host(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    assert isinstance(ws.hub_dock.widget(), HubScrollArea)
    assert ws.hub_scroll.widget() is ws.page_stack
    # 滚动宿主自身不设结构性最小尺寸——dock 手柄永远可拖。
    assert ws.hub_scroll.minimumSize().width() <= 32


def test_page_stack_minimum_reflects_current_page_only(qtbot):
    stack = AdaptivePageStack()
    qtbot.addWidget(stack)
    narrow = QWidget()
    narrow.setMinimumWidth(300)
    wide = QWidget()
    wide.setMinimumWidth(1000)
    stack.addWidget(narrow)
    stack.addWidget(wide)
    stack.setCurrentIndex(0)
    assert stack.minimumSizeHint().width() <= 400
    stack.setCurrentIndex(1)
    assert stack.minimumSizeHint().width() >= 900


def test_hub_scroll_degrades_instead_of_blocking(qtbot, tmp_path):
    """hub dock 打开时窗口压到最小尺寸，滚动宿主仍可继续压缩（B-1 集成）。"""
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    ws.show_hub_page("数据管理")
    shell.resize(960, 600)
    qtbot.wait(50)
    # 滚动宿主的最小宽度远小于任何页面布局最小值（页面最小值由
    # AdaptivePageStack 逐页给出，宽页以滚动条降级）。
    assert ws.hub_scroll.minimumSizeHint().width() < 200


# --- constraint stack (B-2) ----------------------------------------------


def test_constraint_stack_is_relaxed(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    assert ws.inspector.minimumSizeHint().width() <= 240
    assert ws.explorer.minimumSizeHint().width() <= 200
    assert ws.composite.minimumWidth() <= 340
    # 窗口最小尺寸（app.py）：960x600——1366@125% 逻辑屏可完整容纳。
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow(project=_project(tmp_path))
    qtbot.addWidget(window)
    assert window.minimumWidth() == 960
    assert window.minimumHeight() == 600


# --- responsive viewport policies (B-4 debounced + compact surfaces) -----


def test_viewport_policies_compact_vs_wide(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    shell.show()
    shell.resize(1600, 900)
    qtbot.wait(300)
    ws = shell.workstation

    shell.resize(1000, 700)
    qtbot.wait(250)  # 180ms 去抖窗口
    assert ws.app_bar.command_input.minimumWidth() <= 220
    assert not ws.stage_bar.horizon_label.isVisibleTo(ws.stage_bar)
    assert ws.inspector_dock.isHidden()
    assert ws._responsive_hid_inspector is True

    shell.resize(1600, 900)
    qtbot.wait(250)
    assert ws.app_bar.command_input.minimumWidth() >= 300
    assert ws.stage_bar.horizon_label.isVisibleTo(ws.stage_bar)
    assert not ws.inspector_dock.isHidden()
    assert ws._responsive_hid_inspector is False


def test_responsive_policy_is_debounced_out_of_resize_path(qtbot, tmp_path):
    """resizeEvent 不得直接改布局（B-4）：策略只在 180ms 静止后评估。"""
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    shell.show()
    shell.resize(1600, 900)
    qtbot.wait(300)
    ws = shell.workstation
    ws._viewport_timer.stop()
    shell.resize(1000, 700)
    # resizeEvent 刚发生：检查器尚未被隐藏（未过去抖窗）。
    assert ws.inspector_dock.isHidden() is False
    assert ws._viewport_timer.isActive()


# --- lifecycle wiring (C-4) ----------------------------------------------


def test_all_docks_wired_to_layout_save(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    # 孤立构造（宿主未显示）下 isHidden() 恒为 False、setVisible 是空
    # 操作，行为验证不可行；改为验证信号接线本身：每个 shell dock 的
    # visibilityChanged 至少接两路（布局保存调度 + 预设定制追踪）。
    from PySide6.QtCore import SIGNAL

    for dock in ws._shell_docks():
        count = dock.receivers(SIGNAL("visibilityChanged(bool)"))
        assert count >= 2, (
            f"{dock.objectName()} missing layout-save wiring "
            f"(receivers={count})"
        )


# --- R1 review regressions ------------------------------------------------


def test_user_closed_inspector_stays_closed_after_restart(qtbot, tmp_path):
    """原生 X 关闭（无 user 标志路径）→ 下次会话宽屏不得弹回（R1 P1-1）。"""
    from PySide6.QtCore import QSettings

    ini_path = tmp_path / "session.ini"
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    ws._settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
    ws._settings.clear()
    # 构造期同步读发生在替换前——重置被全局状态可能污染的初始标志，
    # 本测试自身的可见性行为完全由会话内动作决定（hermetic）。
    ws._user_hid_inspector = False
    ws._responsive_hid_inspector = False
    shell.show()
    shell.resize(1600, 900)
    qtbot.wait(300)
    ws.inspector_dock.close()  # 原生 X：唯一生产关闭路径，不写 user 标志
    ws._save_timer.stop()
    ws._save_layout(force=True)
    assert ws.inspector_dock.isHidden()

    # 第二会话：同一 QSettings 冷启动恢复。
    shell2 = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell2)
    ws2 = shell2.workstation
    ws2._settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
    ws2._user_hid_inspector = False
    ws2._responsive_hid_inspector = False
    shell2.show()
    shell2.resize(1500, 900)
    qtbot.wait(300)
    assert ws2.inspector_dock.isHidden(), "user hide must survive restart"
    assert ws2._user_hid_inspector, "restored hide must classify as user intent"
    ws2._apply_responsive_panels()  # 宽屏策略不得违背用户意愿弹回
    assert ws2.inspector_dock.isHidden()


def test_first_run_applies_map_dominant_sizes(qtbot, tmp_path):
    """首运行（无持久化布局）：默认尺寸必须真的被执行（R1 P1-2）。

    生产构造顺序是同步 show（showEvent 先于 restore 定时器）；旧实现
    的 _pending_default_sizes 标志在该顺序下永远无人消费，首运行以
    QMainWindow 均分布局打开（检查器列吃 ~700px）。
    """
    from PySide6.QtCore import QSettings

    ini_path = tmp_path / "fresh.ini"
    applied = []
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    ws._settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
    ws._settings.clear()
    real = ws._apply_default_pane_sizes
    ws._apply_default_pane_sizes = lambda: (applied.append(True), real())[1]
    shell.show()  # 同步 show（生产顺序）
    qtbot.wait(200)
    assert applied, "first-run default pane sizes must actually run"


# --- R2 review regressions ------------------------------------------------


def test_float_all_panels_never_floats_gl_docks(qtbot, tmp_path):
    """「全部浮动」不得浮动 GL 承载 dock（R2 P0-1：程序化 setFloating
    不受 DockWidgetFloatable 特性位约束——一键回到 EGL 崩溃类）。"""
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    shell.show()
    qtbot.wait(200)
    ws = shell.workstation
    ws.well_dock.show()
    ws.seismic_dock.show()
    ws.hub_dock.show()
    ws.float_all_panels()
    for dock in (ws.well_dock, ws.seismic_dock, ws.hub_dock):
        assert not dock.isFloating(), (
            f"{dock.objectName()} must never float (GL reparent segfault class)"
        )
    # 普通可浮动 dock 仍被浮动（功能不回退）。
    floated_any = any(
        d.isFloating()
        for d in (ws.nav_dock, ws.inspector_dock, ws.composite_layer_dock)
        if not d.isHidden()
    )
    assert floated_any, "float_all_panels must still float non-GL docks"


def test_inspector_manual_close_beats_policy_reopen(qtbot, tmp_path):
    """紧凑下用户显式关闭检查器 → 宽屏策略不得弹回（R2 P1-1 活跃路径）。

    归因依赖 visibilityChanged：dock 宿主必须可见（生产中宿主即主窗口；
    孤立构造的隐藏宿主下 show/close 不产生可见性信号）。
    """
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    shell.show()
    shell.resize(1600, 900)
    qtbot.wait(300)

    shell.resize(1000, 700)  # compact：策略折叠
    qtbot.wait(300)
    assert ws._responsive_hid_inspector

    # 用户显式重开，再显式关闭（生产路径 = toggleViewAction：面板菜单 /
    # palette / 标题栏 X 同一 action 语义）。
    ws.inspector_dock.toggleViewAction().trigger()
    qtbot.wait(50)
    assert not ws._responsive_hid_inspector, "manual reopen clears policy claim"
    assert not ws._user_hid_inspector
    assert not ws.inspector_dock.isHidden()
    ws.inspector_dock.toggleViewAction().trigger()
    qtbot.wait(50)
    assert ws._user_hid_inspector, "manual close must attribute to user"

    shell.resize(1600, 900)  # 宽屏
    qtbot.wait(300)
    assert ws.inspector_dock.isHidden(), "policy must not override user close"
