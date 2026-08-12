from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QSplitter, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from geoviz import CancellationToken

from paleo_workbench.ui.pages.factor_prepare_worker import FactorPrepareWorker
from paleo_workbench.ui.pages.contour_draft_worker import (
    ContourDraftResult,
    ContourDraftWorker,
    commit_contour_drafts,
)
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel
from paleo_workbench.ui.pages.well_table_panel import WellTablePanel
from paleo_workbench.workflow.factor_prepare_scheduler import (
    FactorPrepareBatchResult,
    FactorPrepareProgress,
    build_prepare_snapshot,
    commit_prepare_batch_result,
)
from paleo_workbench.workflow.well_qc import qc_summary, run_well_table_qc
from paleo_workbench.workflow.well_table import (
    attach_well_table_to_factor_task,
    sample_points_from_well_table,
    well_table_from_factor_task,
)

# Back-compat for tests that imported FactorPrepareResult from the page module.
FactorPrepareResult = FactorPrepareBatchResult


class PreparationPage(QWidget):
    """制备 page: tasks, WellTable, preview grid, boundary + async interpolation."""

    # Emitted after staged prepare results are committed to project.factor_map_tasks
    factor_maps_updated = Signal()
    # Emitted after ContourDraft generation mutates contour_drafts / maps
    contour_drafts_updated = Signal()
    generate_requested = Signal(str)  # method — app may handle when no project bound

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PreparationPage")
        self._project = None
        self._tasks: list = []
        self._prepare_generation = 0
        self._prepare_job = OwnedWorkerJob(self)
        self._prepare_job.released.connect(self._clear_prepare_job)
        self._contour_job = OwnedWorkerJob(self)
        self._contour_job.released.connect(self._clear_contour_job)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_4)

        content = QHBoxLayout()
        content.setSpacing(tokens.SPACE_4)

        self.task_panel = FactorTaskPanel()
        content.addWidget(self.task_panel, 0)

        center = QSplitter(Qt.Orientation.Vertical)
        self.preview_grid = FactorPreviewGrid()
        self.well_table_panel = WellTablePanel()
        center.addWidget(self.preview_grid)
        center.addWidget(self.well_table_panel)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 2)
        content.addWidget(center, 1)

        self.boundary_panel = BoundaryPanel()
        content.addWidget(self.boundary_panel, 0)

        outer.addLayout(content, 1)

        self.task_panel.generate_requested.connect(self._on_generate_requested)
        self.task_panel.contour_draft_requested.connect(self._on_contour_draft_requested)
        self.well_table_panel.run_qc_btn.clicked.connect(self._on_run_well_qc)

    def set_project(self, project) -> None:
        """Bind the live ProjectDocument so batch generate can mutate factor_map_tasks."""
        # Project switch supersedes any in-flight prepare generation.
        if project is not self._project and self.is_prepare_running():
            self._prepare_generation += 1
            self._prepare_job.cancel()
        self._project = project
        self._refresh_well_table_view()

    def update_state(self, tasks: list) -> None:
        self._tasks = list(tasks or [])
        self.task_panel.update_state(self._tasks)
        self.preview_grid.update_state(self._tasks)
        self._refresh_well_table_view()

    def is_prepare_running(self) -> bool:
        return self._prepare_job.is_running

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Quit in-flight prepare thread (call before shell deleteLater)."""
        contour_joined = self._contour_job.shutdown(wait_ms)
        prepare_joined = self._prepare_job.shutdown(wait_ms)
        self._set_generate_enabled(True)
        return contour_joined and prepare_joined

    def _shutdown_contour_worker(self, wait_ms: int) -> None:
        self._contour_job.shutdown(wait_ms)
        if not self.is_prepare_running():
            self._set_generate_enabled(True)

    def is_contour_running(self) -> bool:
        return self._contour_job.is_running

    def _set_generate_enabled(self, enabled: bool) -> None:
        self.task_panel.generate_btn.setEnabled(enabled)
        self.task_panel.contour_draft_btn.setEnabled(enabled)
        self.well_table_panel.run_qc_btn.setEnabled(enabled)

    def _refresh_well_table_view(self) -> None:
        table = self._resolve_display_well_table()
        self.well_table_panel.update_from_well_table(table)

    def _resolve_display_well_table(self):
        """Prefer project.well_tables; else derive from first factor task samples."""
        if self._project is None:
            return None
        tables = getattr(self._project, "well_tables", None) or []
        if tables:
            return tables[0]
        tasks = list(getattr(self._project, "factor_map_tasks", None) or self._tasks or [])
        for task in tasks:
            params = getattr(task, "parameters", None) or {}
            points = params.get("sample_points") if isinstance(params, dict) else None
            if points:
                return well_table_from_factor_task(task)
        return None

    def _on_run_well_qc(self) -> None:
        if self._project is None:
            QMessageBox.information(self, "井点 QC", "请先打开或绑定工程。")
            return
        try:
            self._run_well_qc_impl()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "井点 QC 失败",
                f"{exc.__class__.__name__}: {exc}",
            )

    def _run_well_qc_impl(self) -> None:
        table = None
        if self._project.well_tables:
            table = self._project.well_tables[0]
        elif self._project.factor_map_tasks:
            task = self._project.factor_map_tasks[0]
            table = well_table_from_factor_task(task)
            attach_well_table_to_factor_task(self._project, table, task)
        if table is None or not table.rows:
            QMessageBox.information(self, "井点 QC", "没有可检测的井点数据。")
            return
        run_well_table_qc(table)
        # Keep first table in project
        if not self._project.well_tables:
            self._project.well_tables.append(table)
        else:
            self._project.well_tables[0] = table
        # Sync cleaned sample_points back onto linked tasks
        for task in self._project.factor_map_tasks:
            if task.well_table_id == table.id or task is self._project.factor_map_tasks[0]:
                params = dict(task.parameters or {})
                params["sample_points"] = sample_points_from_well_table(table)
                task.parameters = params
                task.well_table_id = table.id
        self._refresh_well_table_view()
        summary = qc_summary(table)
        QMessageBox.information(
            self,
            "井点 QC",
            f"完成：ok={summary.get('ok', 0)} outlier={summary.get('outlier', 0)} "
            f"invalid_ratio={summary.get('invalid_ratio', 0)} missing={summary.get('missing', 0)}",
        )

    def _on_generate_requested(self, method: str) -> None:
        method = method or self.task_panel.selected_method()
        if self._project is None:
            self.generate_requested.emit(method)
            return
        if self.is_prepare_running():
            QMessageBox.information(self, "单因素图", "正在生成中，请稍候…")
            return
        self._start_prepare_worker(method)

    def _start_prepare_worker(self, method: str) -> None:
        self._set_generate_enabled(False)
        self._prepare_generation += 1
        generation = self._prepare_generation
        token = CancellationToken()
        # Snapshot on the host thread so scientific inputs match Stage-4 fingerprints.
        snapshot = build_prepare_snapshot(
            self._project,
            generation=generation,
            method=method,
        )
        self.task_panel.summary_label.setText(
            f"制备中… 任务 {len(snapshot.tasks)} · 生成代 {generation}"
        )
        worker = FactorPrepareWorker(
            self._project,
            method=method,
            cancellation_token=token,
            generation=generation,
            snapshot=snapshot,
        )
        self._prepare_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed, worker.cancelled),
            result_connections=(
                (worker.completed, self._on_prepare_completed),
                (worker.failed, self._on_prepare_failed),
                (worker.progress, self._on_prepare_progress),
                (worker.cancelled, self._on_prepare_cancelled),
            ),
            cancel=token.cancel,
            target=self._project,
        )

    def _clear_prepare_job(self) -> None:
        if not self.is_contour_running():
            self._set_generate_enabled(True)

    def _on_prepare_progress(self, update: FactorPrepareProgress) -> None:
        if update.generation != self._prepare_generation:
            return
        if self._prepare_job.target is not self._project:
            return
        msg = update.message or update.phase
        self.task_panel.summary_label.setText(
            f"制备中：复用 {update.clean} · 需计算 {update.dirty} · "
            f"已完成 {update.completed}/{update.total_tasks}"
            + (f" · {msg}" if msg else "")
        )

    def _on_prepare_completed(self, result: FactorPrepareBatchResult) -> None:
        target = self._prepare_job.target
        if target is None or self._project is not target:
            return
        if int(result.generation) != int(self._prepare_generation):
            # Superseded by a newer prepare request or project switch.
            return
        discarded = commit_prepare_batch_result(
            target,
            result,
            expected_generation=self._prepare_generation,
        )
        self.update_state(target.factor_map_tasks)
        self.factor_maps_updated.emit()
        extra = ""
        if discarded:
            extra = f" · 丢弃过期 {len(discarded)}"
        self.task_panel.summary_label.setText(
            f"已制备 {sum(1 for t in target.factor_map_tasks if t.status == 'complete')} / "
            f"{len(target.factor_map_tasks)} 个单因素图"
            f" · 复用 {result.clean_count} · 计算 {result.executed_count}{extra}"
        )

    def _on_prepare_failed(self, message: str) -> None:
        if self._prepare_job.target is not self._project:
            return
        # Async failures must not enter a nested modal loop while the shell may
        # be rebuilding. Keep the error visible and recoverable in-page.
        self.task_panel.summary_label.setText(f"单因素图生成失败：{message}")

    def _on_prepare_cancelled(self) -> None:
        if self._prepare_job.target is not self._project:
            return
        self.task_panel.summary_label.setText("单因素图生成已取消")

    def _on_contour_draft_requested(self) -> None:
        """Schedule ContourDraft extraction outside the GUI thread."""
        if self._project is None:
            QMessageBox.information(self, "等值线初稿", "请先打开或绑定工程。")
            return
        if self.is_prepare_running():
            QMessageBox.information(self, "等值线初稿", "单因素图仍在生成中。")
            return
        if self.is_contour_running():
            return
        self._set_generate_enabled(False)
        token = CancellationToken()
        worker = ContourDraftWorker(self._project, cancellation_token=token)
        self._contour_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_contour_completed),
                (worker.failed, self._on_contour_failed),
            ),
            cancel=token.cancel,
            target=self._project,
        )

    def _on_contour_completed(self, result: ContourDraftResult) -> None:
        target = self._contour_job.target
        if target is None or self._project is not target:
            return
        drafts = commit_contour_drafts(target, result)
        if not drafts:
            QMessageBox.information(
                self,
                "等值线初稿",
                "没有可提取的单因素网格。请先「批量生成单因素图」。",
            )
            return
        self.update_state(self._project.factor_map_tasks)
        self.contour_drafts_updated.emit()
        QMessageBox.information(
            self,
            "等值线初稿",
            f"已生成 {len(drafts)} 份等值线初稿并推送到编图。",
        )

    def _on_contour_failed(self, message: str) -> None:
        if self._contour_job.target is not self._project:
            return
        self.task_panel.summary_label.setText(f"等值线初稿失败：{message}")

    def _clear_contour_job(self) -> None:
        if not self.is_prepare_running():
            self._set_generate_enabled(True)
