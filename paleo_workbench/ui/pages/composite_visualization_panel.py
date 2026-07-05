from __future__ import annotations

from PySide6.QtWidgets import QFrame, QTabWidget, QVBoxLayout

from geoviz_seismic import SeismicView
from geoviz_well_log import WellLogCanvas, build_qpainter_tracks
from geoviz_well_log.cross_well_widget import CrossWellWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task, well_log_data_from_prediction
from paleo_workbench.ui.pages.seismic_prediction_helpers import seismic_volume_from_prediction


class CompositeVisualizationPanel(QFrame):
    """Center panel hosting well-log, seismic, and cross-well geo-viz widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CompositeVisualizationPanel")
        self.setStyleSheet(
            f"QFrame#CompositeVisualizationPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; background: {tokens.BG_SEARCH}; }}"
        )

        self.well_canvas = WellLogCanvas()
        self.seismic_view = SeismicView(auto_load=False)
        self.cross_well_widget = CrossWellWidget()

        self.tabs.addTab(self.well_canvas, "测井")
        self.tabs.addTab(self.seismic_view, "地震")
        self.tabs.addTab(self.cross_well_widget, "连井")
        layout.addWidget(self.tabs, 1)

    def update_state(self, prediction_tasks: list | tuple | None) -> None:
        task = active_prediction_task(prediction_tasks)
        if task is None:
            self.well_canvas.set_tracks([])
            self.cross_well_widget.clear_all()
            return

        data = well_log_data_from_prediction(task)
        tracks = build_qpainter_tracks(data)
        self.well_canvas.set_tracks(tracks)

        volume = seismic_volume_from_prediction(task)
        self.seismic_view.load_demo(volume)

        self.cross_well_widget.clear_all()
        for index in range(2):
            canvas = WellLogCanvas()
            canvas.set_tracks(build_qpainter_tracks(data))
            self.cross_well_widget.add_canvas(canvas, f"Well-{index + 1}")
