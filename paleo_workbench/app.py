from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.dashboard import WorkflowDashboard
from paleo_workbench.workflow.service import dashboard_state


class PaleoWorkbenchWindow(QWidget):
    def __init__(self, project: ProjectDocument | None = None):
        super().__init__()
        self.project = project or ProjectDocument.new("Untitled Project")
        self.setWindowTitle(f"{self.project.meta.name} - Paleogeography Workbench")
        self.resize(1280, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard = WorkflowDashboard(dashboard_state(self.project))
        layout.addWidget(self.dashboard)