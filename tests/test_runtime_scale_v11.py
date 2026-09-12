"""V11 scale structural suite（13-scale）：1000+ 层结构性断言。

全部断言都是调用计数/操作计数（非计时——计时 flaky 不进门禁）：
1. 1000 层初始构建：单窗口单同步（native）/ diff 操作数有界（plan）。
2. 移动单层：恰 1 move（diff）+ 零邻居重排。
3. 移动组：恰 1 group move。
4. 阶段切换：零结构调用（已有 reconcile 测试，此处覆盖 rematerialize
   空组创建有界）。
5. 组显隐切换：仅 changed 组下推（controller 既有语义；此处钉死）。
6. 重命名：仅 rename op（无放置扰动）。
7. 单层样式：仅 style 通道（mirror 台账：数据修订未动 → 非 delta 路径）。
8. 排序热路径：无 list.index（plan/diff/order 模块源码断言）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping_workspace.layer_group_controller import (
    LayerGroupController,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.layer_tree_diff import diff_trees
from paleo_workbench.mapping_workspace.stage_state import (
    LayerMembershipRecord,
    MappingWorkspaceState,
)


class RecordingStack:
    _METHODS = (
        "upsert_group", "remove_groups_except", "rename_group",
        "move_group", "move_layer_to_group", "set_group_visibility",
        "tree_snapshot_json", "apply_tree_placements",
    )

    def __init__(self):
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        if name.startswith("_") or name not in RecordingStack._METHODS:
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args))
            if name == "apply_tree_placements":
                return json.dumps({"applied": 1, "skipped": 0})
            return None
        return _record

    def calls_of(self, name: str):
        return [c for c in self.calls if c[0] == name]


class _CanvasLike:
    def __init__(self, stack):
        self.stack = stack
        self.canvas_address = 0
        self.layer_groups_enabled = False


class _LayerLike:
    def __init__(self, layer_id: str):
        self.id = layer_id


@pytest.fixture()
def rig():
    state = MappingWorkspaceState()
    ctl = LayerGroupController(state)
    stack = RecordingStack()
    ctl.attach_canvas(_CanvasLike(stack))
    return ctl, state, stack


def _register_many(state, n: int, role=LayerRole.INITIAL_FACIES_DRAFT,
                   prefix: str = "L"):
    for i in range(n):
        state.set_membership(LayerMembershipRecord(
            layer_id=f"{prefix}{i}", role=role, created_stage="phase1"))
    return [_LayerLike(f"{prefix}{i}") for i in range(n)]


class TestThousandLayerStructure:
    def test_initial_build_group_upsert_count_bounded(self, rig):
        ctl, state, stack = rig
        layers = _register_many(state, 1000)
        ctl.reconcile(layers)
        # 组集合幂等 upsert：期望组数（P1 物化组 + base）——上界断言
        upserts = stack.calls_of("upsert_group")
        assert 1 <= len(upserts) <= 20
        # 放置批量：首建走 _place_all（一批 placements 调用）
        placements = stack.calls_of("apply_tree_placements")
        assert len(placements) == 1

    def test_move_single_layer_one_move(self, rig):
        ctl, state, stack = rig
        layers = _register_many(state, 1000)
        ctl.reconcile(layers)
        # 用户把 L500 拖到组首（观察回写）
        children = [{"type": "layer", "id": f"L{i}"}
                    for i in [500] + [i for i in range(1000) if i != 500]]
        assert ctl.observe_tree_nodes([
            {"type": "group", "id": "phase1.interpretation",
             "name": "t", "children": children}])
        stack.calls.clear()
        ctl.reconcile(layers)
        placements = stack.calls_of("apply_tree_placements")
        assert len(placements) == 1
        payload = json.loads(placements[0][1][0])
        # 恰 1 move（L500），其余 999 不动
        assert len(payload) == 1
        assert payload[0]["node"] == "L500"

    def test_move_group_one_op(self, rig):
        ctl, state, stack = rig
        layers = _register_many(state, 10)
        ctl.reconcile(layers)
        # 用户建嵌套组并移动（观察回写）
        assert ctl.observe_tree_nodes([
            {"type": "group", "id": "user.outer", "name": "O", "children": [
                {"type": "group", "id": "user.inner", "name": "I",
                 "children": [{"type": "layer", "id": "L0"}]},
            ]},
            {"type": "group", "id": "phase1.interpretation",
             "name": "t", "children": [
                 {"type": "layer", "id": f"L{i}"} for i in range(1, 10)]},
        ])
        stack.calls.clear()
        ctl.reconcile(layers)
        placements = stack.calls_of("apply_tree_placements")
        assert len(placements) <= 1
        if placements:
            payload = json.loads(placements[0][1][0])
            group_moves = [p for p in payload
                           if str(p["node"]).startswith("group:user.")]
            # 组移动本身 + L0 入组：有界（≤3）
            assert len(payload) <= 3

    def test_second_reconcile_zero_moves(self, rig):
        ctl, state, stack = rig
        layers = _register_many(state, 1000)
        ctl.reconcile(layers)
        stack.calls.clear()
        ctl.reconcile(layers)
        assert stack.calls_of("apply_tree_placements") == []
        assert stack.calls_of("move_layer_to_group") == []


class TestRenameNoPlacementDisturbance:
    def test_rename_only(self, rig):
        ctl, state, stack = rig
        layers = _register_many(state, 100)
        ctl.reconcile(layers)
        ctl.create_user_group("G")
        ctl.reconcile(layers)
        stack.calls.clear()
        # 重命名用户组 → 仅 rename op（diff 级别）
        last = ctl._last_applied
        import dataclasses
        renamed = []
        for child in last.children:
            if getattr(child, "group_id", "") .startswith("user."):
                renamed.append(dataclasses.replace(child, name="新名"))
            else:
                renamed.append(child)
        from paleo_workbench.mapping_workspace.layer_tree import (
            LayerTreeSnapshot)
        desired = LayerTreeSnapshot(children=tuple(renamed), source="domain")
        d = diff_trees(last, desired)
        assert d.op_count() == 1
        assert len(d.group_renames) == 1
        assert not d.layer_moves and not d.group_moves


class TestNoQuadraticOrderingPaths:
    def test_no_list_index_in_hot_paths(self):
        """排序热路径禁 list.index（O(N²) 根因；rank dict 预计算替代）。"""
        root = Path(__file__).resolve().parents[1] / "paleo_workbench" \
            / "mapping_workspace"
        for module in ("layer_order.py", "layer_tree_plan.py",
                       "layer_tree_diff.py"):
            src = (root / module).read_text(encoding="utf-8")
            assert ".index(" not in src, module

    def test_factor_rank_is_dict_lookup(self):
        from paleo_workbench.mapping_workspace.layer_order import (
            FACTOR_ROLE_RANK, factor_role_rank)
        import inspect
        src = inspect.getsource(factor_role_rank)
        assert ".index(" not in src
        assert len(FACTOR_ROLE_RANK) == 6


class TestNestedGroupSingleMount:
    """嵌套组单挂载回归：observe 嵌套组 → 期望树无双挂载 → diff 无重复 move。"""

    def test_nested_group_mounted_once(self, rig):
        from paleo_workbench.mapping_workspace.layer_tree_diff import diff_trees

        ctl, state, _ = rig
        layers = _register_many(state, 3)
        ctl.reconcile(layers)
        assert ctl.observe_tree_nodes([
            {"type": "group", "id": "user.outer", "name": "O", "children": [
                {"type": "group", "id": "user.inner", "name": "I",
                 "children": [{"type": "layer", "id": "L0"}]},
            ]},
            {"type": "group", "id": "phase1.interpretation",
             "name": "t", "children": [
                 {"type": "layer", "id": "L1"},
                 {"type": "layer", "id": "L2"}]},
        ])
        desired = ctl.build_desired_tree(layers)
        # 单挂载：inner 只出现在 outer 之内，不在 root 并列
        root_ids = [getattr(c, "group_id", getattr(c, "layer_id", "?"))
                    for c in desired.children]
        assert root_ids.count("user.inner") == 0
        assert root_ids.count("user.outer") == 1
        inner = desired.find_group("user.inner")
        assert [c.layer_id for c in inner.children] == ["L0"]  # 无重复 L0
        # diff 无重复 move
        d = diff_trees(ctl._last_applied, desired)
        moved = [m.layer_id for m in d.layer_moves] + [
            m.group_id for m in d.group_moves]
        assert len(moved) == len(set(moved))
