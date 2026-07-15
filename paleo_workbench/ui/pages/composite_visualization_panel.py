from __future__ import annotations

from PySide6.QtWidgets import QFrame, QTabWidget, QVBoxLayout

from geoviz import (
    CrossWellCanvas,
    PaleoMapCanvas,
    SeismicView,
    WellLogCanvas,
    build_qpainter_tracks,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task, well_log_data_from_prediction
from paleo_workbench.ui.pages.seismic_prediction_helpers import seismic_volume_from_prediction
from paleo_workbench.viz.models import VizPayload


class CompositeVisualizationPanel(QFrame):
    """Center panel hosting well-log, seismic, cross-well, and paleomap widgets.

    Uses the same primary package canvas types as geo-viz-engine pages:
    WellLogCanvas, SeismicView, CrossWellCanvas, PaleoMapCanvas.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CompositeVisualizationPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; background: {tokens.BG_SEARCH}; }}"
        )

        self.well_canvas = WellLogCanvas()
        self.seismic_view = SeismicView(auto_load=False)
        # Primary public surface for 连井 (matches geo-viz CrossWellPage).
        self.cross_well_canvas = CrossWellCanvas()
        self.cross_well_widget = self.cross_well_canvas.widget
        self.map_canvas = PaleoMapCanvas()

        self.tabs.addTab(self.well_canvas, "测井")
        self.tabs.addTab(self.seismic_view, "地震")
        self.tabs.addTab(self.cross_well_canvas, "连井")
        self.tabs.addTab(self.map_canvas, "古地理")
        layout.addWidget(self.tabs, 1)

    def _tab_index(self, title: str) -> int:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == title:
                return index
        return 0

    def update_state(self, prediction_tasks: list | tuple | None) -> None:
        """Legacy mock fallback when no explicit VizRef is open."""
        task = active_prediction_task(prediction_tasks)
        if task is None:
            self._clear_canvases()
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

    def load_payload(self, payload: VizPayload) -> None:
        if payload.kind == "message":
            # Soft-fail path: clear stale graphics so prior ref does not linger.
            self._clear_canvases()
            return

        if payload.kind in {"well_log", "prediction"} and payload.well_log is not None:
            tracks = build_qpainter_tracks(payload.well_log)
            self.well_canvas.set_tracks(tracks)
            # Keep 连井 in sync with primary well-log package canvas API.
            self.cross_well_widget.clear_all()
            well_name = str(getattr(payload.well_log, "well_name", "") or payload.label or "Well")
            canvas = WellLogCanvas()
            canvas.set_tracks(tracks)
            self.cross_well_widget.add_canvas(canvas, well_name)
            self.tabs.setCurrentIndex(self._tab_index("测井"))

        if payload.seismic_volume is not None:
            self.seismic_view.load_demo(payload.seismic_volume)
            if payload.kind == "seismic":
                self.tabs.setCurrentIndex(self._tab_index("地震"))

        if payload.kind == "map":
            feats = payload.map_features or []
            wells = payload.map_wells or []
            self.map_canvas.load_features(feats, period_name=payload.period_name, wells=wells)
            self.tabs.setCurrentIndex(self._tab_index("古地理"))

    def _clear_canvases(self) -> None:
        """Reset well / cross-well / map views; seismic has no empty-clear API."""
        self.well_canvas.set_tracks([])
        self.cross_well_widget.clear_all()
        self.map_canvas.load_features([], period_name="", wells=[])
