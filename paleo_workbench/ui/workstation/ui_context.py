"""UIContextService（V6 §2）：派生式 UI 上下文——展示态聚合，非第二权威。

设计约束（对应 /goal V6 §2 "Do NOT create a second domain authority"）：

* 本服务**不持有**任何领域状态；每个快照字段都来自注册的 provider
  （权威侧适配器：SelectionContext / MappingWorkspace controller /
  QGIS 桥探测 / Harness 权限 / TaskScheduler…）。
* provider 缺席 → 字段为诚实未知（``None`` / 安全默认），绝不编造。
* provider 抛异常 → 记 warning 并回落未知（fail-closed，不崩 UI）。
* ``refresh()`` 由权威变更信号在 GUI 线程触发；快照不可变、按值比较，
  仅在变化时发射 ``context_changed``（下游：palette 重新过滤、状态条、
  inspector 头部徽标）。

字段清单刻意精简：只收 V6 §4（命令适用性）与 §5（状态可见性）的
消费者实际读取的项；按需增补，不预置空想字段。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, fields

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UIContextSnapshot:
    """某一时刻的派生 UI 上下文（全部只读；None = 诚实未知）。"""

    # 工程上下文
    project_open: bool = False
    project_name: str | None = None
    # 工作区 / 编图阶段（MappingStage.value；None = 无工程或未进入编图）
    mapping_stage: str | None = None
    mapping_stage_label: str | None = None
    # 活动编辑目标（MappingWorkspaceController.active_target_layer_id 及其角色解析）
    active_layer_id: str | None = None
    active_layer_role: str | None = None
    active_layer_editable: bool | None = None
    active_layer_block_reason: str | None = None
    # V7 §3：活动图层几何类型 / 成熟度 / 冻结（palette applicability 与
    # 工具面求值共用；None = 诚实未知）。
    active_layer_kind: str | None = None
    active_layer_maturity: str | None = None
    active_layer_frozen: bool = False
    editing_active: bool = False
    # SelectionContext 地质槽位摘要（权威仍在 viz.selection_context）
    active_well_id: str | None = None
    active_horizon_id: str | None = None
    active_fault_id: str | None = None
    active_interpretation_id: str | None = None
    # 后端能力 / 降级路径
    qgis_bridge_available: bool | None = None
    # V7 §3：能力三态（native/degraded/unavailable）与原因（比单 bool 更
    # 诚实——降级≠不可用）；capability_reason 在 native 时为空串。
    capability_mode: str | None = None
    capability_reason: str | None = None
    # Harness 权限（WRITE 授权态；权威在 ActionContext.permissions）
    write_granted: bool = False
    # 任务态摘要（TaskScheduler 权威）
    running_task_count: int = 0


_SNAPSHOT_FIELD_NAMES = frozenset(f.name for f in fields(UIContextSnapshot))

Provider = Callable[[], object]


class UIContextService(QObject):
    """聚合各权威 provider → ``UIContextSnapshot``；变更时发信号。"""

    context_changed = Signal(object)  # UIContextSnapshot

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._providers: dict[str, Provider] = {}
        self._last: UIContextSnapshot | None = None

    # -- provider 注册 ---------------------------------------------------------

    def set_provider(self, name: str, fn: Provider) -> None:
        """注册/替换一个字段适配器（``name`` 必须是快照字段名）。"""
        if name not in _SNAPSHOT_FIELD_NAMES:
            raise KeyError(f"UIContextSnapshot 无字段 {name!r}")
        self._providers[name] = fn

    def clear_provider(self, name: str) -> None:
        self._providers.pop(name, None)

    # -- 快照 -------------------------------------------------------------------

    def snapshot(self) -> UIContextSnapshot:
        """从 provider 现值构建快照（不发信号；异常按未知处理）。"""
        values: dict[str, object] = {}
        for name, fn in self._providers.items():
            try:
                values[name] = fn()
            except Exception:  # noqa: BLE001 — 权威侧异常降级为未知
                logger.warning("UIContext provider %r 失败，按未知处理", name, exc_info=True)
        return UIContextSnapshot(**values)  # type: ignore[arg-type]

    def current(self) -> UIContextSnapshot:
        """最近一次 refresh 的快照（从未 refresh 过则现算）。"""
        return self._last if self._last is not None else self.snapshot()

    def refresh(self) -> UIContextSnapshot:
        """重建快照；变化时发射 ``context_changed``。

        拆壳期迟到触发（任务中心轮询定时器等）：C++ 信号源可能已销毁，
        静默忽略而非抛 RuntimeError 刷屏（与 shell 的死壳纪律一致）。
        """
        snap = self.snapshot()
        if snap != self._last:
            self._last = snap
            try:
                self.context_changed.emit(snap)
            except RuntimeError:
                pass  # 信号源已随壳销毁
        return snap
