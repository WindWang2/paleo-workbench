from __future__ import annotations

from typing import Any, Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from geoviz import WellLogCanvas, build_qpainter_tracks

from paleo_workbench.pipeline.assets import WELL_KEY
from paleo_workbench.ui import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.well_log_load_worker import WellLogLoadWorker
from paleo_workbench.viz import welllog_engine_adapter as engine_adapter
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.prediction_helpers import well_log_data_from_prediction
from paleo_workbench.viz.well_log_load import is_well_log_cached
from paleo_workbench.workflow.well_log_prediction import merge_prediction_onto_well_log

BackendName = Literal["legacy", "engine"]


def _primary_resource(project: Any, task: Any, key: str):
    ids = (getattr(task, "input_refs", None) or {}).get(key) or []
    if not ids or project is None:
        return None
    by_id = {r.id: r for r in (getattr(project, "resources", None) or [])}
    return by_id.get(ids[0])


class WellLogCanvasPanel(QFrame):
    """Center panel: Legacy geoviz canvas and optional WellLogEngine view.

    Explicit backend switch (combo) + env default ``PALEO_USE_WELLLOG_ENGINE``
    (default ON for WellLogEngine; set ``=0``/``legacy`` for Legacy).
    Legacy is never deleted (#169/#174).
    """

    canvas_ready = Signal(bool)
    backend_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellLogCanvasPanel")
        self.well_log_data = None
        self._bound_las = False
        self._project = None
        self._project_path = None
        self._engine_error: str | None = None
        self._engine_load: dict[str, Any] | None = None
        self._engine_plan: engine_adapter.EngineLoadPlan | None = None
        self._engine_view: QWidget | None = None
        self._WellLogView = None
        self._welllog_mod = None
        # #842: cold bound-LAS parses run on a worker thread; LRU hits stay
        # synchronous.  _load_seq guards stale completions across re-selects.
        self._well_log_job = OwnedWorkerJob(self)
        self._well_log_job.released.connect(self._on_well_log_job_released)
        self._pending_state = None
        self._load_seq = 0

        # Default backend from env; host may still switch explicitly.
        self._backend: BackendName = (
            "engine" if engine_adapter.welllog_engine_env_enabled() else "legacy"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        outer.setSpacing(tokens.SPACE_2)

        header = QHBoxLayout()
        header.setSpacing(tokens.SPACE_2)
        self.title_label = QLabel("测井预测剖面")
        self.title_label.setObjectName("MapDockTitle")
        header.addWidget(self.title_label, 1)

        self.backend_combo = QComboBox()
        self.backend_combo.setObjectName("WellLogBackendCombo")
        self.backend_combo.addItem("Legacy (QPainter)", "legacy")
        self.backend_combo.addItem("WellLogEngine", "engine")
        self.backend_combo.setCurrentIndex(0 if self._backend == "legacy" else 1)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_combo)
        header.addWidget(self.backend_combo, 0)
        outer.addLayout(header)

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
        self.stack.addWidget(self.empty_label)  # 0

        self.canvas = WellLogCanvas()
        # Wrap canvas in a scroll area so it scrolls horizontally when the
        # track content is wider than the available space.
        from PySide6.QtWidgets import QScrollArea

        self.canvas_scroll = QScrollArea()
        self.canvas_scroll.setWidget(self.canvas)
        self.canvas_scroll.setWidgetResizable(False)
        self.canvas_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.canvas_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.stack.addWidget(self.canvas_scroll)  # 1 legacy

        self.engine_host = QFrame()
        self.engine_host.setObjectName("WellLogEngineHost")
        engine_layout = QVBoxLayout(self.engine_host)
        engine_layout.setContentsMargins(0, 0, 0, 0)
        self.engine_placeholder = QLabel(
            "WellLogEngine 默认启用但当前不可用。\n"
            "请安装 welllog 绑定；或设 PALEO_USE_WELLLOG_ENGINE=0 使用 Legacy。"
        )
        self.engine_placeholder.setObjectName("EmptyStateLabel")
        self.engine_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.engine_placeholder.setWordWrap(True)
        engine_layout.addWidget(self.engine_placeholder)
        self.stack.addWidget(self.engine_host)  # 2 engine

        outer.addWidget(host, 1)

        self._probe_engine()

    # --- public API ---------------------------------------------------------

    def backend(self) -> str:
        return self._backend

    def set_backend(self, name: str) -> None:
        """Explicit Legacy ↔ WellLogEngine switch (does not remove Legacy)."""
        target: BackendName = "engine" if name == "engine" else "legacy"
        if target == self._backend:
            return
        self._backend = target
        idx = 0 if target == "legacy" else 1
        if self.backend_combo.currentIndex() != idx:
            self.backend_combo.blockSignals(True)
            self.backend_combo.setCurrentIndex(idx)
            self.backend_combo.blockSignals(False)
        # Re-render current data on the newly selected path.
        if self.well_log_data is not None:
            self._show_well_log(self.well_log_data, bound_las=self._bound_las)
        else:
            self._show_empty(self.empty_label.text() or "未选择预测任务")
        self.backend_changed.emit(self._backend)

    def is_canvas_ready(self) -> bool:
        # Engine backend with a live load → ready.
        if (
            self._backend == "engine"
            and self._engine_view is not None
            and self._engine_load is not None
        ):
            return True
        # Legacy fallback: engine selected but unavailable falls back to the
        # legacy QPainter canvas (AC "Legacy 回退"), which is equally ready.
        return self.stack.currentWidget() is self.canvas_scroll and bool(self.canvas.tracks)

    def has_bound_las(self) -> bool:
        return self._bound_las

    def engine_error(self) -> str | None:
        return self._engine_error

    def engine_load_report(self) -> dict[str, Any] | None:
        return self._engine_load

    def shutdown(self) -> None:
        """Release the retained native document before a project switch/close."""
        self._pending_state = None
        self._well_log_job.shutdown(3_000)
        self._release_engine_document()
        self.well_log_data = None
        self._bound_las = False
        self.canvas.set_tracks([])

    def track_kinds(self) -> list[str]:
        """Rough labels of built tracks for tests / diagnostics."""
        if self._backend == "engine" and self._engine_load is not None:
            count = int(self._engine_load.get("track_count") or 0)
            return ["WellLogEngine", *["NativeTrack"] * count]
        kinds: list[str] = []
        for track in list(getattr(self.canvas, "tracks", None) or []):
            kinds.append(type(track).__name__)
        return kinds

    def update_state(self, task, project=None) -> None:
        if project is not None:
            self._project = project
        if task is None:
            self._load_seq += 1
            if self._well_log_job.is_running:
                self._well_log_job.cancel()
            self._show_empty("未选择预测任务")
            return

        primary_ids = (getattr(task, "input_refs", None) or {}).get(WELL_KEY) or []
        if project is not None and primary_ids:
            self._load_seq += 1
            seq = self._load_seq
            resource = _primary_resource(project, task, WELL_KEY)
            if resource is None:
                self._show_empty("未找到绑定的井数据资源")
                return
            adapter = VizAdapter()
            ref = adapter.ref_from_resource(resource)
            if ref is None:
                self._show_empty("绑定资源不支持井数据可视化")
                return
            path = VizAdapter._absolute_path(ref.path or "", project) if ref.path else ""
            if path and is_well_log_cached(path):
                # Warm cache → synchronous fast path (no worker churn).  A
                # stale in-flight load is cancelled so it cannot land later.
                if self._well_log_job.is_running:
                    self._well_log_job.cancel()
                payload = adapter.resolve(ref, project)
                self._apply_bound_payload(payload, task, seq=seq)
                return
            if self._well_log_job.is_running:
                # A cold load is still in flight for a previous task; the newer
                # selection wins once the job releases its thread.
                self._pending_state = (task, project)
                self._well_log_job.cancel()
                return
            # Cold cache → parse on a worker thread, merge + render on
            # completion (#842; the merge itself is short GUI-thread work).
            self._show_empty("正在加载绑定井数据…")
            worker = WellLogLoadWorker(ref, project, adapter=adapter)
            self._well_log_job.start(
                worker,
                terminal_signals=(worker.finished, worker.failed, worker.cancelled),
                result_connections=(
                    (worker.finished, lambda payload, t=task, s=seq: self._on_bound_las_resolved(payload, t, s)),
                    (worker.failed, lambda message, s=seq: self._on_bound_las_failed(message, s)),
                ),
                cancel=worker.cancel,
                target=project,
            )
            return

        # Synthetic (no bound resource): invalidate any in-flight bound load.
        self._load_seq += 1
        if self._well_log_job.is_running:
            self._well_log_job.cancel()
        self._show_well_log(well_log_data_from_prediction(task), bound_las=False)

    def _on_well_log_job_released(self) -> None:
        pending = self._pending_state
        self._pending_state = None
        if pending is not None:
            task, project = pending
            self.update_state(task, project)

    def _apply_bound_payload(self, payload, task, *, seq: int) -> None:
        if seq != self._load_seq:
            return
        if payload.well_log is not None:
            merged = merge_prediction_onto_well_log(payload.well_log, task)
            self._show_well_log(merged, bound_las=True)
            return
        message = (payload.message or "").strip() or "无法加载井数据"
        self._show_empty(message)

    def _on_bound_las_resolved(self, payload, task, seq: int) -> None:
        self._apply_bound_payload(payload, task, seq=seq)

    def _on_bound_las_failed(self, message: str, seq: int) -> None:
        if seq != self._load_seq:
            return
        self._show_empty(f"无法加载井数据: {message}")

    # --- internals ----------------------------------------------------------

    def _on_backend_combo(self, _index: int) -> None:
        data = self.backend_combo.currentData()
        self.set_backend("engine" if data == "engine" else "legacy")

    def _probe_engine(self) -> None:
        mod, view_cls, _ = engine_adapter.try_import_welllog()
        self._welllog_mod = mod
        self._WellLogView = view_cls
        if view_cls is None:
            self._engine_error = "welllog 绑定未安装"
        else:
            self._engine_error = None

    def _ensure_engine_view(self) -> QWidget | None:
        if self._engine_view is not None:
            return self._engine_view
        self._probe_engine()
        if self._WellLogView is None:
            return None
        try:
            view = self._WellLogView()
        except Exception as exc:  # pragma: no cover - env dependent
            self._engine_error = f"WellLogView 创建失败: {exc}"
            return None
        layout = self.engine_host.layout()
        assert layout is not None
        self.engine_placeholder.hide()
        layout.addWidget(view, 1)
        self._engine_view = view
        return view

    def _release_engine_document(self) -> None:
        if self._engine_view is not None:
            layout = self.engine_host.layout()
            if layout is not None:
                layout.removeWidget(self._engine_view)
            self._engine_view.hide()
            self._engine_view.setParent(None)
            self._engine_view.deleteLater()
            self._engine_view = None
        self._engine_load = None
        self._engine_plan = None

    def _show_empty(self, message: str) -> None:
        self.well_log_data = None
        self._bound_las = False
        self._release_engine_document()
        self.canvas.set_tracks([])
        self.empty_label.setText(message)
        self.empty_label.setHidden(False)
        self.stack.setCurrentWidget(self.empty_label)
        self.canvas_ready.emit(False)

    def _show_well_log(self, data, *, bound_las: bool = False) -> None:
        # Stage-12: overlay formation tops from selected correlation interpretation
        project = getattr(self, "_project", None)
        if project is not None and data is not None:
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
        self.well_log_data = data
        self._bound_las = bound_las
        name = getattr(data, "well_name", "") or ""
        src = "LAS" if bound_las else "合成"

        if self._backend == "engine":
            ok = self._show_engine(data, name=name, src=src)
            if ok:
                return
            # Fall through to Legacy so the page remains usable (AC: Legacy 回退).
            self._engine_error = self._engine_error or "WellLogEngine 路径失败"
            # Keep backend selection as engine for explicit retry, but paint legacy.

        # A Legacy selection or an Engine failure must release the old native
        # Session and its pinned buffers.  Otherwise engine → legacy switching
        # leaves an invisible retained document alive indefinitely.
        self._release_engine_document()

        tracks = build_qpainter_tracks(self.well_log_data)
        self.canvas.set_tracks(tracks)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.canvas_scroll)
        track_names = [t.label for t in tracks if getattr(t, "label", None)]
        t_str = f"  [{' | '.join(track_names)}]" if track_names else ""
        suffix = ""
        if self._backend == "engine" and self._engine_error:
            suffix = f" · Engine 不可用，已回退 Legacy ({self._engine_error})"
        self.title_label.setText(
            f"测井预测剖面 · {name} ({src}){t_str}{suffix}"
            if name
            else f"测井预测剖面{t_str}{suffix}"
        )
        self.canvas_ready.emit(True)

    def _show_engine(self, data, *, name: str, src: str) -> bool:
        plan = engine_adapter.adapt_well_log_data(data)
        if plan.primary is None:
            self._engine_error = "无可用曲线提交到 WellLogEngine"
            self.engine_placeholder.setText(
                f"WellLogEngine 无法加载井数据。\n{self._engine_error}"
            )
            self.engine_placeholder.show()
            self.stack.setCurrentWidget(self.engine_host)
            self.canvas_ready.emit(False)
            return False

        # Resource/well switches must release the old Session (and its pinned
        # NumPy buffers). Updates to the same document intentionally retain the
        # live view so viewport, selection, and native LOD remain available.
        if (
            self._engine_plan is not None
            and self._engine_plan.document_id != plan.document_id
        ):
            self._release_engine_document()

        view = self._ensure_engine_view()
        if view is None:
            self.engine_placeholder.setText(
                f"WellLogEngine 不可用。\n{self._engine_error or '未知错误'}\n"
                "可切换到 Legacy (QPainter)。"
            )
            self.engine_placeholder.show()
            self.stack.setCurrentWidget(self.engine_host)
            self.canvas_ready.emit(False)
            return False

        try:
            load = engine_adapter.update_plan_to_view(
                view, plan, self._engine_plan
            )
            self._engine_load = load
            self._engine_plan = plan
            self._engine_error = None
            self.engine_placeholder.hide()
            view.show()
            self.empty_label.setHidden(True)
            self.stack.setCurrentWidget(self.engine_host)
            extra = f" · {load.get('curve_count', 0)} 曲线 / {load.get('track_count', 0)} 轨"
            if plan.lithology_bounds or plan.facies_bounds:
                extra += f" · 岩性{len(plan.lithology_bounds)}/相{len(plan.facies_bounds)}"
            self.title_label.setText(
                f"测井预测剖面 · {name} ({src}) · Engine · "
                f"{load.get('update_kind', 'full_replace')}{extra}"
                if name
                else f"测井预测剖面 · Engine{extra}"
            )
            self.canvas_ready.emit(True)
            return True
        except Exception as exc:
            self._engine_error = f"{exc.__class__.__name__}: {exc}"
            self._release_engine_document()
            self.engine_placeholder.setText(
                f"WellLogEngine 加载失败。\n{self._engine_error}\n"
                "已可切换回 Legacy。"
            )
            self.engine_placeholder.show()
            self.stack.setCurrentWidget(self.engine_host)
            self.canvas_ready.emit(False)
            return False
