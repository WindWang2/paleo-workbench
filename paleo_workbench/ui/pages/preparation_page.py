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
    # Emitted after ContourDraft generation mutates contour_drafts / maps
    contour_drafts_updated = Signal()
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
        self.task_panel.contour_draft_requested.connect(self._on_contour_draft_requested)

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

    def _on_contour_draft_requested(self) -> None:
        """Build ContourDraft isolines for all complete factor grids."""
        if self._project is None:
            QMessageBox.information(self, "等值线初稿", "请先打开或绑定工程。")
            return
        try:
            from paleo_workbench.workflow.contour_draft import (
                compile_contour_drafts_for_project,
            )

            drafts = compile_contour_drafts_for_project(self._project, apply_to_map=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "等值线初稿失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
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
