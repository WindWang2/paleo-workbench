def test_ui_exports_app_shell():
    from paleo_workbench.ui import AppShell
    assert AppShell is not None


def test_ui_exports_zone_widgets():
    from paleo_workbench.ui import (
        AppShell, MenuBar, HeaderToolbar, IconRail, TextSidebar, StatusBar
    )
    assert all([
        AppShell, MenuBar, HeaderToolbar, IconRail, TextSidebar, StatusBar
    ])
