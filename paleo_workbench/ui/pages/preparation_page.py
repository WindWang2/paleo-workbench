from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel


class PreparationPage(QWidget):
    """Display-only 制备 page: assembles factor task list, preview grid, boundary panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PreparationPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(16)

        content = QHBoxLayout()
        content.setSpacing(16)

        self.task_panel = FactorTaskPanel()
        content.addWidget(self.task_panel, 0)

        self.preview_grid = FactorPreviewGrid()
        content.addWidget(self.preview_grid, 1)

        self.boundary_panel = BoundaryPanel()
        content.addWidget(self.boundary_panel, 0)

        outer.addLayout(content, 1)

    def update_state(self, tasks: list) -> None:
        self.task_panel.update_state(tasks)
        self.preview_grid.update_state(tasks)
