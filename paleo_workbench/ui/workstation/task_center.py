from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from paleo_workbench import tokens

_STATE_COLORS = {
    "queued": tokens.TEXT_SECONDARY,
    "running": tokens.WARNING,
    "done": tokens.SUCCESS,
    "failed": tokens.ERROR_RED,
    "cancelled": tokens.TEXT_SECONDARY,
}


class TaskCenter(QFrame):
    """Polling Qt model over the process-wide TaskScheduler authority."""

    active_count_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationTaskCenter")
        self._last_active = -1
        # #1157: id-keyed row cache — refresh() diffs instead of rebuilding,
        # so cancel clicks land, selection/scroll survive, and no widget
        # churn happens on every tick.
        self._rows: dict[str, tuple[QTreeWidgetItem, QProgressBar, QPushButton]] = {}
        self._empty_item: QTreeWidgetItem | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("WorkstationTaskTree")
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["状态", "任务", "进度", "用时", "操作"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 150)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self.tree, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    _ROLE_TASK_ID = Qt.ItemDataRole.UserRole

    def refresh(self) -> None:
        from paleo_workbench.runtime.task_scheduler import TaskState, get_scheduler

        scheduler = get_scheduler()
        handles = sorted(
            scheduler.statuses(),
            key=lambda handle: handle.submitted_at,
            reverse=True,
        )[:24]
        active = sum(
            handle.state in (TaskState.QUEUED, TaskState.RUNNING) for handle in handles
        )
        if active != self._last_active:
            self._last_active = active
            self.active_count_changed.emit(active)

        if not handles:
            self._drop_all_rows()
            if self._empty_item is None:
                item = QTreeWidgetItem(["", "当前没有后台任务", "", "", ""])
                item.setDisabled(True)
                color = QColor(tokens.TEXT_SECONDARY)
                for column in range(item.columnCount()):
                    item.setForeground(column, color)
                self._empty_item = item
                self.tree.addTopLevelItem(item)
            return
        if self._empty_item is not None:
            index = self.tree.indexOfTopLevelItem(self._empty_item)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
            self._empty_item = None

        wanted = [handle.task_id for handle in handles]
        wanted_set = set(wanted)
        for task_id in list(self._rows):
            if task_id not in wanted_set:
                self._drop_row(task_id)
        current = []
        for i in range(self.tree.topLevelItemCount()):
            existing = self.tree.topLevelItem(i)
            current.append(existing.data(0, self._ROLE_TASK_ID) if existing is not None else None)
        if current != wanted:
            # Reorder only: take + re-add keeps item widgets attached.
            kept: list[QTreeWidgetItem] = []
            while self.tree.topLevelItemCount():
                taken = self.tree.takeTopLevelItem(0)
                if taken is not None:
                    kept.append(taken)
            by_id = {item.data(0, self._ROLE_TASK_ID): item for item in kept}
            for task_id in wanted:
                item = by_id.get(task_id)
                if item is None:
                    item = self._create_row(task_id, scheduler)
                self.tree.addTopLevelItem(item)

        labels = {
            TaskState.QUEUED: ("排队", "queued"),
            TaskState.RUNNING: ("运行中", "running"),
            TaskState.DONE: ("完成", "done"),
            TaskState.FAILED: ("失败", "failed"),
            TaskState.CANCELLED: ("已取消", "cancelled"),
        }
        now = time.monotonic()
        for handle in handles:
            item, bar, cancel = self._rows[handle.task_id]
            label, state_key = labels.get(handle.state, (str(handle.state), "queued"))
            progress = round(handle.progress * 100)
            item.setText(0, f"{label} {progress}%" if state_key == "running" else label)
            item.setText(1, handle.spec.title or handle.spec.kind or handle.task_id)
            elapsed_from = handle.started_at or handle.submitted_at
            elapsed_to = handle.finished_at or now
            item.setText(3, self._format_elapsed(max(0.0, elapsed_to - elapsed_from)))
            color = QColor(_STATE_COLORS.get(state_key, tokens.TEXT_PRIMARY))
            item.setForeground(0, color)
            item.setToolTip(1, handle.message or handle.error or handle.task_id)
            bar.setProperty("taskState", state_key)
            bar.setValue(progress)
            cancel.setVisible(handle.state in (TaskState.QUEUED, TaskState.RUNNING))

    def _create_row(self, task_id: str, scheduler) -> QTreeWidgetItem:
        """Build one row (item + bar + cancel button) exactly once per task."""
        item = QTreeWidgetItem(["", "", "", "", ""])
        item.setData(0, self._ROLE_TASK_ID, task_id)
        self.tree.addTopLevelItem(item)
        bar = QProgressBar(self.tree)
        bar.setObjectName("WorkstationTaskProgress")
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        self.tree.setItemWidget(item, 2, bar)
        cancel = QPushButton("取消", self.tree)
        cancel.setObjectName("WorkstationTertiaryButton")
        cancel.clicked.connect(
            lambda _checked=False, tid=task_id: scheduler.cancel(tid)
        )
        self.tree.setItemWidget(item, 4, cancel)
        self._rows[task_id] = (item, bar, cancel)
        return item

    def _drop_row(self, task_id: str) -> None:
        entry = self._rows.pop(task_id, None)
        if entry is None:
            return
        item, bar, cancel = entry
        index = self.tree.indexOfTopLevelItem(item)
        if index >= 0:
            self.tree.takeTopLevelItem(index)
        bar.deleteLater()
        cancel.deleteLater()

    def _drop_all_rows(self) -> None:
        for task_id in list(self._rows):
            self._drop_row(task_id)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f} s"
        minutes, remainder = divmod(int(seconds), 60)
        return f"{minutes:02d}:{remainder:02d}"

    def shutdown(self) -> None:
        self.timer.stop()
