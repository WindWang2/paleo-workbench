from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel
from paleo_workbench.ui.pages.visualization_summary_panel import VisualizationSummaryPanel
from paleo_workbench.ui.pages.visualization_trace_panel import VisualizationTracePanel


class VisualizationPage(QWidget):
    """Display-first 可视化 page combining geo-viz widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizationPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(16)

        content = QHBoxLayout()
        content.setSpacing(16)

        self.summary_panel = VisualizationSummaryPanel()
        content.addWidget(self.summary_panel, 0)

        self.composite_panel = CompositeVisualizationPanel()
        content.addWidget(self.composite_panel, 1)

        self.trace_panel = VisualizationTracePanel()
        content.addWidget(self.trace_panel, 0)

        outer.addLayout(content, 1)

    def update_state(self, resources: list, prediction_tasks: list, map_documents: list) -> None:
        self.summary_panel.update_state(resources, prediction_tasks, map_documents)
        self.composite_panel.update_state(prediction_tasks)
        self.trace_panel.update_state(prediction_tasks, map_documents)
