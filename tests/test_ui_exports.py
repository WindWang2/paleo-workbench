import importlib
import sys


def test_ui_exports_app_shell():
    from paleo_workbench.ui import AppShell
    assert AppShell is not None


def test_ui_exports_zone_widgets():
    from paleo_workbench.ui import (
        AppShell, MenuBar, IconRail, TextSidebar, StatusBar
    )
    assert all([
        AppShell, MenuBar, IconRail, TextSidebar, StatusBar
    ])


def test_ui_pages_exports_data_management_widgets():
    from paleo_workbench.ui.pages import DataToolbar, DataWorkspace

    assert DataToolbar is not None
    assert DataWorkspace is not None


def test_navigation_tree_import_does_not_eagerly_import_ui_shell_modules():
    for module_name in [
        "geoviz_paleo_map",
        "geoviz_seismic",
        "geoviz_well_log",
        "paleo_workbench.ui",
        "paleo_workbench.ui.pages",
        "paleo_workbench.ui.pages.navigation_tree",
        "paleo_workbench.ui.app_shell",
        "paleo_workbench.ui.pages.data_page",
    ]:
        sys.modules.pop(module_name, None)

    module = importlib.import_module("paleo_workbench.ui.pages.navigation_tree")

    assert module.NavigationTree is not None
    assert "paleo_workbench.ui.app_shell" not in sys.modules
    assert "paleo_workbench.ui.pages.data_page" not in sys.modules
    assert "geoviz_paleo_map" not in sys.modules
    assert "geoviz_seismic" not in sys.modules
    assert "geoviz_well_log" not in sys.modules
