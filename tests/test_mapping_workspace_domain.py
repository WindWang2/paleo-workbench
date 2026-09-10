"""Geological Mapping Workspace V5 — 纯领域单元测试（无 Qt / 无 QGIS）。

覆盖（V5 §80）：stage profiles / transitions / membership / group templates /
visibility profiles / stage view state / artifact freshness / legacy migration。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping_workspace import (
    MappingStage,
    LayerRole,
    ConstraintKind,
    LayerTreeSnapshot,
    GroupNode,
    LayerRef,
    factor_group_id,
)
from paleo_workbench.mapping_workspace.dependencies import (
    FreshnessStatus,
    MappingDependencyService,
)
from paleo_workbench.mapping_workspace.layer_groups import (
    BASE_REFERENCE_GROUP_ID,
    LEGACY_GROUP_ID,
    SYSTEM_GROUP_TEMPLATES,
    classify_layer_for_migration,
    default_group_visibility,
    home_group_for_role,
    movable_into_system_group,
    stages_for_role,
    system_group_template,
)
from paleo_workbench.mapping_workspace.readiness import (
    ReadinessItemStatus,
    StageReadinessStatus,
    evaluate_stage_readiness,
)
from paleo_workbench.mapping_workspace.stage_profiles import (
    stage_profile,
    stage_profiles,
)
from paleo_workbench.mapping_workspace.stage_state import (
    ArtifactMaturity,
    LayerMembershipRecord,
    MappingWorkspaceState,
    StageViewState,
)
from paleo_workbench.mapping_workspace.stages import (
    next_stage,
    previous_stage,
    stage_from_value,
)


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------

def test_stage_order_and_navigation():
    from paleo_workbench.mapping_workspace.stages import STAGE_ORDER

    assert STAGE_ORDER[0] is MappingStage.FACIES_CALIBRATION
    assert next_stage(MappingStage.FACIES_CALIBRATION) == MappingStage.CONSTRAINT_FACTOR
    assert next_stage(MappingStage.INTEGRATED_COMPILATION) is None
    assert previous_stage(MappingStage.FACIES_CALIBRATION) is None
    assert previous_stage(MappingStage.INTEGRATED_COMPILATION) == MappingStage.CONSTRAINT_FACTOR


def test_first_stage_is_intelligent_prediction():
    first = MappingStage.FACIES_CALIBRATION
    assert first.short_label == "智能预测"
    assert "智能预测" in first.label
    assert previous_stage(first) is None


def test_stage_labels_are_professional_not_pages():
    for stage in MappingStage:
        assert "页面" not in stage.label
        assert stage.label  # 非空中文标签


def test_stage_from_value_aliases():
    assert stage_from_value("phase1") == MappingStage.FACIES_CALIBRATION
    assert stage_from_value("intelligent_prediction") == MappingStage.FACIES_CALIBRATION
    assert stage_from_value("智能预测") == MappingStage.FACIES_CALIBRATION
    assert stage_from_value("integrated") == MappingStage.INTEGRATED_COMPILATION
    assert stage_from_value(MappingStage.CONSTRAINT_FACTOR) == MappingStage.CONSTRAINT_FACTOR
    assert stage_from_value("bogus") is None
    assert stage_from_value(None) is None


# ---------------------------------------------------------------------------
# stage profiles
# ---------------------------------------------------------------------------

def test_every_stage_has_profile_with_checks():
    for profile in stage_profiles():
        assert profile.stage.label
        assert profile.group_visibility
        assert profile.readiness_checks
        assert profile.recommended_docks is not None


def test_stage_profiles_decoupled_from_layout_presets():
    """StageProfile 的 dock 建议与 WorkstationLayoutPreset 是两套体系（V5 §6）。"""
    from paleo_workbench.ui.layout_presets import WORKSTATION_LAYOUT_PRESETS

    profile_ids = {p.stage.value for p in stage_profiles()}
    preset_ids = {p.id for p in WORKSTATION_LAYOUT_PRESETS}
    assert profile_ids.isdisjoint(preset_ids)


def test_phase1_visibility_profile():
    vis = default_group_visibility(MappingStage.FACIES_CALIBRATION)
    assert vis["phase1.initial_facies"] is True
    assert vis["phase1.well_predictions"] is True
    assert vis["phase2.constraints"] is False
    assert vis["phase2.factors"] is False
    assert vis["phase3.integrated"] is False
    assert vis[BASE_REFERENCE_GROUP_ID] is True  # 共享组


def test_phase2_shows_phase1_evidence_locked():
    profile = stage_profile(MappingStage.CONSTRAINT_FACTOR)
    assert "phase1.interpretation" in profile.locked_groups
    assert profile.group_visibility["phase1.interpretation"] is True
    assert profile.group_visibility["phase2.constraints"] is True


def test_phase3_locks_upstream_evidence():
    profile = stage_profile(MappingStage.INTEGRATED_COMPILATION)
    for group in ("phase1.interpretation", "phase2.constraints", "phase2.factors"):
        assert group in profile.locked_groups
    assert profile.group_visibility["phase3.integrated"] is True


def test_editing_roles_per_stage_do_not_overlap_raw():
    for profile in stage_profiles():
        for role in profile.active_editing_roles:
            assert not role.is_raw_protected


# ---------------------------------------------------------------------------
# layer roles & routing
# ---------------------------------------------------------------------------

def test_raw_protected_roles():
    assert LayerRole.INITIAL_FACIES_SOURCE.is_raw_protected
    assert LayerRole.WELL_FACIES_PREDICTION.is_raw_protected
    assert LayerRole.FACTOR_GRID.is_raw_protected
    assert not LayerRole.INITIAL_FACIES_DRAFT.is_raw_protected
    assert not LayerRole.INTEGRATED_FACIES.is_raw_protected


def test_role_home_group_routing():
    assert home_group_for_role(LayerRole.INITIAL_FACIES_SOURCE) == "phase1.initial_facies"
    assert home_group_for_role(LayerRole.PROVENANCE_LINE) == "phase2.constraints"
    assert home_group_for_role(LayerRole.INTEGRATED_FACIES) == "phase3.integrated"
    assert home_group_for_role(LayerRole.BASE_REFERENCE) == BASE_REFERENCE_GROUP_ID


def test_factor_roles_route_to_factor_group():
    group = home_group_for_role(LayerRole.FACTOR_GRID, factor_task_id="task_9")
    assert group == "factor.task_9"
    assert home_group_for_role(LayerRole.FACTOR_GRID) == "phase2.factors"


def test_factor_group_id_roundtrip():
    assert factor_group_id("abc") == "factor.abc"
    assert factor_group_id("") == ""


def test_membership_vs_visibility_distinction():
    """Sand Thickness 属于 P2/P3；P3 可隐藏但不等于非成员（V5 §39）。"""
    stages = stages_for_role(LayerRole.FACTOR_GRID)
    assert MappingStage.CONSTRAINT_FACTOR in stages
    assert MappingStage.INTEGRATED_COMPILATION in stages


def test_movable_into_system_group_rules():
    # 角色图层不能拖进语义不相容的系统组（科学角色 ≠ 视觉放置，V5 §51）。
    assert not movable_into_system_group(LayerRole.FACTOR_GRID, "phase1.well_predictions")
    assert movable_into_system_group(LayerRole.PROVENANCE_LINE, "phase2.constraints")
    # 用户组自由。
    assert movable_into_system_group(LayerRole.FACTOR_GRID, "user.custom")


def test_constraint_kinds_typed():
    assert ConstraintKind.PROVENANCE_LINE.geometry_kind == "line"
    assert ConstraintKind.MASK.geometry_kind == "polygon"
    assert ConstraintKind.FAULT.interpolation_role == "break"
    assert ConstraintKind.SOURCE_DIRECTION.interpolation_role == "direction"
    assert ConstraintKind.PROVENANCE_LINE.layer_role == LayerRole.PROVENANCE_LINE


# ---------------------------------------------------------------------------
# group templates
# ---------------------------------------------------------------------------

def test_system_groups_have_stable_ids_not_display_names():
    ids = [template.group_id for template in SYSTEM_GROUP_TEMPLATES]
    assert len(ids) == len(set(ids))
    assert "phase1.initial_facies" in ids
    assert "phase2.constraints" in ids
    assert "phase3.integrated" in ids


def test_shared_base_group_visible_in_all_stages():
    template = system_group_template(BASE_REFERENCE_GROUP_ID)
    assert template.stages == frozenset(set(MappingStage))


def test_desired_tree_shows_current_stage_groups_and_base_reference():
    from paleo_workbench.mapping_workspace.layer_group_controller import (
        LayerGroupController,
    )
    from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState

    controller = LayerGroupController(MappingWorkspaceState())
    tree = controller.build_desired_tree([])
    ids = [child.group_id for child in tree.children if isinstance(child, GroupNode)]
    assert BASE_REFERENCE_GROUP_ID in ids
    assert "phase1.well_predictions" in ids
    assert "phase1.seismic_predictions" in ids
    assert "phase1.interpretation" in ids
    assert "phase3.cartography" not in ids
    assert "phase2.constraints" not in ids


def test_legacy_fallback_group_exists():
    template = system_group_template(LEGACY_GROUP_ID)
    assert template is not None
    assert template.stages


# ---------------------------------------------------------------------------
# stage view state
# ---------------------------------------------------------------------------

def test_stage_view_state_overrides_survive_stage_switch():
    state = MappingWorkspaceState()
    p2 = state.view_state(MappingStage.CONSTRAINT_FACTOR)
    p2.record_group_visibility("phase2.factors", False)
    p2.record_layer_visibility("layer-a", False)
    # 切走再回：覆盖保留（V5 §37）。
    state.set_current_stage(MappingStage.INTEGRATED_COMPILATION)
    state.set_current_stage(MappingStage.CONSTRAINT_FACTOR)
    assert state.view_state(MappingStage.CONSTRAINT_FACTOR).group_visibility[
        "phase2.factors"] is False
    assert state.view_state(MappingStage.CONSTRAINT_FACTOR).layer_visibility[
        "layer-a"] is False


def test_effective_group_visibility_merges_profile_defaults():
    view = StageViewState(stage=MappingStage.CONSTRAINT_FACTOR)
    view.record_group_visibility("phase2.factors", False)
    defaults = default_group_visibility(MappingStage.CONSTRAINT_FACTOR)
    effective = view.effective_group_visibility(defaults)
    assert effective["phase2.factors"] is False       # 用户覆盖
    assert effective["phase2.constraints"] is True    # profile 默认


def test_restore_stage_defaults_clears_overrides():
    view = StageViewState(stage=MappingStage.FACIES_CALIBRATION)
    view.record_group_visibility("phase1.aux", False)
    view.customized = True
    view.reset_to_defaults()
    assert not view.group_visibility
    assert view.customized is False


def test_workspace_state_roundtrip():
    state = MappingWorkspaceState()
    state.set_current_stage(MappingStage.INTEGRATED_COMPILATION)
    state.set_membership(LayerMembershipRecord(
        layer_id="L1", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_abc"))
    state.set_maturity("phase1_draft:L1", ArtifactMaturity.REVIEWED)
    state.compilation_input_set["砂厚"] = "factor:f1:ver_9"
    restored = MappingWorkspaceState.from_dict(state.to_dict())
    assert restored.current_stage == MappingStage.INTEGRATED_COMPILATION
    assert restored.role_of("L1") == LayerRole.INITIAL_FACIES_DRAFT
    assert restored.maturity_of("phase1_draft:L1") == ArtifactMaturity.REVIEWED
    assert restored.compilation_input_set["砂厚"] == "factor:f1:ver_9"


def test_workspace_state_rejects_unknown_maturity():
    state = MappingWorkspaceState()
    with pytest.raises(ValueError):
        state.set_maturity("k", "bogus")


def test_artifact_maturity_independent_of_stage():
    """Phase ≠ maturity（V5 §33）：同一成熟度词表适用于任何阶段成果。"""
    state = MappingWorkspaceState()
    state.set_maturity("factor:f1", ArtifactMaturity.FROZEN)
    state.set_maturity("integrated:L2", ArtifactMaturity.DRAFT)
    assert state.maturity_of("factor:f1") == ArtifactMaturity.FROZEN


# ---------------------------------------------------------------------------
# layer tree snapshot
# ---------------------------------------------------------------------------

def _sample_tree() -> LayerTreeSnapshot:
    return LayerTreeSnapshot(children=(
        GroupNode(group_id="phase1.interpretation", name="人工解释", children=(
            LayerRef(layer_id="draft-1"),
            GroupNode(group_id="factor.f1", name="砂厚", kind="system", children=(
                LayerRef(layer_id="factor-grid-1"),
            )),
        )),
        LayerRef(layer_id="loose-layer"),
    ))


def test_tree_snapshot_queries():
    tree = _sample_tree()
    assert tree.layer_ids_top_first() == ("draft-1", "factor-grid-1", "loose-layer")
    assert tree.find_group("factor.f1") is not None
    assert tree.find_layer_parent("factor-grid-1").group_id == "factor.f1"
    assert tree.find_layer_parent("loose-layer") is None  # root


def test_flatten_for_render_keps_unlisted_layers():
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    tree = _sample_tree()
    snapshots = [
        MapLayerSnapshot(id="loose-layer", name="loose", layer_type="vector",
                         extent=(0, 0, 1, 1), crs="EPSG:4326",
                         data_revision=1, style_revision=1),
        MapLayerSnapshot(id="draft-1", name="draft", layer_type="vector",
                         extent=(0, 0, 1, 1), crs="EPSG:4326",
                         data_revision=1, style_revision=1),
        MapLayerSnapshot(id="unplaced", name="new", layer_type="vector",
                         extent=(0, 0, 1, 1), crs="EPSG:4326",
                         data_revision=1, style_revision=1),
    ]
    flat = tree.flatten_for_render(snapshots)
    assert [layer.id for layer in flat] == ["draft-1", "loose-layer", "unplaced"]


def test_tree_snapshot_serialization_roundtrip():
    restored = LayerTreeSnapshot.from_dict(_sample_tree().to_dict())
    assert restored.layer_ids_top_first() == _sample_tree().layer_ids_top_first()
    assert restored.group_ids() == _sample_tree().group_ids()


# ---------------------------------------------------------------------------
# legacy migration（V5 §72：保守归类，绝不猜名字）
# ---------------------------------------------------------------------------

class _FakeSnapshotLayer:
    def __init__(self, layer_id, name="", metadata=None, template=""):
        self.id = layer_id
        self.name = name
        self.metadata = metadata or {}
        self.template = template


def test_migration_home_workarea_layers_to_base_reference():
    role, group, _ = classify_layer_for_migration(
        _FakeSnapshotLayer("home_workarea:wells", "井位"))
    assert role == LayerRole.BASE_REFERENCE
    assert group == BASE_REFERENCE_GROUP_ID


def test_migration_reference_layers_to_base_reference():
    role, group, _ = classify_layer_for_migration(
        _FakeSnapshotLayer("ref-1", "外部参考", metadata={"reference": "true"}))
    assert role == LayerRole.BASE_REFERENCE


def test_migration_template_layers_to_constraints():
    role, group, kind = classify_layer_for_migration(
        _FakeSnapshotLayer("uv-1", "随便叫什么", template="断层线"))
    assert role == LayerRole.FAULT_CONSTRAINT
    assert group == "phase2.constraints"
    assert kind == "fault"


def test_migration_unknown_layers_fall_back_unclassified():
    role, group, _ = classify_layer_for_migration(
        _FakeSnapshotLayer("mystery-1", "砂厚图"))
    assert role == LayerRole.LEGACY_UNCLASSIFIED
    assert group == LEGACY_GROUP_ID


def test_migration_respects_explicit_role_metadata():
    role, _, _ = classify_layer_for_migration(
        _FakeSnapshotLayer("x", metadata={"layer_role": "integrated_facies"}))
    assert role == LayerRole.INTEGRATED_FACIES


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------

def test_readiness_empty_project_is_not_ready_but_never_blocks():
    readiness = evaluate_stage_readiness(MappingStage.FACIES_CALIBRATION, document=None)
    assert readiness.status == StageReadinessStatus.NOT_READY
    # 就绪度是提示不是 wizard（返回值从不抛异常阻止调用方切换）。


def test_target_horizon_is_first_readiness_check():
    from paleo_workbench.project.models import ProjectDocument

    for stage in MappingStage:
        assert stage_profile(stage).readiness_checks[0] == "target_horizon"
    empty = ProjectDocument.new("无层位")
    readiness = evaluate_stage_readiness(MappingStage.FACIES_CALIBRATION, document=empty)
    item = next(row for row in readiness.items if row.check_id == "target_horizon")
    assert item.status is ReadinessItemStatus.ERROR
    empty.stratigraphy.target_horizon = "D63"
    ready = evaluate_stage_readiness(MappingStage.FACIES_CALIBRATION, document=empty)
    item = next(row for row in ready.items if row.check_id == "target_horizon")
    assert item.status is ReadinessItemStatus.OK
    assert item.detail == "D63"


def test_readiness_items_carry_locate_targets():
    document = type("Doc", (), {
        "paleomap_documents": [], "prediction_tasks": [], "user_vector_layers": [],
    })()
    readiness = evaluate_stage_readiness(
        MappingStage.FACIES_CALIBRATION, document=document)
    targets = {item.target for item in readiness.items}
    assert "phase1.seismic_predictions" in targets or any(targets)


# ---------------------------------------------------------------------------
# freshness（V5 §32/§85）
# ---------------------------------------------------------------------------

class _FakeVersion:
    def __init__(self, version_id, asset_id, version_number, run_id=""):
        self.id = version_id
        self.asset_id = asset_id
        self.version_number = version_number
        self.run_id = run_id


class _FakeRun:
    def __init__(self, run_id, input_version_ids):
        self.run_id = run_id
        self.input_version_ids = list(input_version_ids)


class _FakeCatalog:
    def __init__(self):
        self.versions: dict[str, _FakeVersion] = {}
        self.runs: dict[str, _FakeRun] = {}

    def add_asset(self, asset_id, *version_ids):
        for number, version_id in enumerate(version_ids, start=1):
            self.versions[version_id] = _FakeVersion(version_id, asset_id, number)
        return version_ids[-1]

    def add_run(self, run_id, input_version_ids, output_version):
        self.runs[run_id] = _FakeRun(run_id, input_version_ids)
        self.versions[output_version] = _FakeVersion(
            output_version, f"asset-{run_id}", 1, run_id=run_id)

    def resolve_version(self, version_id):
        return self.versions.get(version_id)

    def resolve_run(self, run_id):
        return self.runs.get(run_id)

    def list_versions(self, *, stage=None, asset_id=None):
        return [v for v in self.versions.values() if v.asset_id == asset_id]


class _FakeTask:
    def __init__(self, task_id, status="completed", grid_version=""):
        self.id = task_id
        self.status = status
        self.grid_artifact_version_id = grid_version


class _FakeDoc:
    def __init__(self, tasks):
        self.factor_map_tasks = tasks
        self.map_products = []


def test_freshness_current_when_pinned_version_is_latest():
    catalog = _FakeCatalog()
    catalog.add_asset("raw-asset", "ver_1")
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="draft", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_1"))
    summary = MappingDependencyService().evaluate(_FakeDoc([]), state, catalog)
    entry = summary.get("phase1_draft:draft")
    assert entry.status == FreshnessStatus.CURRENT


def test_freshness_stale_when_upstream_superseded():
    catalog = _FakeCatalog()
    catalog.add_asset("raw-asset", "ver_1", "ver_2")  # v2 出现
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="draft", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_1"))
    summary = MappingDependencyService().evaluate(_FakeDoc([]), state, catalog)
    entry = summary.get("phase1_draft:draft")
    assert entry.status == FreshnessStatus.STALE
    assert summary.headline == "1 项输入成果已过期"


def test_freshness_missing_input():
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="draft", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_gone"))
    summary = MappingDependencyService().evaluate(_FakeDoc([]), state, None)
    assert summary.get("phase1_draft:draft").status == FreshnessStatus.MISSING_INPUT


def test_factor_freshness_via_run_inputs():
    catalog = _FakeCatalog()
    catalog.add_asset("raw-asset", "ver_1", "ver_2")
    catalog.add_run("run_1", ["ver_1"], "ver_grid_1")
    doc = _FakeDoc([_FakeTask("f1", grid_version="ver_grid_1")])
    summary = MappingDependencyService().evaluate(doc, MappingWorkspaceState(), catalog)
    assert summary.get("factor:f1").status == FreshnessStatus.STALE


def test_factor_recomputed_against_new_version_is_current():
    """§85：回到 Phase 2 用新输入重算 → 因子恢复 CURRENT（非静默替换）。"""
    catalog = _FakeCatalog()
    catalog.add_asset("raw-asset", "ver_1", "ver_2")
    catalog.add_run("run_1", ["ver_1"], "ver_grid_1")
    catalog.add_run("run_2", ["ver_2"], "ver_grid_2")  # 钉新版本重算
    doc = _FakeDoc([_FakeTask("f2", grid_version="ver_grid_2")])
    summary = MappingDependencyService().evaluate(doc, MappingWorkspaceState(), catalog)
    assert summary.get("factor:f2").status == FreshnessStatus.CURRENT


def test_integrated_freshness_uses_compilation_input_set():
    catalog = _FakeCatalog()
    catalog.add_asset("raw-asset", "ver_1", "ver_2")
    state = MappingWorkspaceState()
    state.compilation_input_set["阶段1解释"] = "ver_1"
    state.set_membership(LayerMembershipRecord(
        layer_id="int", role=LayerRole.INTEGRATED_FACIES))
    summary = MappingDependencyService().evaluate(_FakeDoc([]), state, catalog)
    assert summary.get("integrated:int").status == FreshnessStatus.STALE


def test_stale_results_are_marked_not_deleted():
    """过期成果保留可查（V5 §31/§56）：freshness 是标记不是删除。"""
    catalog = _FakeCatalog()
    catalog.add_asset("raw-asset", "ver_1", "ver_2")
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="draft", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_1"))
    summary = MappingDependencyService().evaluate(_FakeDoc([]), state, catalog)
    # 状态仍在列表中（可查看旧结果），且没有任何删除动作 API。
    assert summary.get("phase1_draft:draft") is not None
    assert state.membership("draft") is not None
