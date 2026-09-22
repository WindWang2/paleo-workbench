"""Empty-state labels must use the EmptyStateLabel objectName so the shared
QSS rule (muted TEXT_SECONDARY color) applies. Companion to the focus-ring
audit in test_focus_states.py.

Scope: key empty / no-selection placeholders surfaced to the user.
"""
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel


def test_reader_empty_label_uses_empty_state_label(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    assert panel.empty_label.objectName() == "EmptyStateLabel"


def test_reader_message_label_uses_empty_state_label(qtbot):
    # The message slot doubles as a placeholder/loading surface, so it shares
    # the EmptyStateLabel styling.
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    assert panel.message_label.objectName() == "EmptyStateLabel"


def test_inspector_empty_state_clears_on_none(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    assert panel.metadata_table.rowCount() == 0


def test_inspector_empty_label_uses_empty_state_label(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    assert panel.empty_label.objectName() == "EmptyStateLabel"


def test_inspector_empty_label_shown_when_no_selection(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    # isHidden() is controlled explicitly in update_asset, unlike isVisible()
    # which depends on the headless display state.
    assert panel.empty_label.isHidden() is False


def test_inspector_empty_label_hidden_when_asset_selected(qtbot):
    from paleo_workbench.project.models import ResourceItem

    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(
        name="well1.las", path="/data/well1.las", type="well_log", format="LAS",
        status="parsed",
    )
    panel.update_asset(res)
    assert panel.empty_label.isHidden() is True


# ---------------------------------------------------------------------------
# Work-page empty-state audit.
#
# Each work page (prediction / sequence / viz / prep / review) surfaces empty
# states through child panels. This block verifies that every placeholder those
# panels build uses the shared ``EmptyStateLabel`` objectName so the muted
# QSS rule in tokens.QSS_TEMPLATE applies consistently.
#
# Panels audited as HAVING a dedicated EmptyStateLabel:
#   - WellLogCanvasPanel      (prediction center)
#   - SeismicViewPanel        (prediction center)
#   - SequenceBoundaryTable   (sequence center)
#   - FactorPreviewGrid       (prep center + viz via PreparationPage reuse)
#   - ResultSummary           (review export list)
#   - MapCanvasPanel          (mapping center; covered by its own test file)
#
# Panels audited as NOT YET having an EmptyStateLabel placeholder (tracked in
# the report, not fixed here per task scope):
#   - CompositeVisualizationPanel  (clears canvases; no placeholder label)
#   - VisualizationSummaryPanel    (empty QListWidget; no label)
#   - VisualizationTracePanel      ("-" value stubs; no label)
#   - SequenceTargetPanel          ("未设置" value stubs; no label)
#   - QCIssueTable                 (empty table; no label)
# ---------------------------------------------------------------------------


def test_well_log_canvas_empty_label_uses_empty_state_label(qtbot):
    from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel

    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(None)
    assert panel.empty_label.objectName() == "EmptyStateLabel"


def test_seismic_view_empty_label_uses_empty_state_label(qtbot):
    from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel

    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    panel.update_state(None)
    assert panel.empty_label.objectName() == "EmptyStateLabel"


def test_sequence_boundary_empty_label_uses_empty_state_label(qtbot):
    from paleo_workbench.project.models import StratigraphicFramework
    from paleo_workbench.ui.pages.sequence_boundary_table import SequenceBoundaryTable

    table = SequenceBoundaryTable()
    qtbot.addWidget(table)
    table.update_state(StratigraphicFramework())
    assert table.empty_label.objectName() == "EmptyStateLabel"
    # No boundaries -> placeholder is the visible surface, not hidden.
    assert table.empty_label.isHidden() is False


def test_factor_preview_empty_label_uses_empty_state_label(qtbot):
    from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid

    grid = FactorPreviewGrid()
    qtbot.addWidget(grid)
    # An empty task list yields no completed factors, so the grid builds its
    # "暂无已生成的单因素图" EmptyStateLabel.
    grid.update_state([])
    assert grid._empty_label is not None
    assert grid._empty_label.objectName() == "EmptyStateLabel"


def test_result_summary_export_empty_label_uses_empty_state_label(qtbot):
    from PySide6.QtWidgets import QLabel

    from paleo_workbench.ui.pages.result_summary import ResultSummary

    widget = ResultSummary()
    qtbot.addWidget(widget)
    # ResultSummary.__init__ calls update_state([], []) so the export list is
    # empty and a placeholder EmptyStateLabel is present.
    empty_labels = [
        child for child in widget.findChildren(QLabel)
        if child.objectName() == "EmptyStateLabel"
    ]
    assert len(empty_labels) == 1
    assert empty_labels[0].text() == "暂无导出图件"
