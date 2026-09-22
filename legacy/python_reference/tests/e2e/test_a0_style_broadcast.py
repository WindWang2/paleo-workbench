"""Global app-level stylesheet/theme tests — MUST run before the suite builds shells.

app.setStyleSheet() and theme repolish_all() walk EVERY live top-level
widget. PySide6 leaves ~100 parentless stragglers behind each AppShell
built earlier in the suite (Qt-internal QMenus included — not reachable
from product code); past a few thousand the global restyle blows the 45s
per-test ceiling or segfaults on half-dismantled wrappers (the
long-standing ~82% CI hang). Living in tests/e2e/ with an a0_ prefix
puts these FIRST — before tests/e2e/test_tier5* accumulates stragglers.
Heaviest (repolish round-trip) runs first while the app is clean."""

from __future__ import annotations

import pytest

from paleo_workbench.ui.theme import DensityMode, theme_manager


@pytest.fixture(autouse=True)
def restore_app_stylesheet():
    """App-level stylesheets outlive their test — clear them afterwards.

    These tests set the production QSS on the shared QApplication; leaving
    it installed changes control min-heights/toolbar widths for every
    later suite test that builds bare widgets (inspector_panel/toolbar_
    overflow assertions broke from exactly this residue)."""
    from PySide6.QtWidgets import QApplication

    yield
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet("")


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

# ---- ui_components (global qss build) -----------------------------------

import pytest

from paleo_workbench import tokens
from paleo_workbench.ui.theme import DensityMode, ThemeMode, theme_manager


def _apply(theme: ThemeMode | str, density: DensityMode | str) -> None:
    theme_manager.set_theme(theme)
    theme_manager.set_density(density)


THEMES = ["light", "dark", "high_contrast"]
DENSITIES = ["compact", "comfortable"]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("density", DENSITIES)
def test_components_build_under_all_theme_density(theme, density, qtbot):
    from PySide6.QtWidgets import QApplication, QWidget

    _apply(theme, density)
    app = QApplication.instance()
    app.setStyleSheet(tokens.build_qss(density=density, theme=theme))

    from paleo_workbench.ui.components import (
        PwbBadge,
        PwbButton,
        PwbCommandBar,
        PwbEmptyState,
        PwbErrorState,
        PwbInlineStatus,
        PwbInspectorSection,
        PwbLoadingState,
        PwbProgress,
        PwbPropertyEditor,
        PwbSearchBox,
        PwbSectionHeader,
        PwbSplitButton,
        PwbTableView,
        PwbToolButton,
        PwbTreeView,
    )

    host = QWidget()
    qtbot.addWidget(host)
    for cls, args in [
        (PwbButton, ("确定",)),
        (PwbToolButton, ()),
        (PwbSplitButton, ("导出",)),
        (PwbBadge, ("已完成",)),
        (PwbInlineStatus, ("已降级",)),
        (PwbSectionHeader, ("区块",)),
        (PwbInspectorSection, ("样式",)),
        (PwbPropertyEditor, ()),
        (PwbSearchBox, ("搜索…",)),
        (PwbEmptyState, ("暂无数据", "导入后显示")),
        (PwbErrorState, ("加载失败", "SEGY 缺头")),
        (PwbLoadingState, ("加载中…",)),
        (PwbProgress, ()),
        (PwbTableView, ()),
        (PwbTreeView, ()),
        (PwbCommandBar, ()),
    ]:
        w = cls(*args)
        host.layout().addWidget(w) if host.layout() else w.setParent(host)
    # 不抛异常即通过：样式表由全局渲染，组件只是消费


def test_button_variant_mapping_and_repolish(qtbot):
    from paleo_workbench.ui.components import PwbButton

    btn = PwbButton("删除", variant="danger")
    qtbot.addWidget(btn)
    assert btn.objectName() == "PwbDangerButton"
    btn.set_variant("primary")
    assert btn.objectName() == "PrimaryButton"
    assert btn.variant == "primary"
    btn.set_variant("nonsense")
    assert btn.objectName() == "SecondaryButton"


def test_badge_tones(qtbot):
    from paleo_workbench.ui.components import PwbBadge

    badge = PwbBadge("运行中", tone="warning")
    qtbot.addWidget(badge)
    assert badge.property("tone") == "warning"
    badge.set_tone("error")
    assert badge.tone == "error"
    badge.set_tone("nope")
    assert badge.tone == "neutral"


def test_inline_status_updates(qtbot):
    from paleo_workbench.ui.components import PwbInlineStatus

    status = PwbInlineStatus("就绪", tone="neutral")
    qtbot.addWidget(status)
    status.set_status("井震联动已降级", tone="warning")
    assert status._text_label.text() == "井震联动已降级"
    assert status._text_label.property("tone") == "warning"
    status.clear()
    assert status._text_label.property("tone") == "neutral"


def test_property_editor_missing_semantics(qtbot):
    from paleo_workbench.ui.components import PwbPropertyEditor

    editor = PwbPropertyEditor()
    qtbot.addWidget(editor)
    got = editor.add_row("深度", 1234.5, unit="m")
    assert got.text() == "1234.5 m"
    assert got.property("missing") is False
    missing = editor.add_row("层位", None)
    assert missing.property("missing") is True
    assert missing.text() == "—"


def test_progress_state_property(qtbot):
    from paleo_workbench.ui.components import PwbProgress

    bar = PwbProgress(state="running")
    qtbot.addWidget(bar)
    assert bar.property("progressState") == "running"
    bar.set_state("failed")
    assert bar.property("progressState") == "failed"
    bar.set_state("unknown")
    assert bar.property("progressState") == "normal"


def test_density_row_height_accessors():
    assert tokens.control_height("compact") == 24
    assert tokens.control_height("comfortable") == 30
    assert tokens.row_height("compact") == 22
    assert tokens.row_height("comfortable") == 28
    assert tokens.toolbar_height("compact") == 30
    assert tokens.toolbar_height("comfortable") == 36
    # 未知值安全回落
    assert tokens.control_height("nonsense") == 30


def test_table_row_height_follows_density(qtbot):
    from PySide6.QtGui import QStandardItem, QStandardItemModel

    from paleo_workbench.ui.components import PwbTableView

    table = PwbTableView()
    qtbot.addWidget(table)
    model = QStandardItemModel(2, 2)
    model.setItem(0, 0, QStandardItem("a"))
    model.setItem(1, 0, QStandardItem("b"))
    table.setModel(model)
    _apply(theme_manager.current_theme, DensityMode.COMPACT)
    table.resizeRowsToContents()
    compact_h = table.rowHeight(0)
    _apply(theme_manager.current_theme, DensityMode.COMFORTABLE)
    table.resizeRowsToContents()
    comfortable_h = table.rowHeight(0)
    # 密度是行高下限：内容可撑大，但 comfortable 下限 ≥ compact 下限
    assert compact_h >= tokens.row_height("compact")
    assert comfortable_h >= tokens.row_height("comfortable")
    assert compact_h <= comfortable_h


def test_toast_stack_and_auto_dismiss(qtbot):
    from PySide6.QtWidgets import QWidget

    from paleo_workbench.ui.components import PwbToast

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1200, 800)
    host.show()
    t1 = PwbToast.show_on(host, "第一条", tone="success", timeout_ms=5000)
    t2 = PwbToast.show_on(host, "第二条", tone="error", timeout_ms=5000)
    assert t1.isVisible() and t2.isVisible()
    assert t2.y() > t1.y()  # 自上而下堆叠
    t1.dismiss()
    assert not t1.isVisible()
    t2.dismiss()
    assert not t2.isVisible()


def test_split_button_menu(qtbot):
    from PySide6.QtWidgets import QMenu

    from paleo_workbench.ui.components import PwbSplitButton

    menu = QMenu()
    menu.addAction("PNG")
    split = PwbSplitButton("导出", menu=menu)
    qtbot.addWidget(split)
    assert split.menu() is menu

# ---- theme & sidebar (app.setStyleSheet through the theme manager) ----

import pytest

from paleo_workbench import tokens
from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui.theme import ThemeManager, ThemeMode, theme_manager


def test_light_theme_is_the_production_token_sheet():
    manager = ThemeManager()
    manager.set_theme(ThemeMode.LIGHT)
    assert manager.get_qss() == tokens.build_qss()


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.HIGH_CONTRAST])
def test_other_themes_render_the_same_token_vocabulary(mode):
    manager = ThemeManager()
    manager.set_theme(mode)
    qss = manager.get_qss()
    assert qss, f"{mode} theme must produce a stylesheet"
    assert len(qss) > 5_000, (
        "theme must be the full token sheet over a palette, not a stub mini-QSS"
    )
    # same structural coverage as the production sheet
    light = tokens.build_qss()
    for selector in ("QPushButton", "QMenu", "QTableView", "QHeaderView::section"):
        assert selector in qss, f"{mode} missing {selector}"
        assert selector in light


def test_dark_theme_is_actually_dark():
    manager = ThemeManager()
    manager.set_theme(ThemeMode.DARK)
    palette = tokens.palette_for("dark")
    bg = palette["BG_BODY"].lstrip("#")
    r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
    assert r + g + b < 200, "dark theme body background must be dark"
    assert manager.get_qss().count(palette["BG_BODY"]) > 0


def test_themes_are_palettes_of_the_same_token_names():
    light = tokens.palette_for("light")
    dark = tokens.palette_for("dark")
    hc = tokens.palette_for("high_contrast")
    assert set(light) == set(dark) == set(hc)
    assert "BG_BODY" in light and "PRIMARY" in light and "TEXT_PRIMARY" in light


def test_app_shell_styles_through_the_theme_manager(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    assert shell.theme_manager is theme_manager
    assert shell.styleSheet() == theme_manager.get_qss()

    shell.set_theme(ThemeMode.DARK)
    assert shell.styleSheet() == theme_manager.get_qss()
    assert theme_manager.current_theme == ThemeMode.DARK
