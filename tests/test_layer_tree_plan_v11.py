"""V11 LayerTreePlan contracts（期望树构建：顺序持久化、路由统一、嵌套用户组）。"""
from __future__ import annotations

from paleo_workbench.mapping_workspace.layer_groups import SYSTEM_GROUP_TEMPLATES
from paleo_workbench.mapping_workspace.layer_tree import LayerTreeSnapshot
from paleo_workbench.mapping_workspace.layer_tree_plan import (
    LayerTreePlanInput,
    PlanLayerRecord,
    PlanUserGroup,
    build_plan,
    effective_home_group,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage


def _records(*specs) -> tuple[PlanLayerRecord, ...]:
    """specs: (layer_id, role, created_stage, factor_task_id?)"""
    out = []
    for i, spec in enumerate(specs):
        layer_id, role = spec[0], spec[1]
        created = spec[2] if len(spec) > 2 else "phase2"
        task = spec[3] if len(spec) > 3 else ""
        out.append(PlanLayerRecord(
            layer_id=layer_id, role=role,
            created_stage=created, factor_task_id=task, sub_order=i))
    return tuple(out)


class TestPlanBasics:
    def test_deterministic_same_input_same_output(self):
        records = _records(
            ("facies_draft", LayerRole.INITIAL_FACIES_DRAFT, "phase1"),
            ("well_pred", LayerRole.WELL_FACIES_PREDICTION, "phase1"),
            ("boundary", LayerRole.FACIES_BOUNDARY, "phase2"),
            ("ref1", LayerRole.BASE_REFERENCE, "phase1"),
        )
        inp = LayerTreePlanInput(records=records, stage=MappingStage.CONSTRAINT_FACTOR)
        snap1, facts1 = build_plan(inp)
        snap2, facts2 = build_plan(inp)
        assert snap1 == snap2
        assert facts1 == facts2
        assert snap1.to_dict() == snap2.to_dict()

    def test_roles_route_to_home_groups(self):
        records = _records(
            ("draft", LayerRole.INITIAL_FACIES_DRAFT, "phase1"),
            ("well", LayerRole.WELL_FACIES_PREDICTION, "phase1"),
            ("integrated", LayerRole.INTEGRATED_FACIES, "phase3"),
        )
        snap, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.FACIES_CALIBRATION))
        draft_parent = snap.find_layer_parent("draft")
        well_parent = snap.find_layer_parent("well")
        integrated_parent = snap.find_layer_parent("integrated")
        assert draft_parent is not None and draft_parent.group_id == "phase1.interpretation"
        assert well_parent is not None and well_parent.group_id == "phase1.well_predictions"
        assert integrated_parent is not None and integrated_parent.group_id == "phase3.integrated"

    def test_keys_roundtrip_through_dict(self):
        records = _records(("a", LayerRole.QC_WARNING, "phase3"),
                           ("b", LayerRole.MAP_ANNOTATION, "phase3"))
        snap, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.INTEGRATED_COMPILATION))
        data = snap.to_dict()
        restored = LayerTreeSnapshot.from_dict(data)
        assert restored == snap
        # 键持久化在 dict 中
        group = restored.find_group("phase3.qc")
        assert group is not None
        layer_ref = group.children[0]
        assert layer_ref.order_key  # 非空键


class TestUserOrderPersistence:
    """D3-ws 修复：系统组内用户重排序跨重建存活（观察序 + 键）。"""

    def _system_reorder_scenario(self):
        records = _records(
            ("l_draft", LayerRole.INITIAL_FACIES_DRAFT, "phase1"),
            ("l_annot", LayerRole.INTERPRETATION_ANNOTATION, "phase1"),
            ("l_pending", LayerRole.PENDING_REVIEW_AREA, "phase1"),
        )
        return records

    def test_observed_order_survives_rebuild(self):
        records = self._system_reorder_scenario()
        # 第一次构建（默认带序）
        base, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.FACIES_CALIBRATION))
        keys = {ref.layer_id: ref.order_key
                for ref in base.iter_layers() if hasattr(ref, "layer_id")}
        # 用户把 pending 拖到最前（观察序回写）
        observed = {"phase1.interpretation": ["l_pending", "l_draft", "l_annot"]}
        rebuilt, _ = build_plan(LayerTreePlanInput(
            records=records, stage=MappingStage.FACIES_CALIBRATION,
            container_orders=observed, order_keys=keys))
        group = rebuilt.find_group("phase1.interpretation")
        assert [c.layer_id for c in group.children if hasattr(c, "layer_id")] == [
            "l_pending", "l_draft", "l_annot"]
        # 再一次重建（无观察序变化、带键）：顺序保持
        rebuilt2, _ = build_plan(LayerTreePlanInput(
            records=records, stage=MappingStage.FACIES_CALIBRATION,
            container_orders=observed,
            order_keys={r.layer_id: ref.order_key
                        for r in rebuilt.iter_layers()
                        if hasattr(r, "layer_id") for ref in (r,)}))
        group2 = rebuilt2.find_group("phase1.interpretation")
        assert [c.layer_id for c in group2.children if hasattr(c, "layer_id")] == [
            "l_pending", "l_draft", "l_annot"]

    def test_default_band_order_for_fresh_group(self):
        # annotation(band 71) 在 draft(70) 之上？——band 小者在上（先遍历）
        records = _records(
            ("b_annot", LayerRole.INTERPRETATION_ANNOTATION, "phase1"),
            ("a_draft", LayerRole.INITIAL_FACIES_DRAFT, "phase1"),
        )
        snap, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.FACIES_CALIBRATION))
        group = snap.find_group("phase1.interpretation")
        ids = [c.layer_id for c in group.children if hasattr(c, "layer_id")]
        assert ids == ["a_draft", "b_annot"]  # draft band 70 < annot 71

    def test_new_member_appends_in_default_order(self):
        records = self._system_reorder_scenario()
        base, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.FACIES_CALIBRATION))
        keys = {r.layer_id: r.order_key for r in base.iter_layers()
                if hasattr(r, "layer_id")}
        # 新图层（无观察序、无键）→ 尾部并入
        records2 = records + (PlanLayerRecord(
            layer_id="l_new", role=LayerRole.INITIAL_FACIES_DRAFT,
            created_stage="phase1", sub_order=99),)
        rebuilt, _ = build_plan(LayerTreePlanInput(
            records=records2, stage=MappingStage.FACIES_CALIBRATION,
            container_orders={"phase1.interpretation":
                              ["l_draft", "l_annot", "l_pending"]},
            order_keys=keys))
        group = rebuilt.find_group("phase1.interpretation")
        ids = [c.layer_id for c in group.children if hasattr(c, "layer_id")]
        assert ids[-1] == "l_new"
        assert set(ids) == {"l_draft", "l_annot", "l_pending", "l_new"}


class TestFactorGroups:
    def test_factor_children_pipeline_order(self):
        records = _records(
            ("f_qc", LayerRole.FACTOR_QC, "phase2", "t1"),
            ("f_grid", LayerRole.FACTOR_GRID, "phase2", "t1"),
            ("f_input", LayerRole.FACTOR_INPUT, "phase2", "t1"),
            ("f_contour", LayerRole.FACTOR_CONTOUR, "phase2", "t1"),
            ("f_cls", LayerRole.FACTOR_CLASSIFICATION, "phase2", "t1"),
            ("f_unc", LayerRole.FACTOR_UNCERTAINTY, "phase2", "t1"),
        )
        snap, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.CONSTRAINT_FACTOR))
        group = snap.find_group("factor.t1")
        assert group is not None
        ids = [c.layer_id for c in group.children if hasattr(c, "layer_id")]
        assert ids == ["f_input", "f_grid", "f_contour", "f_cls", "f_unc", "f_qc"]

    def test_factor_groups_nested_under_root_sorted_by_task(self):
        records = _records(
            ("a", LayerRole.FACTOR_GRID, "phase2", "task-b"),
            ("b", LayerRole.FACTOR_GRID, "phase2", "task-a"),
        )
        snap, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.CONSTRAINT_FACTOR))
        root = snap.find_group("phase2.factors")
        assert root is not None
        nested = [c.group_id for c in root.children if hasattr(c, "group_id")]
        assert nested == ["factor.task-a", "factor.task-b"]


class TestRoutingUnification:
    """D1-ws 修复：QC/AID 按创建阶段路由（树构建与查询同源）。"""

    def test_qc_created_in_phase1_routes_to_aux(self):
        records = _records(("qc1", LayerRole.QC_WARNING, "phase1"))
        snap, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.FACIES_CALIBRATION))
        parent = snap.find_layer_parent("qc1")
        assert parent is not None and parent.group_id == "phase1.aux"

    def test_qc_created_in_phase3_routes_to_qc_group(self):
        records = _records(("qc3", LayerRole.QC_WARNING, "phase3"))
        snap, _ = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.INTEGRATED_COMPILATION))
        parent = snap.find_layer_parent("qc3")
        assert parent is not None and parent.group_id == "phase3.qc"

    def test_effective_home_group_shared_contract(self):
        assert effective_home_group(LayerRole.QC_WARNING, "phase1") == "phase1.aux"
        assert effective_home_group(LayerRole.QC_WARNING, "phase3") == "phase3.qc"
        assert effective_home_group(LayerRole.QC_WARNING) == "phase3.qc"  # 无阶段→静态 home
        assert effective_home_group(LayerRole.ANALYSIS_AID, "phase1") == "phase1.aux"
        assert effective_home_group(LayerRole.ANALYSIS_AID, "phase2") == "phase2.analysis"


class TestNestedUserGroups:
    def test_user_group_nesting(self):
        records = _records(("u1", LayerRole.USER_GENERAL, "phase1"))
        snap, _ = build_plan(LayerTreePlanInput(
            records=records, stage=MappingStage.FACIES_CALIBRATION,
            user_placements={"u1": "user.outer"},
            user_groups={
                "user.outer": PlanUserGroup("user.outer", "外层组", ""),
                "user.inner": PlanUserGroup("user.inner", "内层组", "user.outer"),
            },
            container_orders={"user.outer": ["u1"]}))
        outer = snap.find_group("user.outer")
        assert outer is not None
        inner = snap.find_group("user.inner")
        assert inner is not None and inner.find_group("user.inner") is not None
        # 嵌套组在外层组之内
        assert outer.find_group("user.inner") is not None
        assert "user.inner" in [c.group_id for c in outer.children
                                if hasattr(c, "group_id")]

    def test_deep_nesting_three_levels(self):
        users = {
            "user.a": PlanUserGroup("user.a", "A", ""),
            "user.b": PlanUserGroup("user.b", "B", "user.a"),
            "user.c": PlanUserGroup("user.c", "C", "user.b"),
        }
        snap, _ = build_plan(LayerTreePlanInput(
            records=(), stage=MappingStage.FACIES_CALIBRATION, user_groups=users))
        a = snap.find_group("user.a")
        b = snap.find_group("user.b")
        c = snap.find_group("user.c")
        assert a is not None and b is not None and c is not None
        assert a.find_group("user.c") is not None  # 深层嵌套可达


class TestEmptyGroupMaterialization:
    def test_current_stage_empty_groups_materialize(self):
        # 无任何 P3 图层，但 stage=P3 → P3 组物化（空但可见可展开）
        records = _records(("p1_layer", LayerRole.INITIAL_FACIES_DRAFT, "phase1"))
        snap, facts = build_plan(LayerTreePlanInput(records=records, stage=MappingStage.INTEGRATED_COMPILATION))
        ids = snap.group_ids()
        assert "phase3.integrated" in ids
        assert "phase3.cartography" in ids
        assert "phase1.aux" not in ids  # P1 aux 不在 P3 物化
        assert facts.materialized_empty_groups

    def test_base_reference_always_materialized(self):
        snap, _ = build_plan(LayerTreePlanInput(records=(), stage=MappingStage.FACIES_CALIBRATION))
        assert "base.reference" in snap.group_ids()


class TestSystemGroupKeyStability:
    def test_system_group_keys_anchor_template_index(self):
        records_p1 = _records(("x", LayerRole.INITIAL_FACIES_DRAFT, "phase1"))
        # P1：P1 组非空、P3 组不物化
        snap_p1, _ = build_plan(LayerTreePlanInput(records=records_p1, stage=MappingStage.FACIES_CALIBRATION))
        # P3：P1 interpretation 仍在（全阶段组）但 P3 组物化
        snap_p3, _ = build_plan(LayerTreePlanInput(records=records_p1, stage=MappingStage.INTEGRATED_COMPILATION))
        key_of = lambda snap, gid: snap.find_group(gid).order_key
        # 键锚定全模板索引：P3 空组出现不改变 P1 组的键
        assert key_of(snap_p1, "phase1.interpretation") == key_of(
            snap_p3, "phase1.interpretation")
        assert key_of(snap_p1, "base.reference") == key_of(snap_p3, "base.reference")

    def test_system_groups_ordered_by_template(self):
        snap, _ = build_plan(LayerTreePlanInput(records=(), stage=MappingStage.INTEGRATED_COMPILATION))
        group_ids = [c.group_id for c in snap.children if hasattr(c, "group_id")]
        expected = [t.group_id for t in SYSTEM_GROUP_TEMPLATES
                    if t.stage_visible(MappingStage.INTEGRATED_COMPILATION)]
        assert group_ids == expected


class TestReviewHardening:
    """R1 review 回归：幽灵容器/自环/未过滤挂载不再丢层或递归。"""

    def test_ghost_container_does_not_swallow_layers(self):
        records = _records(("l1", LayerRole.INITIAL_FACIES_DRAFT, "phase1"))
        snap, _ = build_plan(LayerTreePlanInput(
            records=records, stage=MappingStage.FACIES_CALIBRATION,
            user_placements={"l1": "typo-group"},
            container_orders={"typo-group": ["l1"]}))
        # 幽灵容器不创建无挂载容器 → l1 回 home 组
        assert "typo-group" not in snap.group_ids()
        parent = snap.find_layer_parent("l1")
        assert parent is not None and parent.group_id == "phase1.interpretation"

    def test_self_parent_group_mounts_at_root(self):
        users = {"user.x": PlanUserGroup("user.x", "X", "user.x")}
        snap, _ = build_plan(LayerTreePlanInput(
            records=(), stage=MappingStage.FACIES_CALIBRATION,
            user_groups=users))
        group = snap.find_group("user.x")
        assert group is not None  # 自环不递归
        root_ids = [getattr(c, "group_id", "") for c in snap.children]
        assert "user.x" in root_ids  # 回 root

    def test_two_cycle_groups_do_not_recurse(self):
        users = {
            "user.a": PlanUserGroup("user.a", "A", "user.b"),
            "user.b": PlanUserGroup("user.b", "B", "user.a"),
        }
        snap, _ = build_plan(LayerTreePlanInput(
            records=(), stage=MappingStage.FACIES_CALIBRATION,
            user_groups=users))  # 不抛 RecursionError
        assert snap.find_group("user.a") is not None
        assert snap.find_group("user.b") is not None

    def test_observed_foreign_layer_not_mounted_in_user_group(self):
        records = _records(
            ("sys1", LayerRole.FACIES_BOUNDARY, "phase2"),
            ("u1", LayerRole.USER_GENERAL, "phase1"),
        )
        snap, _ = build_plan(LayerTreePlanInput(
            records=records, stage=MappingStage.CONSTRAINT_FACTOR,
            user_placements={"u1": "user.g"},
            user_groups={"user.g": PlanUserGroup("user.g", "G", "")},
            container_orders={"user.g": ["sys1", "u1"]}))
        group = snap.find_group("user.g")
        ids = [c.layer_id for c in group.children if hasattr(c, "layer_id")]
        assert ids == ["u1"]  # 系统组内层不被用户组观察序劫持
        # sys1 仍在其 home 组（无双挂载）
        home = snap.find_layer_parent("sys1")
        assert home is not None and home.group_id == "phase2.constraints"
