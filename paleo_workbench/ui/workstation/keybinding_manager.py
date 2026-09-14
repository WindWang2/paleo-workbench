"""全键盘编图流管理器（M5）+ 状态提示条。

键处理走 **事件过滤器**（composite 与 canvas 双挂）：offscreen 下 QShortcut
模拟键不可靠（仓库既有经验），且 QAbstractItemView/画布会吞未知按键不透传
父级；过滤器对两类接收者都能先见先得。文本输入聚焦时全部让路（复用
:func:`paleo_workbench.ui.shortcuts.focus_in_text_input`，00-decisions D5）。

快捷键面（D5 冲突表已核对全仓占用）：
- ``Space`` 按住临时平移（press 进 pan / release 还原原工具，FSM 瞬态）；
- ``Tab`` 循环选中当前层要素（仅 DIGITIZING/ADJUSTING，不抢焦点链语义）；
- ``Z`` / ``X`` 画布中心放大/缩小（×1.5，无修饰键时才生效，避免吞 Ctrl+Z）；
- ``Ctrl+D`` 吸取选中要素相带属性装备画刷（吸色管的键盘路径，D10）；
- ``Esc`` 安全退出链：退出当前工具 → 关闭浮面向导 → IDLE（无手势期接管；
  手势期的取消仍由既有 map cancel 动作先行，见 04 #23）。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel, QWidget

from paleo_workbench.ui.workstation.mode_state import (
    ModeEvent,
    WorkstationMode,
)

#: 中心缩放倍率。
ZOOM_STEP = 1.5


class KeybindingHintBar(QLabel):
    """画布底部常驻提示条：文本随 FSM 模式切换（信号驱动，S5-2）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KeybindingHintBar")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip("编图快捷键随当前模式变化")

    def apply_mode(self, mode: WorkstationMode) -> None:
        from paleo_workbench.ui.workstation.mode_state import MODE_HINTS

        self.setText(MODE_HINTS.get(mode, ""))


class WorkstationKeyBindingManager(QObject):
    """composite/canvas 双挂键过滤器 + Esc 退出链 + FSM 事件桥。"""

    def __init__(self, composite: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._composite = composite
        self._pan_restore_tool: str | None = None
        self._last_tool_id: str | None = None

    # -- 安装 -----------------------------------------------------------------

    def install(self) -> None:
        composite = self._composite
        composite.installEventFilter(self)
        canvas = getattr(composite, "canvas", None)
        if canvas is not None:
            canvas.installEventFilter(self)
        qc_hub = getattr(composite, "qc_hub", None)
        if qc_hub is not None:
            qc_hub.installEventFilter(self)
        # 工具变化 → FSM（临时平移期抑制，防止模式闪烁）。
        controller = getattr(composite, "edit_controller", None)
        if controller is not None:
            controller.state_changed.connect(self._on_tool_state_changed)

    # -- 工具态 → FSM -----------------------------------------------------------

    def _on_tool_state_changed(self, *_args) -> None:
        if self._pan_restore_tool is not None:
            return  # 临时平移中的工具切换不是用户模式事件
        controller = self._composite.edit_controller
        tool = getattr(controller.tools, "active_tool", None)
        tool_id = str(getattr(tool, "tool_id", "") or "")
        machine = getattr(self._composite, "mode_state", None)
        if machine is None:
            return
        if tool_id and tool_id != "pan":
            if tool_id != self._last_tool_id:
                self._last_tool_id = tool_id
                machine.dispatch_tool_activated(tool_id)
        else:
            if self._last_tool_id:
                self._last_tool_id = None
                machine.dispatch(ModeEvent.TOOL_DEACTIVATED)

    # -- 事件过滤 ---------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        from paleo_workbench.ui.shortcuts import focus_in_text_input

        composite = self._composite
        if obj is getattr(composite, "qc_hub", None):
            if event.type() == QEvent.Type.Show:
                composite.mode_state.dispatch(ModeEvent.QC_HUB_ACTIVATED)
            elif event.type() == QEvent.Type.Hide:
                composite.mode_state.dispatch(ModeEvent.QC_HUB_CLOSED)
            return False

        if event.type() == QEvent.Type.KeyPress:
            if focus_in_text_input():
                return False
            # D9：动画平移期间的任何用户按键先打断动画（cancel 是幂等的）。
            smooth_pan = getattr(composite, "smooth_pan", None)
            if smooth_pan is not None:
                smooth_pan.cancel()
            key = event.key()
            modifiers = event.modifiers()
            if key == Qt.Key.Key_Space and modifiers == Qt.KeyboardModifier.NoModifier:
                self.begin_temporary_pan()
                return True
            if key == Qt.Key.Key_Tab:
                if self._cycle_scope_active():
                    self.cycle_selection()
                    return True
                return False
            if key == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.NoModifier:
                self.zoom_center(ZOOM_STEP)
                return True
            if key == Qt.Key.Key_X and modifiers == Qt.KeyboardModifier.NoModifier:
                self.zoom_center(1.0 / ZOOM_STEP)
                return True
            if key == Qt.Key.Key_D and (
                modifiers & Qt.KeyboardModifier.ControlModifier
            ):
                self.pick_facies_from_selection()
                return True
            if key == Qt.Key.Key_Escape:
                self.handle_escape()
                return True
        elif event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Space and self._pan_restore_tool is not None:
                self.release_temporary_pan()
                return True
        return False

    def _cycle_scope_active(self) -> bool:
        machine = getattr(self._composite, "mode_state", None)
        if machine is None:
            return False
        return machine.mode in (WorkstationMode.DIGITIZING,
                                WorkstationMode.ADJUSTING_BOUNDARY)

    # -- 动作 -------------------------------------------------------------------

    def begin_temporary_pan(self) -> None:
        controller = self._composite.edit_controller
        tool = getattr(controller.tools, "active_tool", None)
        tool_id = str(getattr(tool, "tool_id", "") or "")
        if tool_id in ("", "pan"):
            return
        self._pan_restore_tool = tool_id
        machine = getattr(self._composite, "mode_state", None)
        if machine is not None:
            machine.dispatch(ModeEvent.PAN_HELD)
        controller.activate_tool("pan")

    def release_temporary_pan(self) -> None:
        restore = self._pan_restore_tool
        self._pan_restore_tool = None
        machine = getattr(self._composite, "mode_state", None)
        if machine is not None:
            machine.dispatch(ModeEvent.PAN_RELEASED)
        if restore:
            self._composite.edit_controller.activate_tool(restore)

    def cycle_selection(self) -> None:
        handler = getattr(self._composite, "tab_cycle_selection", None)
        if callable(handler):
            handler()

    def zoom_center(self, factor: float) -> None:
        canvas = getattr(self._composite, "canvas", None)
        if canvas is not None:
            canvas.zoom_by(float(factor))

    def pick_facies_from_selection(self) -> None:
        handler = getattr(self._composite, "ctrl_d_pick_facies", None)
        if callable(handler):
            handler()

    def _escape_step(self, machine) -> None:
        if machine is not None:
            machine.dispatch(ModeEvent.ESC)

    def handle_escape(self) -> None:
        """安全退出链（D9 顺序；04 #23 两级接力）。

        手势进行中 → 先取消采点（既有 map cancel 语义）；洋葱皮激活 →
        结束期次对比；工具激活 → 退出工具；向导可见 → 关闭；最后 IDLE。
        """
        composite = self._composite
        machine = getattr(composite, "mode_state", None)
        controller = composite.edit_controller
        tool = getattr(controller.tools, "active_tool", None)
        tool_id = str(getattr(tool, "tool_id", "") or "")
        # B4（review）：数字化手势进行中——先取消手势（不退工具），与既有
        # map cancel 接力（composite 右键同款 tool.points 探测先例）。
        if tool is not None and getattr(tool, "points", None):
            controller.cancel_active_tool()
            return
        # F2（review）：洋葱皮激活——Esc 首按结束期次对比（02 表语义）。
        timeline = getattr(composite, "timeline", None)
        epoch_timeline = getattr(composite, "epoch_timeline", None)
        if timeline is not None and timeline.onion_button.isChecked():
            timeline.onion_button.blockSignals(True)
            timeline.onion_button.setChecked(False)
            timeline.onion_button.blockSignals(False)
            if epoch_timeline is not None:
                epoch_timeline.set_onion(False)
            self._escape_step(machine)
            return
        if tool_id and tool_id != "pan":
            controller.activate_tool("pan")
            self._escape_step(machine)
            return
        qc_hub = getattr(composite, "qc_hub", None)
        if qc_hub is not None and qc_hub.isVisible():
            qc_hub.hide()
            self._escape_step(machine)
            return
        self._escape_step(machine)
