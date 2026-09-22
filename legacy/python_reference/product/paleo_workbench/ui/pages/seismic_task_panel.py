from __future__ import annotations

from paleo_workbench.ui.pages.task_panel_base import TaskPanelBase


class SeismicTaskPanel(TaskPanelBase):
    """Left-hand summary of seismic prediction tasks with selection."""

    def __init__(self, parent=None):
        super().__init__(
            object_name="SeismicTaskPanel",
            title="地震预测任务",
            show_review_count=False,
            parent=parent,
        )
