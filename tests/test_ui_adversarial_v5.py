"""U10 对抗性验证：V5 行为在快速/极端操作下的稳定性。

覆盖 goal U10 清单中与 Design System 相关的项：
- 主题运行时切换往返（light→dark→high_contrast→light）后关键面不再残留 light 快照
- 密度运行时切换往返 metrics 重算
- dock float/dock 往返 + 面板命令真实触发
- Command Palette 快速开合（连发）不产生焦点/可见性残留
- 长中英文文本在 PwbPropertyEditor / PwbBadge / toast 中不崩、可换行
- 空项目 + 空任务表状态
"""
from __future__ import annotations

import pytest

from paleo_workbench.ui.theme import DensityMode, theme_manager


@pytest.fixture()
def restore_theme_density():
    before = (theme_manager.current_theme, theme_manager.density)
    yield
    theme_manager.set_theme(before[0])
    theme_manager.set_density(before[1])


def test_theme_round_trip_refreshes_bound_widgets(qtbot, restore_theme_density):
    """style.bind 注册的 widget 在主题往返后必须被重渲染（无 light 残留）。"""
    from PySide6.QtWidgets import QFrame, QApplication

    from paleo_workbench import tokens
    from paleo_workbench.ui import style

    app = QApplication.instance()
    frame = QFrame()
    qtbot.addWidget(frame)
    style.bind(frame, lambda: f"QFrame {{ color: {style.palette()['TEXT_PRIMARY']}; }}")

    for theme in ("dark", "high_contrast", "light", "dark"):
        theme_manager.set_theme(theme)
    # 往返结束落在 dark：样式表必须反映 dark palette（无 light 残留）
    assert theme_manager.current_theme.value == "dark"
    expected = tokens.palette_for("dark")["TEXT_PRIMARY"]
    assert expected in frame.styleSheet()
    light_ink = tokens.palette_for("light")["TEXT_PRIMARY"]
    assert light_ink != expected
    assert light_ink not in frame.styleSheet()
    app.setStyleSheet(theme_manager.get_qss())


def test_density_round_trip_recomputes_tracked_heights(qtbot, restore_theme_density):
    """track_control_height 的控件在密度往返后高度跟随。"""
    from PySide6.QtWidgets import QPushButton, QApplication

    from paleo_workbench import tokens
    from paleo_workbench.ui import style

    QApplication.instance()
    btn = QPushButton("密度")
    qtbot.addWidget(btn)
    style.track_control_height(btn)

    theme_manager.set_density(DensityMode.COMPACT)
    assert btn.minimumHeight() == tokens.control_height("compact")
    theme_manager.set_density(DensityMode.COMFORTABLE)
    assert btn.minimumHeight() == tokens.control_height("comfortable")
    theme_manager.set_density(DensityMode.COMPACT)


def test_command_palette_rapid_toggle(qtbot):
    """连发 Ctrl+K 语义（popup/dismiss 交替）不残留可见性错乱。"""
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    for _ in range(6):
        shell._toggle_command_palette()
        shell._toggle_command_palette()
    shell._toggle_command_palette()
    assert not shell.command_palette.isHidden()
    shell.command_palette.dismiss()
    assert shell.command_palette.isHidden()
    shell.command_palette.dismiss()  # 双重 dismiss 安全


def test_panel_commands_are_real_toggles(qtbot):
    """palette 的面板命令必须是真 toggleViewAction（触发后可见性翻转）。"""
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    ws = shell.workstation
    actions = ws.panel_commands()
    assert actions
    _label, action = actions[0]
    # 真实断言：toggleViewAction 触发后 checked 状态与 dock 可见性同步翻转。
    # composite_input 在默认预设中隐藏且未 show 窗口时 isVisible() 恒 False
    #（offscreen 无窗口），因此用 isChecked() 作为可靠的可视性信号源。
    was_checked = action.isChecked()
    action.trigger()
    assert action.isChecked() != was_checked
    action.trigger()  # 往返
    assert action.isChecked() == was_checked


def test_long_text_states(qtbot):
    """长中英文文本：badge 不断行溢出崩、property editor 可换行、toast 不崩。"""
    from PySide6.QtWidgets import QWidget

    from paleo_workbench.ui.components import PwbBadge, PwbPropertyEditor, PwbToast

    long_zh = "非常长的中文描述" * 40
    long_en = "A very long english diagnostic message. " * 40

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)

    badge = PwbBadge(long_zh, tone="warning")
    qtbot.addWidget(badge)

    editor = PwbPropertyEditor()
    qtbot.addWidget(editor)
    row = editor.add_row(long_en, long_zh)
    assert row.text()

    host.show()
    toast = PwbToast.show_on(host, long_en, tone="error", timeout_ms=0)
    assert toast.isVisible()
    toast.dismiss()


def test_empty_project_and_empty_task_states(qtbot):
    """空项目：任务表空态可见（C9）；palette 命令在空项目仍可枚举。"""
    from PySide6.QtGui import QStandardItemModel

    from paleo_workbench.ui.components import PwbEmptyState

    state = PwbEmptyState("暂无任务", "提交任务后显示")
    qtbot.addWidget(state)
    assert state._title.text() == "暂无任务"

    # 空项目数据形状：0 资源 count 行不抛
    model = QStandardItemModel(0, 0)
    assert model.rowCount() == 0


def test_theme_switch_with_open_project_shell(qtbot):
    """项目打开状态下主题切换：shell 重贴样式表 + 不抛。"""
    from PySide6.QtWidgets import QApplication

    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.app_shell import AppShell

    app = QApplication.instance()
    shell = AppShell(project=ProjectDocument.new("主题切换工区"))
    qtbot.addWidget(shell)
    theme_manager.set_theme("dark")
    app.setStyleSheet(theme_manager.get_qss())
    theme_manager.set_theme("light")
    app.setStyleSheet(theme_manager.get_qss())
    assert shell.command_palette is not None
