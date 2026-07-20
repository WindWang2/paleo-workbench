from __future__ import annotations

from paleo_workbench.ui.pages.task_panel_base import TaskPanelBase


class PredictionTaskPanel(TaskPanelBase):
    """Left-hand summary of prediction tasks with selection."""

    def __init__(self, parent=None):
        super().__init__(
            object_name="PredictionTaskPanel",
            title="测井预测任务",
            show_review_count=True,
            parent=parent,
        )
