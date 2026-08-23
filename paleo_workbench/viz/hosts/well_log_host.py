from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from geoviz import WellLogCanvas, build_qpainter_tracks

from paleo_workbench import tokens
from paleo_workbench.viz import welllog_engine_adapter as engine_adapter
from paleo_workbench.viz.models import VizPayload


class TrackVisibilityDialog(QDialog):
    """Modal dialog for customizing visible well log tracks."""

    def __init__(self, tracks: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙️ 设置显示井道")
        self.resize(360, 480)
        self._tracks = tracks

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_3)

        info_lbl = QLabel("请勾选需要在绘图画布中显示的井道：")
        info_lbl.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-weight: 500;")
        layout.addWidget(info_lbl)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        box_layout = QVBoxLayout(container)
        box_layout.setSpacing(tokens.SPACE_2)

        self._checkboxes: list[tuple[object, QCheckBox]] = []
        for track in tracks:
            label = getattr(track, "label", "未命名井道")
            cb = QCheckBox(label, container)
            cb.setChecked(getattr(track, "_visible", True))
            box_layout.addWidget(cb)
            self._checkboxes.append((track, cb))

        box_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选", self)
        select_none_btn = QPushButton("反选", self)

        select_all_btn.clicked.connect(self._select_all)
        select_none_btn.clicked.connect(self._invert_selection)

        btn_layout.addWidget(select_all_btn)
        btn_layout.addWidget(select_none_btn)
        btn_layout.addStretch()

        ok_btn = QPushButton("确定", self)
        ok_btn.setStyleSheet(f"background: {tokens.PRIMARY}; color: white; font-weight: bold;")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _select_all(self) -> None:
        for _, cb in self._checkboxes:
            cb.setChecked(True)

    def _invert_selection(self) -> None:
        for _, cb in self._checkboxes:
            cb.setChecked(not cb.isChecked())

    def apply_visibility(self) -> None:
        for track, cb in self._checkboxes:
            track._visible = cb.isChecked()


class WellLogHost:
    """Standalone single-well viewer, intentionally rendered by Legacy QPainter.

    The visualisation workspace defaults to the mature, fully exportable
    GeoViz QPainter canvas. Native WellLogEngine support remains available to
    specialised hosts, but must not change the single-well screen according to
    environment configuration.
    """

    tab_title = "测井"

    def __init__(self) -> None:
        self.widget = QFrame()
        self.widget.setObjectName("WellLogHostContainer")
        self.widget.setStyleSheet("QFrame#WellLogHostContainer { background-color: #ffffff; }")
        self.widget.setAutoFillBackground(True)
        self.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.widget.setMinimumSize(100, 100)
        # Export capability resolution must come from the active backend, not
        # from duck-typing the (possibly empty) legacy canvas: the engine
        # surface clears the legacy tracks, and claiming vector export from
        # that empty canvas produced blank "successful" SVG/PDF files (#381).
        self.widget.export_capabilities = self.export_capabilities

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
        )
        layout.setSpacing(tokens.SPACE_2)

        # Header toolbar with track summary and settings button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(tokens.SPACE_2)

        self.track_bar = QLabel("测井道列表: 未加载数据")
        self.track_bar.setObjectName("WellLogTrackBar")
        self.track_bar.setStyleSheet(
            f"QLabel {{ background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px;"
            f" padding: 6px 12px;"
            f" color: {tokens.TEXT_SECONDARY};"
            f" font-size: {tokens.FONT_SIZE_BASE};"
            f" font-weight: 500; }}"
        )
        self.track_bar.setWordWrap(True)
        header_layout.addWidget(self.track_bar, 1)

        self.settings_btn = QPushButton("⚙️ 设置显示井道")
        self.settings_btn.setStyleSheet(
            f"QPushButton {{ background: {tokens.BG_HEADER};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px;"
            f" padding: 6px 12px;"
            f" color: {tokens.TEXT_PRIMARY};"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {tokens.BG_SEARCH}; border-color: {tokens.PRIMARY}; }}"
        )
        self.settings_btn.clicked.connect(self._open_track_settings)
        header_layout.addWidget(self.settings_btn)

        layout.addLayout(header_layout)

        self.view_host = QFrame()
        self.view_stack = QStackedLayout(self.view_host)
        self.view_stack.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("WellLogScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scroll_area.setMinimumSize(100, 100)
        self.scroll_area.setStyleSheet(
            f"QScrollArea#WellLogScrollArea {{ border: 1px solid {tokens.BORDER};"
            f" background-color: #ffffff; }}"
        )
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.canvas = WellLogCanvas()
        self.widget.canvas = self.canvas
        self.scroll_area.setWidget(self.canvas)
        self.view_stack.addWidget(self.scroll_area)

        self.engine_host = QFrame()
        self.engine_host.setObjectName("WellLogHostEngineSurface")
        engine_layout = QVBoxLayout(self.engine_host)
        engine_layout.setContentsMargins(0, 0, 0, 0)
        self.engine_placeholder = QLabel("WellLogEngine 不可用，已使用 Legacy (QPainter)")
        self.engine_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.engine_placeholder.setWordWrap(True)
        engine_layout.addWidget(self.engine_placeholder)
        self.view_stack.addWidget(self.engine_host)
        layout.addWidget(self.view_host, 1)

        self._engine_view: QWidget | None = None
        self._engine_plan: engine_adapter.EngineLoadPlan | None = None
        self._engine_load: dict | None = None
        self._WellLogView = None
        self._engine_error: str | None = None
        self._probe_engine()

    def _open_track_settings(self) -> None:
        if self._engine_plan is not None and self.view_stack.currentWidget() is self.engine_host:
            QMessageBox.information(
                self.widget,
                "设置显示井道",
                "WellLogEngine 当前保留完整文档；请切换到 Legacy 调整兼容画布井道。",
            )
            return
        if not self.canvas.tracks:
            QMessageBox.information(self.widget, "设置显示井道", "当前未加载测井道数据")
            return
        dialog = TrackVisibilityDialog(self.canvas.tracks, self.widget)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply_visibility()
            self.canvas._cache_dirty = True
            self.canvas.update()
            self._update_track_bar()

    def _update_track_bar(self) -> None:
        if self._engine_plan is not None and self.view_stack.currentWidget() is self.engine_host:
            names = [curve.mnemonic for curve in self._engine_plan.curves]
            interval_count = len(self._engine_plan.intervals)
            suffix = f" · 区间 {interval_count}" if interval_count else ""
            self.track_bar.setText(
                f"📋 WellLogEngine ({len(names)} 曲线):  {' | '.join(names)}{suffix}"
            )
            return
        visible_tracks = [
            t for t in self.canvas.tracks if getattr(t, "_visible", True)
        ]
        track_names = [getattr(t, "label", str(t)) for t in visible_tracks if getattr(t, "label", None)]
        if track_names:
            names_str = "  |  ".join(track_names)
            self.track_bar.setText(f"📋 显示中井道 ({len(track_names)}/{len(self.canvas.tracks)} 道):  {names_str}")
        else:
            self.track_bar.setText("📋 显示中井道 (0 道): 已隐藏全部井道")

    def has_data(self) -> bool:
        """Return True when either the native engine or the legacy canvas holds data."""
        if self._engine_plan is not None and self.view_stack.currentWidget() is self.engine_host:
            return bool(self._engine_plan.curves)
        return bool(self.canvas.tracks)

    def clear(self) -> None:
        self._release_engine_document()
        self.canvas.set_tracks([])
        self.view_stack.setCurrentWidget(self.scroll_area)
        self.settings_btn.setEnabled(True)
        self.track_bar.setText("测井道列表: 未加载数据")

    def _probe_engine(self) -> None:
        _mod, view_cls, _errors = engine_adapter.try_import_welllog()
        self._WellLogView = view_cls
        self._engine_error = None if view_cls is not None else "welllog 绑定未安装"

    def _ensure_engine_view(self) -> QWidget | None:
        if self._engine_view is not None:
            return self._engine_view
        self._probe_engine()
        if self._WellLogView is None:
            return None
        try:
            view = self._WellLogView()
        except Exception as exc:  # pragma: no cover - platform/binding specific
            self._engine_error = f"WellLogView 创建失败: {exc}"
            return None
        engine_layout = self.engine_host.layout()
        assert engine_layout is not None
        engine_layout.addWidget(view, 1)
        self.engine_placeholder.hide()
        self._engine_view = view
        return view

    def _release_engine_document(self) -> None:
        if self._engine_view is not None:
            engine_layout = self.engine_host.layout()
            if engine_layout is not None:
                engine_layout.removeWidget(self._engine_view)
            self._engine_view.hide()
            self._engine_view.setParent(None)
            self._engine_view.deleteLater()
            self._engine_view = None
        self._engine_plan = None
        self._engine_load = None

    def _show_engine(self, data) -> bool:
        plan = engine_adapter.adapt_well_log_data(data)
        if plan.primary is None:
            self._engine_error = "无可用曲线提交到 WellLogEngine"
            return False
        if (
            self._engine_plan is not None
            and self._engine_plan.document_id != plan.document_id
        ):
            self._release_engine_document()
        view = self._ensure_engine_view()
        if view is None:
            return False
        try:
            self._engine_load = engine_adapter.update_plan_to_view(
                view, plan, self._engine_plan
            )
        except Exception as exc:
            self._engine_error = f"{exc.__class__.__name__}: {exc}"
            self._release_engine_document()
            return False
        self._engine_plan = plan
        self.canvas.set_tracks([])
        self.engine_placeholder.hide()
        view.show()
        self.view_stack.setCurrentWidget(self.engine_host)
        self.settings_btn.setEnabled(True)
        self._update_track_bar()
        return True

    def export_capabilities(self) -> frozenset[str]:
        """Formats this host can honestly export for the active backend.

        The legacy QPainter canvas is the only vector-exportable surface.
        When the WellLogEngine surface owns the view the legacy canvas is
        intentionally empty (``set_tracks([])``), and duck-typing it would
        yield a blank "successful" SVG/PDF/PNG.  The engine surface only
        supports a widget grab (PNG, same limitation as #169).
        """
        if self.view_stack.currentWidget() is self.engine_host:
            return frozenset({"PNG"})
        if self.canvas.tracks:
            return frozenset({"PNG", "SVG", "PDF"})
        return frozenset()

    def set_project(self, project, project_path=None) -> None:
        """Optional project binding for Stage-12 correlation top overlays."""
        self._project = project
        self._project_path = project_path

    def apply(self, payload: VizPayload) -> bool:
        data = payload.well_log
        if data is None and payload.well_logs:
            data = payload.well_logs[0]
        if data is None:
            self.clear()
            return False

        # Stage-12: inject selected correlation interpretation tops as markers
        project = getattr(self, "_project", None)
        if project is not None:
            try:
                from paleo_workbench.workflow.correlation_overlay import (
                    apply_correlation_tops_to_well_log_data,
                )

                data = apply_correlation_tops_to_well_log_data(
                    data,
                    project,
                    well_name=str(getattr(data, "well_name", "") or ""),
                    project_path=getattr(self, "_project_path", None),
                )
            except Exception:
                pass

        # Single-well visualisation is deliberately Legacy by default (and
        # independent of PALEO_USE_WELLLOG_ENGINE). This also keeps its
        # editable display tracks and vector exports consistently available.
        self._release_engine_document()
        tracks = build_qpainter_tracks(data)
        self.canvas.set_tracks(tracks)
        self.view_stack.setCurrentWidget(self.scroll_area)
        self.settings_btn.setEnabled(True)
        self._update_track_bar()

        return True
