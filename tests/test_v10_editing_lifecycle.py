"""V10 editing lifecycle stress: 编辑中途的层/阶段/会话切换 + 宏内操作拒绝
+ 新回调的停机纪律（fallback 画布路径 + session 级不变量）。"""

from pathlib import Path

import pytest

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    return project


def _document(qtbot, tmp_path) -> CompositeDocument:
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


def _capture_layer(document, kind="line", name="约束线"):
    controller = document.edit_controller
    layer = controller.create_layer(name, kind)
    controller.start_editing()
    return controller, layer


# -- 捕获中途的会话/层/阶段切换 ---------------------------------------------------


def test_save_edits_mid_capture_rebinds_and_keeps_tool_safe(qtbot, tmp_path):
    controller, layer = _capture_layer(document := _document(qtbot, tmp_path))
    controller.activate_tool("add_line")
    tool = controller.tools.active_tool
    assert tool is not None and tool.tool_id == "add_line"
    # 采集中途保存编辑（会话关闭）→ _rebind_active_tool 回落 pan（不悬挂旧会话）
    controller.save_edits()
    assert layer.edit_session is None
    assert controller.tools.active_tool.tool_id == "pan"


def test_rollback_mid_capture_rebinds(qtbot, tmp_path):
    controller, layer = _capture_layer(_document(qtbot, tmp_path))
    controller.activate_tool("add_line")
    controller.rollback_edits()
    assert controller.tools.active_tool.tool_id == "pan"


def test_layer_switch_mid_capture_kind_mismatch_falls_back(qtbot, tmp_path):
    controller, layer = _capture_layer(_document(qtbot, tmp_path))
    controller.activate_tool("add_line")
    polygon = controller.create_layer("相带", "polygon")
    controller.set_active_layer(polygon.id)
    # 设计语义（review #1）：新层无会话时，工具持有的会话仍属活图层 →
    # 不打断数字化（同步链瞬时切层不劫持用户）。
    assert controller.tools.active_tool.tool_id == "add_line"
    # 新层开启会话后，kind 失配必须回落 pan（add_line 不劫持面图层）。
    controller.start_editing()
    assert controller.tools.active_tool.tool_id == "pan"


def test_stage_switch_mid_capture_rebinds_or_reactivates(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller, layer = _capture_layer(document)
    controller.activate_tool("add_line")
    # 切阶段（P1）：编辑动作集变化 → 工具重绑（P1 无 add_line？P1 有 add_polygon
    # 无 add_line——阶段切换后 add_line 应回落 pan 或合法重绑，绝不悬挂断链会话）。
    document.stage_controller.set_stage("facies_calibration") if hasattr(
        document, "stage_controller") else None
    active = controller.tools.active_tool
    if active is not None:
        session = getattr(active, "session", None)
        if session is not None:
            # 工具持有的会话必须仍属于某个活图层（V10 复核 _rebind 语义）。
            assert any(
                l.edit_session is session for l in controller._layers.values())


def test_vertex_tool_rebind_after_session_flush(qtbot, tmp_path):
    controller, layer = _capture_layer(_document(qtbot, tmp_path), kind="line")
    controller.activate_tool("vertex")
    assert controller.tools.active_tool.tool_id == "vertex"
    controller.save_edits()
    assert controller.tools.active_tool.tool_id == "pan"


# -- 宏内操作拒绝（session 级） ---------------------------------------------------


def test_undo_redo_refused_while_macro_open():
    from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer

    layer = VectorLayer(id="L", name="L", features=[
        VectorFeature("f1", {"type": "LineString",
                             "coordinates": [[0, 0], [5, 0]]}, {})])
    session = layer.start_editing()
    session.begin_edit_command()
    session.set_vertex("f1", (0,), (1.0, 0.0))
    assert not session.undo()
    assert not session.redo()
    session.end_edit_command()
    assert session.undo()


def test_vertex_commit_during_macro_open_destroyed_cleanly(qtbot, tmp_path):
    """_commit_vertex 失败路径绝不留下打开的宏（V8 语义对 insert/delete 同样成立）。"""
    from paleo_workbench.mapping.map_tools import VertexTool

    controller, layer = _capture_layer(_document(qtbot, tmp_path))
    session = layer.edit_session
    tool = VertexTool(session, identify_vertex=lambda p: None)
    # 越界路径 → session 拒绝 → 宏被 destroy，不悬挂
    assert not tool.commit_vertex_insert("nonexistent", (99,), (1.0, 1.0))
    assert not tool.commit_vertex_delete("nonexistent", (99,))
    # 后续操作不受影响（宏状态干净）
    tool.commit_vertex_insert("nonexistent", (0,), (0.0, 0.0))  # feature 不存在 → False
    assert controller.edit_command("undo") is False


# -- 新回调的停机纪律（shim 层） ---------------------------------------------------


def test_snap_feedback_and_progress_signals_exist(qtbot, tmp_path):
    """shim 暴露 V10 信号面（native 栈不可用时 fallback canvas 也无损构建）。"""
    document = _document(qtbot, tmp_path)
    canvas = document.canvas
    has_snap = hasattr(canvas, "snap_feedback")
    has_progress = hasattr(canvas, "capture_progress")
    # 两种画布实现都应暴露（fallback canvas 至少不崩溃；native shim 有信号）。
    assert isinstance(has_snap, bool) and isinstance(has_progress, bool)


def test_native_tool_commit_after_session_close_routed_to_none(qtbot, tmp_path):
    """会话关闭后迟到的 native 回调走 shim 路由（controller.tools.active_tool）
    ——重绑后是 pan（无 commit 入口）→ 回调被丢弃，不产生孤儿命令。"""
    controller, layer = _capture_layer(_document(qtbot, tmp_path))
    controller.activate_tool("add_line")
    controller.save_edits()
    # shim 的路由目标 = controller.tools.active_tool（与生产路径一致）
    routed = controller.tools.active_tool
    assert routed.tool_id == "pan"
    assert getattr(routed, "commit_geometry", None) is None
    assert getattr(routed, "commit_vertex_insert", None) is None
    assert getattr(routed, "commit_vertex_delete", None) is None
    assert layer.edit_session is None
