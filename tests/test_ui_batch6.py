"""Unit tests for Batch 6: UI & UX Modernization (ThemeManager & DockManager)."""

import pytest

from paleo_workbench.ui.dock_manager import DockManager, WorkspacePreset, dock_manager
from paleo_workbench.ui.panel_float_controller import _registry_title
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


# --- panel-id registry (FloatController vocabulary, M4) ------------------


def test_panel_registry_seeded_from_default_presets():
    manager = DockManager()
    for panel_id in ("layer_tree", "map_tools", "property_inspector", "well_tree", "crossplot"):
        assert manager.has_panel(panel_id)
        assert manager.panel_title(panel_id)
    assert "layer_tree" in manager.panel_ids()


def test_panel_registry_register_and_namespaced_lookup():
    manager = DockManager()
    config = manager.register_panel("factor_grid", "单因素网格编辑器", area="right")
    assert config.title == "单因素网格编辑器"
    assert config.area == "right"
    assert manager.panel_title("mapping:factor_grid") == "单因素网格编辑器"
    assert manager.panel_title("missing_panel") is None

    # Re-registering an existing id only retitles it.
    manager.register_panel("factor_grid", "网格编辑器")
    assert manager.panel_title("factor_grid") == "网格编辑器"
    assert len(manager.panel_ids()) == len({*manager.panel_ids()})


def test_panel_registry_matches_controller_title_resolution():
    manager = DockManager()
    controller_default = _registry_title("mapping:layer_tree")
    assert controller_default == "图层管理树"

    manager.register_panel("custom", "自定义面板")
    assert manager.panel_title("page:custom") == "自定义面板"
    # Unknown ids fall through to the raw key.
    assert manager.panel_title("page:unknown") is None
