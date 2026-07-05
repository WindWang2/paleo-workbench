from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import AppShell
from paleo_workbench.workflow.service import dashboard_state


class PaleoWorkbenchWindow(QWidget):
    def __init__(self, project: ProjectDocument | None = None):
        super().__init__()
        self.project = project or ProjectDocument.new("Untitled Project")
        self.setWindowTitle(f"{self.project.meta.name} - Paleogeography Workbench")
        self.resize(1440, 900)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.app_shell = AppShell()
        state = dashboard_state(self.project)
        self.app_shell.set_project_name(state.get("project_name", self.project.meta.name))
        active_run = self.project.compilation_runs[-1] if self.project.compilation_runs else None
        steps = active_run.workflow_steps if active_run else []
        self.app_shell.update_home_page(state, steps)
        self.app_shell.update_data_page(state, self.project.resources)
        self.app_shell.update_well_log_prediction_page(self.project.prediction_tasks)
        self.app_shell.update_seismic_prediction_page(self.project.prediction_tasks)
        self.app_shell.update_sequence_framework_page(self.project.stratigraphy)
        self.app_shell.update_visualization_page(
            self.project.resources,
            self.project.prediction_tasks,
            self.project.paleomap_documents,
        )
        self.app_shell.update_preparation_page(self.project.factor_map_tasks)
        self.app_shell.update_mapping_page(self.project.paleomap_documents)
        self.app_shell.update_review_export_page(
            self.project.quality_reports,
            self.project.paleomap_documents,
            self.project.export_artifacts,
        )
        layout.addWidget(self.app_shell)
