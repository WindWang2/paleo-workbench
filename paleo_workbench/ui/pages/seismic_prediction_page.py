from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task
from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel
from paleo_workbench.ui.pages.seismic_task_panel import SeismicTaskPanel
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel


class SeismicPredictionPage(QWidget):
    """Display-first 地震预测 page backed by PredictionTask and SeismicView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicPredictionPage")

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

    def update_state(self, prediction_tasks: list | tuple | None, project=None) -> None:
        task = active_prediction_task(prediction_tasks)
        self.task_panel.update_state(prediction_tasks)
        self.view_panel.update_state(task, project=project)
        self.control_panel.update_state(task, self.view_panel.volume_shape)
