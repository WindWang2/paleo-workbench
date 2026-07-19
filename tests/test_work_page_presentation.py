"""Structural presentation contracts for multi-panel work pages (chrome + empty)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel
from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.pages.result_summary import ResultSummary
from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel
from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar
from paleo_workbench.ui.pages.seismic_task_panel import SeismicTaskPanel
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
from paleo_workbench.ui.pages.qc_issue_table import QCIssueTable
from paleo_workbench.ui.pages.sequence_boundary_table import SequenceBoundaryTable
from paleo_workbench.ui.pages.sequence_scheme_summary import SequenceSchemeSummary
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel
from paleo_workbench.ui.pages.visualization_summary_panel import VisualizationSummaryPanel
from paleo_workbench.ui.pages.visualization_trace_panel import VisualizationTracePanel
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.ui import tokens


def _dock_titles(widget) -> list[QLabel]:
    return [c for c in widget.findChildren(QLabel) if c.objectName() == "MapDockTitle"]


def _empty_labels(widget) -> list[QLabel]:
    return [c for c in widget.findChildren(QLabel) if c.objectName() == "EmptyStateLabel"]


def test_prediction_side_panels_use_dock_chrome(qtbot):
    task = PredictionTaskPanel()
    evidence = PredictionEvidencePanel()
    qtbot.addWidget(task)
    qtbot.addWidget(evidence)
    assert task.objectName() == "PredictionTaskPanel"
    assert evidence.objectName() == "PredictionEvidencePanel"
    assert _dock_titles(task)
    assert _dock_titles(evidence)
    assert task.task_list.objectName() == "WorkListWidget"
    assert evidence.evidence_list.objectName() == "WorkListWidget"
    # No frame-level stylesheet fighting global dock QSS
    assert "QFrame#PredictionTaskPanel" not in (task.styleSheet() or "")
    assert "QListWidget" not in (evidence.evidence_list.styleSheet() or "")


def test_well_log_and_seismic_centers_empty_state(qtbot):
    well = WellLogCanvasPanel()
    seismic = SeismicViewPanel()
    qtbot.addWidget(well)
    qtbot.addWidget(seismic)
    assert well.objectName() == "WellLogCanvasPanel"
    assert seismic.objectName() == "SeismicViewPanel"
    assert well.title_label.objectName() == "MapDockTitle"
    assert seismic.title_label.objectName() == "MapDockTitle"
    assert well.empty_label.objectName() == "EmptyStateLabel"
    assert seismic.empty_label.objectName() == "EmptyStateLabel"
    well.update_state(None)
    assert well.stack.currentWidget() is well.empty_label
    seismic.update_state(None)
    assert seismic.stack.currentWidget() is seismic.empty_label


def test_seismic_side_panels_dock_titles(qtbot):
    attributes = SeismicAttributePanel()
    context = SeismicContextToolbar()
    control = SeismicControlPanel()
    qtbot.addWidget(attributes)
    qtbot.addWidget(context)
    qtbot.addWidget(control)
    assert _dock_titles(attributes)
    assert _dock_titles(context)
    assert _dock_titles(control)
    assert attributes.objectName() == "SeismicAttributePanel"
    assert context.objectName() == "SeismicContextToolbar"
    assert control.objectName() == "SeismicControlPanel"
    assert "SeismicAttributePanel" in tokens.QSS_TEMPLATE
    assert "SeismicContextToolbar" in tokens.QSS_TEMPLATE


def test_preparation_panels_presentation(qtbot):
    factors = FactorTaskPanel()
    boundary = BoundaryPanel()
    grid = FactorPreviewGrid()
    qtbot.addWidget(factors)
    qtbot.addWidget(boundary)
    qtbot.addWidget(grid)
    assert factors.objectName() == "FactorTaskPanel"
    assert boundary.objectName() == "BoundaryPanel"
    assert factors.horizon_label.objectName() == "MapDockTitle"
    assert _dock_titles(boundary)
    assert grid.header_label.objectName() == "MapDockTitle"
    grid.update_state([])
    empties = _empty_labels(grid)
    assert empties
    assert empties[0].text() == "暂无已生成的单因素图"


def test_visualization_panels_dock_chrome(qtbot):
    summary = VisualizationSummaryPanel()
    trace = VisualizationTracePanel()
    qtbot.addWidget(summary)
    qtbot.addWidget(trace)
    assert summary.objectName() == "VisualizationSummaryPanel"
    assert trace.objectName() == "VisualizationTracePanel"
    assert _dock_titles(summary)
    assert _dock_titles(trace)
    assert summary.asset_list.objectName() == "WorkListWidget"
    # Field values use shared WorkFieldValue (not local color sheets)
    assert trace.task_value.objectName() == "WorkFieldValue"
    assert "color:" not in (trace.task_value.styleSheet() or "")


def test_sequence_and_review_empty_presentation(qtbot):
    target = SequenceTargetPanel()
    table = SequenceBoundaryTable()
    scheme = SequenceSchemeSummary()
    summary = ResultSummary()
    qtbot.addWidget(target)
    qtbot.addWidget(table)
    qtbot.addWidget(scheme)
    qtbot.addWidget(summary)
    assert _dock_titles(target)
    assert _dock_titles(scheme)
    assert table.title_label.objectName() == "MapDockTitle"
    assert table.empty_label.objectName() == "EmptyStateLabel"
    table.update_state(None)
    assert not table.empty_label.isHidden() or table.empty_label.isVisible()
    # Sequence scheme summary matches target panel field chrome
    assert scheme.objectName() == "PanelCard"
    assert scheme.scheme_value.objectName() == "WorkFieldValue"
    assert "color:" not in (scheme.scheme_value.styleSheet() or "")
    assert scheme.save_btn.objectName() == "PrimaryButton"
    assert "PrimaryButton" not in (scheme.save_btn.styleSheet() or "")
    # result summary uses PanelCard + empty export state without local empty color sheet
    assert summary.objectName() == "PanelCard"
    summary.update_state(None, [])
    empties = _empty_labels(summary)
    assert any(e.text() == "暂无导出图件" for e in empties)
    for empty in empties:
        if empty.text() == "暂无导出图件":
            assert empty.objectName() == "EmptyStateLabel"
            assert "color:" not in (empty.styleSheet() or "")


def test_sequence_table_and_primary_buttons_do_not_override_global_roles(qtbot):
    """Construct real widgets and assert no local QHeader/PrimaryButton overrides."""
    table_panel = SequenceBoundaryTable()
    qtbot.addWidget(table_panel)
    table_ss = table_panel.table.styleSheet() or ""
    assert "QHeaderView::section" not in table_ss
    assert "QTableWidget" not in table_ss or table_ss.strip() == ""

    # Review-page QC table must also inherit global header/table roles
    qc_table = QCIssueTable()
    qtbot.addWidget(qc_table)
    qc_ss = qc_table.table.styleSheet() or ""
    assert "QHeaderView::section" not in qc_ss
    assert "QTableWidget" not in qc_ss or qc_ss.strip() == ""

    evidence = PredictionEvidencePanel()
    qtbot.addWidget(evidence)
    # Primary/Secondary buttons on work docks must not re-style #PrimaryButton
    for btn in (evidence.run_btn, evidence.send_btn):
        ss = btn.styleSheet() or ""
        assert "PrimaryButton" not in ss
        assert "QPushButton#" not in ss
    assert evidence.send_btn.objectName() == "PrimaryButton"
    assert evidence.run_btn.objectName() == "SecondaryButton"

    # Global sheet still defines the roles these objectNames rely on
    qss = tokens.QSS_TEMPLATE
    assert "QHeaderView::section" in qss
    assert "QPushButton#PrimaryButton:hover" in qss or "PrimaryButton:hover" in qss


def test_work_page_padding_uses_density_tokens(qtbot):
    factors = FactorTaskPanel()
    from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel

    composite = CompositeVisualizationPanel()
    summary = ResultSummary()
    scheme = SequenceSchemeSummary()
    qtbot.addWidget(factors)
    qtbot.addWidget(composite)
    qtbot.addWidget(summary)
    qtbot.addWidget(scheme)
    for widget in (factors, composite, summary, scheme):
        m = widget.layout().contentsMargins()
        assert m.left() == tokens.PANEL_PADDING
        assert m.top() == tokens.PANEL_PADDING
        assert widget.layout().spacing() == tokens.SPACE_2


def test_work_pages_construct_with_presentation_hooks(qtbot):
    """Full pages construct and expose dock/empty contracts via real widgets."""
    pages = [
        WellLogPredictionPage(),
        SeismicPredictionPage(),
        PreparationPage(),
        VisualizationPage(),
        SequenceFrameworkPage(),
        ReviewExportPage(),
    ]
    for page in pages:
        qtbot.addWidget(page)
    # Prediction center empty hooks
    assert pages[0].canvas_panel.empty_label.objectName() == "EmptyStateLabel"
    assert pages[1].view_panel.empty_label.objectName() == "EmptyStateLabel"
    # QSS still defines work-page dock selectors and control states
    qss = tokens.QSS_TEMPLATE
    assert "PredictionTaskPanel" in qss
    assert "EmptyStateLabel" in qss
    assert "PrimaryButton:hover" in qss or "QPushButton#PrimaryButton:hover" in qss
    assert "QHeaderView::section" in qss
    # Review page primary buttons must not locally override PrimaryButton
    export_btn = pages[5].action_header.export_btn
    assert export_btn.objectName() == "PrimaryButton"
    assert "PrimaryButton" not in (export_btn.styleSheet() or "")
