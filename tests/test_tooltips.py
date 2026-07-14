"""Tooltip coverage tests - Task 3 (RED first).

Asserts that toolbar buttons, nav icons, table headers, and action-panel
buttons all carry a non-empty static tooltip.
"""
from PySide6.QtCore import Qt

from paleo_workbench.ui.icon_rail import IconRail
from paleo_workbench.ui.menu_bar import MenuBar
from paleo_workbench.ui.pages.action_header import ActionHeader
from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_toolbar import DataToolbar


def test_icon_rail_has_tooltips(qtbot):
    rail = IconRail()
    qtbot.addWidget(rail)
    assert rail.nav_buttons, "expected nav buttons to be built"
    for btn in rail.nav_buttons:
        assert btn.toolTip() != "", "nav button missing tooltip"


def test_data_toolbar_buttons_have_tooltips(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.import_btn.toolTip() != ""
    assert tb.import_folder_btn.toolTip() != ""
    assert tb.rescan_btn.toolTip() != ""
    assert tb.remove_btn.toolTip() != ""
    assert tb.open_folder_btn.toolTip() != ""
    assert tb.visualize_btn.toolTip() != ""
    assert tb.reader_btn.toolTip() != ""
    assert tb.search_box.toolTip() != ""


def test_menu_bar_search_box_has_tooltip(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)
    assert bar.search_box.toolTip() != ""


def test_data_asset_table_column_headers_have_tooltips(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    model = table.model
    col_count = model.columnCount()
    assert col_count > 0
    for col in range(col_count):
        tip = model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
        assert tip, f"column {col} header missing tooltip"


def test_action_header_buttons_have_tooltips(qtbot):
    header = ActionHeader()
    qtbot.addWidget(header)
    assert header.run_btn.toolTip() != ""
    assert header.config_btn.toolTip() != ""
    assert header.export_btn.toolTip() != ""


def test_boundary_panel_button_has_tooltip(qtbot):
    panel = BoundaryPanel()
    qtbot.addWidget(panel)
    assert panel.generate_btn.toolTip() != ""
