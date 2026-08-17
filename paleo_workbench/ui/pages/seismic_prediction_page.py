from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.viz.prediction_helpers import active_prediction_task
from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel
from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
from paleo_workbench.workflow.stratigraphy import active_target_horizon
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


class SeismicPredictionPage(QWidget):
    """Reference-style seismic analysis workbench around the existing view."""

    prediction_updated = Signal()
    send_to_mapping_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicPredictionPage")
        self._project = None
        self._tasks: list = []
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

        self.context_toolbar = SeismicContextToolbar()
        outer.addWidget(self.context_toolbar)

        content = QHBoxLayout()
        content.setSpacing(tokens.SPACE_4)

        self.attribute_panel = SeismicAttributePanel()
        content.addWidget(self.attribute_panel, 0)

        self.view_panel = SeismicViewPanel()
        content.addWidget(self.view_panel, 1)

        self.control_panel = SeismicControlPanel()
        content.addWidget(self.control_panel, 0)

        outer.addLayout(content, 1)

        self.context_toolbar.run_requested.connect(self._on_run)
        self.context_toolbar.demo_requested.connect(self._on_demo)
        self.control_panel.send_requested.connect(self.send_to_mapping_requested.emit)
        self.control_panel.display_mode_changed.connect(self.view_panel.set_display_mode)
        self.attribute_panel.attribute_changed.connect(self._on_attribute)
        self.control_panel.well_tie_toggled.connect(self.view_panel.set_well_tie_enabled)
        self.view_panel.view_ready.connect(self._on_view_ready)

    def set_project(self, project) -> None:
        if project is not self._project:
            self._session_token = object()
        self._project = project

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Stop project-owned inference before its catalog is rebound."""
        joined = self._inference_job.shutdown(wait_ms)
        # A switch is aborted when a job cannot join.  Preserve the current
        # page/session in that case; result signals were disconnected by the
        # owned job and the old catalog remains open for the detached worker.
        if not joined:
            return False
        self._session_token = object()
        self._active_inference_context = None
        self._inference_service = None
        self._project = None
        shutdown = getattr(self.view_panel, "shutdown", None)
        if callable(shutdown):
            shutdown()
        return joined

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # A page owns its inference thread; joining here covers direct widget
        # destruction as well as normal project-session shutdown.
        self.shutdown_workers()
        event.accept()

    def update_state(self, prediction_tasks: list | tuple | None, project=None) -> None:
        if project is not None:
            self.set_project(project)
        self._tasks = list(prediction_tasks or [])
        task = self._current_task()
        self.view_panel.update_state(task, project=self._project)
        self.control_panel.update_state(task, self.view_panel.volume_shape)
        self._sync_workbench_context(task)
        self.control_panel.set_controls_enabled(self.view_panel.is_view_ready())

    def _current_task(self):
        return active_prediction_task(self._tasks)

    def _on_attribute(self, label: str) -> None:
        self.view_panel.set_attribute_label(label)
        self.attribute_panel.set_selected_attribute(label)
        self._sync_workbench_context(self._current_task())

    def _on_view_ready(self, enabled: bool) -> None:
        self.control_panel.set_controls_enabled(enabled)
        if enabled:
            self._sync_workbench_context(self._current_task())

    def _sync_workbench_context(self, task) -> None:
        attribute = self.view_panel.attribute_label()
        mode = self.view_panel.display_mode()
        self.attribute_panel.set_selected_attribute(attribute)
        self.control_panel.set_attribute_label(attribute)
        self.context_toolbar.set_context(
            task,
            self.control_panel.horizon_value.text(),
            attribute,
            mode,
        )

    def _on_run(self) -> None:
        """Production inference: resolve a production model, never auto-run mock.

        No production model in the ModelRegistry → explicit 「未配置生产模型」
        unavailable state (spec P2 §3d). Demo requires explicit demo mode.
        """
        if self._project is None:
            QMessageBox.warning(self, "地震预测", "未绑定工程，无法运行")
            return
        service = get_catalog_service()
        if service is None:
            QMessageBox.warning(self, "地震预测", "未连接数据目录，无法运行推断")
            return
        ensure_default_models(service)
        model_version = service.find_production_model(CAPABILITY_FACIES)
        if model_version is None:
            QMessageBox.warning(
                self,
                "地震预测",
                "未配置生产模型，无法运行科学预测。\n"
                "请先注册生产模型（ModelRegistry），或通过「运行演示预测」查看演示结果。",
            )
            return
        self._start_inference(
            service,
            model_version.id,
            workflow="seismic_facies",
            name_prefix="地震相预测",
            demo=False,
        )

    def _on_demo(self) -> None:
        """Explicit demo mode: run the registered DemoModelProvider."""
        if self._project is None:
            QMessageBox.warning(self, "地震预测", "未绑定工程，无法运行")
            return
        service = get_catalog_service()
        if service is None:
            QMessageBox.warning(self, "地震预测", "未连接数据目录，无法运行推断")
            return
        ensure_default_models(service)
        try:
            demo_version = service.get_model_version(MODEL_ID_DEMO, "1")
        except Exception as exc:
            QMessageBox.warning(self, "地震预测", f"演示模型未注册: {exc}")
            return
        self._start_inference(
            service,
            demo_version.id,
            workflow="seismic_facies",
            name_prefix="地震相预测(Demo)",
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
                QMessageBox.warning(self, "地震预测", f"输入不满足模型契约: {exc}")
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
        run = payload.get("run")
        if run is None or getattr(run, "status", "") == "failed":
            error = "未知错误"
            if run is not None:
                error = (run.parameters or {}).get("error", "未知错误")
            QMessageBox.warning(self, "地震预测失败", f"推断失败: {error}")
            return
        result = payload.get("result")
        if not result:
            error = (getattr(run, "parameters", None) or {}).get("error") or (
                "预测完成但未返回可用结果"
            )
            QMessageBox.warning(self, "地震预测失败", f"推断失败: {error}")
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
            name_prefix=params.get("name_prefix", "地震相预测"),
            workflow=params.get("workflow", "seismic_facies"),
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
        self.update_state(self._tasks, project=self._project)
        self.prediction_updated.emit()

    def _on_inference_failed(self, text: str) -> None:
        QMessageBox.critical(self, "地震预测失败", f"推断失败: {text}")
