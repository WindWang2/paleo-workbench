"""V11 五目标模型合同（07-active-edit-state）。

不变式：
1. 无手势：tool/edit/selection 目标 == active 图层（无分歧）。
2. 手势进行中（画布原生工具忙 + 工具持有活会话）：tool/edit 锁定会话层，
   切活动层不打断（V10 review #1 语义保持）且快照 divergent=True。
3. #1268 收敛：armed 捕获工具持有旧会话且无手势时，用户切目标 → 工具
   解除（pan）+ 原因可查 + 会话保持打开（切割线等跨层工作流依赖会话
   跨切换存活）——「树选 B、捕获仍写 A」的静默通道不存在。
4. 工具不在写旧层：切换零副作用（程序扫描安全）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.vector_layer import VectorLayer
from paleo_workbench.ui.workstation.composite_editing import (
    CompositeEditController,
    EditTargetSnapshot,
)


class _Tools:
    """duck-type 工具寄存器（session 持有 + 激活记录）。"""

    def __init__(self):
        self.active_tool = None
        self.activated: list[str] = []

    def set_active_tool(self, tool, *_args, **_kwargs):
        self.active_tool = tool


class _SessionTool:
    """armed 捕获工具（持有会话）。"""

    def __init__(self, session, busy: bool = False):
        self.session = session
        self.busy = busy


class _Canvas:
    def __init__(self):
        self.current = None
        self.busy = False

    def set_current_layer(self, doc_id):
        self.current = doc_id

    @property
    def native_tool_busy(self) -> bool:
        return self.busy

    def setFocus(self):
        pass

    def setCursor(self, *args, **kwargs):
        pass


@pytest.fixture()
def controller(qapp):
    ctl = CompositeEditController()
    ctl._canvas = _Canvas()
    ctl.tools = _Tools()
    return ctl


def _make_layer(ctl, layer_id: str, kind: str = "point") -> VectorLayer:
    layer = VectorLayer(id=layer_id, name=layer_id)
    ctl._layers[layer_id] = layer
    ctl._kinds[layer_id] = kind
    return layer


class TestTargetSnapshot:
    def test_no_gesture_all_targets_align(self, controller):
        _make_layer(controller, "A")
        _make_layer(controller, "B")
        controller.note_tree_selection("B")
        controller.set_active_layer("B")
        snap = controller.edit_targets()
        assert isinstance(snap, EditTargetSnapshot)
        assert snap.selected_tree_node == "B"
        assert snap.active_map_layer == "B"
        assert snap.edit_target_layer == "B"
        assert snap.tool_target_layer == "B"
        assert snap.selection_layer == "B"
        assert snap.divergent is False

    def test_gesture_locks_tool_target(self, controller):
        layer_a = _make_layer(controller, "A")
        _make_layer(controller, "B")
        controller.set_active_layer("A")
        session = controller._open_session(layer_a)
        controller.tools.active_tool = _SessionTool(session, busy=True)
        controller._canvas.busy = True
        # 用户点选 B（手势进行中：不打断）
        controller.set_active_layer("B")
        snap = controller.edit_targets()
        assert snap.active_map_layer == "B"
        assert snap.tool_target_layer == "A"
        assert snap.edit_target_layer == "A"
        assert snap.divergent is True
        assert layer_a.edit_session is session  # 会话不被打断


class TestSwitchConvergence:
    def test_armed_tool_keeps_session_with_honest_divergence(self, controller):
        """#1268 收敛（review #1 语义保持）：armed 工具跨切换保持会话，
        但 tool/edit 目标锁定会话层 + divergent + 信息性说明可查。"""
        layer_a = _make_layer(controller, "A")
        _make_layer(controller, "B")
        controller.set_active_layer("A")
        session = controller._open_session(layer_a)
        tool = _SessionTool(session, busy=False)
        controller.tools.active_tool = tool
        controller.set_active_layer("B")
        # 工具保持（不打断数字化）+ 会话保持
        assert controller.tools.active_tool is tool
        assert layer_a.edit_session is session
        # 五目标快照：诚实分歧
        snap = controller.edit_targets()
        assert snap.active_map_layer == "B"
        assert snap.tool_target_layer == "A"
        assert snap.edit_target_layer == "A"
        assert snap.divergent is True
        # 信息性说明可查（UI 呈现「数字化目标 A（树选中 B）」）
        reason = controller.last_switch_block_reason
        assert reason is not None and reason[0] == "A"
        assert "捕获目标保持" in reason[1]

    def test_unarmed_session_survives_switch(self, controller):
        """无工具写旧层：切换零副作用（切割线工作流：会话跨切换存活）。"""
        layer_a = _make_layer(controller, "A")
        _make_layer(controller, "B")
        controller.set_active_layer("A")
        session = controller._open_session(layer_a)
        controller.set_active_layer("B")
        assert layer_a.edit_session is session
        assert controller.last_switch_block_reason is None
        assert controller.edit_targets().divergent is False
        # 切回 A：会话仍可用
        controller.set_active_layer("A")
        assert controller.active_layer.edit_session is session

    def test_split_workflow_survives(self, controller):
        """跨层工作流端到端：会话存活 → geometry 命令路径可用。"""
        layer_a = _make_layer(controller, "A", kind="polygon")
        controller.set_active_layer("A")
        session = controller._open_session(layer_a)
        # 建切割线层（内部切换活动层）
        controller.create_layer("切割线", "line")
        # 切回 A：会话仍在（#1268 修复不破坏此流）
        controller.set_active_layer(layer_a.id)
        assert controller.active_layer.edit_session is session
