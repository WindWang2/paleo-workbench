from __future__ import annotations

import time
from typing import Any

import numpy as np

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

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


# ----------------------------------------------------------------------
# Profile interpretation mode (2-D surface) — engine-view probing facts.
#
# These names describe the embedded geoviz.SeismicView's internal layout.
# They are an implementation detail of *this panel* (which wraps the
# engine); callers must configure the surface through the public API
# (``enter_profile_mode`` / ``exit_profile_mode`` / ``set_profile_mode``),
# never by reaching into ``panel.view`` privates themselves.
# ----------------------------------------------------------------------
_PROFILE_MODE_TOOLBAR_HIDDEN_WIDGETS = (
    "_3d_mode_combo",
    "_horizon_menu_btn",
    "_render_menu_btn",
    "_overlay_menu_btn",
    "_slice_label",
    "_readout_label",
)
# Toolbar entries identified by caption because the engine builds them as
# bare QPushButton/QLabel widgets without keeping a named attribute.
_PROFILE_MODE_TOOLBAR_HIDDEN_ACTION_LABELS = frozenset({"3D模式:", "加载 SEGY", "Demo"})
_PROFILE_MODE_SECONDARY_PROFILES = ("_profile_xl", "_profile_t", "_profile_arb")
_QWIDGETSIZE_MAX = 0x00FFFFFF  # mirrors Qt's QWIDGETSIZE_MAX


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
        # Profile interpretation mode (2-D surface) state. ``_profile_mode_restore``
        # keeps the *first-enter* pristine geometry so exit can undo exactly what
        # enter did, even across repeated mode cycles.
        self._profile_mode = False
        self._profile_mode_restore: dict[str, Any] = {}
        self._profile_mode_hidden_widgets: list[QWidget] = []
        self._profile_mode_hidden_actions: list[QAction] = []
        self._profile_mode_inline_header: QWidget | None = None

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
        # ------------------------------------------------------------------
        # Interpretation lifecycle (P1-B): the engine already picks points;
        # this bar turns picks into a versioned horizon interpretation.
        interp_row = QWidget()
        interp_layout = QHBoxLayout(interp_row)
        interp_layout.setContentsMargins(0, 0, 0, 0)
        interp_layout.setSpacing(tokens.SPACE_2)
        self.interp_draft_btn = QPushButton("开始层位解释")
        self.interp_draft_btn.setObjectName("SecondaryButton")
        self.interp_draft_btn.setToolTip("将拾取点收集为层位解释草稿（可撤销编辑）")
        self.interp_draft_btn.clicked.connect(self._start_interpretation_draft)
        self.interp_sync_btn = QPushButton("同步拾取→草稿")
        self.interp_sync_btn.setObjectName("SecondaryButton")
        self.interp_sync_btn.setToolTip("把当前剖面拾取点写入解释草稿（稀疏可撤销）")
        self.interp_sync_btn.clicked.connect(self._sync_picks_to_draft)
        self.interp_undo_btn = QPushButton("撤销")
        self.interp_undo_btn.clicked.connect(self._undo_interpretation)
        self.interp_redo_btn = QPushButton("重做")
        self.interp_redo_btn.clicked.connect(self._redo_interpretation)
        self.interp_save_btn = QPushButton("保存解释版本")
        self.interp_save_btn.setObjectName("SecondaryButton")
        self.interp_save_btn.setToolTip("冻结草稿为不可变解释版本（目录血缘 + 工程引用）")
        self.interp_save_btn.clicked.connect(self._save_interpretation_version)
        self.interp_reload_btn = QPushButton("重开解释")
        self.interp_reload_btn.setObjectName("SecondaryButton")
        self.interp_reload_btn.setToolTip("从工程引用重开最新解释版本为草稿")
        self.interp_reload_btn.clicked.connect(self._reopen_interpretation)
        for btn in (
            self.interp_draft_btn,
            self.interp_sync_btn,
            self.interp_undo_btn,
            self.interp_redo_btn,
            self.interp_save_btn,
            self.interp_reload_btn,
        ):
            interp_layout.addWidget(btn)
        interp_layout.addStretch(1)
        self.interp_status_label = QLabel("")
        self.interp_status_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS}px;"
        )
        interp_layout.addWidget(self.interp_status_label)
        outer.addWidget(interp_row)
        self._interp_draft = None
        self._picking_controller = None
        self._interp_project = None
        self._interp_project_path = None
        self._sync_interp_buttons()
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
    # Profile interpretation mode (public API — the documented entry point)
    #
    # ``enter_profile_mode`` reshapes the panel into a 2-D inline profile
    # interpretation surface: the 3-D renderer and 3-D-only toolbar chrome
    # are hidden, the inline VD profile becomes the main surface and an
    # "Inline 剖面" badge marks the toolbar.  ``exit_profile_mode`` restores
    # the default 3-D + profiles layout.  Both are idempotent and mutually
    # exclusive with the default mode; data-loading paths are unaffected and
    # a volume loaded while in profile mode keeps the 3-D renderer hidden.
    # ------------------------------------------------------------------

    @property
    def profile_mode(self) -> bool:
        """Whether the panel is currently a 2-D profile interpretation surface.

        Read-only by design — switch modes via :meth:`enter_profile_mode` /
        :meth:`exit_profile_mode` / :meth:`set_profile_mode`.
        """
        return self._profile_mode

    def set_profile_mode(self, enabled: bool) -> None:
        """Enter or exit profile mode (boolean convenience alias)."""
        if bool(enabled):
            self.enter_profile_mode()
        else:
            self.exit_profile_mode()

    def enter_profile_mode(self) -> None:
        """Configure the panel as a 2-D inline profile interpretation surface.

        Hides the 3-D renderer, the crossline/time/arbitrary profile panels,
        the inline panel's row header and all 3-D-only toolbar widgets and
        actions; shows an "Inline 剖面" badge on the primary toolbar.  The
        display-mode / colormap / attribute / picking toolbar tools stay
        available for inline/crossline interpretation.  Idempotent: calling
        it while already in profile mode is a no-op.
        """
        if self._profile_mode:
            return
        self._profile_mode = True
        self._apply_profile_mode()

    def exit_profile_mode(self) -> None:
        """Restore the default 3-D + profiles layout.

        Undoes exactly what :meth:`enter_profile_mode` changed (renderer,
        splitter geometry, profile panels, toolbar widgets/actions, badge).
        Idempotent: calling it while already in the default mode is a no-op.
        """
        if not self._profile_mode:
            return
        self._profile_mode = False
        self._restore_default_layout()

    def set_interpretation_bar_visible(self, visible: bool) -> None:
        """Show/hide the horizon-interpretation action row (P1-B bar).

        The bar is a panel-owned feature; hiding it is a layout-space
        decision of the hosting workspace and is orthogonal to profile mode.
        """
        for button in (
            self.interp_draft_btn,
            self.interp_sync_btn,
            self.interp_undo_btn,
            self.interp_redo_btn,
            self.interp_save_btn,
            self.interp_reload_btn,
        ):
            button.setVisible(bool(visible))

    # ------------------------------------------------------------------
    # Profile mode internals — all geoviz.SeismicView private probing is
    # encapsulated here and degrades to no-ops when an engine internal is
    # missing (e.g. tests running against a stub view).
    # ------------------------------------------------------------------

    def _view_main_splitter(self) -> QSplitter | None:
        """The engine's vertical [3-D renderer | profiles] splitter, if any.

        The engine keeps the splitter as a local of ``SeismicView.__init__``,
        so the only stable handle is the renderer's parent widget.
        """
        renderer = getattr(self.view, "_renderer_3d", None)
        parent = renderer.parentWidget() if renderer is not None else None
        return parent if isinstance(parent, QSplitter) else None

    def _view_profile_panel(self, profile_name: str) -> QWidget | None:
        """Wrapper panel (header + profile canvas) for an engine profile."""
        profile = getattr(self.view, profile_name, None)
        return profile.parentWidget() if profile is not None else None

    def _make_inline_badge(self) -> QLabel:
        from paleo_workbench.ui import style as _style

        badge = QLabel("Inline 剖面")
        pal = _style.palette()
        badge.setStyleSheet(
            f"color: {pal['ERROR_RED']}; font-weight: bold;"
            " font-size: 11px; padding: 0 4px;"
        )
        return badge

    def _apply_profile_mode(self) -> None:
        view = self.view
        renderer = getattr(view, "_renderer_3d", None)
        splitter = self._view_main_splitter()
        if not self._profile_mode_restore:
            # First transition into profile mode: capture the pristine
            # geometry so every later exit restores the original layout.
            if renderer is not None:
                self._profile_mode_restore["renderer_min_height"] = (
                    renderer.minimumHeight()
                )
            if splitter is not None:
                sizes = splitter.sizes()
                self._profile_mode_restore["splitter_sizes"] = (
                    sizes if sum(sizes) > 0 else None
                )
                self._profile_mode_restore["splitter_handle_width"] = (
                    splitter.handleWidth()
                )
                self._profile_mode_restore["splitter_collapsible0"] = (
                    splitter.isCollapsible(0)
                )
            inline_panel = self._view_profile_panel("_profile_il")
            inline_layout = inline_panel.layout() if inline_panel is not None else None
            header = (
                inline_layout.itemAt(0).widget()
                if inline_layout is not None and inline_layout.count() > 0
                else None
            )
            if header is not None:
                self._profile_mode_restore["inline_header_max"] = header.maximumHeight()

        # Collapse the 3-D renderer pane; the inline profile takes the space.
        if renderer is not None:
            renderer.setMinimumHeight(0)
            renderer.hide()
        if splitter is not None:
            splitter.setCollapsible(0, True)
            splitter.setHandleWidth(0)
            splitter.setSizes([0, 1000])

        hidden: list[QWidget] = []
        for name in _PROFILE_MODE_SECONDARY_PROFILES:
            panel = self._view_profile_panel(name)
            if panel is not None:
                panel.hide()
                hidden.append(panel)
        # The inline row header is too tall for a compact 2-D surface; the
        # identity moves into the toolbar badge below.
        inline_panel = self._view_profile_panel("_profile_il")
        header = None
        if inline_panel is not None:
            inline_layout = inline_panel.layout()
            if inline_layout is not None and inline_layout.count() > 0:
                header = inline_layout.itemAt(0).widget()
            if header is not None:
                header.hide()
                header.setFixedHeight(0)
        self._profile_mode_inline_header = header

        toolbar = getattr(view, "_toolbar_row1", None)
        badge = getattr(view, "_inline_badge", None)
        if toolbar is not None and badge is None:
            badge = self._make_inline_badge()
            actions = toolbar.actions()
            if actions:
                toolbar.insertWidget(actions[0], badge)
            else:
                toolbar.addWidget(badge)
            # Compat shim: earlier workspaces read this private attribute.
            view._inline_badge = badge
        if badge is not None:
            badge.show()

        for name in _PROFILE_MODE_TOOLBAR_HIDDEN_WIDGETS:
            widget = getattr(view, name, None)
            if widget is not None:
                widget.hide()
                hidden.append(widget)

        hidden_actions: list[QAction] = []
        if toolbar is not None:
            hidden_set = set(hidden)
            for action in toolbar.actions():
                if not action.isVisible():
                    continue
                widget = toolbar.widgetForAction(action)
                label = widget.text().strip() if hasattr(widget, "text") else ""
                if (
                    widget in hidden_set
                    or label in _PROFILE_MODE_TOOLBAR_HIDDEN_ACTION_LABELS
                ):
                    action.setVisible(False)
                    hidden_actions.append(action)
        self._profile_mode_hidden_widgets = hidden
        self._profile_mode_hidden_actions = hidden_actions

    def _restore_default_layout(self) -> None:
        view = self.view
        restore = self._profile_mode_restore
        renderer = getattr(view, "_renderer_3d", None)
        splitter = self._view_main_splitter()
        if renderer is not None:
            renderer.setMinimumHeight(
                int(restore.get("renderer_min_height", 200))
            )
            renderer.show()
        if splitter is not None:
            splitter.setCollapsible(
                0, bool(restore.get("splitter_collapsible0", False))
            )
            splitter.setHandleWidth(int(restore.get("splitter_handle_width", 8)))
            sizes = restore.get("splitter_sizes") or [350, 350]
            splitter.setSizes([int(size) for size in sizes])

        for widget in self._profile_mode_hidden_widgets:
            try:
                widget.show()
            except RuntimeError:  # underlying C++ object already deleted
                continue
        self._profile_mode_hidden_widgets = []
        for action in self._profile_mode_hidden_actions:
            try:
                action.setVisible(True)
            except RuntimeError:
                continue
        self._profile_mode_hidden_actions = []

        header = self._profile_mode_inline_header
        if header is not None:
            header.setMinimumHeight(0)
            header.setMaximumHeight(
                int(restore.get("inline_header_max", _QWIDGETSIZE_MAX))
            )
            header.show()
        self._profile_mode_inline_header = None

        badge = getattr(view, "_inline_badge", None)
        if badge is not None:
            badge.hide()

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

    # ------------------------------------------------------------------
    # Interpretation lifecycle (P1-B)
    # ------------------------------------------------------------------

    def set_project_path(self, path) -> None:
        """Receive the open ``*.paleo.json`` path (AppShell broadcast)."""
        self._interp_project_path = str(path) if path else None

    def interpretation_draft(self):
        return self._interp_draft

    def picked_points(self) -> list:
        """Engine picks in survey coordinates (IL, XL, TWT ms)."""
        return list(getattr(self.view, "_picked_points", None) or [])

    def refresh_pick_overlay(self, points) -> None:
        """Re-push survey-coordinate picks onto the engine panels (reopen path)."""
        clear = getattr(self.view, "_on_clear_picks", None)
        if callable(clear):
            clear()
        else:
            for profile in ("_profile_il", "_profile_xl", "_profile_t"):
                vd = getattr(getattr(self.view, profile, None), "_vd", None)
                if vd is not None:
                    vd.clear_picked_points()
        to_voxel = getattr(self.view, "_survey_to_voxel", None)
        renderer = getattr(self.view, "_renderer_3d", None)
        set_picks = getattr(renderer, "set_horizon_picks", None)
        voxel_points = []
        for il, xl, twt in points:
            try:
                self.view._profile_il._vd.add_picked_point(float(xl), float(twt))
                self.view._profile_xl._vd.add_picked_point(float(il), float(twt))
                self.view._profile_t._vd.add_picked_point(float(il), float(xl))
                if callable(to_voxel):
                    voxel_points.append(to_voxel(float(il), float(xl), float(twt)))
            except Exception:
                continue
        if callable(set_picks) and voxel_points:
            set_picks(voxel_points)
        readout = getattr(self.view, "_readout_label", None)
        if readout is not None:
            readout.setText(f"已载入解释 {len(points)} 点")

    def _interpretation_grid(self):
        from paleo_workbench.viz.picking_controller import SurveyGridGeometry

        return SurveyGridGeometry.from_engine_meta(getattr(self.view, "_meta", None))

    def _start_interpretation_draft(self) -> None:
        from paleo_workbench.viz.picking_controller import HorizonPickingController
        from paleo_workbench.viz.interpretation_lifecycle import open_draft_from_array

        grid = self._interpretation_grid()
        if grid is None or self.volume_shape is None:
            self.interp_status_label.setText("无地震体几何，无法开始解释")
            return
        n_il, n_xl = self.volume_shape[0], self.volume_shape[1]
        # A fresh interpretation is undefined everywhere until picked; NaN is
        # the honest "not interpreted" value (never 0 ms).
        baseline = np.full((n_il, n_xl), np.nan, dtype=np.float32)
        horizon_key = self._horizon_name or "H1"
        self._interp_draft = open_draft_from_array(
            baseline,
            horizon_key=horizon_key,
            name=horizon_key,
            vertical_domain="time",
        )
        self._picking_controller = HorizonPickingController(self, self._interp_draft)
        self._picking_controller.set_grid(grid)
        self.interp_status_label.setText(
            f"解释草稿 {horizon_key}（{n_il}×{n_xl}）— 在剖面拾取后点击「同步拾取→草稿」"
        )
        self._sync_interp_buttons()

    def _sync_picks_to_draft(self) -> None:
        if self._picking_controller is None:
            self._start_interpretation_draft()
            if self._picking_controller is None:
                return
        written = self._picking_controller.sync_picks_into_draft()
        draft = self._interp_draft
        if draft is None:
            return
        status = draft.refresh_status()
        self.interp_status_label.setText(
            f"已写入 {written} 个网格节点 · 草稿状态: {status}"
        )
        self._publish_horizon_selection(draft)
        self._sync_interp_buttons()

    def _undo_interpretation(self) -> None:
        if self._interp_draft is not None and self._interp_draft.undo():
            self._refresh_draft_overlay()

    def _redo_interpretation(self) -> None:
        if self._interp_draft is not None and self._interp_draft.redo():
            self._refresh_draft_overlay()

    def _refresh_draft_overlay(self) -> None:
        if self._picking_controller is None or self._interp_draft is None:
            return
        self._picking_controller.push_draft_to_panel()
        self.interp_status_label.setText(
            f"草稿状态: {self._interp_draft.refresh_status()}"
        )
        self._sync_interp_buttons()

    def _save_interpretation_version(self) -> None:
        from paleo_workbench.viz.interpretation_lifecycle import save_draft_as_new_version

        draft = self._interp_draft
        if draft is None:
            self.interp_status_label.setText("尚无解释草稿")
            return
        if self._interp_project is None or self._interp_project_path is None:
            self.interp_status_label.setText("未绑定工程，无法保存解释版本")
            return
        ref, message = save_draft_as_new_version(
            draft, self._interp_project, self._interp_project_path
        )
        if ref is None:
            self.interp_status_label.setText(f"保存失败: {message}")
            return
        self.interp_status_label.setText(
            f"已保存版本 {ref.current_version_id[:14]}… ({message})"
        )
        self._publish_horizon_selection(draft)
        self._sync_interp_buttons()

    def _reopen_interpretation(self) -> None:
        from paleo_workbench.viz.interpretation_lifecycle import (
            restore_draft_from_project_ref,
        )
        from paleo_workbench.viz.picking_controller import HorizonPickingController

        if self._interp_project is None or self._interp_project_path is None:
            self.interp_status_label.setText("未绑定工程，无法重开解释")
            return
        draft = restore_draft_from_project_ref(
            self._interp_project, self._interp_project_path
        )
        if draft is None:
            self.interp_status_label.setText("工程中尚无层位解释")
            return
        grid = self._interpretation_grid()
        shape = getattr(draft, "shape", None)
        if grid is not None and shape is not None and (grid.n_il, grid.n_xl) != tuple(shape):
            self.interp_status_label.setText(
                "解释网格与当前数据体几何不一致，已取消载入"
            )
            return
        self._interp_draft = draft
        if grid is not None:
            self._picking_controller = HorizonPickingController(self, draft)
            self._picking_controller.set_grid(grid)
            self._picking_controller.push_draft_to_panel()
        self.interp_status_label.setText(f"已重开解释 {draft.name}")
        self._publish_horizon_selection(draft)
        self._sync_interp_buttons()

    def _publish_horizon_selection(self, draft) -> None:
        """Announce the active horizon identity on the coordination bus (D)."""
        controller = self._coordination
        publish = getattr(controller, "publish_horizon_selection", None)
        if callable(publish) and draft is not None:
            publish(str(draft.interpretation_id), source="seismic_view")

    def _sync_interp_buttons(self) -> None:
        draft = self._interp_draft
        has_draft = draft is not None
        self.interp_sync_btn.setEnabled(has_draft)
        self.interp_undo_btn.setEnabled(has_draft and draft.can_undo())
        self.interp_redo_btn.setEnabled(has_draft and draft.can_redo())
        self.interp_save_btn.setEnabled(
            has_draft and self._interp_project is not None and self._interp_project_path is not None
        )
        self.interp_reload_btn.setEnabled(
            self._interp_project is not None and self._interp_project_path is not None
        )

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
        self._interp_draft = None
        self._picking_controller = None
        self._interp_project = None
        self._interp_project_path = None
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
        if project is not None:
            self._interp_project = project
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
