"""#1047 — one theme system (tokens.py).

``ThemeManager`` used to carry its own ~30-line hardcoded mini-stylesheet,
disconnected from the 700-line production token sheet — two parallel theme
systems where only tokens.build_qss() ever ran.

These tests pin:
* every theme renders through tokens.build_qss (single source),
* dark / high-contrast are real palettes of the same token vocabulary,
* AppShell styles itself via the ThemeManager,
* inline token-colored chrome re-resolves on theme switches.
"""

from __future__ import annotations

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


def test_theme_change_reapplies_inline_token_colors(qtbot):
    """Inline token-colored chrome (stepper connectors) must re-resolve
    against the active palette on theme_changed — no stale light colors on a
    dark session."""
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.theme_manager.set_theme(ThemeMode.LIGHT)
    light_connector = shell.workflow_stepper._connectors[0].styleSheet()

    shell.set_theme(ThemeMode.DARK)
    dark_connector = shell.workflow_stepper._connectors[0].styleSheet()

    assert dark_connector != light_connector
    assert tokens.palette_for("dark")["BORDER_STRONG"] in dark_connector


def test_shell_constructed_under_dark_gets_dark_inline_colors(qtbot):
    """r1 p2-1: theme_changed only fires on switches — a shell constructed
    while the manager is already dark/high-contrast must start with the dark
    palette's inline colors, not light ones."""
    theme_manager.set_theme(ThemeMode.DARK)
    try:
        shell = AppShell()
        qtbot.addWidget(shell)

        assert shell.theme_manager.current_theme == ThemeMode.DARK
        dark = tokens.palette_for("dark")
        assert dark["BORDER_STRONG"] in shell.workflow_stepper._connectors[0].styleSheet()
        assert tokens.BORDER_STRONG not in shell.workflow_stepper._connectors[0].styleSheet()
    finally:
        theme_manager.set_theme(ThemeMode.LIGHT)
