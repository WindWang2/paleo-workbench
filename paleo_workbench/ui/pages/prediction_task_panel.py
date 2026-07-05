from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task, field_value


class PredictionTaskPanel(QFrame):
    """Left-hand read-only summary of prediction tasks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PredictionTaskPanel")
        self.setFixedWidth(240)
        self.setStyleSheet(
            f"QFrame#PredictionTaskPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("测井预测任务")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.name_value = self._add_value(layout, "当前任务", "未选择预测任务")
        self.adapter_value = self._add_value(layout, "适配器", "—")
        self.status_value = self._add_value(layout, "状态", "待开始")
        self.mean_probability_value = self._add_value(layout, "平均概率", "—")
        self.review_count_value = self._add_value(layout, "待复核区", "0 个")

        list_label = QLabel("任务列表")
        list_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(list_label)
        self.task_list = QListWidget()
        self.task_list.setStyleSheet(
            f"QListWidget {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px; }}"
        )
        layout.addWidget(self.task_list, 1)

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

    def update_state(self, prediction_tasks: list | tuple | None) -> None:
        tasks = list(prediction_tasks or [])
        task = active_prediction_task(tasks)

        self.name_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.adapter_value.setText(field_value(task, "adapter_kind", "") or "—")
        self.status_value.setText(field_value(task, "status", "") or "待开始")
        probability = (field_value(task, "probability_summary", {}) or {}).get("mean_probability")
        self.mean_probability_value.setText(str(probability) if probability is not None else "—")
        self.review_count_value.setText(f"{len(field_value(task, 'review_areas', []) or [])} 个")

        self.task_list.clear()
        for item in tasks:
            name = field_value(item, "name", "") or "未命名预测任务"
            status = field_value(item, "status", "") or "pending"
            self.task_list.addItem(f"{name} · {status}")
