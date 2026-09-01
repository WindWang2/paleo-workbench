"""Ribbon 右键面板菜单：当前页面内容面板的显隐/浮动管理。

Covers the provider-driven context menu on RibbonBar and the
floatable_panel_entries helper (docked hide/show + float toggle).
"""

from PySide6.QtWidgets import QSplitter, QWidget

from paleo_workbench.ui.panel_float_controller import (
    FloatController,
    floatable_panel_entries,
)
from paleo_workbench.ui.ribbon import RibbonBar


def _entries(titles=("数据预览", "数据资产检查器")):
    state = {t: {"visible": True, "floating": False} for t in titles}

    def make():
        return [
            {
                "key": f"data:{i}",
                "title": t,
                "visible": state[t]["visible"],
                "set_visible": (lambda tt=t: lambda on: state[tt].update(visible=bool(on)))(),
                "floating": state[t]["floating"],
                "toggle_float": (lambda tt=t: lambda: state[tt].update(
                    floating=not state[tt]["floating"]))(),
            }
            for i, t in enumerate(titles)
        ]

    return make, state


def test_context_menu_lists_current_page_panels(qtbot):
    ribbon = RibbonBar(["数据", "井"])
    qtbot.addWidget(ribbon)
    provider, _state = _entries()
    ribbon.set_panel_provider(provider)

    menu = ribbon._build_context_menu()
    texts = [a.text() for a in menu.actions()]

    assert "数据预览" in texts
    assert "数据资产检查器" in texts
    assert "浮动 · 数据预览" in texts
    assert "全部显示" in texts
    assert "折叠功能区" in texts
    menu.deleteLater()


def test_menu_actions_drive_visibility_and_float(qtbot):
    ribbon = RibbonBar(["数据", "井"])
    qtbot.addWidget(ribbon)
    provider, state = _entries()
    ribbon.set_panel_provider(provider)

    menu = ribbon._build_context_menu()
    by_text = {a.text(): a for a in menu.actions()}

    by_text["数据预览"].toggled.emit(False)
    assert state["数据预览"]["visible"] is False

    by_text["浮动 · 数据资产检查器"].toggled.emit(True)
    assert state["数据资产检查器"]["floating"] is True

    state["数据预览"]["visible"] = False
    by_text["全部显示"].triggered.emit()
    assert state["数据预览"]["visible"] is True
    menu.deleteLater()


def test_menu_without_panels_still_offers_collapse(qtbot):
    ribbon = RibbonBar(["数据", "井"])
    qtbot.addWidget(ribbon)
    ribbon.set_panel_provider(lambda: [])

    menu = ribbon._build_context_menu()
    texts = [a.text() for a in menu.actions()]
    assert texts == ["折叠功能区"]
    menu.deleteLater()


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
