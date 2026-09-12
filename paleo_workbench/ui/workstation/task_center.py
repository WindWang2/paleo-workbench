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
from paleo_workbench.ui.components.states import PwbEmptyState

def _state_colors() -> dict[str, str]:
    """状态→前景色，每调用取当前主题调色板（此前 import 时快照 light 值）。"""
    from paleo_workbench.ui.style import palette

    p = palette()
    return {
        "queued": p["TEXT_SECONDARY"],
        "running": p["WARNING"],
        "cancelling": p["WARNING"],
        "done": p["SUCCESS"],
        "degraded": p["WARNING"],
        "failed": p["ERROR_RED"],
        "cancelled": p["TEXT_SECONDARY"],
    }

_MAX_ROWS = 100
# 列：状态 / 任务 / 进度 / 用时 / 操作
_COL_STATE, _COL_TITLE, _COL_PROGRESS, _COL_ELAPSED, _COL_ACTION = range(5)
_COLUMNS = 5


class _OpSpecShim:
    """OperationRecord → 模型期望的 spec 形状（title/kind）。"""

    def __init__(self, record) -> None:
        self.title = record.title
        self.kind = "operation"


class _OperationHandleAdapter:
    """把 OperationRegistry 记录适配成任务模型可消费的 handle 形状。

    V11（goal §12）：页面级长操作（校验/导入/导出/重算…）与调度器任务
    在任务中心**同一张表**呈现，同一状态词表、同一取消交互。
    """

    registry_op = True

    def __init__(self, record, registry) -> None:
        self._record = record
        self._registry = registry
        self.task_id = f"op:{record.op_id}"
        self.spec = _OpSpecShim(record)
        from paleo_workbench.runtime.task_scheduler import TaskState

        mapping = {
            "queued": TaskState.QUEUED,
            "running": TaskState.RUNNING,
            "cancelling": TaskState.CANCELLING,
            "completed": TaskState.DONE,
            "warning": TaskState.DEGRADED,
            "failed": TaskState.FAILED,
            "cancelled": TaskState.CANCELLED,
        }
        self.state = mapping.get(record.state.value, TaskState.RUNNING)
        fraction = record.progress_fraction
        self.progress = fraction if fraction is not None else 0.0
        parts = []
        if record.object_label:
            parts.append(str(record.object_label))
        if record.stage:
            parts.append(str(record.stage))
        if record.state.terminal and record.result_label:
            parts.append(str(record.result_label))
        self.message = " · ".join(parts) if parts else None
        self.error = record.error
        self.result = None
        self.submitted_at = record.started_at
        self.started_at = record.started_at
        self.finished_at = record.finished_at
        self.cancel_requested = record.state.value == "cancelling"

    def cancel(self) -> bool:
        return self._registry.request_cancel(self._record.op_id)

    @property
    def record(self):
        return self._record


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
                title = handle.spec.title or handle.spec.kind or handle.task_id
                # 视觉 QA（10）：失败原因必须可读，不只藏在 tooltip。
                if getattr(handle.state, "value", "") == "failed" and handle.error:
                    short = str(handle.error).strip().splitlines()[0][:40]
                    return f"{title} — {short}"
                return title
            if column == _COL_STATE:
                # 视觉 QA（09/10）：状态列必须给模型文本——ResizeToContents
                # 以模型数据计宽，纯 delegate 绘制会让列塌缩成「…」。
                return _TaskRowDelegate._state_text(handle)
            if column == _COL_ELAPSED:
                return TaskCenter.format_elapsed(
                    max(
                        0.0,
                        (handle.finished_at or time.monotonic())
                        - (handle.started_at or handle.submitted_at),
                    )
                )
        if role == Qt.ItemDataRole.ForegroundRole and column == _COL_STATE:
            from paleo_workbench.ui.style import palette as _palette

            return QColor(_state_colors().get(self._state_key(handle), _palette()["TEXT_PRIMARY"]))
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
        if column == _COL_PROGRESS:
            # 手绘进度单元（视觉 QA 09）：CE_ProgressBar 在无行高的表视图里
            # 常渲染成空框；直接画填充条 + 百分比文本，失败/取消给文字态。
            from PySide6.QtGui import QColor

            painter.save()
            rect = option.rect.adjusted(4, 4, -4, -4)
            progress = max(0, min(100, round(handle.progress * 100)))
            from paleo_workbench.ui.theme import theme_manager
            from paleo_workbench import tokens

            pal = tokens.palette_for(theme_manager.current_theme.value)
            if handle.state is TaskState.FAILED:
                painter.setPen(QColor(pal["ERROR_RED"]))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "失败")
            elif handle.state is TaskState.CANCELLED:
                painter.setPen(QColor(pal["TEXT_SECONDARY"]))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "已取消")
            elif handle.state is TaskState.DEGRADED:
                painter.setPen(QColor(pal["WARNING"]))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "降级完成")
            else:
                track = QColor(pal["BORDER_LIGHT"])
                painter.fillRect(rect, track)
                fill_w = max(2, int(rect.width() * progress / 100))
                fill = QColor(pal["SUCCESS"] if handle.state is TaskState.DONE else pal["WARNING"])
                painter.fillRect(rect.adjusted(0, 0, -(rect.width() - fill_w), 0), fill)
                painter.setPen(QColor(pal["TEXT_SECONDARY"]))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{progress}%")
            painter.restore()
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
            TaskState.CANCELLING: "取消中",
            TaskState.DONE: "完成",
            TaskState.DEGRADED: "降级完成",
            TaskState.FAILED: "失败",
            TaskState.CANCELLED: "已取消",
        }
        text = labels.get(handle.state, str(handle.state))
        # V7 R1-P1：取消中优先于运行中（RUNNING+cancel_requested 是协作
        # 取消等待期——显示「运行中 N%」是假状态）。
        if handle.cancel_requested and handle.state in (
            TaskState.QUEUED,
            TaskState.RUNNING,
        ):
            text = "取消中"
        elif handle.state is TaskState.RUNNING:
            text = f"{text} {round(handle.progress * 100)}%"
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
        if getattr(handle, "registry_op", False):
            handle.cancel()
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
        self._registry = None
        self._registry_op_changed = None
        self._registry_op_removed = None

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
        header.setSectionResizeMode(_COL_ACTION, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_COL_ACTION, 64)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.doubleClicked.connect(self._on_double_clicked)
        self.tree.selectionModel().selectionChanged.connect(self._remember_selection)
        outer.addWidget(self.tree, 1)

        # V5-C9：空任务表的统一空态（此前是空白网格）
        self._empty_state = PwbEmptyState(
            "暂无任务",
            "提交制备 / 预测 / 转码等任务后将在此显示进度与状态",
        )
        self._empty_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_state.setParent(self.tree)
        self._empty_state.hide()
        self.model.rowsInserted.connect(self._update_empty_state)
        self.model.rowsRemoved.connect(self._update_empty_state)
        self.model.modelReset.connect(self._update_empty_state)

        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._empty_state.isVisible():
            self._empty_state.setGeometry(self.tree.viewport().rect())

    def _update_empty_state(self, *_args) -> None:
        if self.model.rowCount() == 0:
            self._empty_state.setGeometry(self.tree.viewport().rect())
            self._empty_state.show()
            self._empty_state.raise_()
        else:
            self._empty_state.hide()

    # -- 刷新 ----------------------------------------------------------------

    def attach_registry(self, registry) -> None:
        """V11：接入 OperationRegistry（页面级操作与调度器任务同表呈现）。"""
        if self._registry is registry:
            return
        if self._registry is not None:
            try:
                self._registry.operation_changed.disconnect(self._registry_op_changed)
                self._registry.operation_removed.disconnect(self._registry_op_removed)
            except (RuntimeError, TypeError):
                pass
        self._registry = registry
        # 批量操作的逐文件进度 tick 会高频发 operation_changed——
        # 用 100ms 单发合并刷新（400ms 轮询兜底；评审 P1-2 刷新风暴）。
        self._registry_refresh_timer = QTimer(self)
        self._registry_refresh_timer.setSingleShot(True)
        self._registry_refresh_timer.setInterval(100)
        self._registry_refresh_timer.timeout.connect(self.refresh)
        self._registry_op_changed = self._schedule_registry_refresh
        self._registry_op_removed = self._schedule_registry_refresh
        registry.operation_changed.connect(self._registry_op_changed)
        registry.operation_removed.connect(self._registry_op_removed)
        self.refresh()

    def _schedule_registry_refresh(self, _op: str = "") -> None:
        timer = getattr(self, "_registry_refresh_timer", None)
        if timer is not None:
            timer.start()

    def refresh(self) -> None:
        from paleo_workbench.runtime.task_scheduler import TaskState, get_scheduler

        handles = list(get_scheduler().statuses())
        if self._registry is not None:
            handles.extend(
                _OperationHandleAdapter(record, self._registry)
                for record in self._registry.records()
            )
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
        self._update_empty_state()
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
            if handle.cancel_requested:
                action.setEnabled(False)
                action.setToolTip("正在等待任务协作取消（长计算步骤间检查取消点）")
            action.triggered.connect(
                lambda: (
                    handle.cancel()
                    if getattr(handle, "registry_op", False)
                    else scheduler.cancel(handle.task_id)
                )
            )
        # V11：终态操作记录提供结果跳转（goal §12 jump-to-output）。
        record = getattr(handle, "record", None)
        if record is not None and record.jump is not None and record.state.terminal:
            jump_action = menu.addAction(
                f"跳转：{record.result_label}" if record.result_label else "跳转到结果"
            )
            jump_action.triggered.connect(lambda: self._run_jump(record))
        if handle.state in (TaskState.FAILED, TaskState.CANCELLED):
            action = menu.addAction("重试")
            # V7 §12：如实说明重试语义——重新提交相同 spec（闭包参数原样
            # 重放，输入若已变化不会自动更新）。
            action.setToolTip("用完全相同的参数重新提交该任务")
            action.setEnabled(not getattr(handle, "registry_op", False))
            action.triggered.connect(lambda: scheduler.submit(handle.spec))
        action = menu.addAction("复制任务 ID")
        action.triggered.connect(
            lambda: QApplication.clipboard().setText(handle.task_id)
        )
        detail = menu.addAction("详情…")
        detail.triggered.connect(lambda: self._show_details(handle))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    @staticmethod
    def _run_jump(record) -> None:
        if record.jump is None:
            return
        try:
            record.jump()
        except RuntimeError:
            pass  # 目标页面已销毁（迟到跳转）

    def _on_double_clicked(self, index) -> None:
        """双击终态操作记录 → 结果跳转（goal §12 jump-to-output）。"""
        if not index.isValid():
            return
        handle = self.model.handle_at(index.row())
        record = getattr(handle, "record", None) if handle is not None else None
        if record is not None and record.jump is not None and record.state.terminal:
            self._run_jump(record)

    def _show_details(self, handle) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

        dialog = QDialog(self)
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
