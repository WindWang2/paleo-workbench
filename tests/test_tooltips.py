"""Tooltip coverage tests - Task 3 (RED first).

Asserts that ribbon buttons, toolbar buttons, table headers, and action-panel
buttons all carry a non-empty static tooltip.
"""
from PySide6.QtCore import Qt

from paleo_workbench.ui.pages.action_header import ActionHeader
from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_toolbar import DataToolbar
from paleo_workbench.ui.ribbon import RibbonBar


def test_ribbon_project_group_buttons_have_tooltips(qtbot):
    ribbon = RibbonBar(["数据", "井", "地震", "编图", "可视化"])
    qtbot.addWidget(ribbon)
    body = ribbon.add_context("data:overview")
    group = ribbon.populate_project_group(body)
    body.finish()
    assert group.buttons, "expected 工程 group buttons to be built"
    for btn in group.buttons:
        assert btn.toolTip() != "", f"ribbon button {btn.text()!r} missing tooltip"


def test_data_toolbar_buttons_have_tooltips(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.import_btn.toolTip() != ""
    assert tb.import_folder_btn.toolTip() != ""
    assert tb.rescan_btn.toolTip() != ""
    assert tb.remove_btn.toolTip() != ""
    assert tb.open_folder_btn.toolTip() != ""
    assert tb.visualize_btn.toolTip() != ""
    assert tb.clear_preview_cache_btn.toolTip() != ""
    assert tb.reader_btn.toolTip() != ""
    assert tb.search_box.toolTip() != ""


def test_ribbon_search_box_has_tooltip(qtbot):
    ribbon = RibbonBar(["数据", "井", "地震", "编图", "可视化"])
    qtbot.addWidget(ribbon)
    assert ribbon.search_box.toolTip() != ""


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
