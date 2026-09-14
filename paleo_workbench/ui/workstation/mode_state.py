"""编图工作台模式状态机（M5，02-state-machine-design.md 的实现）。

纯 QObject 投影层（00-decisions D12）：只观察既有信号（工具激活/期次提交/
QC 面板显隐/临时平移），广播 ``mode_changed`` 供只读消费者（提示条、快捷键
域判定）订阅；不拥有工具/画布状态——删除本层系统行为不变。回环契约：
消费者不得再向 FSM 派发事件（M5-ECHO 测试钉住）。
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal


class WorkstationMode(str, Enum):
    IDLE = "IDLE"
    DIGITIZING = "DIGITIZING"
    ADJUSTING_BOUNDARY = "ADJUSTING_BOUNDARY"
    INSPECTING_QC = "INSPECTING_QC"
    TIME_TRAVELLING = "TIME_TRAVELLING"


class ModeEvent(Enum):
    TOOL_ACTIVATED = "tool_activated"
    TOOL_DEACTIVATED = "tool_deactivated"
    ESC = "esc"
    VERTEX_ACT = "vertex_act"
    QC_HUB_ACTIVATED = "qc_hub_activated"
    QC_HUB_CLOSED = "qc_hub_closed"
    SCRUB_START = "scrub_start"
    EPOCH_COMMIT = "epoch_commit"
    ONION_TOGGLED = "onion_toggled"
    PAN_HELD = "pan_held"
    PAN_RELEASED = "pan_released"


#: 顶点/重塑类工具（TOOL_ACTIVATED 直接进 ADJUSTING_BOUNDARY）。
ADJUSTING_TOOLS: frozenset[str] = frozenset({"vertex", "reshape", "move_feature"})

#: 各模式提示条文案（S5-2 查找表；信号驱动，非轮询）。
MODE_HINTS: dict[WorkstationMode, str] = {
    WorkstationMode.IDLE: (
        "浏览：Space 平移 · Z/X 缩放 · Tab 循环要素 · Ctrl+D 吸属性"),
    WorkstationMode.DIGITIZING: (
        "数字化中：Space 平移 · Tab 下一要素 · Ctrl+D 吸属性 · Esc 取消"),
    WorkstationMode.ADJUSTING_BOUNDARY: (
        "边界调整：Tab 下一要素 · Z/X 缩放 · Esc 退出"),
    WorkstationMode.INSPECTING_QC: (
        "质检向导：↑↓ 选择 · Enter 定位 · F 修复 · Esc 关闭"),
    WorkstationMode.TIME_TRAVELLING: (
        "期次对比：←→ 步进 · 🧅 洋葱皮 · Esc 返回编图"),
}


class ModeStateMachine(QObject):
    """确定性转移（见 02 转移表）；``pan_held`` 是模式之上的瞬态标志。"""

    mode_changed = Signal(object)  # WorkstationMode

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = WorkstationMode.IDLE
        self._mode_before_travel = WorkstationMode.IDLE
        self._pan_held = False

    # -- 读 -----------------------------------------------------------------

    @property
    def mode(self) -> WorkstationMode:
        return self._mode

    @property
    def pan_held(self) -> bool:
        return self._pan_held

    # -- 事件 ---------------------------------------------------------------

    def dispatch(self, event: ModeEvent, *, tool_id: str = "") -> None:
        if event is ModeEvent.PAN_HELD:
            self._pan_held = True
            return
        if event is ModeEvent.PAN_RELEASED:
            self._pan_held = False
            return
        if event is ModeEvent.ONION_TOGGLED:
            return  # 自环：洋葱皮不换状态

        current = self._mode
        if event is ModeEvent.TOOL_ACTIVATED:
            if current is WorkstationMode.TIME_TRAVELLING:
                return  # 拒绝：先 Esc 结束期次对比（02 表 †）
            target = (WorkstationMode.ADJUSTING_BOUNDARY
                      if str(tool_id) in ADJUSTING_TOOLS
                      else WorkstationMode.DIGITIZING)
        elif event is ModeEvent.VERTEX_ACT:
            if current is WorkstationMode.TIME_TRAVELLING:
                return
            target = WorkstationMode.ADJUSTING_BOUNDARY
        elif event is ModeEvent.TOOL_DEACTIVATED:
            target = WorkstationMode.IDLE
        elif event is ModeEvent.ESC:
            target = WorkstationMode.IDLE
        elif event is ModeEvent.QC_HUB_ACTIVATED:
            target = WorkstationMode.INSPECTING_QC
        elif event is ModeEvent.QC_HUB_CLOSED:
            target = (WorkstationMode.IDLE
                      if current is WorkstationMode.INSPECTING_QC else current)
        elif event is ModeEvent.SCRUB_START:
            if current is not WorkstationMode.TIME_TRAVELLING:
                self._mode_before_travel = current
            target = WorkstationMode.TIME_TRAVELLING
        elif event is ModeEvent.EPOCH_COMMIT:
            target = (self._mode_before_travel
                      if current is WorkstationMode.TIME_TRAVELLING else current)
        else:  # pragma: no cover - 未知事件不抛异常（D12）
            target = current
        if target is not current:
            self._mode = target
            self.mode_changed.emit(target)

    # -- 便捷注入（宿主接线用） -----------------------------------------------

    def dispatch_tool_activated(self, tool_id: str) -> None:
        self.dispatch(ModeEvent.TOOL_ACTIVATED, tool_id=tool_id)

    def hint_text(self) -> str:
        return MODE_HINTS.get(self._mode, MODE_HINTS[WorkstationMode.IDLE])
