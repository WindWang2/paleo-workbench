from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz_seismic import SeismicView

from paleo_workbench.pipeline.assets import SEISMIC_KEY
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.seismic_prediction_helpers import seismic_volume_from_prediction
from paleo_workbench.viz.adapter import VizAdapter


def _primary_resource(project: Any, task: Any, key: str):
    ids = (getattr(task, "input_refs", None) or {}).get(key) or []
    if not ids or project is None:
        return None
    by_id = {r.id: r for r in (getattr(project, "resources", None) or [])}
    return by_id.get(ids[0])


class SeismicViewPanel(QFrame):
    """Center panel embedding geo-viz-engine's SeismicView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicViewPanel")
        self.volume_shape: tuple[int, int, int] | None = None
        self.setStyleSheet(
            f"QFrame#SeismicViewPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.title_label = QLabel("地震预测体")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
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

        self.view = SeismicView(auto_load=False)
        self.stack.addWidget(self.view)
        outer.addWidget(host, 1)

    def _show_empty(self, message: str) -> None:
        self.volume_shape = None
        self.empty_label.setText(message)
        self.empty_label.setHidden(False)
        self.stack.setCurrentWidget(self.empty_label)

    def _show_volume(self, volume) -> None:
        self.volume_shape = tuple(int(value) for value in volume.shape)
        self.view.load_demo(volume)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.view)

    def update_state(self, task, project=None) -> None:
        if task is None:
            self._show_empty("未选择预测任务")
            return

        primary_ids = (getattr(task, "input_refs", None) or {}).get(SEISMIC_KEY) or []
        if project is not None and primary_ids:
            resource = _primary_resource(project, task, SEISMIC_KEY)
            if resource is None:
                self._show_empty("未找到绑定的地震数据资源")
                return
            adapter = VizAdapter()
            ref = adapter.ref_from_resource(resource)
            if ref is None:
                self._show_empty("绑定资源不支持地震体可视化")
                return
            payload = adapter.resolve(ref, project)
            if payload.seismic_volume is not None:
                self._show_volume(payload.seismic_volume)
                return
            message = (payload.message or "").strip() or "无法加载地震体数据"
            self._show_empty(message)
            return

        volume = seismic_volume_from_prediction(task)
        self._show_volume(volume)
