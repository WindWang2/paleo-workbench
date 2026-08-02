from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.hosts.cross_well_host import CrossWellHost
from paleo_workbench.viz.hosts.engine_preview_host import EnginePreviewHost
from paleo_workbench.viz.hosts.paleo_map_host import PaleoMapHost
from paleo_workbench.viz.hosts.seismic_host import SeismicHost
from paleo_workbench.viz.hosts.well_log_host import WellLogHost
from paleo_workbench.viz.hosts.well_section_host import WellSectionHost
from paleo_workbench.viz.hosts.well_tie_host import WellTieHost
from paleo_workbench.viz.models import VizPayload, VizRef
from paleo_workbench.viz.prediction_helpers import active_prediction_task


class VisualizationWorkspace(QFrame):
    """Deep composite visualization module for Paleo Workbench.

    Encapsulates dataset payload routing, multi-tab lazy widget instantiation,
    in-place hydration, synchronized cross-canvas viewports, and snapshot
    exports behind a small 2-method interface (``load``, ``export_snapshot``).
    """

    def __init__(self, parent=None, *, well_state_store=None):
        super().__init__(parent)
        self.setObjectName("CompositeVisualizationPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(100, 100)

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
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tabs.setMinimumSize(100, 100)
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; background: {tokens.BG_SIDEBAR}; }}"
        )

        self.well_host = WellLogHost()
        self.well_section_host = WellSectionHost()
        self.seismic_host = SeismicHost()
        self.cross_well_host = CrossWellHost()
        self.map_host = PaleoMapHost()
        self.well_tie_host = WellTieHost()
        self.engine_host = EnginePreviewHost(well_state_store=well_state_store)

        # Backward-compatible attributes used by tests and trace code.
        self.well_canvas = self.well_host.canvas
        self.seismic_view = self.seismic_host.widget
        self.cross_well_canvas = self.cross_well_host.widget
        self.cross_well_widget = self.cross_well_host.inner
        self.map_canvas = self.map_host.widget
        self.well_tie_canvas = self.well_tie_host.widget
        self.engine_preview = self.engine_host.widget

        self.tabs.addTab(self.well_host.widget, WellLogHost.tab_title)
        self.tabs.addTab(self.well_section_host.widget, WellSectionHost.tab_title)
        self.tabs.addTab(self.seismic_host.widget, SeismicHost.tab_title)

        self.cross_well_scroll = QScrollArea()
        self.cross_well_scroll.setObjectName("CrossWellTabScrollArea")
        self.cross_well_scroll.setWidgetResizable(True)
        self.cross_well_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cross_well_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.cross_well_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.cross_well_scroll.setWidget(self.cross_well_host.widget)
        self.tabs.addTab(self.cross_well_scroll, CrossWellHost.tab_title)

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
        self.load(payload)

    def load(self, payload_or_ref: VizPayload | VizRef) -> None:
        """Deep interface method 1/2: load dataset payload into workspace."""
        if isinstance(payload_or_ref, VizRef):
            payload = VizAdapter().from_ref(payload_or_ref)
        else:
            payload = payload_or_ref

        self.load_payload(payload)

    def export_snapshot(
        self,
        tab_name: str | None = None,
        path: Path | str | None = None,
        format_label: str = "PNG",
    ) -> Any:
        """Deep interface method 2/2: export active tab snapshot image or vector file."""
        widget = self.tabs.currentWidget()
        if widget is None:
            return None

        from paleo_workbench.resources.export_service import (
            export_widget_snapshot,
            view_export_capabilities,
        )

        if path is None:
            return view_export_capabilities(widget)

        return export_widget_snapshot(
            widget,
            Path(path),
            format_label,
            linked_id="viz_workspace",
        )

    def load_payload(self, payload: VizPayload) -> None:
        if payload.kind == "message":
            self._clear_all()
            self.status_label.setText(payload.message or "无可视化数据")
            return

        self._clear_all()
        parts: list[str] = []
        if payload.warning:
            parts.append(payload.warning)

        applied: list[str] = []

        if payload.kind in {"well_log", "prediction", "cross_well"}:
            if self.well_host.apply(payload):
                applied.append(WellLogHost.tab_title)
            if self.well_section_host.apply(payload):
                applied.append(WellSectionHost.tab_title)
            if self.cross_well_host.apply(payload):
                applied.append(CrossWellHost.tab_title)

        if payload.kind in {"seismic", "prediction"} or payload.seismic_path or payload.seismic_volume is not None:
            if self.seismic_host.apply(payload):
                applied.append(SeismicHost.tab_title)

        if payload.kind == "map" or payload.map_features or payload.map_wells:
            if self.map_host.apply(payload):
                applied.append(PaleoMapHost.tab_title)

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

        kind_tab = {
            "well_log": WellLogHost.tab_title,
            "seismic": SeismicHost.tab_title,
            "cross_well": CrossWellHost.tab_title,
            "map": PaleoMapHost.tab_title,
            "engine_preview": EnginePreviewHost.tab_title,
            "prediction": SeismicHost.tab_title if payload.seismic_volume is not None else WellLogHost.tab_title,
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
        self.well_section_host.clear()
        self.seismic_host.clear()
        self.cross_well_host.clear()
        self.map_host.clear()
        self.well_tie_host.clear()
        self.engine_host.clear()

    def _clear_canvases(self) -> None:
        """Alias kept for older tests / callers."""
        self._clear_all()


# Backward-compatible alias
CompositeVisualizationPanel = VisualizationWorkspace

