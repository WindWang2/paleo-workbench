"""内容面板的显隐/浮动管理（原 Ribbon 右键菜单的数据源）。

RibbonBar 已随死 chrome 移除（B2），但 :func:`floatable_panel_entries`
辅助器仍是页面面板浮动的通用 entry 构造器，此处覆盖其 docked
hide/show + float toggle 语义。
"""

from PySide6.QtWidgets import QSplitter, QWidget

from paleo_workbench.ui.panel_float_controller import (
    FloatController,
    floatable_panel_entries,
)


def test_floatable_panel_entries_docked_and_floating(qtbot):
    splitter = QSplitter()
    qtbot.addWidget(splitter)
    panel = QWidget()
    splitter.addWidget(panel)
    controller = FloatController(resolver=lambda _k: panel, parent=splitter)

    entries = floatable_panel_entries(controller, {"p:one": panel})
    (entry,) = entries
    assert entry["visible"] is True
    assert entry["floating"] is False

    # Docked hide → entry reports hidden.
    entry["set_visible"](False)
    assert panel.isHidden()
    assert floatable_panel_entries(controller, {"p:one": panel})[0]["visible"] is False

    # Float → entry flips to floating; set_visible then drives the window.
    entry["toggle_float"]()
    assert controller.is_floating("p:one")
    floated = floatable_panel_entries(controller, {"p:one": panel})[0]
    assert floated["floating"] is True
    window = controller.floating_panel("p:one")
    floated["set_visible"](False)
    assert window.isHidden()
