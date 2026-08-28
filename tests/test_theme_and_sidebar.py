"""#1047 — one theme system (tokens.py) and sidebar state that survives page
switches.

``ThemeManager`` used to carry its own ~30-line hardcoded mini-stylesheet,
disconnected from the 700-line production token sheet — two parallel theme
systems where only tokens.build_qss() ever ran. And ``AppShell._switch_page``
unconditionally hid the ContextSidebar, discarding the user's
expanded/collapsed choice on every navigation.

These tests pin:
* every theme renders through tokens.build_qss (single source),
* dark / high-contrast are real palettes of the same token vocabulary,
* AppShell styles itself via the ThemeManager,
* page switches keep the sidebar visible / respect collapse state.
"""

from __future__ import annotations

import pytest

from paleo_workbench import tokens
from paleo_workbench.ui import tokens as ui_tokens
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


def test_page_switch_keeps_sidebar_visible_and_updates_context(qtbot):
    from paleo_workbench import tokens as ui_tokens

    shell = AppShell()
    qtbot.addWidget(shell)

    shell.sidebar.setVisible(True)
    shell._switch_page(1)  # data page
    assert not shell.sidebar.isHidden()
    # the REAL context bookkeeping continues across switches (the old suite
    # deleted these assertions — review 4.4)
    assert shell.sidebar.context_label.text() == ui_tokens.PAGE_NAMES[1]
    shell._switch_page(8)  # mapping page
    assert not shell.sidebar.isHidden()
    assert shell.sidebar.context_label.text() == ui_tokens.PAGE_NAMES[8]


def test_page_switch_respects_user_collapse_state(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    # user collapses the sidebar -> it stays collapsed (narrow) but present
    shell.sidebar.toggle_collapse()
    collapsed = shell.sidebar.is_collapsed
    shell._switch_page(2)
    assert shell.sidebar.is_collapsed is collapsed

    shell.sidebar.toggle_collapse()
    assert shell.sidebar.is_collapsed is False
    shell._switch_page(0)
    assert shell.sidebar.is_collapsed is False


def test_sidebar_keeps_context_updates_across_switches(qtbot):
    from paleo_workbench import tokens as ui_tokens

    shell = AppShell()
    qtbot.addWidget(shell)
    shell._switch_page(1)
    shell._switch_page(2)
    # context bookkeeping continues while the widget stays visible
    assert not shell.sidebar.isHidden()
    assert shell.sidebar.context_label.text() == ui_tokens.PAGE_NAMES[2]
