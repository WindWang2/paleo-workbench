from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz import WellLogCanvas, build_qpainter_tracks

from paleo_workbench.pipeline.assets import WELL_KEY
from paleo_workbench.ui import tokens
from paleo_workbench.viz.prediction_helpers import well_log_data_from_prediction
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.workflow.well_log_prediction import merge_prediction_onto_well_log


def _primary_resource(project: Any, task: Any, key: str):
    ids = (getattr(task, "input_refs", None) or {}).get(key) or []
    if not ids or project is None:
        return None
    by_id = {r.id: r for r in (getattr(project, "resources", None) or [])}
    return by_id.get(ids[0])


class WellLogCanvasPanel(QFrame):
    """Center panel embedding geo-viz-engine's WellLogCanvas."""

    canvas_ready = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellLogCanvasPanel")
        self.well_log_data = None
        self._bound_las = False

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

    def is_canvas_ready(self) -> bool:
        return self.stack.currentWidget() is self.canvas and bool(self.canvas.tracks)

    def has_bound_las(self) -> bool:
        return self._bound_las

    def track_kinds(self) -> list[str]:
        """Rough labels of built tracks for tests / diagnostics."""
        kinds: list[str] = []
        for track in list(getattr(self.canvas, "tracks", None) or []):
            kinds.append(type(track).__name__)
        return kinds

    def _show_empty(self, message: str) -> None:
        self.well_log_data = None
        self._bound_las = False
        self.canvas.set_tracks([])
        self.empty_label.setText(message)
        self.empty_label.setHidden(False)
        self.stack.setCurrentWidget(self.empty_label)
        self.canvas_ready.emit(False)

    def _show_well_log(self, data, *, bound_las: bool = False) -> None:
        self.well_log_data = data
        self._bound_las = bound_las
        tracks = build_qpainter_tracks(self.well_log_data)
        self.canvas.set_tracks(tracks)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.canvas)
        name = getattr(data, "well_name", "") or ""
        src = "LAS" if bound_las else "合成"
        track_names = [t.label for t in tracks if getattr(t, "label", None)]
        t_str = f"  [{' | '.join(track_names)}]" if track_names else ""
        self.title_label.setText(f"测井预测剖面 · {name} ({src}){t_str}" if name else f"测井预测剖面{t_str}")
        self.canvas_ready.emit(True)

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
                merged = merge_prediction_onto_well_log(payload.well_log, task)
                self._show_well_log(merged, bound_las=True)
                return
            message = (payload.message or "").strip() or "无法加载井数据"
            self._show_empty(message)
            return

        self._show_well_log(well_log_data_from_prediction(task), bound_las=False)
