from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
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


class TaskCenter(QFrame):
    """Polling Qt model over the process-wide TaskScheduler authority."""

    active_count_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationTaskCenter")
        self._last_active = -1

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

        self.tree.clear()
        if not handles:
            item = QTreeWidgetItem(["就绪", "当前没有后台任务", "", "", ""])
            item.setDisabled(True)
            self.tree.addTopLevelItem(item)
            return

        labels = {
            TaskState.QUEUED: "排队",
            TaskState.RUNNING: "运行中",
            TaskState.DONE: "完成",
            TaskState.FAILED: "失败",
            TaskState.CANCELLED: "已取消",
        }
        now = time.monotonic()
        for handle in handles:
            elapsed_from = handle.started_at or handle.submitted_at
            elapsed_to = handle.finished_at or now
            elapsed = max(0.0, elapsed_to - elapsed_from)
            item = QTreeWidgetItem(
                [
                    labels.get(handle.state, str(handle.state)),
                    handle.spec.title or handle.spec.kind or handle.task_id,
                    "",
                    self._format_elapsed(elapsed),
                    "",
                ]
            )
            item.setToolTip(1, handle.message or handle.error or handle.task_id)
            self.tree.addTopLevelItem(item)

            progress = QProgressBar(self.tree)
            progress.setRange(0, 100)
            progress.setValue(round(handle.progress * 100))
            progress.setTextVisible(True)
            self.tree.setItemWidget(item, 2, progress)

            if handle.state in (TaskState.QUEUED, TaskState.RUNNING):
                cancel = QPushButton("取消", self.tree)
                cancel.setObjectName("WorkstationTertiaryButton")
                cancel.clicked.connect(
                    lambda _checked=False, task_id=handle.task_id: scheduler.cancel(task_id)
                )
                self.tree.setItemWidget(item, 4, cancel)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f} s"
        minutes, remainder = divmod(int(seconds), 60)
        return f"{minutes:02d}:{remainder:02d}"

    def shutdown(self) -> None:
        self.timer.stop()
