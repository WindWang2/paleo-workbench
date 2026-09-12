"""V11 reconcile 结构断言：调用计数（单层移动 O(1)、无全组 upsert 风暴）。"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping_workspace.layer_group_controller import (
    LayerGroupController,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import (
    LayerMembershipRecord,
    MappingWorkspaceState,
)


class RecordingStack:
    """duck-type 桥：记录每次调用（name, args）。

    白名单方法集（模拟 0.6.x 旧桥——无树事务窗口，验证降级路径与
    调用计数；窗口行为由 native 测试覆盖）。
    """

    _METHODS = (
        "upsert_group", "remove_groups_except", "rename_group",
        "move_group", "move_layer_to_group", "set_group_visibility",
        "tree_snapshot_json", "apply_tree_placements",
    )

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def __getattr__(self, name):
        if name.startswith("_") or name not in RecordingStack._METHODS:
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args))
            if name == "apply_tree_placements":
                return json.dumps({"applied": len(args[0]), "skipped": 0})
            return None
        return _record

    def calls_of(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]


class _LayerLike:
    def __init__(self, layer_id: str):
        self.id = layer_id


@pytest.fixture()
def state() -> MappingWorkspaceState:
    return MappingWorkspaceState()


@pytest.fixture()
def controller(state):
    ctl = LayerGroupController(state)
    stack = RecordingStack()
    ctl.attach_canvas(_CanvasLike(stack))
    return ctl


class _CanvasLike:
    def __init__(self, stack):
        self.stack = stack
        self.canvas_address = 0
        self.layer_groups_enabled = False


def _register(state, layer_id: str, role=LayerRole.INITIAL_FACIES_DRAFT):
    state.set_membership(LayerMembershipRecord(
        layer_id=layer_id, role=role, created_stage="phase1"))


class TestReconcileCallCounts:
    def test_single_layer_insertion_is_one_move(self, controller, state):
        layers = [_LayerLike(f"draft{i}") for i in range(1000)]
        for layer in layers:
            _register(state, layer.id)
        controller.reconcile(layers)
        first_wave = len(controller._stack.calls)
        assert first_wave > 0  # 首次全量

        layers.append(_LayerLike("draft_new"))
        _register(state, "draft_new")
        controller._stack.calls.clear()
        controller.reconcile(layers)

        placements = controller._stack.calls_of("apply_tree_placements")
        assert len(placements) == 1
        payload = json.loads(placements[0][1][0])
        assert len(payload) == 1  # 恰一个 move：新图层
        assert payload[0]["node"] == "draft_new"
        # 无组结构变化 → 无 upsert_group
        assert controller._stack.calls_of("upsert_group") == []

    def test_noop_reconcile_emits_no_moves(self, controller, state):
        layers = [_LayerLike(f"d{i}") for i in range(200)]
        for layer in layers:
            _register(state, layer.id)
        controller.reconcile(layers)
        controller._stack.calls.clear()
        controller.reconcile(layers)
        assert controller._stack.calls_of("apply_tree_placements") == []
        assert controller._stack.calls_of("move_layer_to_group") == []
        # 幂等 keep-set 清理仍在（一次桥调用，自愈语义）
        assert len(controller._stack.calls_of("remove_groups_except")) == 1

    def test_rename_only_calls_rename(self, controller, state):
        layers = [_LayerLike("a"), _LayerLike("b")]
        for layer in layers:
            _register(state, layer.id)
        controller.reconcile(layers)
        controller.create_user_group("My Group")
        controller._stack.calls.clear()
        controller.reconcile(layers)
        upserts = controller._stack.calls_of("upsert_group")
        assert len(upserts) == 1  # 仅新组
        assert upserts[0][1][0].startswith("user.")
        placements = controller._stack.calls_of("apply_tree_placements")
        payload = json.loads(placements[0][1][0])
        assert all(p["node"].startswith("group:user.")
                   for p in payload)  # 只有组自身 move

    def test_user_reorder_survives_next_reconcile(self, controller, state):
        """D3-ws 回归：系统组内用户重排不被下一次 reconcile 打回。"""
        layers = [_LayerLike("a"), _LayerLike("b"), _LayerLike("c")]
        for layer in layers:
            _register(state, layer.id)
        controller.reconcile(layers)
        # 用户把 c 拖到最前（观察回写）
        accepted = controller.observe_tree_nodes([
            {"type": "group", "id": "phase1.interpretation",
             "name": "沉积相解释", "children": [
                 {"type": "layer", "id": "c"},
                 {"type": "layer", "id": "a"},
                 {"type": "layer", "id": "b"},
             ]},
        ])
        assert accepted
        controller._stack.calls.clear()
        controller.reconcile(layers)
        # 期望树保持用户序：c 在前
        desired = controller.build_desired_tree(layers)
        group = desired.find_group("phase1.interpretation")
        assert [child.layer_id for child in group.children] == ["c", "a", "b"]

    def test_stage_switch_no_tree_calls(self, controller, state):
        from paleo_workbench.mapping_workspace.controller import MappingStageController
        layers = [_LayerLike("a")]
        _register(state, "a")
        stage_controller = MappingStageController(state)
        stage_controller.group_controller = controller
        controller.reconcile(layers)
        controller._stack.calls.clear()
        # 阶段切换只走显隐增量（结构零调用）
        stage_controller.group_controller.apply_stage_visibility(
            __import__("paleo_workbench.mapping_workspace.stages",
                       fromlist=["MappingStage"]).MappingStage.FACIES_CALIBRATION)
        structure_calls = [c for c in controller._stack.calls
                           if c[0] in ("upsert_group", "apply_tree_placements",
                                       "move_layer_to_group", "move_group",
                                       "rename_group")]
        assert structure_calls == []


class TestEchoRevisionGate:
    def test_echo_is_stale_semantics(self, controller, state):
        # 未应用过（applied=0）→ 任何回声不过期（旧桥兼容，revision 恒 0）
        assert controller.echo_is_stale(0) is False
        assert controller.echo_is_stale(5) is False
        controller.note_applied_tree_revision(10)
        assert controller._applied_tree_revision == 10
        # 过期：revision ≤ 已应用值（自身程序化变更的迟到回显）
        assert controller.echo_is_stale(9) is True
        assert controller.echo_is_stale(10) is True
        # 新鲜：窗口之后的用户编辑
        assert controller.echo_is_stale(11) is False

    def test_revision_only_moves_forward(self, controller, state):
        controller.note_applied_tree_revision(10)
        controller.note_applied_tree_revision(4)  # 乱序/旧值不回退
        assert controller._applied_tree_revision == 10

    def test_reconcile_records_window_revision(self, controller, state):
        layers = [_LayerLike("a")]
        _register(state, "a")
        controller.reconcile(layers)
        # RecordingStack 无 begin/end（旧桥）→ revision 保持 0（不过期语义）
        assert controller._applied_tree_revision == 0
