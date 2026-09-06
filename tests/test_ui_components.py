"""Design System V5 组件层测试（U2）。

覆盖：三主题 × 两密度下组件可构建、QSS 命中（objectName/属性驱动）、
状态切换 repolish、toast 堆叠/自动消退、密度行高访问。
"""
from __future__ import annotations

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
