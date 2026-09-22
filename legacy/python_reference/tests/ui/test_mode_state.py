"""M5 FSM：编图工作台模式状态机全转移矩阵 + 回环审计（02-state-machine）。

FSM 是投影层（00-decisions D12）：无 setter 链，事件→状态→mode_changed
只读广播；参数化覆盖 5 状态 × 8 事件 = 40 组合。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.ui.workstation.mode_state import (  # noqa: E402
    ModeEvent,
    ModeStateMachine,
    WorkstationMode,
)

STATES = tuple(WorkstationMode)
EVENTS = tuple(ModeEvent)


def test_initial_state_is_idle():
    machine = ModeStateMachine()
    assert machine.mode is WorkstationMode.IDLE


def test_full_transition_table_matrix():
    """全 (状态 × 事件) 组合符合 02-state-machine-design.md 转移表。"""
    machine = ModeStateMachine()
    expected: dict[tuple[WorkstationMode, ModeEvent], WorkstationMode | None] = {}

    def fill(state, event, target):
        expected[(state, event)] = target

    for state in STATES:
        fill(state, ModeEvent.QC_HUB_ACTIVATED, WorkstationMode.INSPECTING_QC)
        fill(state, ModeEvent.SCRUB_START, WorkstationMode.TIME_TRAVELLING)
        fill(state, ModeEvent.TOOL_DEACTIVATED, WorkstationMode.IDLE)
    for state in (WorkstationMode.IDLE, WorkstationMode.DIGITIZING,
                  WorkstationMode.ADJUSTING_BOUNDARY,
                  WorkstationMode.INSPECTING_QC):
        fill(state, ModeEvent.TOOL_ACTIVATED, WorkstationMode.DIGITIZING)
        fill(state, ModeEvent.VERTEX_ACT, WorkstationMode.ADJUSTING_BOUNDARY)
    fill(WorkstationMode.TIME_TRAVELLING, ModeEvent.TOOL_ACTIVATED, None)  # 拒绝
    fill(WorkstationMode.TIME_TRAVELLING, ModeEvent.VERTEX_ACT, None)  # 拒绝
    for state in (WorkstationMode.IDLE, WorkstationMode.DIGITIZING,
                  WorkstationMode.ADJUSTING_BOUNDARY,
                  WorkstationMode.INSPECTING_QC):
        fill(state, ModeEvent.ESC, WorkstationMode.IDLE)
    fill(WorkstationMode.TIME_TRAVELLING, ModeEvent.ESC, WorkstationMode.IDLE)
    fill(WorkstationMode.IDLE, ModeEvent.QC_HUB_CLOSED,
         WorkstationMode.IDLE)
    fill(WorkstationMode.INSPECTING_QC, ModeEvent.QC_HUB_CLOSED,
         WorkstationMode.IDLE)
    # EPOCH_COMMIT：从 TIME_TRAVELLING 回进入前模式；其余保持
    for state in STATES:
        fill(state, ModeEvent.EPOCH_COMMIT, state)
    fill(WorkstationMode.TIME_TRAVELLING, ModeEvent.EPOCH_COMMIT, "BACK")
    # ONION_TOGGLED 自环（不换状态）
    for state in STATES:
        fill(state, ModeEvent.ONION_TOGGLED, state)
    # 顶点类工具的 TOOL_ACTIVATED 直接进 ADJUSTING_BOUNDARY
    for state in (WorkstationMode.IDLE, WorkstationMode.DIGITIZING,
                  WorkstationMode.INSPECTING_QC):
        expected[(state, ModeEvent.TOOL_ACTIVATED)] = "TOOL_KIND"

    for state in STATES:
        for event in EVENTS:
            machine._mode = state  # 直接布置初态（测试注入）
            machine._mode_before_travel = WorkstationMode.DIGITIZING
            before = machine.mode
            machine.dispatch(event, tool_id="add_polygon")
            after = machine.mode
            want = expected.get((state, event))
            if want == "BACK":
                assert after is WorkstationMode.DIGITIZING, (state, event)
            elif want == "TOOL_KIND":
                assert after in (WorkstationMode.DIGITIZING,
                                 WorkstationMode.ADJUSTING_BOUNDARY), (state, event)
            elif want is None:
                assert after is state, (state, event)  # 拒绝 = 保持
            else:
                assert after is want, (state, event, after)
            _ = before


def test_time_travel_returns_to_mode_before():
    machine = ModeStateMachine()
    machine.dispatch(ModeEvent.TOOL_ACTIVATED, tool_id="add_polygon")
    assert machine.mode is WorkstationMode.DIGITIZING
    machine.dispatch(ModeEvent.SCRUB_START)
    assert machine.mode is WorkstationMode.TIME_TRAVELLING
    machine.dispatch(ModeEvent.EPOCH_COMMIT)
    assert machine.mode is WorkstationMode.DIGITIZING  # 回到进入前模式


def test_vertex_tool_enters_adjusting():
    machine = ModeStateMachine()
    machine.dispatch(ModeEvent.TOOL_ACTIVATED, tool_id="vertex")
    assert machine.mode is WorkstationMode.ADJUSTING_BOUNDARY
    machine2 = ModeStateMachine()
    machine2.dispatch(ModeEvent.TOOL_ACTIVATED, tool_id="reshape")
    assert machine2.mode is WorkstationMode.ADJUSTING_BOUNDARY


def test_transient_pan_flag_does_not_change_mode():
    machine = ModeStateMachine()
    machine.dispatch(ModeEvent.TOOL_ACTIVATED, tool_id="add_polygon")
    machine.dispatch(ModeEvent.PAN_HELD)
    assert machine.mode is WorkstationMode.DIGITIZING
    assert machine.pan_held is True
    machine.dispatch(ModeEvent.PAN_RELEASED)
    assert machine.mode is WorkstationMode.DIGITIZING
    assert machine.pan_held is False


def test_echo_audit_mode_changed_only_on_real_change():
    """回环审计：全组合注入，mode_changed 发射次数 == 实际状态变化数。"""
    machine = ModeStateMachine()
    changes: list[WorkstationMode] = []
    machine.mode_changed.connect(changes.append)
    real_changes = 0
    previous = machine.mode
    for state in STATES:
        for event in EVENTS:
            machine._mode = state
            if machine.mode != previous:
                real_changes += 0  # 测试注入不算（不经 dispatch）
            previous = machine.mode
            machine.dispatch(event, tool_id="add_polygon")
            if machine.mode != previous:
                real_changes += 1
            previous = machine.mode
    assert len(changes) == real_changes


def test_unknown_tool_kind_defaults_to_digitizing():
    machine = ModeStateMachine()
    machine.dispatch(ModeEvent.TOOL_ACTIVATED, tool_id="measure_distance")
    assert machine.mode is WorkstationMode.DIGITIZING
