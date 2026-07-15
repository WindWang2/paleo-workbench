from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz import WellLogCanvas, build_qpainter_tracks

from paleo_workbench.pipeline.assets import WELL_KEY
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import well_log_data_from_prediction
from paleo_workbench.viz.adapter import VizAdapter


def _primary_resource(project: Any, task: Any, key: str):
    ids = (getattr(task, "input_refs", None) or {}).get(key) or []
    if not ids or project is None:
        return None
    by_id = {r.id: r for r in (getattr(project, "resources", None) or [])}
    return by_id.get(ids[0])


class WellLogCanvasPanel(QFrame):
    """Center panel embedding geo-viz-engine's WellLogCanvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellLogCanvasPanel")
        self.well_log_data = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        outer.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("测井预测剖面")
        self.title_label.setObjectName("MapDockTitle")
        outer.addWidget(self.title_label)

        host = QFrame()
        host.setStyleSheet(
            f"QFrame {{ background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; }}"
        )
        self.stack = QStackedLayout(host)
        self.stack.setContentsMargins(0, 0, 0, 0)

        self.empty_label = QLabel("未选择预测任务")
        self.empty_label.setObjectName("EmptyStateLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty_label)

        self.canvas = WellLogCanvas()
        self.stack.addWidget(self.canvas)
        outer.addWidget(host, 1)

    def _show_empty(self, message: str) -> None:
        self.well_log_data = None
        self.canvas.set_tracks([])
        self.empty_label.setText(message)
        self.empty_label.setHidden(False)
        self.stack.setCurrentWidget(self.empty_label)

    def _show_well_log(self, data) -> None:
        self.well_log_data = data
        self.canvas.set_tracks(build_qpainter_tracks(self.well_log_data))
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.canvas)

    def update_state(self, task, project=None) -> None:
        if task is None:
            self._show_empty("未选择预测任务")
            return

        primary_ids = (getattr(task, "input_refs", None) or {}).get(WELL_KEY) or []
        if project is not None and primary_ids:
            resource = _primary_resource(project, task, WELL_KEY)
            if resource is None:
                self._show_empty("未找到绑定的井数据资源")
                return
            adapter = VizAdapter()
            ref = adapter.ref_from_resource(resource)
            if ref is None:
                self._show_empty("绑定资源不支持井数据可视化")
                return
            payload = adapter.resolve(ref, project)
            if payload.well_log is not None:
                self._show_well_log(payload.well_log)
                return
            message = (payload.message or "").strip() or "无法加载井数据"
            self._show_empty(message)
            return

        self._show_well_log(well_log_data_from_prediction(task))
