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

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from paleo_workbench import tokens
from paleo_workbench.ui import app_shell as app_shell_module
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


def test_theme_change_reapplies_inline_token_colors(qtbot):
    """Inline token-colored chrome (stepper connectors, sidebar accent) must
    re-resolve against the active palette on theme_changed — no stale light
    colors on a dark session."""
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.theme_manager.set_theme(ThemeMode.LIGHT)
    light_connector = shell.workflow_stepper._connectors[0].styleSheet()
    light_accent = shell.sidebar.context_label.styleSheet()

    shell.set_theme(ThemeMode.DARK)
    dark_connector = shell.workflow_stepper._connectors[0].styleSheet()
    dark_accent = shell.sidebar.context_label.styleSheet()

    assert dark_connector != light_connector
    assert tokens.palette_for("dark")["BORDER_STRONG"] in dark_connector
    assert tokens.palette_for("dark")["PRIMARY"] in dark_accent
    assert dark_accent != light_accent


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
        assert dark["PRIMARY"] in shell.sidebar.context_label.styleSheet()
    finally:
        theme_manager.set_theme(ThemeMode.LIGHT)


# --- M7: the floated sidebar window must follow theme switches ---------------


@pytest.fixture
def float_store(monkeypatch):
    """Real M4 FloatController + in-memory LayoutPersistence stand-in
    (skips while feat/float-panel-framework is unmerged, keeps QSettings
    clean). Mirrors the fixture in tests/test_app_shell.py."""
    framework = app_shell_module._load_float_framework()
    if framework is None:
        pytest.skip("M4 float framework not merged yet")
    controller_cls = framework[0]
    store: dict = {}

    def save_float(key, geometry):
        store[key] = {
            "floating": True,
            "geometry": QRect(geometry),
            "docked_sizes": None,
            "visible": True,
        }

    def save_dock(key, sizes):
        state = store.setdefault(
            key,
            {
                "floating": False,
                "geometry": None,
                "docked_sizes": None,
                "visible": True,
            },
        )
        state["floating"] = False
        state["geometry"] = None
        state["docked_sizes"] = tuple(sizes)

    def save_docked_sizes(key, sizes):
        state = store.setdefault(
            key,
            {
                "floating": False,
                "geometry": None,
                "docked_sizes": None,
                "visible": True,
            },
        )
        state["docked_sizes"] = tuple(sizes)

    def save_visibility(key, visible):
        state = store.setdefault(
            key,
            {
                "floating": False,
                "geometry": None,
                "docked_sizes": None,
                "visible": True,
            },
        )
        state["visible"] = bool(visible)

    def load(key):
        from paleo_workbench.ui.layout_persistence import PanelLayoutRecord

        state = store.get(key)
        if state is None:
            return PanelLayoutRecord()
        return PanelLayoutRecord(
            floating=state["floating"],
            geometry=state["geometry"],
            docked_sizes=state["docked_sizes"],
            visible=state["visible"],
        )

    def clear(key):
        store.pop(key, None)

    fake_instance = SimpleNamespace(
        save_float=save_float,
        save_dock=save_dock,
        save_docked_sizes=save_docked_sizes,
        save_visibility=save_visibility,
        load=load,
        clear=clear,
    )
    monkeypatch.setattr(
        app_shell_module,
        "_load_float_framework",
        lambda: (controller_cls, lambda settings=None: fake_instance),
    )
    return store


@pytest.fixture
def windowed_platform(monkeypatch):
    """Clear the offscreen env to unblock the float guard; tests never call
    show(), so no real window can appear."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "")


def test_theme_switch_restyles_floated_sidebar_window(
    qtbot, float_store, windowed_platform
):
    """Floated sidebar = top-level window outside the shell: the app-level
    QSS re-apply reaches it and the inline accent re-resolves (M7 constraint:
    theme switching must restyle the floated window too)."""
    shell = AppShell()
    qtbot.addWidget(shell)
    shell._toggle_sidebar_float()
    panel = shell.sidebar.window()
    assert panel.isWindow() and panel is not shell

    theme_manager.set_theme(ThemeMode.LIGHT)
    light_accent = shell.sidebar.context_label.styleSheet()
    try:
        shell.set_theme(ThemeMode.DARK)
        assert QApplication.instance().styleSheet() == theme_manager.get_qss()
        dark_accent = shell.sidebar.context_label.styleSheet()
        assert dark_accent != light_accent
        assert tokens.palette_for("dark")["PRIMARY"] in dark_accent
        # the panel is a plain styled window, not a self-styled rogue
        assert panel.styleSheet() == ""
    finally:
        theme_manager.set_theme(ThemeMode.LIGHT)
