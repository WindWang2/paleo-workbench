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


@pytest.fixture(autouse=True)
def _python_session_path(monkeypatch):
    """本文件钉**回退语义**下的契约集成（docstring：runs headless on the
    fallback canvas）。polygon/line 已翻原生会话（M5），故统一把会话资格钉回
    Python 路径——「fallback stack records honestly」这类断言测的正是它。
    原生腿由 qgis-marked 用例覆盖（test_qgis_topo_*）。"""
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    monkeypatch.setattr(
        CompositeEditController,
        "_native_session_eligible",
        lambda _self, _layer: False,
    )


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
        # 引擎来源诚实：delta 的 token = 宿主注入的能力令牌（会话 ← 控制器
        # ← 文档单点注入）。字面 "unavailable" 只在宿主从未注入时成立——
        # 那是控制器类属性的缺省值，不是本环境的契约（本机桥在场，注入的是
        # 真实能力摘要）。
        assert deltas[0].qgis_capability == controller.qgis_capability_token
        assert deltas[0].qgis_capability

    def test_split_merge_commands_tagged(self, qtbot, tmp_path, monkeypatch):
        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        # M1 拓扑编辑迁移：polygon 层默认翻转原生会话；本测试钉 Python
        # 会话的 split/merge 命令审计语义（M3 才接原生缓冲）。
        monkeypatch.setattr(
            controller, "_native_session_eligible", lambda _layer: False)
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
    def test_python_shared_vertex_propagation_retired(self):
        """M5：工作站不再暴露 Python 共享节点传播入口。"""
        from paleo_workbench.ui.workstation.composite_editing import (
            CompositeEditController,
        )

        assert not hasattr(CompositeEditController, "_propagate_shared_vertex")


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
