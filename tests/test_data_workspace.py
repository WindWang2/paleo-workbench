from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.navigation_tree import NavigationTree


def test_workspace_has_three_panes(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    assert isinstance(ws.navigation_tree, NavigationTree)
    assert isinstance(ws.asset_table, DataAssetTable)
    assert isinstance(ws.reader_panel, DataReaderPanel)
    assert isinstance(ws.inspector_panel, InspectorPanel)


def test_workspace_main_splitter_three_segments(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    assert ws.main_splitter.count() == 3
    # Navigation | Center (table/overview stack) | Right column — in order.
    assert ws.main_splitter.widget(0) is ws.navigation_tree
    center = ws.main_splitter.widget(1)
    assert ws._center_stack.parentWidget() is center
    assert ws._center_stack.indexOf(ws.asset_table) == 0
    assert ws._center_stack.indexOf(ws.overview_panel) == 1
    assert ws.main_splitter.widget(2) is ws.right_splitter


def test_workspace_overview_stack_swap(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    assert not ws.overview_visible()
    ws.show_overview(True)
    assert ws.overview_visible()
    ws.show_overview(False)
    assert not ws.overview_visible()


def test_workspace_right_splitter_two_segments(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    assert ws.right_splitter.count() == 2
    assert ws.right_splitter.widget(0) is ws.reader_panel
    assert ws.right_splitter.widget(1) is ws.inspector_panel


def test_workspace_set_right_visible(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    ws.set_right_visible(False)
    assert not ws.right_splitter.isVisible()
