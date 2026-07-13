from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel


class WellLogPredictionPage(QWidget):
    """Display-first 测井预测 page backed by PredictionTask and WellLogCanvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellLogPredictionPage")

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

        self.task_panel = PredictionTaskPanel()
        content.addWidget(self.task_panel, 0)

        self.canvas_panel = WellLogCanvasPanel()
        content.addWidget(self.canvas_panel, 1)

        self.evidence_panel = PredictionEvidencePanel()
        content.addWidget(self.evidence_panel, 0)

        outer.addLayout(content, 1)

    def update_state(self, prediction_tasks: list | tuple | None, project=None) -> None:
        task = active_prediction_task(prediction_tasks)
        self.task_panel.update_state(prediction_tasks)
        self.canvas_panel.update_state(task, project=project)
        self.evidence_panel.update_state(task)
