from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.viz.prediction_helpers import active_prediction_task
from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel
from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
from paleo_workbench.workflow.seismic_prediction import run_seismic_facies_prediction


class SeismicPredictionPage(QWidget):
    """Reference-style seismic analysis workbench around the existing view."""

    prediction_updated = Signal()
    send_to_mapping_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicPredictionPage")
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
        self.control_panel.send_requested.connect(self.send_to_mapping_requested.emit)
        self.control_panel.display_mode_changed.connect(self.view_panel.set_display_mode)
        self.attribute_panel.attribute_changed.connect(self._on_attribute)
        self.control_panel.well_tie_toggled.connect(self.view_panel.set_well_tie_enabled)
        self.view_panel.view_ready.connect(self._on_view_ready)

    def set_project(self, project) -> None:
        self._project = project

    def update_state(self, prediction_tasks: list | tuple | None, project=None) -> None:
        if project is not None:
            self._project = project
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
        if self._project is None:
            QMessageBox.warning(self, "地震预测", "未绑定工程，无法运行")
            return
        try:
            task = run_seismic_facies_prediction(self._project, seed=len(self._tasks))
        except Exception as exc:
            QMessageBox.warning(
                self,
                "地震预测失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        self._tasks = list(self._project.prediction_tasks)
        self.update_state(self._tasks, project=self._project)
        self.prediction_updated.emit()
        _ = task  # used for side effects on project
