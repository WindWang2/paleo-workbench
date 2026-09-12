from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.components.badges import PwbBadge
from paleo_workbench.ui.modelview import reconcile_widget_items
from paleo_workbench.ui.workstation.state_language import (
    state_token,
    tone_to_badge,
)
from paleo_workbench.viz.prediction_helpers import active_prediction_task, field_value

#: 预测任务原始状态（英文字符串）→ state_language 任务词表键。
#: V11（01-ui-audit G3）：任务列表此前直接显示 pending/running 等英文
#: 裸串；统一经任务词表渲染（glyph + 中文 + tone）。
_TASK_STATUS_ALIASES = {
    "pending": "queued",
    "queued": "queued",
    "running": "running",
    "cancelling": "cancelling",
    "cancelled": "cancelled",
    "complete": "done",
    "completed": "done",
    "done": "done",
    "failed": "failed",
    "warning": "degraded",  # V11：warning=完成但有警示 → 降级完成（与 OperationRegistry/任务中心同义）
}


def task_status_token(status: str | None):
    """预测任务状态 → state_language 任务 StateToken（未知 → 排队中口径之外的
    「未知」不编造：回落 queued 之前先映射未知为 muted 的排队中）。"""
    key = _TASK_STATUS_ALIASES.get(str(status or "").strip().lower())
    if key is None:
        from paleo_workbench.ui.workstation.state_language import StateToken

        return StateToken("·", str(status or "待开始"), "muted")
    return state_token("task", key)


class TaskPanelBase(QFrame):
    """Shared left-hand task summary panel with selection list."""

    task_selected = Signal(int)

    def __init__(
        self,
        *,
        object_name: str,
        title: str,
        show_review_count: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        # V9：固定 240 → 最小 200 地板。面板可在 splitter/dock 中自由
        # 调整宽度（页面对最大宽度的提升已解除上限）。
        self.setMinimumWidth(200)
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

        title_label = QLabel(title)
        title_label.setObjectName("MapDockTitle")
        layout.addWidget(title_label)

        self.name_value = self._add_value(layout, "当前任务", "未选择预测任务")
        self.adapter_value = self._add_value(layout, "适配器", "—")
        # V11：状态值经任务词表渲染为徽章（tone 随状态），不再是英文裸串。
        status_label = QLabel("状态")
        status_label.setObjectName("WorkFieldLabel")
        layout.addWidget(status_label)
        self.status_badge = PwbBadge("待开始", tone="neutral")
        self.status_value = self.status_badge  # 兼容既有属性名（setText 可用）
        layout.addWidget(self.status_badge)
        self.mean_probability_value = self._add_value(layout, "平均概率", "—")
        self.review_count_value = (
            self._add_value(layout, "待复核区", "0 个") if show_review_count else None
        )

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

    @staticmethod
    def _task_key(item) -> str:
        identity = field_value(item, "id", None)
        if identity:
            return f"id:{identity}"
        return f"name:{field_value(item, 'name', '') or ''}"

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
        token = task_status_token(field_value(task, "status", None) if task else None)
        self.status_badge.setText(token.label)
        self.status_badge.set_tone(tone_to_badge(token.tone))
        probability = (field_value(task, "probability_summary", {}) or {}).get(
            "mean_probability"
        )
        self.mean_probability_value.setText(
            str(probability) if probability is not None else "—"
        )
        if self.review_count_value is not None:
            self.review_count_value.setText(
                f"{len(field_value(task, 'review_areas', []) or [])} 个"
            )

        # V11：列表按键差分同步（同键任务不重建行，滚动/选择保持），
        # 行文本经任务词表渲染。键→任务一次映射（评审 P2：避免逐行全表
        # 键扫描的 O(n²)）。
        self._suppress = True
        keys = [self._task_key(item) for item in tasks]
        row_objects = dict(zip(keys, tasks))
        reconcile_widget_items(
            self.task_list,
            keys,
            make_item=lambda _key: QListWidgetItem(),
            update_item=lambda row_item, key: self._render_task_row(
                row_item, row_objects.get(key)
            ),
        )
        active_row = -1
        active_key = self._task_key(task) if task is not None else None
        for index, key in enumerate(keys):
            if active_key is not None and key == active_key:
                active_row = index
                break
        if active_row >= 0:
            self.task_list.setCurrentRow(active_row)
        self._suppress = False

    @staticmethod
    def _render_task_row(row_item, item) -> None:
        if item is None:
            return
        name = field_value(item, "name", "") or "未命名预测任务"
        token = task_status_token(field_value(item, "status", None))
        row_item.setText(f"{name} · {token.label}")
        row_item.setToolTip(f"{name}\n状态：{token.label}")
