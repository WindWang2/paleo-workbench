from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from paleo_workbench.workflow.service import dashboard_state, home_workflow_steps
from paleo_workbench.ui.preview_settings_dialog import PreviewSettingsDialog


class WorkflowController:
    """Manages cross-page workflow logic and signal wiring for PaleoWorkbenchWindow."""

    def __init__(self, window) -> None:
        self.window = window
        self._preview_settings_dialog: PreviewSettingsDialog | None = None

    def _show_preview_settings(self) -> None:
        """Open the shared preview settings for the current DataPage."""
        if self._preview_settings_dialog is None:
            dialog = PreviewSettingsDialog(
                self.window,
                store=self.window._preview_settings_store,
            )
            dialog.settings_applied.connect(self._apply_preview_settings)
            self._preview_settings_dialog = dialog
        reader = self.window.app_shell.data_page.reader_panel
        self._preview_settings_dialog.set_settings(reader.preview_settings)
        self._preview_settings_dialog.set_preview_mode(reader.current_mode)
        self._preview_settings_dialog.exec()

    def _apply_preview_settings(self, settings) -> None:
        """Route dialog output to the current shell, never a stale page."""
        self.window.app_shell.data_page.reader_panel.set_preview_settings(settings)

    def _wire_data_visualization_jump(self) -> None:
        page = self.window.app_shell.data_page_widget()
        if hasattr(page, "open_in_visualization"):
            page.open_in_visualization.connect(self._on_open_in_visualization)

    def _wire_mapping_page(self) -> None:
        page = self.window.app_shell.mapping_page_widget()
        if page is None:
            return
        if hasattr(page, "set_project"):
            page.set_project(self.window.project)
        if hasattr(page, "generate_demo_draft_requested"):
            page.generate_demo_draft_requested.connect(
                self._on_generate_demo_map_draft
            )
        if hasattr(page, "contour_drafts_updated"):
            page.contour_drafts_updated.connect(self._on_contour_drafts_updated)

    def _wire_preparation_page(self) -> None:
        page = self.window.app_shell.preparation_page_widget()
        if page is None:
            return
        if hasattr(page, "set_project"):
            page.set_project(self.window.project)
        if hasattr(page, "factor_maps_updated"):
            page.factor_maps_updated.connect(self._on_factor_maps_updated)
        if hasattr(page, "contour_drafts_updated"):
            page.contour_drafts_updated.connect(self._on_contour_drafts_updated)

    def _wire_sequence_page(self) -> None:
        page = self.window.app_shell.sequence_framework_page_widget()
        if page is None:
            return
        if hasattr(page, "set_project"):
            page.set_project(self.window.project)
        if hasattr(page, "stratigraphy_updated"):
            # Avoid duplicate connections across shell rebuilds of the same page
            # instance is new each rebuild; connect once per shell.
            page.stratigraphy_updated.connect(self._on_stratigraphy_updated)

    def _wire_seismic_page(self) -> None:
        page = self.window.app_shell.seismic_prediction_page_widget()
        if page is None:
            return
        if hasattr(page, "set_project"):
            page.set_project(self.window.project)
        if hasattr(page, "prediction_updated"):
            page.prediction_updated.connect(self._on_seismic_prediction_updated)
        if hasattr(page, "send_to_mapping_requested"):
            page.send_to_mapping_requested.connect(self._on_seismic_send_to_mapping)

    def _wire_well_log_page(self) -> None:
        page = self.window.app_shell.well_log_prediction_page_widget()
        if page is None:
            return
        if hasattr(page, "set_project"):
            page.set_project(self.window.project)
        if hasattr(page, "prediction_updated"):
            page.prediction_updated.connect(self._on_well_log_prediction_updated)
        if hasattr(page, "send_to_preparation_requested"):
            page.send_to_preparation_requested.connect(self._on_well_log_send_to_prep)

    def _wire_review_page(self) -> None:
        page = self.window.app_shell.review_export_page_widget()
        if page is None:
            return
        if hasattr(page, "set_project"):
            page.set_project(self.window.project)
        if hasattr(page, "reports_updated"):
            page.reports_updated.connect(self._on_qc_reports_updated)

    def _on_qc_reports_updated(self) -> None:
        from paleo_workbench.workflow.qc import active_quality_reports

        state = dashboard_state(self.window.project)
        steps = home_workflow_steps(self.window.project)
        self.window.app_shell.update_home_page(state, steps)
        self.window.app_shell.update_review_export_page(
            active_quality_reports(self.window.project),
            self.window.project.paleomap_documents,
            self.window.project.export_artifacts,
        )

    def _on_well_log_prediction_updated(self) -> None:
        """Refresh well-log / seismic / viz pages after a new single-well task."""
        self._on_seismic_prediction_updated()

    def _on_well_log_send_to_prep(self) -> None:
        """Batch-prepare factor maps from current project and open 制备 page."""
        from paleo_workbench.ui.app_shell import PAGE_INDEX_PREPARATION
        from paleo_workbench.workflow.factor_interpolation import (
            batch_prepare_factor_maps,
        )

        if not self.window.project.prediction_tasks:
            QMessageBox.information(self.window, "发送制备", "请先运行测井预测")
            return
        try:
            batch_prepare_factor_maps(self.window.project, method="IDW")
        except Exception as exc:
            QMessageBox.warning(
                self.window,
                "发送制备失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        self.window.app_shell.update_preparation_page(
            self.window.project.factor_map_tasks
        )
        self.window.app_shell.update_mapping_page(
            self.window.project.paleomap_documents,
            factor_tasks=self.window.project.factor_map_tasks,
            project_crs=self.window.project.coordinate.project_crs,
        )
        self.window.app_shell.icon_rail.set_active(PAGE_INDEX_PREPARATION)
        self.window.app_shell._switch_page(PAGE_INDEX_PREPARATION)

    def _on_seismic_prediction_updated(self) -> None:
        """Refresh seismic / visualization / home after a new facies task."""
        state = dashboard_state(self.window.project)
        steps = home_workflow_steps(self.window.project)
        self.window.app_shell.update_home_page(state, steps)
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

    def _on_seismic_send_to_mapping(self) -> None:
        """Compile a map draft from the latest prediction and open 编图."""
        from paleo_workbench.pipeline.compile_map import compile_map_draft
        from paleo_workbench.ui.app_shell import PAGE_INDEX_MAPPING

        if not self.window.project.prediction_tasks:
            QMessageBox.information(self.window, "发送编图", "请先运行地震预测")
            return
        compile_map_draft(self.window.project, seed=0)
        self.window.app_shell.update_mapping_page(
            self.window.project.paleomap_documents,
            factor_tasks=self.window.project.factor_map_tasks,
            project_crs=self.window.project.coordinate.project_crs,
        )
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
        self.window.app_shell.update_home_page(state, steps)

    def _on_stratigraphy_updated(self) -> None:
        """Re-push stratigraphy-bound pages after sequence scheme save/target change."""
        state = dashboard_state(self.window.project)
        steps = home_workflow_steps(self.window.project)
        self.window.app_shell.update_home_page(state, steps)
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
        from paleo_workbench.pipeline.compile_map import compile_map_draft

        compile_map_draft(self.window.project, seed=0)
        self.window._refresh_shell()

    def _on_open_in_visualization(self, ref) -> None:
        from paleo_workbench.ui.app_shell import PAGE_INDEX_VISUALIZATION

        self.window.app_shell.icon_rail.set_active(PAGE_INDEX_VISUALIZATION)
        self.window.app_shell._switch_page(PAGE_INDEX_VISUALIZATION)
        viz = self.window.app_shell.page_stack.widget(PAGE_INDEX_VISUALIZATION)
        if hasattr(viz, "open_ref"):
            viz.open_ref(ref)
