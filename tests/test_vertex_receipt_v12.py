# -*- coding: utf-8 -*-
"""V12 M0-3：节点编辑的失败回执（纯 Python，不依赖桥）。

钉死 D-B2/D-B3 的收口面：原生会话打开时 Python 侧工具持有 ``session=None``
（编辑发生在 QGIS 缓冲），此时 v1 回调落下来必然失败——失败**必须**变成
可感知的状态，而不是无声死键。修复前 ``vertex_moved`` 既不发
``commit_rejected`` 也不发 ``tool_operation``，用户拖动顶点看到的就是
"什么都没发生"。
"""
from __future__ import annotations

import pytest


class _Recorder:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args[0] if len(args) == 1 else args)


class _ShimStub:
    def __init__(self):
        self.commit_rejected = _Recorder()
        self.tool_operation = _Recorder()
        self.snap_feedback = _Recorder()


def _vertex_tool_without_session():
    """原生会话下的真实形态：工具拿到的是 None 会话。"""
    from paleo_workbench.mapping.map_tools import VertexTool

    return VertexTool(None, identify_vertex=lambda _point: None)


@pytest.mark.parametrize(
    "action,payload",
    [
        ("vertex_moved", {"feature_id": "f1", "path": [0, 1], "x": 1.0, "y": 2.0}),
        ("vertex_inserted", {"feature_id": "f1", "path": [0, 1], "x": 1.0, "y": 2.0}),
        ("vertex_deleted", {"feature_id": "f1", "path": [0, 1]}),
    ],
)
def test_session_less_vertex_pick_surfaces_rejection(action, payload):
    """三族节点回执在"无 Python 会话"时都必须上浮成拒绝。"""
    from paleo_workbench.ui.qgis_stack.canvas_shim import dispatch_edit_pick

    shim = _ShimStub()
    accepted = dispatch_edit_pick(shim, _vertex_tool_without_session(),
                                  action, payload)
    assert accepted is False
    assert len(shim.commit_rejected.values) == 1, (
        f"{action} 失败无回执 → 用户看到的只有「没反应」")
    assert shim.tool_operation.values == [False]
    assert "节点编辑未写入" in shim.commit_rejected.values[0]


def test_accepted_vertex_move_stays_silent_positive():
    """成功路径不被拒绝逻辑污染（只发 tool_operation(True)）。"""
    from paleo_workbench.ui.qgis_stack.canvas_shim import dispatch_edit_pick

    class _Accepting:
        def commit_vertex_move(self, feature_id, path, point):
            return True

    shim = _ShimStub()
    assert dispatch_edit_pick(
        shim, _Accepting(), "vertex_moved",
        {"feature_id": "f1", "path": [0, 1], "x": 1.0, "y": 2.0}) is True
    assert shim.tool_operation.values == [True]
    assert not shim.commit_rejected.values


def test_vertex_without_target_warns_once_per_state():
    """节点工具"无编辑目标"提示按状态去重，目标就位后复位（M0-2c）。

    没这条：用户在空目标状态下每点一次地图都刷一条同样的提示；
    有这条但没复位：用户修好之后再次踩坑就再也看不到提示。
    """
    from paleo_workbench.ui.qgis_stack.canvas_shim import (
        _warn_vertex_without_target,
    )

    shim = _ShimStub()
    _warn_vertex_without_target(shim)
    _warn_vertex_without_target(shim)
    assert len(shim.commit_rejected.values) == 1, "同一状态重复告警"
    assert "没有编辑目标" in shim.commit_rejected.values[0]

    # 目标层就位（shim.set_current_layer 成功路径会复位该旗标）→ 可再次告警。
    shim._vertex_no_target_warned = False
    _warn_vertex_without_target(shim)
    assert len(shim.commit_rejected.values) == 2
