"""Unit tests for Batch 6: UI & UX Modernization (ThemeManager & DockManager)."""

import pytest

from paleo_workbench.ui.dock_manager import WorkspacePreset, dock_manager
from paleo_workbench.ui.theme import ThemeMode, theme_manager


@pytest.fixture(autouse=True)
def _restore_theme_singleton():
    """The module singleton now styles every AppShell — never leak a test
    theme into later suites (review 4.7)."""
    from paleo_workbench.ui.theme import ThemeMode

    yield
    theme_manager.set_theme(ThemeMode.LIGHT)


def test_theme_manager_switching():
    # #1047: every theme renders through the single token sheet; the manager
    # owns only the switching state (no parallel mini-QSS anymore).
    from paleo_workbench import tokens

    theme_manager.set_theme(ThemeMode.DARK)
    assert theme_manager.current_theme == ThemeMode.DARK
    assert theme_manager.get_qss() == tokens.build_qss(theme="dark")

    # Switch to Light
    emitted = []
    theme_manager.theme_changed.connect(lambda t: emitted.append(t))
    theme_manager.set_theme(ThemeMode.LIGHT)
    assert theme_manager.current_theme == ThemeMode.LIGHT
    assert len(emitted) == 1
    assert emitted[0] == "light"
    assert theme_manager.get_qss() == tokens.build_qss()

    # Switch to High Contrast
    theme_manager.set_theme(ThemeMode.HIGH_CONTRAST)
    assert theme_manager.current_theme == ThemeMode.HIGH_CONTRAST
    assert theme_manager.get_qss() == tokens.build_qss(theme="high_contrast")


def test_dock_manager_layouts():
    layout = dock_manager.get_layout(WorkspacePreset.MAP_AUTHORING)
    assert layout is not None
    assert layout.name == "古地理综合编图工作区"
    assert len(layout.docks) >= 4

    dock_manager.set_active_preset(WorkspacePreset.WELL_LOG_INTERPRETATION)
    active = dock_manager.active_layout
    assert active.preset == WorkspacePreset.WELL_LOG_INTERPRETATION
    assert len(active.docks) >= 3
