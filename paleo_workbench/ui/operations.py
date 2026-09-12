"""V11 统一操作注册表（goal §12 Task/Progress UX 的后端权威）。

问题（01-ui-audit G1/G3）：长任务散落 7 种进度习惯用法；TaskCenter 只轮询
TaskScheduler，页面级 worker（完整性校验、导入、导出、重算……）对任务中心
不可见；结果无跳转；模态进度对话框到处复制。

本模块是**表现层**操作登记处（不是第二个调度器——计算调度仍在
TaskScheduler / OwnedWorkerJob）：

* 生命周期 ``QUEUED → RUNNING → CANCELLING → COMPLETED | WARNING | FAILED
  | CANCELLED``（与 state_language 任务词表同义）；
* 每条记录携带：操作标题、对象上下文、进度（done/total 或阶段文本）、
  耗时、取消入口、结果跳转（label + callable）；
* TaskCenter 将 registry 快照与 scheduler 任务合并呈现；
* 工程关闭 ``clear()`` —— 会话结束不留悬挂记录（01-ui-audit C7 的 UI 侧
  修复；scheduler 侧重置仍归 Data Fabric owner）。

用法::

    ops = operation_registry()  # app shell 持有；默认全局惰性单例随 shell 销毁
    op = ops.begin("verify:abc", "完整性校验", object_label="well-1.las",
                   cancellable=True)
    ops.set_cancel(op, lambda: worker.cancel())
    ops.update(op, done=3, total=10, stage="SHA-256")
    ops.finish(op, OperationState.WARNING, result_label="2 项过期",
               jump=lambda: data_page.locate_asset("abc"))
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class OperationState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (
            OperationState.COMPLETED,
            OperationState.WARNING,
            OperationState.FAILED,
            OperationState.CANCELLED,
        )


@dataclass
class OperationRecord:
    op_id: str
    title: str
    state: OperationState = OperationState.QUEUED
    object_label: str | None = None
    done: int | None = None
    total: int | None = None
    stage: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    error: str | None = None
    cancellable: bool = False
    result_label: str | None = None
    # 跳转回调用 label 描述目标；跳转函数由登记方持有页面引用（随页面
    # 销毁失效时 jump_checked 会吞 RuntimeError）。
    jump: Callable[[], None] | None = None
    _cancel: Callable[[], None] | None = field(default=None, repr=False)

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    @property
    def progress_fraction(self) -> float | None:
        if self.done is None or not self.total:
            return None
        return max(0.0, min(1.0, self.done / self.total))


class OperationRegistry(QObject):
    """登记前台长操作；TaskCenter / 状态条从这里取统一视图。"""

    operation_changed = Signal(str)  # op_id
    operation_removed = Signal(str)

    _MAX_TERMINAL = 40  # 终态记录保留上限（FIFO 淘汰）

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ops: dict[str, OperationRecord] = {}
        self._terminal_order: list[str] = []

    # -- 登记与推进 ---------------------------------------------------------------

    def begin(
        self,
        op_id: str,
        title: str,
        *,
        object_label: str | None = None,
        cancellable: bool = False,
        total: int | None = None,
        queued: bool = False,
    ) -> str:
        if not op_id:
            raise ValueError("op_id 不能为空")
        record = OperationRecord(
            op_id=op_id,
            title=title,
            object_label=object_label,
            cancellable=cancellable,
            total=total,
            state=OperationState.QUEUED if queued else OperationState.RUNNING,
        )
        self._ops[op_id] = record
        self.operation_changed.emit(op_id)
        return op_id

    def update(
        self,
        op_id: str,
        *,
        done: int | None = None,
        total: int | None = None,
        stage: str | None = None,
        object_label: str | None = None,
    ) -> None:
        record = self._ops.get(op_id)
        if record is None or record.state.terminal:
            return
        if done is not None:
            record.done = max(0, int(done))
        if total is not None:
            record.total = max(0, int(total))
        if stage is not None:
            record.stage = stage
        if object_label is not None:
            record.object_label = object_label
        if record.state is OperationState.QUEUED:
            record.state = OperationState.RUNNING
        self.operation_changed.emit(op_id)

    def set_cancel(self, op_id: str, cancel: Callable[[], None]) -> None:
        record = self._ops.get(op_id)
        if record is None:
            return
        record._cancel = cancel
        record.cancellable = True

    def request_cancel(self, op_id: str) -> bool:
        record = self._ops.get(op_id)
        if (
            record is None
            or record.state.terminal
            or record.state is OperationState.CANCELLING
            or record._cancel is None
        ):
            return False
        try:
            record._cancel()
        except Exception:  # noqa: BLE001 — 取消失败不隐藏原状态
            logger.exception("操作 %s 取消钩子失败", op_id)
            return False
        # 取消钩子可能同步终结任务（worker 已停 → finish(CANCELLED) 已入账）
        # ——终态不回退（评审 P2-4）。
        if record.state.terminal:
            return True
        record.state = OperationState.CANCELLING
        self.operation_changed.emit(op_id)
        return True

    def finish(
        self,
        op_id: str,
        state: OperationState = OperationState.COMPLETED,
        *,
        error: str | None = None,
        result_label: str | None = None,
        jump: Callable[[], None] | None = None,
    ) -> None:
        record = self._ops.get(op_id)
        if record is None:
            return
        # 已终态的记录不回退（迟到 finish 不覆盖新状态）。
        if record.state.terminal:
            return
        if state is not None and not state.terminal:
            # finish 只接受终态；误传运行态按 FAILED 处理（诚实降级）。
            state = OperationState.FAILED
        record.state = state
        record.finished_at = time.monotonic()
        record.error = error
        record.result_label = result_label
        record.jump = jump
        self._terminal_order.append(op_id)
        self._evict_terminals()
        self.operation_changed.emit(op_id)

    # -- 查询 ---------------------------------------------------------------------

    def record(self, op_id: str) -> OperationRecord | None:
        return self._ops.get(op_id)

    def records(self) -> list[OperationRecord]:
        """全部记录（新→旧）。"""
        return list(self._ops.values())[::-1]

    def active_records(self) -> list[OperationRecord]:
        return [r for r in self.records() if not r.state.terminal]

    def active_label(self) -> str | None:
        active = self.active_records()
        if not active:
            return None
        first = active[0]
        if first.object_label:
            return f"{first.title} · {first.object_label}"
        return first.title

    # -- 会话 ---------------------------------------------------------------------

    def clear(self) -> None:
        """工程关闭：清空全部记录（终态与在途一并移除，不留悬挂回调）。"""
        for record in list(self._ops.values()):
            record.jump = None
            record._cancel = None
        self._ops.clear()
        self._terminal_order.clear()

    def _evict_terminals(self) -> None:
        while len(self._terminal_order) > self._MAX_TERMINAL:
            victim = self._terminal_order.pop(0)
            record = self._ops.get(victim)
            # 同 op_id 复活（begin 重用）时旧排队键可能指向新的运行态记录
            # ——只淘汰真正终态的记录（评审 P2）。
            if record is None or not record.state.terminal:
                continue
            record.jump = None
            record._cancel = None
            del self._ops[victim]
            self.operation_removed.emit(victim)


_default_registry: OperationRegistry | None = None


def operation_registry() -> OperationRegistry:
    """进程级惰性注册表（新 shell 经 ``bind_registry_to_shell`` 换新实例，
    全局引用随之改指——长期持有请保存 shell 侧 ``self.operations`` 引用，
    不要反复调本函数）。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = OperationRegistry()
    return _default_registry


def bind_registry_to_shell(shell_parent: QObject) -> OperationRegistry:
    """为当前 shell 创建独立注册表并接管全局引用（销毁即随 shell 回收）。"""
    global _default_registry
    registry = OperationRegistry(parent=shell_parent)
    _default_registry = registry
    return registry
