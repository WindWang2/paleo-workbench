"""Goal V7 workstation integration: ToolContext/evaluator/EditDelta/topology wiring.

Runs headless on the fallback canvas (bridge optional) — these tests pin the
*contract integration*, not the native execution itself (qgis-marked tests
cover the native leg).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from tests.test_composite_editing import _document, _project  # noqa: F401

from paleo_workbench.mapping.tool_availability import evaluate_all
from paleo_workbench.mapping.vector_layer import VectorFeature


def _polygon(fid: str, offset: float = 0.0) -> VectorFeature:
    return VectorFeature(
        fid,
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [0.0 + offset, 0.0],
                    [4.0 + offset, 0.0],
                    [4.0 + offset, 4.0],
                    [0.0 + offset, 4.0],
                    [0.0 + offset, 0.0],
                ]
            ],
        },
        {"name": fid},
    )


class TestEvaluatorIntegration:
    def test_document_builds_context_and_applies_reasons(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        actions = document.action_controller.actions

        # No layer: session tools visible-but-disabled with the layer reason
        # (V8 M1: A's old invisible behavior dropped); navigation on the
        # fallback canvas is available (project open).
        ctx = document._build_tool_context()
        assert ctx.project_open
        assert not ctx.active_layer_id
        availability = evaluate_all(ctx)
        assert availability["add_polygon"].visible
        assert not availability["add_polygon"].enabled
        assert availability["add_polygon"].disabled_reason == "没有活动的矢量图层"
        assert availability["pan"].enabled

        controller = document.edit_controller
        layer = controller.create_layer("相带", "polygon")
        controller.start_editing()
        document._sync_action_state()

        ctx = document._build_tool_context()
        assert ctx.editing and ctx.active_layer_kind == "polygon"
        assert ctx.edit_gate_open  # no gate rejections on a fresh composite layer
        availability = evaluate_all(ctx)
        assert availability["add_polygon"].enabled
        assert availability["add_point"].enabled is False
        assert "点图层" in availability["add_point"].disabled_reason
        # QAction wiring consumed the same evaluation: tooltip carries reason.
        assert not actions["add_point"].isEnabled()
        assert "点图层" in actions["add_point"].toolTip()

    def test_dirty_gate_on_save_action(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        actions = document.action_controller.actions
        controller = document.edit_controller
        controller.create_layer("相带", "polygon")
        controller.start_editing()
        document._sync_action_state()
        assert not actions["save_edits"].isEnabled()

        controller.activate_tool("add_polygon")
        tool = controller.tools.active_tool
        tool.mouse_press((0.0, 0.0))
        tool.mouse_press((2.0, 0.0))
        tool.mouse_press((2.0, 2.0))
        tool.double_click((0.0, 0.0))
        document._sync_action_state()
        assert actions["save_edits"].isEnabled()
        assert actions["rollback"].isEnabled()

    def test_raw_lock_disables_editing_with_reason(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        layer = controller.create_layer("原始相图", "polygon")

        def _deny(layer_id):
            return False, "图层角色为「RAW 不可变」——请创建 DERIVED 草稿后编辑"

        document.edit_controller.set_edit_gate(_deny)
        document._sync_action_state()
        actions = document.action_controller.actions
        assert not actions["toggle_editing"].isEnabled()
        assert "RAW" in actions["toggle_editing"].toolTip()
        ctx = document._build_tool_context()
        assert not ctx.edit_gate_open
        availability = evaluate_all(ctx)
        assert "RAW" in availability["toggle_editing"].disabled_reason
        document.edit_controller.set_edit_gate(document._role_allows_editing)

    def test_snapping_toggle_checked_state_follows_controller(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        controller.create_layer("断层", "line")
        document._sync_action_state()
        actions = document.action_controller.actions
        # No layer session needed: snapping toggles with a layer present (V7 matrix).
        assert actions["snapping"].isEnabled()
        assert not actions["snapping"].isChecked()
        controller.set_snapping(True)
        document._sync_action_state()
        assert actions["snapping"].isChecked()


class TestEditDeltaWorkstationFlow:
    def test_fallback_capture_records_python_fallback_source(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        controller.create_layer("相带", "polygon")
        controller.start_editing()
        controller.activate_tool("add_polygon")
        tool = controller.tools.active_tool
        tool.mouse_press((0.0, 0.0))
        tool.mouse_press((2.0, 0.0))
        tool.mouse_press((2.0, 2.0))
        tool.double_click((0.0, 0.0))
        session = controller.active_layer.edit_session
        deltas = session.deltas()
        assert len(deltas) == 1
        assert deltas[0].operation == "create_feature"
        assert deltas[0].source_tool == "add_polygon(python-fallback)"
        assert not deltas[0].from_native_tool
        # Engine provenance token is honest on the fallback stack.
        assert deltas[0].qgis_capability == "unavailable"

    def test_split_merge_commands_tagged(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        polygons = controller.create_layer("相带", "polygon")
        lines = controller.create_layer("切割线", "line")
        controller.set_active_layer(polygons.id)
        controller.start_editing()
        session = polygons.edit_session
        assert session is not None
        session.add_feature(_polygon("p1"))
        session.add_feature(_polygon("p2", offset=10.0))
        line_feature = VectorFeature(
            "cut1",
            {"type": "LineString", "coordinates": [[-1.0, 2.0], [5.0, 2.0]]},
            {},
        )
        line_session = lines.start_editing()
        line_session.add_feature(line_feature)
        polygons.set_selection(("p1",))
        lines.set_selection(("cut1",))
        document._sync_action_state()

        ok, message = controller.geometry_command("split")
        if ok:
            deltas = [d for d in session.deltas() if d.operation == "split_feature"]
            assert deltas and deltas[0].source_tool == "split(command)"
        else:
            # Bridge missing AND shapely fallback may refuse degenerate cuts —
            # the honest outcome is the message, never a silent no-op.
            assert message


class TestTopologyPropagationWiring:
    def test_vertex_commit_propagates_to_shared_neighbor(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        controller.set_topology(True)
        layer = controller.create_layer("相邻相带", "polygon")
        controller.start_editing()
        session = layer.edit_session
        upper = [
            [0.0, 0.0],
            [4.0, 0.0],
            [4.0, 4.0],
            [0.0, 4.0],
            [0.0, 0.0],
        ]
        below = [[0.0, -4.0], [4.0, -4.0], [4.0, 0.0], [0.0, 0.0], [0.0, -4.0]]
        session.add_feature(VectorFeature("a", {"type": "Polygon", "coordinates": [upper]}, {}))
        session.add_feature(
            VectorFeature("b", {"type": "Polygon", "coordinates": [below]}, {})
        )
        controller.activate_tool("vertex")
        tool = controller.tools.active_tool
        assert tool._on_vertex_committed is not None  # V7 wiring present

        # a 的 (0,0)（path (0,0)）与 b 的 (0,0)（path (0,3)）共享——
        # 原生顶点提交入口完成主编辑 + 传播（两个 move_vertex delta）。
        assert tool.commit_vertex_move("a", (0, 0), (-1.0, 0.0))
        geom_b = session.feature("b").as_record()["geometry"]
        assert [-1.0, 0.0] in geom_b["coordinates"][0]

        ops = [d.operation for d in session.deltas()]
        assert ops.count("move_vertex") >= 2
        sources = {d.source_tool for d in session.deltas()}
        assert "vertex(native)" in sources
        # P1-4：主编辑 + 同会话传播合成一个 undo 命令（一次 Ctrl+Z 整体回退，
        # 共享节点不因撤销而断裂）。2 个 add_feature + 1 个 compound = 3。
        undo_steps_before = len(session.undo_stack)
        assert undo_steps_before == 3
        assert session.undo()
        geom_a = session.feature("a").as_record()["geometry"]
        geom_b2 = session.feature("b").as_record()["geometry"]
        assert [0.0, 0.0] in geom_a["coordinates"][0]
        assert [-1.0, 0.0] not in geom_b2["coordinates"][0]

    def test_propagation_respects_edit_gate(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        controller.set_topology(True)
        layer = controller.create_layer("相邻相带", "polygon")
        controller.start_editing()
        session = layer.edit_session
        session.add_feature(_polygon("a"))
        controller.set_edit_gate(lambda layer_id: (False, "锁定"))

        controller._propagate_shared_vertex("a", (0, 1), (4.0, 0.0), (5.0, 0.0))
        geom = session.feature("a").as_record()["geometry"]
        # Locked layer keeps its geometry (no dirty writes from propagation).
        assert [4.0, 0.0] in geom["coordinates"][0]
        controller.set_edit_gate(document._role_allows_editing)


class TestCapabilityTokenInjection:
    def test_sessions_carry_engine_token(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        layer = controller.create_layer("相带", "polygon")
        controller.start_editing()
        session = layer.edit_session
        assert session.qgis_capability_token  # non-empty provenance
        # Fallback stack (bridge missing) records honestly.
        assert session.qgis_capability_token == controller.qgis_capability_token


class TestProjectSwitchFlush:
    """Review-3 P1-4：工程切换先 flush，阻断时拒绝带病切换。"""

    def test_dirty_session_committed_on_project_switch(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        layer = controller.create_layer("相带", "polygon")
        controller.start_editing()
        controller.activate_tool("add_polygon")
        tool = controller.tools.active_tool
        tool.mouse_press((0.0, 0.0))
        tool.mouse_press((2.0, 0.0))
        tool.mouse_press((2.0, 2.0))
        tool.double_click((0.0, 0.0))
        assert layer.edit_session is not None  # 脏会话

        assert controller.load_from_project(document._project) is not False
        # 脏会话已提交（不丢数据），新工程图层已装载。
        assert layer.edit_session is None

    def test_blocked_session_refuses_project_switch(self, qtbot, tmp_path):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        layer = controller.create_layer("原始相图", "polygon")
        controller.start_editing()
        session = layer.edit_session
        from paleo_workbench.mapping.vector_layer import VectorFeature

        session.add_feature(
            VectorFeature(
                "r1",
                {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                {},
            )
        )
        # 门禁拒绝提交（模拟 RAW 会话）：flush 留下打开会话。
        controller.set_edit_gate(lambda layer_id: (False, "RAW 不可变"))
        assert controller.load_from_project(document._project) is False
        assert layer.edit_session is not None  # 会话保持打开，可回滚
        controller.set_edit_gate(document._role_allows_editing)
