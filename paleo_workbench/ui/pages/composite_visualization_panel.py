from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QTabWidget, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.hosts import (
    CrossWellHost,
    EnginePreviewHost,
    PaleoMapHost,
    SeismicHost,
    WellLogHost,
    WellTieHost,
)
from paleo_workbench.viz.models import VizPayload


class CompositeVisualizationPanel(QFrame):
    """Thin tab coordinator over modular geo-viz-engine hosts.

    Each tab is an engine product surface (WellLog / SeismicView / CrossWell /
    PaleoMap / WellTie / GeoVizEngine preview). Payload routing is kind-driven;
    hosts own widget APIs so the workbench does not reimplement render logic.
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

        self.status_label = QLabel("")
        self.status_label.setObjectName("WorkFieldLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; background: {tokens.BG_SEARCH}; }}"
        )

        self.well_host = WellLogHost()
        self.seismic_host = SeismicHost()
        self.cross_well_host = CrossWellHost()
        self.map_host = PaleoMapHost()
        self.well_tie_host = WellTieHost()
        self.engine_host = EnginePreviewHost()

        # Backward-compatible attributes used by tests and trace code.
        self.well_canvas = self.well_host.canvas
        self.seismic_view = self.seismic_host.widget
        self.cross_well_canvas = self.cross_well_host.widget
        self.cross_well_widget = self.cross_well_host.inner
        self.map_canvas = self.map_host.widget
        self.well_tie_canvas = self.well_tie_host.widget
        self.engine_preview = self.engine_host.widget

        self.tabs.addTab(self.well_host.widget, WellLogHost.tab_title)
        self.tabs.addTab(self.seismic_host.widget, SeismicHost.tab_title)
        self.tabs.addTab(self.cross_well_host.widget, CrossWellHost.tab_title)
        self.tabs.addTab(self.map_host.widget, PaleoMapHost.tab_title)
        self.tabs.addTab(self.well_tie_host.widget, WellTieHost.tab_title)
        self.tabs.addTab(self.engine_host.widget, EnginePreviewHost.tab_title)
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
            self._clear_all()
            self.status_label.setText("选择左侧资产或等待预测任务…")
            return
        payload = VizAdapter().from_prediction(task)
        self.load_payload(payload)

    def load_payload(self, payload: VizPayload) -> None:
        if payload.kind == "message":
            self._clear_all()
            self.status_label.setText(payload.message or "无可视化数据")
            return

        # Clear all hosts so switching asset kinds never leaves stale graphics.
        self._clear_all()

        parts: list[str] = []
        if payload.warning:
            parts.append(payload.warning)

        # Always attempt relevant hosts; kind selects primary tab.
        applied: list[str] = []

        if payload.kind in {"well_log", "prediction", "cross_well"}:
            if self.well_host.apply(payload):
                applied.append(WellLogHost.tab_title)
            if self.cross_well_host.apply(payload):
                applied.append(CrossWellHost.tab_title)

        if payload.kind in {"seismic", "prediction"} or payload.seismic_path or payload.seismic_volume is not None:
            if self.seismic_host.apply(payload):
                applied.append(SeismicHost.tab_title)

        if payload.kind == "map" or payload.map_features or payload.map_wells:
            if self.map_host.apply(payload):
                applied.append(PaleoMapHost.tab_title)

        # Well-tie workspace: any well log and/or seismic volume can seed the 7 tracks.
        if (
            payload.kind in {"well_log", "seismic", "prediction", "cross_well"}
            or payload.well_log is not None
            or payload.well_logs
            or payload.seismic_volume is not None
        ):
            if self.well_tie_host.apply(payload):
                applied.append(WellTieHost.tab_title)

        if payload.kind == "engine_preview" or payload.prepared is not None:
            if self.engine_host.apply(payload):
                applied.append(EnginePreviewHost.tab_title)

        # Primary tab by kind
        kind_tab = {
            "well_log": WellLogHost.tab_title,
            "seismic": SeismicHost.tab_title,
            "cross_well": CrossWellHost.tab_title,
            "map": PaleoMapHost.tab_title,
            "engine_preview": EnginePreviewHost.tab_title,
            "prediction": WellLogHost.tab_title,
        }.get(payload.kind)
        if kind_tab:
            self.tabs.setCurrentIndex(self._tab_index(kind_tab))

        if applied:
            parts.insert(0, f"已加载: {payload.label} → {', '.join(dict.fromkeys(applied))}")
        else:
            parts.insert(0, f"未能加载: {payload.label}")
        self.status_label.setText(" · ".join(p for p in parts if p))

    def _clear_all(self) -> None:
        self.well_host.clear()
        self.seismic_host.clear()
        self.cross_well_host.clear()
        self.map_host.clear()
        self.well_tie_host.clear()
        self.engine_host.clear()

    def _clear_canvases(self) -> None:
        """Alias kept for older tests / callers."""
        self._clear_all()
