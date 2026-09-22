"""V11 audit F — 键盘/无障碍修复的回归面（01-ui-audit.md §F）。

覆盖：
- F1 显式 Tab 链：代表页（home / preparation / seismic_prediction）暴露
  ``_setup_tab_order``，源码含足量 ``setTabOrder`` 配对，重复调用与焦点
  前进不抛错（其余五页同构，由源码计数断言兜底）；
- F4 图标按钮 ``accessibleName``：home / mapping 页上所有带图标且无文字
  的 QToolButton/QPushButton 必须有非空 accessibleName（Qt 内部钮除外）；
- Escape 通道：geological_modeling_3d_page 的 keyPressEvent 在无待取消
  操作时必须把 Escape 传回 super()（事件不被吞）。

约定沿用 tests/test_a11y_dpi_v6.py（offscreen pytest-qt；不做整窗截图）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit, QPushButton, QToolButton, QWidget

_PAGES_DIR = Path(__file__).resolve().parents[1] / "paleo_workbench" / "ui" / "pages"

#: 页面模块 → 源码中 setTabOrder 调用数的下限（8 页全部纳入源码断言：
#: 其余页面与三个代表页同构，离屏实例化代价高，只做静态验证；
#: geo3d / mapping 用 zip 链式写法，字面出现次数为 1）。
_TAB_ORDER_PAGES = {
    "home_page.py": 3,
    "preparation_page.py": 8,
    "seismic_prediction_page.py": 14,
    "stratigraphy_correlation_page.py": 20,
    "geological_modeling_3d_page.py": 1,
    "mapping_page.py": 1,
    "review_export_page.py": 4,
    "visualization_page.py": 5,
}


def _icon_only_buttons(root: QWidget) -> list[QToolButton | QPushButton]:
    """带图标且无可见文字的按钮（Qt 内部钮除外）。

    QLineEdit 的清除钮与 QToolBar 的溢出钮是 Qt 自动创建的内部件，不由
    页面代码命名（PySide6 下清除钮 objectName 为空，需按父件识别）——
    同 test_a11y_dpi_v6.py 对 Qt 内部钮的豁免。
    """
    buttons: list[QToolButton | QPushButton] = []
    for button in (*root.findChildren(QToolButton), *root.findChildren(QPushButton)):
        if button.objectName().startswith(("qt_", "_q_")):
            continue
        if isinstance(button.parentWidget(), QLineEdit):
            continue
        if not button.text().strip() and not button.icon().isNull():
            buttons.append(button)
    return buttons


# --- F1: explicit tab order -------------------------------------------------


@pytest.mark.parametrize("file_name, min_pairs", sorted(_TAB_ORDER_PAGES.items()))
def test_page_source_defines_explicit_tab_order(file_name: str, min_pairs: int) -> None:
    """每页都有 _setup_tab_order，且 setTabOrder 配对数达到下限。"""
    source = (_PAGES_DIR / file_name).read_text(encoding="utf-8")
    assert "_setup_tab_order" in source, "必须暴露 _setup_tab_order 方法"
    assert source.count("setTabOrder") >= min_pairs


def test_home_page_tab_order_chain(qtbot) -> None:
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    page.show()
    assert callable(page._setup_tab_order)
    page._setup_tab_order()  # 幂等：重复调用不抛错
    assert isinstance(page.focusNextPrevChild(True), bool)


def test_preparation_page_tab_order_chain(qtbot) -> None:
    from paleo_workbench.ui.pages.preparation_page import PreparationPage

    page = PreparationPage()
    qtbot.addWidget(page)
    page.show()
    assert callable(page._setup_tab_order)
    page._setup_tab_order()
    assert isinstance(page.focusNextPrevChild(True), bool)


def test_seismic_prediction_page_tab_order_chain(qtbot) -> None:
    from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage

    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.show()
    assert callable(page._setup_tab_order)
    page._setup_tab_order()
    assert isinstance(page.focusNextPrevChild(True), bool)


# --- F4: accessible names on icon-only buttons ------------------------------


def test_home_page_icon_only_buttons_have_accessible_names(qtbot) -> None:
    from paleo_workbench.ui.pages.home_page import HomePage

    page = HomePage()
    qtbot.addWidget(page)
    unnamed = [b for b in _icon_only_buttons(page) if not b.accessibleName().strip()]
    assert not unnamed, (
        "首页存在未命名的图标按钮（audit F4）: "
        + ", ".join(b.objectName() or b.__class__.__name__ for b in unnamed)
    )


def test_mapping_page_icon_only_buttons_have_accessible_names(qtbot) -> None:
    from paleo_workbench.ui.pages.mapping_page import MappingPage

    page = MappingPage()
    qtbot.addWidget(page)
    unnamed = [b for b in _icon_only_buttons(page) if not b.accessibleName().strip()]
    assert not unnamed, (
        "编图页存在未命名的图标按钮（audit F4）: "
        + ", ".join(b.objectName() or b.__class__.__name__ for b in unnamed)
    )


def test_mapping_page_panels_button_and_rail_named(qtbot) -> None:
    from paleo_workbench.ui.pages.mapping_page import MappingPage

    page = MappingPage()
    qtbot.addWidget(page)
    panels = page.findChild(QToolButton, "MapPanelsMenuButton")
    assert panels is not None
    assert panels.accessibleName() == "面板"
    for key, entry in page.dock_manager._panels.items():
        button = entry["button"]
        assert button.accessibleName() == entry["title"], f"侧栏钮 {key} 未命名"


# --- Escape passthrough (page-level key handlers) ---------------------------


def test_geo3d_page_escape_passes_through_without_pending_pick(qtbot) -> None:
    """无待取消井拾取/剖面时，Escape 必须传回 super() 而非被吞掉。

    本批页面文件未定义 QDialog 子类（默认 Escape/Enter 行为已足够）；
    唯一的 keyPressEvent 覆写在此页——验证其透传分支。
    """
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    # 无半选井、无活动剖面：Escape 无可取消对象，必须走透传分支。
    assert page._well_pick.half_select is None and page._well_pick.draw_from is None
    page.keyPressEvent(event)
    # QWidget.keyPressEvent 对未处理的键 ignore()——事件未被页面吞掉。
    assert not event.isAccepted()
