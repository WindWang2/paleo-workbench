from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedLayout, QVBoxLayout

from geoviz import SeismicView

from paleo_workbench.pipeline.assets import SEISMIC_KEY
from paleo_workbench.ui import tokens
from paleo_workbench.viz.seismic_prediction_helpers import seismic_volume_from_prediction
from paleo_workbench.viz.adapter import VizAdapter


class SeismicCursorGate:
    """Debounce gate for seismic cursor publications (#1029 producer).

    A publication goes out when at least ``min_interval_ms`` elapsed since
    the previous one OR the inline moved by more than ``il_jump`` lines —
    slow drags stay quiet while big jumps never wait out the timer. Pure
    logic with an injectable clock so the behaviour is unit-testable.
    """

    def __init__(
        self,
        min_interval_ms: float = 30.0,
        il_jump: float = 1.0,
        clock=None,
    ) -> None:
        self.min_interval_ms = float(min_interval_ms)
        self.il_jump = float(il_jump)
        self._clock = clock or time.monotonic
        self._last_pub_ms: float | None = None
        self._last_il: float | None = None

    def should_publish(self, il: float) -> bool:
        now_ms = self._clock() * 1000.0
        il_val = float(il)
        if self._last_pub_ms is None:
            publish = True
        else:
            elapsed = now_ms - self._last_pub_ms
            jumped = (
                self._last_il is None or abs(il_val - self._last_il) > self.il_jump
            )
            publish = elapsed >= self.min_interval_ms or jumped
        if publish:
            self._last_pub_ms = now_ms
            self._last_il = il_val
        return publish


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
        self._expected_segy_path: str | None = None
        self._segy_session_active = True

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
        self.title_label.hide()

        self.attribute_strip = QFrame()
        self.attribute_strip.setObjectName("SeismicAttributeStrip")
        attribute_layout = QHBoxLayout(self.attribute_strip)
        attribute_layout.setContentsMargins(0, 0, 0, 0)
        attribute_layout.setSpacing(tokens.SPACE_2)
        for label, status in (
            ("振幅能量", "已加载"),
            ("频率响应", "可选"),
            ("连续性", "可选"),
            ("构造特征", "可选"),
        ):
            attribute_layout.addWidget(self._attribute_card(label, status))
        self.attribute_strip.hide()

        host = QFrame()
        host.setObjectName("SeismicViewHost")
        self.stack = QStackedLayout(host)
        self.stack.setContentsMargins(0, 0, 0, 0)

        self.empty_label = QLabel("未选择预测任务")
        self.empty_label.setObjectName("EmptyStateLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty_label)

        self.view = SeismicView(auto_load=False)
        if hasattr(self.view, "segy_loaded"):
            self.view.segy_loaded.connect(self._on_segy_loaded)
        self.stack.addWidget(self.view)
        # Multi-view cursor producer (#1029): tap the engine's EXISTING
        # per-profile cursor signals — the same ones that drive the internal
        # crosshair linking — and republish them on the coordination bus.
        # No engine subclassing/patching; missing internals degrade to a no-op.
        self._coordination = None
        self._cursor_gate = SeismicCursorGate()
        self._connect_engine_cursor_signals()
        outer.addWidget(host, 1)
        # #1079: auto-switch 2-D browsing to the chunked store the moment a
        # background transcode of the displayed SEG-Y completes.
        try:
            from paleo_workbench.seismic_lifecycle import add_derived_hook

            add_derived_hook(self._on_derived_store_registered)
        except Exception:
            pass

    def __del__(self) -> None:
        # pytest and other non-interactive owners may drop the Python wrapper
        # without delivering QWidget close/deferred-delete events.  The
        # engine's SliceReadWorker is unparented by design, so make this final
        # best-effort cleanup explicit as well.
        try:
            self.shutdown()
        except Exception:
            pass

    @staticmethod
    def _attribute_card(label_text: str, status_text: str) -> QFrame:
        card = QFrame()
        card.setObjectName("SeismicAttributeCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1)
        layout.setSpacing(0)
        label = QLabel(label_text)
        label.setObjectName("SeismicAttributeCardLabel")
        status = QLabel(status_text)
        status.setObjectName("SeismicAttributeCardStatus")
        layout.addWidget(label)
        layout.addWidget(status)
        return card

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

    # ------------------------------------------------------------------
    # Multi-view cursor producer (#1029)
    # ------------------------------------------------------------------

    def attach_coordination(self, controller) -> None:
        """Receive the shell's coordination controller (app_shell wires this).

        The panel never reaches for a global singleton; without an attached
        controller cursor moves simply stay panel-local.
        """
        self._coordination = controller

    def locate_position(self, il: int, xl: int, twt: float | None = None) -> bool:
        """Navigate the seismic profiles to a survey position (scenario A/B).

        ``twt`` may be None when no calibration authored a time — only the
        inline/crossline slices move then. Safe no-op (False) when no volume
        is loaded or the engine internals needed for the survey→voxel
        mapping are unavailable.
        """
        view = self.view
        if not self.is_view_ready():
            return False
        to_voxel = getattr(view, "_survey_to_voxel", None)
        renderer = getattr(view, "_renderer_3d", None)
        set_position = getattr(renderer, "set_position_external", None)
        if not callable(to_voxel) or not callable(set_position):
            return False
        try:
            il_idx, xl_idx, t_idx = to_voxel(float(il), float(xl), float(twt or 0.0))
            set_position("inline", int(il_idx))
            set_position("crossline", int(xl_idx))
            if twt is not None:
                set_position("time", int(t_idx))
        except Exception:
            return False
        return True

    def notify_cursor(self, iline_value: float, xl_value: float, twt_ms: float) -> bool:
        """Publish a seismic cursor position to the coordination bus.

        Values must be LOGICAL survey numbers (inline/crossline) plus TWT in
        milliseconds — the same units the engine's coordinate readout uses.
        Debounced by ``SeismicCursorGate`` (30 ms or >1 inline jump). Returns
        True when a publication actually went out.
        """
        controller = self._coordination
        if controller is None:
            return False
        try:
            il = float(iline_value)
            xl = float(xl_value)
            twt = float(twt_ms)
        except (TypeError, ValueError):
            return False
        if not self._cursor_gate.should_publish(il):
            return False
        publish = getattr(controller, "publish_seismic_cursor", None)
        if not callable(publish):
            return False
        publish(int(round(il)), int(round(xl)), twt)
        return True

    def _connect_engine_cursor_signals(self) -> None:
        """Connect the engine's existing ``cursor_moved_3d`` profile signals.

        The three orthogonal profile canvases (IL/XL/T) each emit
        ``cursor_moved_3d(h, v, slice_type)`` on mouse move, in survey units.
        Guarded by ``hasattr`` so engine internals evolving never breaks the
        panel — the producer then simply stays disconnected.
        """
        for profile_name in ("_profile_il", "_profile_xl", "_profile_t"):
            vd = getattr(getattr(self.view, profile_name, None), "_vd", None)
            signal = getattr(vd, "cursor_moved_3d", None)
            if signal is None:
                continue
            try:
                signal.connect(self._on_engine_cursor)
            except (RuntimeError, TypeError):
                continue

    def _on_engine_cursor(self, h_val: float, v_val: float, slice_type: str) -> None:
        """Republish an engine cursor move as logical (IL, XL, TWT ms).

        Mirrors the engine's own ``_on_cursor_3d`` mapping: the moved panel
        contributes two axes, the third comes from the current slice sliders,
        converted to survey numbers through the engine's existing
        ``_preview_to_survey_coords`` (handles downsample + iline_start/step).
        """
        view = self.view
        current = getattr(view, "_current_il_xl_t", None)
        if callable(current):
            il_pos, xl_pos, _t_pos = current()
        else:
            renderer = getattr(view, "_renderer_3d", None)
            il_pos = getattr(renderer, "_il_pos", 0)
            xl_pos = getattr(renderer, "_xl_pos", 0)
            _t_pos = getattr(renderer, "_t_pos", 0)
        to_survey = getattr(view, "_preview_to_survey_coords", None)
        if callable(to_survey):
            try:
                il_val, xl_val, t_val = to_survey("inline", il_pos)
            except Exception:
                il_val, xl_val, t_val = float(il_pos), float(xl_pos), float(_t_pos)
        else:
            il_val, xl_val, t_val = float(il_pos), float(xl_pos), float(_t_pos)
        if slice_type == "inline":
            # h = crossline number, v = TWT ms; inline from the slider
            self.notify_cursor(il_val, h_val, v_val)
        elif slice_type == "crossline":
            # h = inline number, v = TWT ms; crossline from the slider
            self.notify_cursor(h_val, xl_val, v_val)
        elif slice_type == "time":
            # h = inline number, v = crossline number; TWT from the slider
            self.notify_cursor(h_val, v_val, t_val)

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
        self._expected_segy_path = None
        self.view.cancel_pending_segy_load()
        self.volume_shape = None
        self.empty_label.setText(message)
        self.empty_label.setHidden(False)
        self.stack.setCurrentWidget(self.empty_label)
        self.view_ready.emit(False)

    def _attach_chunked_store_if_available(self, segy_path) -> None:
        """Switch 2-D browsing to the chunked store for this SEG-Y, if the
        project has a fresh DERIVED zarr for it (#1079 auto-switch)."""
        if not segy_path or not hasattr(self.view, "set_chunked_volume"):
            return
        try:
            from paleo_workbench.catalog import get_catalog_service
            from paleo_workbench.seismic_lifecycle import derived_store_for_path

            catalog = get_catalog_service()
            if catalog is None:
                return
            store = derived_store_for_path(catalog, segy_path)
            if store is not None and store.is_dir():
                self.view.set_chunked_volume(str(store))
        except Exception:
            pass  # browsing stays on the RAW fallback path — never fatal

    def _on_derived_store_registered(self, raw_version_id, raw_path, store_path) -> None:
        """Lifecycle hook: a transcode finished; swap browsing if it is the
        volume this panel is currently showing."""
        if (
            self._segy_session_active
            and raw_path
            and self._expected_segy_path
            and str(raw_path) == str(self._expected_segy_path)
            and hasattr(self.view, "set_chunked_volume")
        ):
            try:
                self.view.set_chunked_volume(str(store_path))
            except Exception:
                pass

    def shutdown(self) -> None:
        """Cancel retained SEGY/slice work before the project session closes."""

        self._segy_session_active = False
        self._expected_segy_path = None
        cleanup = getattr(self.view, "cleanup", None)
        if callable(cleanup):
            cleanup()
        else:
            cancel = getattr(self.view, "cancel_pending_segy_load", None)
            if callable(cancel):
                cancel()
        self.volume_shape = None
        self.stack.setCurrentWidget(self.empty_label)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    def event(self, event: QEvent) -> bool:  # type: ignore[override]
        # QWidget parents can dispose this panel through ``deleteLater``
        # without a close event.  Stop SeismicView's retained slice worker in
        # both paths so it cannot outlive a discarded project shell.
        if event.type() == QEvent.Type.DeferredDelete:
            self.shutdown()
        return super().event(event)

    def _show_volume(self, volume) -> None:
        self._expected_segy_path = None
        self.view.cancel_pending_segy_load()
        self.volume_shape = tuple(int(value) for value in volume.shape)
        self.view.load_demo(volume)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.view)
        if self._horizon_name:
            self.set_horizon_context(self._horizon_name)
        self.view_ready.emit(True)

    def _show_segy_loading(self, path: str) -> None:
        """Keep the engine surface visible while its worker prepares SEGY."""
        self._segy_session_active = True
        path = str(path)
        already_loaded = (
            self._expected_segy_path == path and self.volume_shape is not None
        )
        if already_loaded:
            # The same SEGY is already loaded for this session (task refresh /
            # inference write-back repeat update_state): don't cancel and
            # re-read the whole file every time — that flashes the loading
            # state and multiplies IO.
            self._expected_segy_path = path
            self.empty_label.setHidden(True)
            self.stack.setCurrentWidget(self.view)
            self.view_ready.emit(True)
            return
        self._expected_segy_path = path
        self.volume_shape = None
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.view)
        self.view_ready.emit(False)
        self.view.load_segy_async(path)

    def _on_segy_loaded(self, result) -> None:
        # SeismicView has its own generation filtering.  Keep an additional
        # panel/session guard so a queued terminal signal can never revive a
        # panel after project shutdown or after a different task is selected.
        if (
            not self._segy_session_active
            or getattr(result, "path", None) != self._expected_segy_path
        ):
            return
        volume = getattr(result, "volume", None)
        if volume is None:
            return
        self.volume_shape = tuple(int(value) for value in volume.shape)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.view)
        self._attach_chunked_store_if_available(getattr(result, "path", None))
        if self._horizon_name:
            self.set_horizon_context(self._horizon_name)
        self.view_ready.emit(True)

    def show_resource(self, resource, project=None) -> bool:
        """Display one Data Management seismic resource without a prediction task."""
        if resource is None or getattr(resource, "type", "") != "seismic":
            self._show_empty("所选资源不是地震数据")
            return False
        adapter = VizAdapter()
        ref = adapter.ref_from_resource(resource)
        if ref is None:
            self._show_empty("所选资源不支持地震体可视化")
            return False
        payload = adapter.resolve(ref, project)
        if payload.seismic_volume is not None:
            self._show_volume(payload.seismic_volume)
            return True
        path = (payload.seismic_path or "").strip()
        if path:
            self._show_segy_loading(path)
            return True
        message = (payload.message or "").strip() or "无法加载地震体数据"
        self._show_empty(message)
        return False

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
            self.show_resource(resource, project)
            return

        volume = seismic_volume_from_prediction(task)
        self._show_volume(volume)
