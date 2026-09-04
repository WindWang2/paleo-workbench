"""TaskCenter：后台任务中心（model/view 增量刷新）。

历史实现（#1157 之前）每 400ms ``tree.clear()`` 后整树重建，逐行 new
QProgressBar/QPushButton——取消按钮在点击与重建竞态中被吞、选中与滚动每
tick 丢失、常驻 widget 反复析构。本实现：

- ``QAbstractTableModel`` 差分刷新：结构变化走 insert/removeRows，状态/进
  度/用时变化只发 ``dataChanged``；
- 进度条与取消按钮由 delegate 绘制（``editorEvent`` 承接点击），行内不再
  创建任何常驻 widget；
- 选中按 task_id 跨结构变化保持；滚动位置在顶部插入新行时保持；
- 右键菜单：取消 / 重试（failed·cancelled）/ 复制任务 ID / 详情。
"""
from __future__ import annotations

import time

from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QStyledItemDelegate,
    QTableView,
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

_MAX_ROWS = 100
# 列：状态 / 任务 / 进度 / 用时 / 操作
_COL_STATE, _COL_TITLE, _COL_PROGRESS, _COL_ELAPSED, _COL_ACTION = range(5)
_COLUMNS = 5


class _TaskTableModel(QAbstractItemModel):
    """TaskScheduler 快照的增量镜像；行序按 submitted_at 倒序（最新在顶）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []  # TaskHandle，最新在顶
        # 行内容签名：仅变化列发 dataChanged（elapsed 每秒变化单独处理）。
        self._signatures: dict[str, tuple] = {}

    # -- Qt 模型契约 ----------------------------------------------------------

    def index(self, row, column, parent=QModelIndex()):
        if parent.isValid() or not (0 <= row < len(self._rows)):
            return QModelIndex()
        return self.createIndex(row, column, row)

    def parent(self, child):  # noqa: N802 - Qt 命名
        return QModelIndex()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else _COLUMNS

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        handle = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.UserRole:
            return handle
        if role == Qt.ItemDataRole.DisplayRole:
            if column == _COL_TITLE:
                return handle.spec.title or handle.spec.kind or handle.task_id
            if column == _COL_ELAPSED:
                return TaskCenter.format_elapsed(
                    max(
                        0.0,
                        (handle.finished_at or time.monotonic())
                        - (handle.started_at or handle.submitted_at),
                    )
                )
        if role == Qt.ItemDataRole.ForegroundRole and column == _COL_STATE:
            return QColor(_STATE_COLORS.get(self._state_key(handle), tokens.TEXT_PRIMARY))
        if role == Qt.ItemDataRole.ToolTipRole and column == _COL_TITLE:
            return handle.message or handle.error or handle.task_id
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return ("状态", "任务", "进度", "用时", "操作")[section]
        return None

    # -- 行取值（delegate 消费） ----------------------------------------------

    @staticmethod
    def _state_key(handle) -> str:
        return getattr(handle.state, "value", str(handle.state))

    def handle_at(self, row: int):
        return self._rows[row] if 0 <= row < len(self._rows) else None

    # -- 增量刷新 --------------------------------------------------------------

    def refresh(self, handles: list) -> None:
        """差分应用新快照；保持行序 submitted_at 倒序。"""
        from paleo_workbench.runtime.task_scheduler import TaskState

        handles = sorted(handles, key=lambda h: h.submitted_at, reverse=True)[:_MAX_ROWS]
        new_ids = [h.task_id for h in handles]
        old_ids = [h.task_id for h in self._rows]
        old_by_id = {h.task_id: h for h in self._rows}
        new_by_id = {h.task_id: h for h in handles}

        # 1) 移除消失的行（从后往前删避免索引漂移）。
        for row in range(len(old_ids) - 1, -1, -1):
            if old_ids[row] not in new_by_id:
                self.beginRemoveRows(QModelIndex(), row, row)
                removed = self._rows.pop(row)
                self._signatures.pop(removed.task_id, None)
                self.endRemoveRows()

        # 2) 插入新行（按目标位置升序插入，保持倒序）。
        existing = {h.task_id for h in self._rows}
        for position, task_id in enumerate(new_ids):
            if task_id in existing:
                continue
            self.beginInsertRows(QModelIndex(), position, position)
            self._rows.insert(position, new_by_id[task_id])
            self.endInsertRows()

        # 3) 原位更新变化的行：仅变化列发 dataChanged。
        active = TaskState.QUEUED, TaskState.RUNNING
        now = time.monotonic()
        for row, handle in enumerate(self._rows):
            core = (
                self._state_key(handle),
                round(handle.progress, 3),
                handle.message,
                handle.error,
            )
            signature = self._signatures.get(handle.task_id)
            elapsed_changed = (
                signature is not None
                and signature[4] != int(
                    (handle.finished_at or now)
                    - (handle.started_at or handle.submitted_at)
                )
            )
            self._signatures[handle.task_id] = (*core, int(
                (handle.finished_at or now)
                - (handle.started_at or handle.submitted_at)
            ))
            if signature is None or signature[:4] != core:
                left = self.index(row, 0)
                right = self.index(row, _COLUMNS - 1)
                self.dataChanged.emit(left, right)
            elif elapsed_changed:
                self.dataChanged.emit(
                    self.index(row, _COL_ELAPSED), self.index(row, _COL_ELAPSED)
                )
            # 取消按钮的可见性随 state 变化，已覆盖在整行 dataChanged 中；
            # 活动行超时防悬挂标记（无消费者，仅诊断）。
            _ = active


class _TaskRowDelegate(QStyledItemDelegate):
    """进度条 + 取消按钮的纯绘制 delegate：行内零常驻 widget。"""

    def __init__(self, model: _TaskTableModel, parent=None):
        super().__init__(parent)
        self._model = model

    def paint(self, painter, option, index):
        from paleo_workbench.runtime.task_scheduler import TaskState

        handle = self._model.handle_at(index.row())
        if handle is None:
            super().paint(painter, option, index)
            return
        column = index.column()
        if column == _COL_STATE:
            option.text = self._state_text(handle)
            super().paint(painter, option, index)
        elif column == _COL_PROGRESS:
            progress = max(0, min(100, round(handle.progress * 100)))
            from PySide6.QtWidgets import QStyle, QStyleOptionProgressBar

            bar_option = QStyleOptionProgressBar()
            bar_option.rect = option.rect
            bar_option.minimum = 0
            bar_option.maximum = 100
            bar_option.progress = progress
            bar_option.textVisible = False
            bar_option.state = option.state
            bar_option.direction = option.direction
            bar_option.fontMetrics = option.fontMetrics
            bar_option.palette = option.palette
            option.widget.style().drawControl(
                QStyle.ControlElement.CE_ProgressBar, bar_option, painter
            )
        elif column == _COL_ACTION and handle.state in (
            TaskState.QUEUED,
            TaskState.RUNNING,
        ):
            from PySide6.QtWidgets import QStyle, QStyleOptionButton

            button = QStyleOptionButton()
            button.rect = option.rect.adjusted(2, 2, -2, -2)
            button.text = "取消"
            button.state = option.state | QStyle.StateFlag.State_Enabled
            button.direction = option.direction
            button.fontMetrics = option.fontMetrics
            button.palette = option.palette
            option.widget.style().drawControl(
                QStyle.ControlElement.CE_PushButton, button, painter
            )
        else:
            super().paint(painter, option, index)

    @staticmethod
    def _state_text(handle) -> str:
        from paleo_workbench.runtime.task_scheduler import TaskState

        labels = {
            TaskState.QUEUED: "排队",
            TaskState.RUNNING: "运行中",
            TaskState.DONE: "完成",
            TaskState.FAILED: "失败",
            TaskState.CANCELLED: "已取消",
        }
        text = labels.get(handle.state, str(handle.state))
        if handle.state is TaskState.RUNNING:
            text = f"{text} {round(handle.progress * 100)}%"
        elif handle.cancel_requested and handle.state in (
            TaskState.QUEUED,
            TaskState.RUNNING,
        ):
            text = "取消中"
        return text

    def editorEvent(self, event, model, option, index) -> bool:
        from paleo_workbench.runtime.task_scheduler import TaskState

        if event.type() != event.Type.MouseButtonRelease:
            return super().editorEvent(event, model, option, index)
        handle = self._model.handle_at(index.row())
        if handle is None or index.column() != _COL_ACTION:
            return super().editorEvent(event, model, option, index)
        if handle.state not in (TaskState.QUEUED, TaskState.RUNNING):
            return True
        from paleo_workbench.runtime.task_scheduler import get_scheduler

        get_scheduler().cancel(handle.task_id)
        return True


class TaskCenter(QFrame):
    """轮询 Qt model over the process-wide TaskScheduler authority（增量）。"""

    active_count_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationTaskCenter")
        self._last_active = -1
        self._selected_task_id: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.model = _TaskTableModel(self)
        self.tree = QTableView(self)
        self.tree.setObjectName("WorkstationTaskTree")
        self.tree.setModel(self.model)
        self.tree.setItemDelegate(_TaskRowDelegate(self.model, self.tree))
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setShowGrid(False)
        self.tree.setWordWrap(False)
        self.tree.verticalHeader().setVisible(False)
        self.tree.horizontalHeader().setStretchLastSection(False)
        header = self.tree.horizontalHeader()
        header.setSectionResizeMode(_COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_TITLE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_COL_PROGRESS, 150)
        header.setSectionResizeMode(_COL_ELAPSED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_ACTION, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.selectionModel().selectionChanged.connect(self._remember_selection)
        outer.addWidget(self.tree, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # -- 刷新 ----------------------------------------------------------------

    def refresh(self) -> None:
        from paleo_workbench.runtime.task_scheduler import TaskState, get_scheduler

        handles = get_scheduler().statuses()
        active = sum(
            handle.state in (TaskState.QUEUED, TaskState.RUNNING) for handle in handles
        )
        if active != self._last_active:
            self._last_active = active
            self.active_count_changed.emit(active)

        scroll_before = self.tree.verticalScrollBar().value()
        at_top = scroll_before == 0
        self.model.refresh(handles)
        self._restore_selection()
        if not at_top:
            self.tree.verticalScrollBar().setValue(min(scroll_before, self.tree.verticalScrollBar().maximum()))

    def _remember_selection(self, *_args) -> None:
        rows = self.tree.selectionModel().selectedRows(_COL_TITLE)
        handle = self.model.handle_at(rows[0].row()) if rows else None
        self._selected_task_id = handle.task_id if handle else None

    def _restore_selection(self) -> None:
        if self._selected_task_id is None:
            return
        for row, handle in enumerate(self.model._rows):
            if handle.task_id == self._selected_task_id:
                self.tree.selectRow(row)
                return

    # -- 上下文菜单 ------------------------------------------------------------

    def _show_context_menu(self, position) -> None:
        from paleo_workbench.runtime.task_scheduler import TaskState, get_scheduler

        index = self.tree.indexAt(position)
        handle = self.model.handle_at(index.row()) if index.isValid() else None
        if handle is None:
            return
        scheduler = get_scheduler()
        menu = QMenu(self)
        if handle.state in (TaskState.QUEUED, TaskState.RUNNING):
            action = menu.addAction("取消")
            action.triggered.connect(lambda: scheduler.cancel(handle.task_id))
        if handle.state in (TaskState.FAILED, TaskState.CANCELLED):
            action = menu.addAction("重试")
            action.triggered.connect(lambda: scheduler.submit(handle.spec))
        action = menu.addAction("复制任务 ID")
        action.triggered.connect(
            lambda: QApplication.clipboard().setText(handle.task_id)
        )
        detail = menu.addAction("详情…")
        detail.triggered.connect(lambda: self._show_details(handle))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    @staticmethod
    def _show_details(handle) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

        dialog = QDialog()
        dialog.setWindowTitle(f"任务详情 — {handle.spec.title or handle.task_id}")
        layout = QVBoxLayout(dialog)
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(
            "\n".join(
                [
                    f"任务 ID: {handle.task_id}",
                    f"类型: {handle.spec.kind}",
                    f"状态: {getattr(handle.state, 'value', handle.state)}",
                    f"进度: {round(handle.progress * 100)}%",
                    f"消息: {handle.message or '—'}",
                    f"错误: {handle.error or '—'}",
                    f"结果: {repr(handle.result)[:2000] if handle.result is not None else '—'}",
                ]
            )
        )
        layout.addWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.resize(520, 360)
        dialog.exec()

    @staticmethod
    def format_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f} s"
        minutes, remainder = divmod(int(seconds), 60)
        return f"{minutes:02d}:{remainder:02d}"

    def shutdown(self) -> None:
        self.timer.stop()
