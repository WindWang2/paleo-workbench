from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task, field_value


class PredictionTaskPanel(QFrame):
    """Left-hand summary of prediction tasks with selection."""

    task_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PredictionTaskPanel")
        self.setFixedWidth(240)
        self._tasks: list = []
        self._suppress = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("测井预测任务")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.name_value = self._add_value(layout, "当前任务", "未选择预测任务")
        self.adapter_value = self._add_value(layout, "适配器", "—")
        self.status_value = self._add_value(layout, "状态", "待开始")
        self.mean_probability_value = self._add_value(layout, "平均概率", "—")
        self.review_count_value = self._add_value(layout, "待复核区", "0 个")

        list_label = QLabel("任务列表")
        list_label.setObjectName("WorkFieldLabel")
        layout.addWidget(list_label)
        self.task_list = QListWidget()
        self.task_list.setObjectName("WorkListWidget")
        self.task_list.currentRowChanged.connect(self._on_row)
        layout.addWidget(self.task_list, 1)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def _on_row(self, row: int) -> None:
        if not self._suppress and row >= 0:
            self.task_selected.emit(row)

    def update_state(
        self,
        prediction_tasks: list | tuple | None,
        *,
        selected_index: int | None = None,
    ) -> None:
        tasks = list(prediction_tasks or [])
        self._tasks = tasks
        if selected_index is not None and 0 <= selected_index < len(tasks):
            task = tasks[selected_index]
        else:
            task = active_prediction_task(tasks)

        self.name_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.adapter_value.setText(field_value(task, "adapter_kind", "") or "—")
        self.status_value.setText(field_value(task, "status", "") or "待开始")
        probability = (field_value(task, "probability_summary", {}) or {}).get(
            "mean_probability"
        )
        self.mean_probability_value.setText(
            str(probability) if probability is not None else "—"
        )
        self.review_count_value.setText(
            f"{len(field_value(task, 'review_areas', []) or [])} 个"
        )

        self._suppress = True
        self.task_list.clear()
        active_row = -1
        for index, item in enumerate(tasks):
            name = field_value(item, "name", "") or "未命名预测任务"
            status = field_value(item, "status", "") or "pending"
            self.task_list.addItem(f"{name} · {status}")
            if task is not None and (
                item is task
                or field_value(item, "id", None) == field_value(task, "id", None)
            ):
                active_row = index
        if active_row >= 0:
            self.task_list.setCurrentRow(active_row)
        self._suppress = False
