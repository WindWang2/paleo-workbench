from PySide6.QtWidgets import QSplitter

from paleo_workbench.ui.pages.action_panel import ActionPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.data_workspace import DataWorkspace


def test_data_workspace_uses_splitter_for_table_and_reader_only(qtbot):
    workspace = DataWorkspace()
    qtbot.addWidget(workspace)

    assert isinstance(workspace.content_splitter, QSplitter)
    assert isinstance(workspace.asset_table, DataAssetTable)
    assert isinstance(workspace.reader_panel, DataReaderPanel)
    assert workspace.content_splitter.indexOf(workspace.asset_table) == 0
    assert workspace.content_splitter.indexOf(workspace.reader_panel) == 1
    assert workspace.content_splitter.indexOf(workspace.catalog_panel) == -1
    assert workspace.content_splitter.indexOf(workspace.action_panel) == -1


def test_data_workspace_wraps_catalog_and_actions_in_floating_panels(qtbot):
    workspace = DataWorkspace()
    qtbot.addWidget(workspace)

    assert isinstance(workspace.catalog_panel, DataCatalogPanel)
    assert isinstance(workspace.action_panel, ActionPanel)
    assert workspace.catalog_floating_panel.is_expanded() is False
    assert workspace.actions_floating_panel.is_expanded() is True


def test_data_workspace_toggles_catalog_and_reader(qtbot):
    workspace = DataWorkspace()
    qtbot.addWidget(workspace)

    workspace.toggle_catalog_panel()
    workspace.set_reader_visible(False)

    assert workspace.catalog_floating_panel.is_expanded() is True
    assert workspace.reader_panel.isVisible() is False
