from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.catalog import get_catalog_service
from paleo_workbench.prediction.inference_service import (
    link_run_to_domain_task,
    materialize_prediction_task,
    resolve_prediction_inputs,
    start_inference,
)
from paleo_workbench.prediction.inference_worker import InferenceWorker
from paleo_workbench.prediction.providers import (
    CAPABILITY_FACIES,
    MODEL_ID_DEMO,
    ensure_default_models,
)
from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.ui import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.viz.prediction_helpers import (
    active_prediction_task,
    export_well_canvas,
)
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.workflow.stratigraphy import active_target_horizon


class WellLogPredictionPage(QWidget):
    """测井预测 page: LAS-bound well + lithology/facies tracks + export."""

    prediction_updated = Signal()
    send_to_preparation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellLogPredictionPage")
        self._project = None
        self._project_path: Path | None = None
        self._tasks: list = []
        self._selected_index: int | None = None
        self._inference_service = None
        self._inference_job = OwnedWorkerJob(self)
        self._session_token = object()
        self._active_inference_context = None

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

        self.task_panel = PredictionTaskPanel()
        content.addWidget(self.task_panel, 0)

        self.canvas_panel = WellLogCanvasPanel()
        content.addWidget(self.canvas_panel, 1)

        self.evidence_panel = PredictionEvidencePanel()
        content.addWidget(self.evidence_panel, 0)

        outer.addLayout(content, 1)

        self.task_panel.task_selected.connect(self._on_task_selected)
        self.evidence_panel.run_requested.connect(self._on_run)
        self.evidence_panel.demo_requested.connect(self._on_demo)
        self.evidence_panel.send_requested.connect(self.send_to_preparation_requested.emit)
        self.evidence_panel.export_requested.connect(self._on_export)
        # A bound LAS finishes loading on a worker thread (#842); refresh the
        # evidence summary once it lands so the "绑定 LAS" source label and the
        # export gating track the actual canvas state.
        self.canvas_panel.canvas_ready.connect(self._on_canvas_ready)

    def set_project(self, project) -> None:
        if project is not self._project:
            self._session_token = object()
        self._project = project

    def set_project_path(self, path) -> None:
        """Bind the real ``*.paleo.json`` path for export/artifact routing."""
        self._project_path = Path(path) if path else None

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Cancel project-owned inference and release pinned native buffers."""
        joined = self._inference_job.shutdown(wait_ms)
        # A failed join means ProjectController will keep the current session
        # and its catalog alive.  Keep this page's current document/native
        # canvas intact as well; the detached worker has no result connection
        # and cannot publish into it.
        if not joined:
            return False
        self._session_token = object()
        self._active_inference_context = None
        self._inference_service = None
        self._project = None
        self.canvas_panel.shutdown()
        return joined

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # qtbot/application teardown can destroy a page between a worker's
        # terminal signal and its queued release callback.  Join first so the
        # QThread can never outlive this QObject parent.
        self.shutdown_workers()
        event.accept()

    def update_state(self, prediction_tasks: list | tuple | None, project=None) -> None:
        if project is not None:
            self.set_project(project)
        self._tasks = list(prediction_tasks or [])
        if self._selected_index is not None and not (
            0 <= self._selected_index < len(self._tasks)
        ):
            self._selected_index = None
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=self._selected_index)
        self.canvas_panel.update_state(task, project=self._project)
        self.evidence_panel.update_state(
            task, bound_las=self.canvas_panel.has_bound_las()
        )

    def _current_task(self):
        if self._selected_index is not None and 0 <= self._selected_index < len(
            self._tasks
        ):
            return self._tasks[self._selected_index]
        return active_prediction_task(self._tasks)

    def _on_canvas_ready(self, _ready: bool) -> None:
        task = self._current_task()
        self.evidence_panel.update_state(
            task, bound_las=self.canvas_panel.has_bound_las()
        )

    def _on_task_selected(self, index: int) -> None:
        self._selected_index = index
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=index)
        self.canvas_panel.update_state(task, project=self._project)
        self.evidence_panel.update_state(
            task, bound_las=self.canvas_panel.has_bound_las()
        )

    def set_selected_well(self, well_name: str) -> bool:
        """Cross-page seam: select the prediction task whose name matches *well_name*.

        Returns True when a matching task was found and selected. Used by the
        workflow controller to sync a well picked on the 3D page into this page.
        """
        if not well_name:
            return False
        for index, task in enumerate(self._tasks):
            if getattr(task, "name", None) == well_name:
                # Set the list selection synchronously. ``setCurrentItem`` fires
                # currentRowChanged → _on_task_selected (full canvas+evidence
                # update); block signals during the set so the update below runs
                # exactly once instead of duplicating the LAS-merge/engine-plan
                # work on every 3D-page well sync.
                lst = self.task_panel.task_list
                item = lst.item(index)
                lst.blockSignals(True)
                lst.setCurrentRow(-1)
                if item is not None:
                    lst.setCurrentItem(item)
                lst.blockSignals(False)
                self._selected_index = index
                task = self._current_task()
                self.canvas_panel.update_state(task, project=self._project)
                self.evidence_panel.update_state(
                    task, bound_las=self.canvas_panel.has_bound_las()
                )
                return True
        return False

    def _on_run(self) -> None:
        """Production inference: resolve a production model, never auto-run mock."""
        if self._project is None:
            QMessageBox.warning(self, "测井预测", "未绑定工程，无法运行")
            return
        service = get_catalog_service()
        if service is None:
            QMessageBox.warning(self, "测井预测", "未连接数据目录，无法运行推断")
            return
        ensure_default_models(service)
        model_version = service.find_production_model(CAPABILITY_FACIES)
        if model_version is None:
            QMessageBox.warning(
                self,
                "测井预测",
                "未配置生产模型，无法运行科学预测。\n"
                "请先注册生产模型（ModelRegistry），或通过「运行演示预测」查看演示结果。",
            )
            return
        self._start_inference(
            service,
            model_version.id,
            workflow="well_log_facies",
            name_prefix="测井相预测",
            demo=False,
        )

    def _on_demo(self) -> None:
        """Explicit demo mode: run the registered DemoModelProvider."""
        if self._project is None:
            QMessageBox.warning(self, "测井预测", "未绑定工程，无法运行")
            return
        service = get_catalog_service()
        if service is None:
            QMessageBox.warning(self, "测井预测", "未连接数据目录，无法运行推断")
            return
        ensure_default_models(service)
        try:
            demo_version = service.get_model_version(MODEL_ID_DEMO, "1")
        except Exception as exc:
            QMessageBox.warning(self, "测井预测", f"演示模型未注册: {exc}")
            return
        self._start_inference(
            service,
            demo_version.id,
            workflow="well_log_facies",
            name_prefix="测井相预测(Demo)",
            demo=True,
        )

    def _start_inference(
        self,
        service,
        model_version_id: str,
        *,
        workflow: str,
        name_prefix: str,
        demo: bool,
    ) -> None:
        if self._inference_job.is_running:
            return
        self._inference_service = service
        if demo:
            input_ids = []
        else:
            from paleo_workbench.prediction.inference_service import (
                resolve_inputs_for_model,
            )
            from paleo_workbench.prediction.input_contract import InputContractError

            try:
                input_ids = resolve_inputs_for_model(
                    self._project, service, model_version_id, strict=True
                )
            except InputContractError as exc:
                QMessageBox.warning(self, "测井预测", f"输入不满足模型契约: {exc}")
                return
        run = start_inference(
            service,
            model_version_id=model_version_id,
            input_version_ids=input_ids,
            parameters={
                "seed": len(self._tasks),
                "workflow": workflow,
                "name_prefix": name_prefix,
                "demo": demo,
            },
        )
        worker = InferenceWorker(service, run.id)
        self._active_inference_context = (self._session_token, self._project, service)
        # #850-7: expose the busy state instead of silently swallowing clicks.
        self.evidence_panel.set_inferring(True)
        self._inference_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_inference_completed_if_current),
                (worker.failed, self._on_inference_failed_if_current),
            ),
            target=name_prefix,
        )

    @Slot(object)
    def _on_inference_completed_if_current(self, payload) -> None:
        context = self._active_inference_context
        if context != (self._session_token, self._project, self._inference_service):
            return
        self._on_inference_completed(payload)

    @Slot(str)
    def _on_inference_failed_if_current(self, text: str) -> None:
        context = self._active_inference_context
        if context is None or context[:2] != (self._session_token, self._project):
            return
        self._on_inference_failed(text)

    def _on_inference_completed(self, payload: dict) -> None:
        self.evidence_panel.set_inferring(False)
        run = payload.get("run")
        if run is None or getattr(run, "status", "") == "failed":
            error = "未知错误"
            if run is not None:
                error = (run.parameters or {}).get("error", "未知错误")
            QMessageBox.warning(self, "测井预测失败", f"推断失败: {error}")
            return
        result = payload.get("result")
        if not result:
            error = (getattr(run, "parameters", None) or {}).get("error") or (
                "预测完成但未返回可用结果"
            )
            QMessageBox.warning(self, "测井预测失败", f"推断失败: {error}")
            return
        params = result.get("parameters") or {}
        factor_ids = [
            task.id
            for task in self._project.factor_map_tasks
            if getattr(task, "status", "") == "complete"
        ]
        out_vids = list(getattr(run, "output_version_ids", None) or [])
        task = materialize_prediction_task(
            self._project,
            result,
            name_prefix=params.get("name_prefix", "测井相预测"),
            workflow=params.get("workflow", "well_log_facies"),
            target_horizon=(
                active_target_horizon(self._project)
                or self._project.stratigraphy.target_horizon
                or ""
            ),
            factor_map_ids=factor_ids,
            run_id=str(getattr(run, "id", "") or ""),
            output_version_id=str(out_vids[0]) if out_vids else "",
        )
        self._project.prediction_tasks.append(task)
        if self._inference_service is not None:
            try:
                link_run_to_domain_task(self._inference_service, run.id, task.id)
            except Exception:
                # Provenance-critical bridge: record the failure instead of
                # silently dropping it (H3 — downstream lineage would be empty).
                import logging

                logging.getLogger(__name__).warning(
                    "link_run_to_domain_task failed for run %s task %s",
                    run.id,
                    task.id,
                    exc_info=True,
                )
                task.model_metadata = dict(task.model_metadata or {})
                task.model_metadata["link_failed"] = True
        self._tasks = list(self._project.prediction_tasks)
        self._selected_index = len(self._tasks) - 1
        self.update_state(self._tasks, project=self._project)
        self.prediction_updated.emit()

    def _on_inference_failed(self, text: str) -> None:
        self.evidence_panel.set_inferring(False)
        QMessageBox.critical(self, "测井预测失败", f"推断失败: {text}")

    def _on_export(self, format_label: str = "PNG") -> None:
        if not self.canvas_panel.is_canvas_ready():
            QMessageBox.warning(self, "导出", "当前没有可导出的测井剖面")
            return
        label = (format_label or "PNG").upper()
        suffix = {"PNG": ".png", "SVG": ".svg", "PDF": ".pdf"}.get(label, ".png")
        data = self.canvas_panel.well_log_data
        stem = getattr(data, "well_name", None) or "well_log"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(stem))[:64]
        start_dir = default_export_dir(self._project_path)
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出单井剖面 ({label})",
            str(start_dir / f"{safe}_well{suffix}"),
            f"{label} (*{suffix})",
        )
        if not path:
            return
        try:
            if (
                self.canvas_panel.backend() == "engine"
                and self.canvas_panel._engine_view is not None
            ):
                # Engine binding currently exposes curve submit + OpenGL view;
                # vector export stays on the Legacy canvas path. PNG uses a
                # widget grab so Feature Flag users still get a graphic export.
                if label != "PNG":
                    raise RuntimeError(
                        "WellLogEngine 路径暂仅支持 PNG 抓屏导出；"
                        "请切换到 Legacy 导出 SVG/PDF"
                    )
                view = self.canvas_panel._engine_view
                if view is None:
                    raise RuntimeError("WellLogEngine 视图不可用")
                pixmap = view.grab()
                if pixmap.isNull():
                    raise RuntimeError("WellLogEngine 抓屏失败")
                if not pixmap.save(path, "PNG"):
                    raise RuntimeError("PNG 写入失败")
                # Best-effort provenance for the engine-branch export (the
                # legacy branch registers via export_well_canvas; this branch
                # writes directly, so register here — review finding I5).
                self._register_canvas_export(path, "png")
            else:
                task = self._current_task()
                export_well_canvas(
                    self.canvas_panel.canvas,
                    path,
                    label,
                    project=self._project,
                    source_task_ids=[task.id] if task is not None else None,
                )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导出失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")

    def _register_canvas_export(self, path: str, fmt: str) -> None:
        """Best-effort OUTPUT DataVersion registration for the engine-branch
        canvas export (no catalog open → no-op; lineage links the active
        prediction task when available)."""
        if self._project is None:
            return
        try:
            from paleo_workbench.project.artifacts import record_export

            task = self._current_task()
            record_export(
                self._project,
                linked_id="well_log_canvas",
                output_path=str(path),
                fmt=fmt,
                source_task_ids=[task.id] if task is not None else [],
            )
        except Exception:
            # Provenance is best-effort; never break the export flow.
            import logging

            logging.getLogger(__name__).warning(
                "engine canvas export provenance registration failed",
                exc_info=True,
            )
