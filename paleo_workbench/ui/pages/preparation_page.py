from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel


class PreparationPage(QWidget):
    """制备 page: factor task list, preview grid, boundary panel + real interpolation."""

    # Emitted after batch_prepare_factor_maps mutates project.factor_map_tasks
    factor_maps_updated = Signal()
    generate_requested = Signal(str)  # method — app may handle when no project bound

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PreparationPage")
        self._project = None
        self._tasks: list = []

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

        self.preview_grid = FactorPreviewGrid()
        content.addWidget(self.preview_grid, 1)

        self.boundary_panel = BoundaryPanel()
        content.addWidget(self.boundary_panel, 0)

        outer.addLayout(content, 1)

        self.task_panel.generate_requested.connect(self._on_generate_requested)

    def set_project(self, project) -> None:
        """Bind the live ProjectDocument so batch generate can mutate factor_map_tasks."""
        self._project = project

    def update_state(self, tasks: list) -> None:
        self._tasks = list(tasks or [])
        self.task_panel.update_state(self._tasks)
        self.preview_grid.update_state(self._tasks)

    def _on_generate_requested(self, method: str) -> None:
        method = method or self.task_panel.selected_method()
        if self._project is None:
            # App should bind project; still bubble for tests / alternate hosts.
            self.generate_requested.emit(method)
            return
        try:
            from paleo_workbench.workflow.factor_interpolation import batch_prepare_factor_maps

            batch_prepare_factor_maps(self._project, method=method)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "单因素图生成失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        self.update_state(self._project.factor_map_tasks)
        self.factor_maps_updated.emit()
