from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz import SeismicView

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

    # Surface state changes for the control dock
    view_ready = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicViewPanel")
        self.volume_shape: tuple[int, int, int] | None = None
        self._horizon_name: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        outer.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("地震预测体")
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

        self.view = SeismicView(auto_load=False)
        self.stack.addWidget(self.view)
        outer.addWidget(host, 1)

    def is_view_ready(self) -> bool:
        return self.stack.currentWidget() is self.view and bool(
            getattr(self.view, "is_ready", lambda: False)()
        )

    def set_display_mode(self, mode: str) -> None:
        """Bridge workbench control → SeismicView (vd / wiggle)."""
        if hasattr(self.view, "set_display_mode"):
            self.view.set_display_mode(str(mode or "vd"))

    def display_mode(self) -> str:
        if hasattr(self.view, "display_mode"):
            try:
                return str(self.view.display_mode() or "vd")
            except Exception:
                return "vd"
        return "vd"

    def set_attribute_label(self, label: str) -> bool:
        """Select an attribute on the embedded SeismicView combo if present."""
        combo = getattr(self.view, "_attr_combo", None)
        if combo is None:
            return False
        text = str(label or "").strip()
        if not text:
            return False
        idx = combo.findText(text)
        if idx < 0:
            return False
        combo.setCurrentIndex(idx)
        return True

    def attribute_label(self) -> str:
        combo = getattr(self.view, "_attr_combo", None)
        if combo is None:
            return "振幅"
        return combo.currentText() or "振幅"

    def set_well_tie_enabled(self, enabled: bool) -> bool:
        """Toggle Auto-Tie / 井震标定 panel on SeismicView."""
        btn = getattr(self.view, "_well_tie_btn", None)
        if btn is None:
            # Fallback: call private handler if button not built yet
            handler = getattr(self.view, "_on_well_tie_toggled", None)
            if callable(handler):
                handler(bool(enabled))
                return True
            return False
        btn.setChecked(bool(enabled))
        return True

    def set_horizon_context(self, horizon: str) -> None:
        """Show target horizon context on the panel title / view slice label."""
        self._horizon_name = str(horizon or "").strip()
        if self._horizon_name:
            self.title_label.setText(f"地震预测体 · {self._horizon_name}")
        else:
            self.title_label.setText("地震预测体")
        label = getattr(self.view, "_slice_label", None)
        if label is not None and self._horizon_name:
            current = label.text() or ""
            if "目标层位" not in current:
                label.setText(f"{current}  目标层位:{self._horizon_name}".strip())

    def _show_empty(self, message: str) -> None:
        self.volume_shape = None
        self.empty_label.setText(message)
        self.empty_label.setHidden(False)
        self.stack.setCurrentWidget(self.empty_label)
        self.view_ready.emit(False)

    def _show_volume(self, volume) -> None:
        self.volume_shape = tuple(int(value) for value in volume.shape)
        self.view.load_demo(volume)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.view)
        if self._horizon_name:
            self.set_horizon_context(self._horizon_name)
        self.view_ready.emit(True)

    def update_state(self, task, project=None) -> None:
        if task is None:
            self._show_empty("未选择预测任务")
            return

        # Prefer stratigraphy / task metadata for horizon caption
        horizon = ""
        meta = getattr(task, "model_metadata", None) or {}
        if isinstance(meta, dict):
            horizon = str(meta.get("target_horizon") or "")
        if not horizon and project is not None:
            horizon = str(getattr(getattr(project, "stratigraphy", None), "target_horizon", "") or "")
        self.set_horizon_context(horizon)

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
