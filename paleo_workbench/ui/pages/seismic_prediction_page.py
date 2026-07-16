from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task
from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel
from paleo_workbench.ui.pages.seismic_task_panel import SeismicTaskPanel
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel


class SeismicPredictionPage(QWidget):
    """地震预测 page: PredictionTask list + SeismicView + attribute/Auto-Tie controls."""

    prediction_updated = Signal()
    send_to_mapping_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicPredictionPage")
        self._project = None
        self._tasks: list = []
        self._selected_index: int | None = None

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

        self.task_panel = SeismicTaskPanel()
        content.addWidget(self.task_panel, 0)

        self.view_panel = SeismicViewPanel()
        content.addWidget(self.view_panel, 1)

        self.control_panel = SeismicControlPanel()
        content.addWidget(self.control_panel, 0)

        outer.addLayout(content, 1)

        self.task_panel.task_selected.connect(self._on_task_selected)
        self.control_panel.run_requested.connect(self._on_run)
        self.control_panel.send_requested.connect(self.send_to_mapping_requested.emit)
        self.control_panel.display_mode_changed.connect(self.view_panel.set_display_mode)
        self.control_panel.attribute_changed.connect(self._on_attribute)
        self.control_panel.well_tie_toggled.connect(self.view_panel.set_well_tie_enabled)
        self.view_panel.view_ready.connect(self.control_panel.set_controls_enabled)

    def set_project(self, project) -> None:
        self._project = project

    def update_state(self, prediction_tasks: list | tuple | None, project=None) -> None:
        if project is not None:
            self._project = project
        self._tasks = list(prediction_tasks or [])
        if self._selected_index is not None and not (
            0 <= self._selected_index < len(self._tasks)
        ):
            self._selected_index = None
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=self._selected_index)
        self.view_panel.update_state(task, project=self._project)
        self.control_panel.update_state(task, self.view_panel.volume_shape)
        # Sync controls from live view after volume load
        if self.view_panel.is_view_ready():
            mode = self.view_panel.display_mode()
            self.control_panel._suppress = True
            idx = self.control_panel.mode_combo.findText(mode)
            if idx >= 0:
                self.control_panel.mode_combo.setCurrentIndex(idx)
            self.control_panel._suppress = False

    def _current_task(self):
        if self._selected_index is not None and 0 <= self._selected_index < len(
            self._tasks
        ):
            return self._tasks[self._selected_index]
        return active_prediction_task(self._tasks)

    def _on_task_selected(self, index: int) -> None:
        self._selected_index = index
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=index)
        self.view_panel.update_state(task, project=self._project)
        self.control_panel.update_state(task, self.view_panel.volume_shape)

    def _on_attribute(self, label: str) -> None:
        if not self.view_panel.set_attribute_label(label):
            # Soft failure: volume may be empty / combo unavailable
            pass

    def _on_run(self) -> None:
        if self._project is None:
            QMessageBox.warning(self, "地震预测", "未绑定工程，无法运行")
            return
        try:
            from paleo_workbench.workflow.seismic_prediction import (
                run_seismic_facies_prediction,
            )

            task = run_seismic_facies_prediction(self._project, seed=len(self._tasks))
        except Exception as exc:
            QMessageBox.warning(
                self,
                "地震预测失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        self._tasks = list(self._project.prediction_tasks)
        self._selected_index = len(self._tasks) - 1
        self.update_state(self._tasks, project=self._project)
        self.prediction_updated.emit()
        _ = task  # used for side effects on project
