from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.catalog import get_catalog_service
from paleo_workbench.prediction.inference_service import (
    link_run_to_domain_task,
    materialize_prediction_task,
    resolve_prediction_inputs,
    start_inference,
)
from paleo_workbench.prediction.inference_worker import InferenceWorker
from paleo_workbench.prediction.providers import (
    MODEL_ID_DEMO,
    ensure_default_models,
    ensure_geoviz_online_model,
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


_AUTHORIZATION_RE = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*([=:])\s*[^\s,;&]+"
)


def _redact_endpoint(value) -> str:
    """Strip credentials and query values before rendering a remote endpoint."""
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return "<无效地址>"
    if not parsed.scheme or not parsed.hostname:
        return _SECRET_VALUE_RE.sub(r"\1\2<REDACTED>", endpoint)
    host = parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _redact_diagnostic_text(value) -> str:
    """Keep useful failure content while ensuring auth material cannot reach UI logs."""
    text = str(value or "")
    text = _AUTHORIZATION_RE.sub(r"\1<REDACTED>", text)
    text = _SECRET_VALUE_RE.sub(r"\1\2<REDACTED>", text)
    return text[:3_000]


class WellLogPredictionPage(QWidget):
    """测井预测 page: LAS-bound well + lithology/facies tracks + export."""

    prediction_updated = Signal()
    send_to_preparation_requested = Signal()
    # Keep importing owned by DataPage so the imported file follows the same
    # catalog, provenance and domain-binding lifecycle as a normal data import.
    well_log_import_requested = Signal(object)  # list[str]

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
        self._selected_well_resource_id: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_4)

        source_row = QHBoxLayout()
        source_label = QLabel("测井数据源")
        source_label.setObjectName("WorkFieldLabel")
        source_row.addWidget(source_label)
        self.well_source_combo = QComboBox()
        self.well_source_combo.setObjectName("WellPredictionSourceCombo")
        self.well_source_combo.setToolTip(
            "选择数据管理中已归档的 LAS 或 XML 测井数据，加载后可直接运行预测"
        )
        self.well_source_combo.currentIndexChanged.connect(self._on_well_source_changed)
        source_row.addWidget(self.well_source_combo, 1)
        self.import_well_btn = QPushButton("导入 LAS / XML…")
        self.import_well_btn.setObjectName("SecondaryButton")
        self.import_well_btn.setToolTip(
            "导入外部 LAS、WITSML 或 SpreadsheetML XML 测井数据，并纳入数据管理"
        )
        self.import_well_btn.clicked.connect(self._on_import_well_logs)
        source_row.addWidget(self.import_well_btn)
        outer.addLayout(source_row)

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
            self._selected_well_resource_id = None
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
        self._sync_well_sources()
        if self._selected_index is not None and not (
            0 <= self._selected_index < len(self._tasks)
        ):
            self._selected_index = None
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=self._selected_index)
        if task is not None:
            self.canvas_panel.update_state(task, project=self._project)
            self.evidence_panel.update_state(
                task, bound_las=self.canvas_panel.has_bound_las()
            )
            return
        resource = self._selected_well_resource()
        if resource is not None:
            self.canvas_panel.show_resource(resource, self._project)
            self.evidence_panel.update_state(
                None,
                bound_las=self.canvas_panel.has_bound_las(),
                selected_source=True,
            )
            return
        self.canvas_panel.update_state(None, project=self._project)
        self.evidence_panel.update_state(None, bound_las=False)

    def _current_task(self):
        if self._selected_index is not None and 0 <= self._selected_index < len(
            self._tasks
        ):
            return self._tasks[self._selected_index]
        return active_prediction_task(self._tasks)

    def _on_canvas_ready(self, _ready: bool) -> None:
        task = self._current_task()
        if task is not None:
            self.evidence_panel.update_state(
                task, bound_las=self.canvas_panel.has_bound_las()
            )
        elif self._selected_well_resource() is not None:
            self.evidence_panel.update_state(
                None,
                bound_las=self.canvas_panel.has_bound_las(),
                selected_source=True,
            )

    def _on_task_selected(self, index: int) -> None:
        self._selected_index = index
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=index)
        self.canvas_panel.update_state(task, project=self._project)
        self.evidence_panel.update_state(
            task, bound_las=self.canvas_panel.has_bound_las()
        )

    def _sync_well_sources(self) -> None:
        previous = self._selected_well_resource_id
        resources = [
            resource
            for resource in (getattr(self._project, "resources", None) or [])
            if getattr(resource, "type", "") == "well_log"
        ]
        self.well_source_combo.blockSignals(True)
        self.well_source_combo.clear()
        for resource in resources:
            name = str(getattr(resource, "name", "未命名测井"))
            format_label = str(getattr(resource, "format", "") or "").upper()
            self.well_source_combo.addItem(
                f"{name} · {format_label}" if format_label else name,
                str(getattr(resource, "id", "")),
            )
        if not resources:
            self.well_source_combo.addItem("数据管理中暂无 LAS / XML 测井数据", None)
            self._selected_well_resource_id = None
        else:
            selected_index = next(
                (
                    index
                    for index, resource in enumerate(resources)
                    if str(getattr(resource, "id", "")) == previous
                ),
                -1,
            )
            self.well_source_combo.setCurrentIndex(selected_index)
            if selected_index < 0:
                self._selected_well_resource_id = None
        self.well_source_combo.blockSignals(False)

    def _selected_well_resource(self):
        if not self._selected_well_resource_id or self._project is None:
            return None
        return next(
            (
                resource
                for resource in (getattr(self._project, "resources", None) or [])
                if str(getattr(resource, "id", "")) == self._selected_well_resource_id
                and getattr(resource, "type", "") == "well_log"
            ),
            None,
        )

    def selected_well_resource_id(self) -> str | None:
        """The direct Data Management input currently selected for prediction."""
        return self._selected_well_resource_id

    def _on_well_source_changed(self, _index: int) -> None:
        resource_id = self.well_source_combo.currentData()
        if resource_id:
            self.select_well_resource(str(resource_id))

    def _on_import_well_logs(self) -> None:
        """Ask the DataPage owner to import external well logs asynchronously."""
        if self._project is None:
            QMessageBox.warning(self, "导入测井数据", "请先打开或创建工程")
            return
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "导入测井数据",
            "",
            "测井数据 (*.las *.LAS *.xml *.XML)",
        )
        if paths:
            self.well_log_import_requested.emit([str(Path(path)) for path in paths])

    def set_source_import_status(self, text: str) -> None:
        """Expose import lifecycle feedback without duplicating DataPage UI."""
        self.evidence_panel.set_status(str(text or ""))

    def select_well_resource(self, resource_id: str) -> bool:
        """Load one Data Management well into the prediction canvas.

        This intentionally clears the selected task: before inference there is
        no prediction overlay, only the user-selected source well.
        """
        if self._project is None:
            return False
        resource = next(
            (
                item
                for item in (getattr(self._project, "resources", None) or [])
                if str(getattr(item, "id", "")) == str(resource_id)
                and getattr(item, "type", "") == "well_log"
            ),
            None,
        )
        if resource is None:
            return False
        self._selected_well_resource_id = str(resource.id)
        combo_index = self.well_source_combo.findData(self._selected_well_resource_id)
        if combo_index >= 0 and combo_index != self.well_source_combo.currentIndex():
            self.well_source_combo.blockSignals(True)
            self.well_source_combo.setCurrentIndex(combo_index)
            self.well_source_combo.blockSignals(False)
        self._selected_index = None
        self.task_panel.update_state(self._tasks, selected_index=None)
        self.canvas_panel.show_resource(resource, self._project)
        self.evidence_panel.update_state(
            None,
            bound_las=self.canvas_panel.has_bound_las(),
            selected_source=True,
        )
        self._restore_latest_failed_online_run(resource.id)
        return True

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
        """Run the explicit authenticated online single-well prediction route."""
        if self._project is None:
            QMessageBox.warning(self, "测井预测", "未绑定工程，无法运行")
            return
        resource = self._selected_well_resource()
        if resource is None:
            QMessageBox.warning(self, "测井预测", "请先从数据管理选择一口井数据")
            return
        service = get_catalog_service()
        if service is None:
            QMessageBox.warning(self, "测井预测", "未连接数据目录，无法运行推断")
            return
        try:
            model_version = ensure_geoviz_online_model(service)
            from paleo_workbench.prediction.geoviz_online import (
                online_endpoint,
                online_model_version_id,
                online_poll_timeout_seconds,
                online_timeout_seconds,
                online_wait_timeout_seconds,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "测井预测",
                f"无法准备线上测井预测: {exc}",
            )
            return
        self._start_inference(
            service,
            model_version.id,
            workflow="inference_api_well_log_facies",
            name_prefix="线上测井相预测",
            demo=False,
            well_log_resource_id=resource.id,
            extra_parameters={
                "online_endpoint": online_endpoint(),
                "online_model_version_id": online_model_version_id(),
                "online_wait_timeout_seconds": online_wait_timeout_seconds(),
                "online_request_timeout_seconds": online_timeout_seconds(),
                "online_poll_timeout_seconds": online_poll_timeout_seconds(),
            },
        )

    def _on_demo(self) -> None:
        """Explicit demo mode: run the registered DemoModelProvider."""
        if self._project is None:
            QMessageBox.warning(self, "测井预测", "未绑定工程，无法运行")
            return
        resource = self._selected_well_resource()
        if resource is None:
            QMessageBox.warning(self, "测井预测", "请先从数据管理选择一口井数据")
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
            well_log_resource_id=resource.id,
        )

    def _start_inference(
        self,
        service,
        model_version_id: str,
        *,
        workflow: str,
        name_prefix: str,
        demo: bool,
        well_log_resource_id: str | None = None,
        extra_parameters: dict | None = None,
    ):
        if self._inference_job.is_running:
            return None
        self._inference_service = service
        if demo and not well_log_resource_id:
            input_ids = []
        else:
            from paleo_workbench.prediction.inference_service import (
                resolve_inputs_for_model,
            )
            from paleo_workbench.prediction.input_contract import InputContractError

            try:
                input_ids = resolve_inputs_for_model(
                    self._project,
                    service,
                    model_version_id,
                    strict=True,
                    resource_ids=[well_log_resource_id]
                    if well_log_resource_id
                    else None,
                )
                if workflow == "inference_api_well_log_facies":
                    from paleo_workbench.prediction.inference_service import (
                        resolve_prediction_postprocess_inputs,
                    )

                    input_ids.extend(
                        resolve_prediction_postprocess_inputs(self._project, service)
                    )
                    input_ids = list(dict.fromkeys(input_ids))
            except InputContractError as exc:
                QMessageBox.warning(self, "测井预测", f"输入不满足模型契约: {exc}")
                return None
        run_parameters = {
            "seed": len(self._tasks),
            "workflow": workflow,
            "name_prefix": name_prefix,
            "demo": demo,
            "well_log_resource_ids": [well_log_resource_id]
            if well_log_resource_id
            else [],
        }
        run_parameters.update(dict(extra_parameters or {}))
        run = start_inference(
            service,
            model_version_id=model_version_id,
            input_version_ids=input_ids,
            parameters=run_parameters,
        )
        worker = InferenceWorker(service, run.id)
        self._active_inference_context = (self._session_token, self._project, service)
        # #850-7: expose the busy state instead of silently swallowing clicks.
        self.evidence_panel.set_inferring(True)
        if workflow in {"geoviz_online_well_log_facies", "inference_api_well_log_facies"}:
            self.evidence_panel.set_status("正在调用线上测井预测服务…")
        self._write_run_diagnostic(run, status="推断中")
        self._inference_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_inference_completed_if_current),
                (worker.failed, self._on_inference_failed_if_current),
            ),
            target=name_prefix,
        )
        return run

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
            safe_error = _redact_diagnostic_text(error)
            # Async completion: in-page status instead of a modal dialog
            # (the shell may be rebuilding, #897).
            self.evidence_panel.set_status(f"推断失败: {safe_error}")
            self._write_run_diagnostic(run, status="失败", error=error)
            return
        result = payload.get("result")
        if not result:
            error = (getattr(run, "parameters", None) or {}).get("error") or (
                "预测完成但未返回可用结果"
            )
            self.evidence_panel.set_status(f"推断失败: {_redact_diagnostic_text(error)}")
            self._write_run_diagnostic(run, status="失败", error=error)
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
            well_log_resource_ids=list(
                (params.get("well_log_resource_ids") or [])
            ),
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
        if (task.result_summary or {}).get("model_type") in {
            "geoviz_online",
            "inference_api_online",
        }:
            self.evidence_panel.set_status(
                "线上测井预测完成，结果已保存到数据管理"
            )
        else:
            self.evidence_panel.set_status("预测完成，结果已保存到数据管理")
        self._write_run_diagnostic(run, status="完成")
        self.prediction_updated.emit()

    def _on_inference_failed(self, text: str) -> None:
        self.evidence_panel.set_inferring(False)
        self.evidence_panel.set_status(f"推断失败: {_redact_diagnostic_text(text)}")
        self._write_run_diagnostic(None, status="异常中断", error=text)

    def _restore_latest_failed_online_run(self, resource_id: str) -> None:
        """Show the selected well's newest persisted online failure, if any."""
        if self._inference_job.is_running or not resource_id:
            return
        service = get_catalog_service()
        if service is None:
            return
        try:
            failed_runs = [
                run
                for run in service.list_runs()
                if str(getattr(run, "status", "") or "").lower() == "failed"
                and (getattr(run, "parameters", None) or {}).get("workflow")
                in {"geoviz_online_well_log_facies", "inference_api_well_log_facies"}
                and str(resource_id)
                in {
                    str(item)
                    for item in (
                        (getattr(run, "parameters", None) or {}).get(
                            "well_log_resource_ids", []
                        )
                        or []
                    )
                }
            ]
        except Exception:
            return
        if not failed_runs:
            return
        run = max(failed_runs, key=lambda item: str(getattr(item, "created_at", "")))
        error = (getattr(run, "parameters", None) or {}).get("error", "未知错误")
        self.evidence_panel.set_status(
            f"上次推断失败: {_redact_diagnostic_text(error)}"
        )
        self._write_run_diagnostic(run, status="失败（历史运行）", error=error)

    def _write_run_diagnostic(self, run, *, status: str, error: str = "") -> None:
        """Render one user-copyable, credential-safe prediction diagnostic."""
        params = dict(getattr(run, "parameters", None) or {})
        resource = self._selected_well_resource()
        resource_name = str(getattr(resource, "name", "") or "未解析")
        resource_id = str(getattr(resource, "id", "") or "")
        endpoint = _redact_endpoint(params.get("online_endpoint"))
        lines = [
            "线上测井预测运行日志",
            f"状态: {status}",
            f"运行 ID: {str(getattr(run, 'id', '') or '未创建')}",
            f"井数据: {resource_name}{f' ({resource_id})' if resource_id else ''}",
            f"模型版本: {str(params.get('model_version') or '未记录')}",
        ]
        if endpoint:
            lines.append(f"服务地址: {endpoint}")
        if params.get("online_model_version_id"):
            lines.append(f"远端模型 ID: {params['online_model_version_id']}")
        if params.get("online_wait_timeout_seconds"):
            lines.append(f"同步等待: {params['online_wait_timeout_seconds']} 秒")
        if params.get("online_request_timeout_seconds"):
            lines.append(f"请求超时: {params['online_request_timeout_seconds']} 秒")
        elif params.get("online_timeout_seconds"):
            lines.append(f"请求超时: {params['online_timeout_seconds']} 秒")
        if params.get("online_poll_timeout_seconds"):
            lines.append(f"轮询超时: {params['online_poll_timeout_seconds']} 秒")
        if error:
            lines.extend(("错误:", _redact_diagnostic_text(error)))
        self.evidence_panel.set_diagnostic_log("\n".join(lines))

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
