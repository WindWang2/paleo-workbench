from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from geoviz import CancellationToken

from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.factor_prepare_worker import FactorPrepareWorker
from paleo_workbench.workflow.factor_prepare_scheduler import (
    build_prepare_snapshot,
    commit_prepare_batch_result,
)
from paleo_workbench.pipeline.compile_map import compile_map_draft
from paleo_workbench.workflow.qc import active_quality_reports
from paleo_workbench.workflow.service import dashboard_state, home_workflow_steps
from paleo_workbench.ui.navigation import (
    PAGE_INDEX_GEOMODEL,
    PAGE_INDEX_MAPPING,
    PAGE_INDEX_PREPARATION,
    PAGE_INDEX_REVIEW,
    PAGE_INDEX_SEISMIC,
    PAGE_INDEX_SEQUENCE,
    PAGE_INDEX_VISUALIZATION,
    PAGE_INDEX_WELL_LOG,
)
from paleo_workbench.ui.preview_settings_dialog import PreviewSettingsDialog


class WorkflowController:
    """Manages cross-page workflow logic and signal wiring for PaleoWorkbenchWindow."""

    def __init__(self, window) -> None:
        self.window = window
        self.preview_settings_dialog: PreviewSettingsDialog | None = None
        self._prepare_job = OwnedWorkerJob(window)
        self._prepare_generation = 0

    def show_preview_settings(self) -> None:
        """Open the shared preview settings for the current DataPage."""
        if self.preview_settings_dialog is None:
            dialog = PreviewSettingsDialog(
                self.window,
                store=self.window._preview_settings_store,
            )
            dialog.settings_applied.connect(self.apply_preview_settings)
            self.preview_settings_dialog = dialog
        reader = self.window.app_shell.data_page.reader_panel
        self.preview_settings_dialog.set_settings(reader.preview_settings)
        self.preview_settings_dialog.set_preview_mode(reader.current_mode)
        self.preview_settings_dialog.exec()

    def apply_preview_settings(self, settings) -> None:
        """Route dialog output to the current shell, never a stale page."""
        self.window.app_shell.data_page.reader_panel.set_preview_settings(settings)

    def _refresh_data_page(self) -> None:
        """Refresh the Data Manager after workflow products changed.

        Factor grids, predictions, QC outputs and map compiles register new
        catalog versions; without this the produce→browse journey breaks
        (the data page kept showing pre-run rows until a manual refresh).
        """
        try:
            app_shell = self.window.app_shell
            if hasattr(app_shell, "update_data_page"):
                app_shell.update_data_page(
                    dashboard_state(self.window.project),
                    self.window.project.resources,
                    self.window.project.export_artifacts,
                )
        except Exception:
            pass

    def wire_home_page(self) -> None:
        page = self.window.app_shell.home_page_widget()
        if page is None:
            return
        if hasattr(page, "navigation_requested"):
            page.navigation_requested.connect(self._on_home_navigation)

    def wire_data_visualization_jump(self) -> None:
        page = self.window.app_shell.data_page_widget()
        if hasattr(page, "open_in_visualization"):
            page.open_in_visualization.connect(self._on_open_in_visualization)

    def wire_mapping_page(self) -> None:
        page = self.window.app_shell.mapping_page_widget()
        if page is None:
            return
        self.window.app_shell.defer_page_project_binding(PAGE_INDEX_MAPPING, page)
        if hasattr(page, "generate_demo_draft_requested"):
            page.generate_demo_draft_requested.connect(
                self._on_generate_demo_map_draft
            )
        if hasattr(page, "contour_drafts_updated"):
            page.contour_drafts_updated.connect(self._on_contour_drafts_updated)

    def wire_preparation_page(self) -> None:
        page = self.window.app_shell.preparation_page_widget()
        if page is None:
            return
        self.window.app_shell.defer_page_project_binding(PAGE_INDEX_PREPARATION, page)
        if hasattr(page, "factor_maps_updated"):
            page.factor_maps_updated.connect(self._on_factor_maps_updated)
        if hasattr(page, "contour_drafts_updated"):
            page.contour_drafts_updated.connect(self._on_contour_drafts_updated)

    def wire_sequence_page(self) -> None:
        page = self.window.app_shell.sequence_framework_page_widget()
        if page is None:
            return
        self.window.app_shell.defer_page_project_binding(
            PAGE_INDEX_SEQUENCE, page
        )
        if hasattr(page, "stratigraphy_updated"):
            # Avoid duplicate connections across shell rebuilds of the same page
            # instance is new each rebuild; connect once per shell.
            page.stratigraphy_updated.connect(self._on_stratigraphy_updated)

    def wire_seismic_page(self) -> None:
        page = self.window.app_shell.seismic_prediction_page_widget()
        if page is None:
            return
        self.window.app_shell.defer_page_project_binding(PAGE_INDEX_SEISMIC, page)
        if hasattr(page, "prediction_updated"):
            page.prediction_updated.connect(self._on_seismic_prediction_updated)
        if hasattr(page, "send_to_mapping_requested"):
            page.send_to_mapping_requested.connect(self._on_seismic_send_to_mapping)

    def wire_well_log_page(self) -> None:
        page = self.window.app_shell.well_log_prediction_page_widget()
        if page is None:
            return
        self.window.app_shell.defer_page_project_binding(PAGE_INDEX_WELL_LOG, page)
        if hasattr(page, "prediction_updated"):
            page.prediction_updated.connect(self._on_well_log_prediction_updated)
        if hasattr(page, "send_to_preparation_requested"):
            page.send_to_preparation_requested.connect(self._on_well_log_send_to_prep)

    def wire_geomodel_page(self) -> None:
        """Wire the 3D well-seismic joint page (project + cross-page well sync)."""
        page = self.window.app_shell.page_stack.widget(PAGE_INDEX_GEOMODEL)
        if page is None:
            return
        self.window.app_shell.defer_page_project_binding(PAGE_INDEX_GEOMODEL, page)
        if hasattr(page, "well_selected"):
            page.well_selected.connect(self._on_geomodel_well_selected)

    def _on_geomodel_well_selected(self, well_name: str) -> None:
        """Sync a well picked on the 3D page into the WellLog page selection."""
        page = self.window.app_shell.well_log_prediction_page_widget()
        if page is None:
            return
        setter = getattr(page, "set_selected_well", None)
        if callable(setter):
            setter(well_name)

    def wire_review_page(self) -> None:
        page = self.window.app_shell.review_export_page_widget()
        if page is None:
            return
        self.window.app_shell.defer_page_project_binding(PAGE_INDEX_REVIEW, page)
        if hasattr(page, "reports_updated"):
            page.reports_updated.connect(self._on_qc_reports_updated)

    def _on_qc_reports_updated(self) -> None:
        state = dashboard_state(self.window.project)
        steps = home_workflow_steps(self.window.project)
        self.window.app_shell.update_home_page(state, steps, project=self.window.project)
        self.window.app_shell.update_review_export_page(
            active_quality_reports(self.window.project),
            self.window.project.paleomap_documents,
            self.window.project.export_artifacts,
        )
        self._refresh_data_page()

    def _on_well_log_prediction_updated(self) -> None:
        """Refresh well-log / seismic / viz pages after a new single-well task."""
        self._on_seismic_prediction_updated()

    def _on_well_log_send_to_prep(self) -> None:
        """Batch-prepare factor maps via FactorPrepareWorker and open 制备 page.

        The heavy interpolation never runs on the GUI thread: the batch runs
        on an OwnedWorkerJob thread with progress + cancel, mirroring the
        preparation page's own wiring (C05). The synchronous
        ``batch_prepare_factor_maps`` API stays available for script paths.
        """
        project = self.window.project
        if not project.prediction_tasks:
            QMessageBox.information(self.window, "发送制备", "请先运行测井预测")
            return
        if self._prepare_job.is_running:
            QMessageBox.information(self.window, "发送制备", "单因素图制备正在进行中…")
            return
        self._prepare_generation += 1
        generation = self._prepare_generation
        token = CancellationToken()
        try:
            # Snapshot on the host thread so scientific inputs match Stage-4
            # fingerprints (same as preparation_page._start_prepare_worker).
            snapshot = build_prepare_snapshot(
                project, generation=generation, method="IDW"
            )
        except Exception as exc:  # noqa: BLE001 — surface prepare setup failure
            QMessageBox.warning(
                self.window,
                "发送制备失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        worker = FactorPrepareWorker(
            project,
            method="IDW",
            cancellation_token=token,
            generation=generation,
            snapshot=snapshot,
        )
        prep_page = self.window.app_shell.preparation_page_widget()
        if prep_page is not None and hasattr(prep_page, "task_panel"):
            prep_page.task_panel.summary_label.setText(
                f"制备中… 任务 {len(snapshot.tasks)} · 发送制备"
            )
        self.window.app_shell.icon_rail.set_active(PAGE_INDEX_PREPARATION)
        self.window.app_shell._switch_page(PAGE_INDEX_PREPARATION)
        self._prepare_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed, worker.cancelled),
            result_connections=(
                (worker.completed, self._on_prep_send_completed),
                (worker.failed, self._on_prep_send_failed),
                (worker.progress, self._on_prep_send_progress),
                (worker.cancelled, self._on_prep_send_cancelled),
            ),
            cancel=token.cancel,
            target=project,
        )

    def _prep_page(self):
        """Current preparation page widget, if any (progress/task panel target)."""
        try:
            return self.window.app_shell.preparation_page_widget()
        except Exception:  # pragma: no cover - shell teardown races
            return None

    def _on_prep_send_progress(self, update) -> None:
        if self._prepare_job.target is not self.window.project:
            return
        page = self._prep_page()
        if page is None or not hasattr(page, "task_panel"):
            return
        msg = update.message or update.phase
        page.task_panel.summary_label.setText(
            f"制备中：复用 {update.clean} · 需计算 {update.dirty} · "
            f"已完成 {update.completed}/{update.total_tasks}"
            + (f" · {msg}" if msg else "")
        )

    def _on_prep_send_completed(self, result) -> None:
        project = self.window.project
        if self._prepare_job.target is not project:
            return
        if int(result.generation) != int(self._prepare_generation):
            return
        # Fingerprint-guarded commit — same semantics as the preparation page.
        commit_prepare_batch_result(
            project, result, expected_generation=self._prepare_generation
        )
        self._on_factor_maps_updated()
        page = self._prep_page()
        if page is not None and hasattr(page, "task_panel"):
            page.update_state(project.factor_map_tasks)
            page.task_panel.summary_label.setText(
                f"已制备 {sum(1 for t in project.factor_map_tasks if t.status == 'complete')} / "
                f"{len(project.factor_map_tasks)} 个单因素图"
                f" · 复用 {result.clean_count} · 计算 {result.executed_count}"
            )
        self.window.app_shell.icon_rail.set_active(PAGE_INDEX_PREPARATION)
        self.window.app_shell._switch_page(PAGE_INDEX_PREPARATION)

    def _on_prep_send_failed(self, message: str) -> None:
        QMessageBox.warning(self.window, "发送制备失败", message)
        page = self._prep_page()
        if page is not None and hasattr(page, "task_panel"):
            page.task_panel.summary_label.setText(f"单因素图生成失败：{message}")

    def _on_prep_send_cancelled(self) -> None:
        page = self._prep_page()
        if page is not None and hasattr(page, "task_panel"):
            page.task_panel.summary_label.setText("发送制备已取消")

    def _on_seismic_prediction_updated(self) -> None:
        """Refresh seismic / visualization / home after a new facies task."""
        state = dashboard_state(self.window.project)
        steps = home_workflow_steps(self.window.project)
        self.window.app_shell.update_home_page(state, steps, project=self.window.project)
        self.window.app_shell.update_seismic_prediction_page(
            self.window.project.prediction_tasks, project=self.window.project
        )
        self.window.app_shell.update_well_log_prediction_page(
            self.window.project.prediction_tasks, project=self.window.project
        )
        self.window.app_shell.update_visualization_page(
            self.window.project.resources,
            self.window.project.prediction_tasks,
            self.window.project.paleomap_documents,
            project=self.window.project,
        )
        self._refresh_data_page()

    def _on_seismic_send_to_mapping(self) -> None:
        """Compile a map from the latest prediction and open 编图.

        Production predictions with spatial geometry → production compiler.
        Explicit Demo/mock tasks → demo draft only (never mixed).
        Scientific/non-demo tasks without spatial geometry → BLOCK
        (never silently fall through to fake squares).
        """
        if not self.window.project.prediction_tasks:
            QMessageBox.information(self.window, "发送编图", "请先运行地震预测")
            return
        task = self.window.project.prediction_tasks[-1]
        summary = dict(task.result_summary or {})
        meta = dict(task.model_metadata or {})
        is_demo_task = bool(
            summary.get("demo")
            or summary.get("is_mock")
            or meta.get("demo")
            or meta.get("demo_only")
            or getattr(task, "adapter_kind", "") == "mock"
        )

        from paleo_workbench.pipeline.compile_map_production import (
            ProductionMapError,
            compile_map_production,
        )
        from paleo_workbench.prediction.spatial_result import is_map_compilable

        payload = {"result_summary": summary}
        if is_demo_task:
            # Explicit Demo path only.
            compile_map_draft(self.window.project, seed=0)
        elif is_map_compilable(payload):
            try:
                catalog_service = None
                try:
                    from paleo_workbench.catalog import get_catalog_service

                    catalog_service = get_catalog_service()
                except Exception:
                    catalog_service = None
                pred_vid = str(
                    meta.get("prediction_version_id")
                    or meta.get("output_version_id")
                    or ""
                ) or None
                compile_map_production(
                    self.window.project,
                    prediction_task_id=task.id,
                    prediction_payload=payload,
                    catalog_service=catalog_service,
                    prediction_version_id=pred_vid,
                )
            except ProductionMapError as exc:
                QMessageBox.warning(
                    self.window,
                    "发送编图",
                    f"生产编图失败（不会生成演示占位方块）:\n{exc}",
                )
                return
        else:
            QMessageBox.warning(
                self.window,
                "发送编图",
                "当前预测结果无可编绘的平面空间几何。\n"
                "井深区间或非空间结果不能自动变成古地理图；"
                "也不会生成「未分类」占位方块。\n"
                "请使用生产模型输出 VECTOR_POLYGONS，或通过「生成演示草稿」显式运行演示。",
            )
            return
        self.window.app_shell.update_mapping_page(
            self.window.project.paleomap_documents,
            factor_tasks=self.window.project.factor_map_tasks,
            project_crs=self.window.project.coordinate.project_crs,
        )
        # The production compile registered a paleomap catalog version —
        # surface it in the Data Manager too.
        self._refresh_data_page()
        self.window.app_shell.icon_rail.set_active(PAGE_INDEX_MAPPING)
        self.window.app_shell._switch_page(PAGE_INDEX_MAPPING)

    def _on_factor_maps_updated(self) -> None:
        """Refresh preparation + mapping factor shelf after real IDW batch generate."""
        self.window.app_shell.update_preparation_page(
            self.window.project.factor_map_tasks
        )
        self.window.app_shell.update_mapping_page(
            self.window.project.paleomap_documents,
            factor_tasks=self.window.project.factor_map_tasks,
            project_crs=self.window.project.coordinate.project_crs,
        )
        self._refresh_data_page()

    def _on_contour_drafts_updated(self) -> None:
        """Refresh mapping after ContourDraft isolines are pushed to map documents."""
        page = self.window.app_shell.mapping_page_widget()
        if page is not None and hasattr(page, "set_project"):
            page.set_project(self.window.project)
        self.window.app_shell.update_preparation_page(
            self.window.project.factor_map_tasks
        )
        self.window.app_shell.update_mapping_page(
            self.window.project.paleomap_documents,
            factor_tasks=self.window.project.factor_map_tasks,
            project_crs=self.window.project.coordinate.project_crs,
        )
        state = dashboard_state(self.window.project)
        steps = home_workflow_steps(self.window.project)
        self.window.app_shell.update_home_page(state, steps, project=self.window.project)

    def _on_stratigraphy_updated(self) -> None:
        """Re-push stratigraphy-bound pages after sequence scheme save/target change."""
        state = dashboard_state(self.window.project)
        steps = home_workflow_steps(self.window.project)
        self.window.app_shell.update_home_page(state, steps, project=self.window.project)
        self.window.app_shell.update_sequence_framework_page(
            self.window.project.stratigraphy
        )
        self.window.app_shell.update_stratigraphy_correlation_page(
            self.window.project
        )
        self.window.app_shell.update_preparation_page(
            self.window.project.factor_map_tasks
        )
        self.window.app_shell.update_mapping_page(
            self.window.project.paleomap_documents,
            factor_tasks=self.window.project.factor_map_tasks,
            project_crs=self.window.project.coordinate.project_crs,
        )

    def _on_generate_demo_map_draft(self) -> None:
        """Compile a deterministic demo draft; confirm if mapping scene is dirty."""
        page = self.window.app_shell.mapping_page_widget()
        if page is not None and hasattr(page, "is_dirty") and page.is_dirty():
            reply = QMessageBox.question(
                self.window,
                "未保存的编图修改",
                "当前图件有未保存修改。生成演示草稿将刷新编图页面。是否先保存草稿？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                if not page.save_draft():
                    return
        compile_map_draft(self.window.project, seed=0)
        self.window._refresh_shell()

    def _on_open_in_visualization(self, ref) -> None:
        self.window.app_shell.icon_rail.set_active(PAGE_INDEX_VISUALIZATION)
        self.window.app_shell._switch_page(PAGE_INDEX_VISUALIZATION)
        viz = self.window.app_shell.page_stack.widget(PAGE_INDEX_VISUALIZATION)
        if hasattr(viz, "open_ref"):
            viz.open_ref(ref)

    def _on_home_navigation(self, index: int) -> None:
        self.window.app_shell.icon_rail.set_active(index)
        self.window.app_shell._switch_page(index)
