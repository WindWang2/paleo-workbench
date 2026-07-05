from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from paleo_workbench.ui import tokens


class VisualizationSummaryPanel(QFrame):
    """Left-hand project-slice summary for composite visualization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizationSummaryPanel")
        self.setFixedWidth(220)
        self.setStyleSheet(
            f"QFrame#VisualizationSummaryPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("可视化总览")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.prediction_count_value = self._add_value(layout, "预测任务", "0 个")
        self.map_count_value = self._add_value(layout, "古地理图", "0 幅")
        self.resource_count_value = self._add_value(layout, "资源项", "0 项")
        layout.addStretch()

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
            " border: none; background: transparent;"
        )
        layout.addWidget(value)
        return value

    def update_state(self, resources: list, prediction_tasks: list, map_documents: list) -> None:
        self.prediction_count_value.setText(f"{len(prediction_tasks or [])} 个")
        self.map_count_value.setText(f"{len(map_documents or [])} 幅")
        self.resource_count_value.setText(f"{len(resources or [])} 项")
