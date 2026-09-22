"""``LayerPresentationState`` (goal §8 / D9) — 纯派生呈现状态测试。

全部纯领域（无 Qt / 无 QGIS，always run）：用最小 duck-typed
document（SimpleNamespace）+ 真实 ``MappingWorkspaceState`` /
``StaleSummary`` 权威对象覆盖：editable vs RAW 锁定、P3 组锁、stale
传播计数、QC error 计数、missing 标记、显隐派生、序列化回环，以及
goal §8 精确字段集漂移防御（同 spec 测试的 guard 风格）。
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from paleo_workbench.mapping_workspace.dependencies import (
    ArtifactFreshness,
    FreshnessStatus,
    StaleSummary,
)
from paleo_workbench.mapping_workspace.layer_groups import factor_group_id
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.layer_tree import GroupNode, LayerRef, LayerTreeSnapshot
from paleo_workbench.mapping_workspace.presentation import (
    FRESHNESS_VALUES,
    LayerPresentationState,
    build_presentation_states,
)
from paleo_workbench.mapping_workspace.stage_state import (
    ArtifactMaturity,
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.mapping_workspace.stages import MappingStage

P1 = MappingStage.FACIES_CALIBRATION
P2 = MappingStage.CONSTRAINT_FACTOR
P3 = MappingStage.INTEGRATED_COMPILATION

#: goal §8 的精确字段集（漂移防御：跨分支 UI 契约，增删字段必须走契约评审）。
GOAL_SECTION_8_FIELDS = {
    "layer_id", "group_id", "role", "visible", "active", "editable", "dirty",
    "raw_locked", "stage_locked", "maturity", "freshness", "stale_count",
    "qc_error_count", "missing", "degraded", "version",
}


def _ws(*records: LayerMembershipRecord) -> MappingWorkspaceState:
    state = MappingWorkspaceState()
    for record in records:
        state.set_membership(record)
    return state


def _states(document, workspace_state, **kwargs):
    return {
        state.layer_id: state
        for state in build_presentation_states(document, workspace_state, **kwargs)
    }


# ---------------------------------------------------------------------------
# 契约防御：goal §8 精确字段集
# ---------------------------------------------------------------------------

def test_field_set_is_exactly_goal_section_8():
    assert LayerPresentationState.__dataclass_params__.frozen is True
    names = {field.name for field in dataclasses.fields(LayerPresentationState)}
    assert names == GOAL_SECTION_8_FIELDS, (
        f"field drift vs goal §8: +{names - GOAL_SECTION_8_FIELDS} "
        f"-{GOAL_SECTION_8_FIELDS - names}"
    )
    sample = LayerPresentationState(layer_id="L")
    assert set(sample.to_dict()) == GOAL_SECTION_8_FIELDS
    assert sample.to_dict()["role"] == LayerRole.LEGACY_UNCLASSIFIED.value
    assert FRESHNESS_VALUES == {
        "current", "stale", "missing_input", "superseded", "unknown"}


# ---------------------------------------------------------------------------
# editable vs RAW 锁定
# ---------------------------------------------------------------------------

def test_editable_draft_vs_raw_locked_factor_grid():
    ws = _ws(
        LayerMembershipRecord(layer_id="draft1", role=LayerRole.INITIAL_FACIES_DRAFT,
                              source_version_id="ver_raw_1"),
        LayerMembershipRecord(layer_id="grid1", role=LayerRole.FACTOR_GRID,
                              factor_task_id="task1"),
    )
    document = SimpleNamespace(
        user_vector_layers=[SimpleNamespace(id="draft1")],
        workstation_reference_layers=[],
        factor_map_tasks=[],
        quality_reports=[],
    )
    states = _states(document, ws)

    draft = states["draft1"]
    assert draft.editable is True and draft.raw_locked is False
    assert draft.group_id == "phase1.interpretation"
    assert draft.version == "ver_raw_1"
    assert draft.maturity == ArtifactMaturity.DRAFT  # 未记录 → 领域默认
    assert draft.freshness == "unknown"              # 无摘要 → 诚实未知
    assert draft.missing is False

    grid = states["grid1"]
    assert grid.editable is False and grid.raw_locked is True
    assert grid.group_id == factor_group_id("task1")
    assert grid.missing is True  # 仅运行时存在且调用方未声明 present


# ---------------------------------------------------------------------------
# stage_locked（P3 组锁）
# ---------------------------------------------------------------------------

def test_stage_locked_from_group_template_locked_stages():
    ws = _ws(
        LayerMembershipRecord(layer_id="prov1", role=LayerRole.PROVENANCE_LINE),
        LayerMembershipRecord(layer_id="draft1", role=LayerRole.INITIAL_FACIES_DRAFT),
        LayerMembershipRecord(layer_id="grid1", role=LayerRole.FACTOR_GRID,
                              factor_task_id="task1"),
    )
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])
    # phase2.constraints 锁 P3；phase1.interpretation 锁 P2/P3；factor 子组
    # 继承 phase2.factors 根组锁 P3。
    at_p2 = _states(document, ws, current_stage=P2)
    assert at_p2["prov1"].stage_locked is False
    assert at_p2["draft1"].stage_locked is True
    assert at_p2["grid1"].stage_locked is False

    at_p3 = _states(document, ws, current_stage=P3)
    assert at_p3["prov1"].stage_locked is True
    assert at_p3["draft1"].stage_locked is True
    assert at_p3["grid1"].stage_locked is True

    # current_stage 缺省 → 回落 workspace_state.current_stage。
    ws.set_current_stage(P1)
    at_p1 = _states(document, ws)
    assert at_p1["prov1"].stage_locked is False
    assert at_p1["draft1"].stage_locked is False


# ---------------------------------------------------------------------------
# freshness / stale 传播计数
# ---------------------------------------------------------------------------

def _artifact(key, status, culprits=()):
    return ArtifactFreshness(
        key, key.split(":", 1)[0],
        P2 if key.startswith("factor:") else P1,
        status, "", upstream_culprits=tuple(culprits))


def test_stale_propagation_counted_via_dependency_keys():
    ws = _ws(
        LayerMembershipRecord(layer_id="draft1", role=LayerRole.INITIAL_FACIES_DRAFT),
        LayerMembershipRecord(layer_id="grid1", role=LayerRole.FACTOR_GRID,
                              factor_task_id="task1"),
        LayerMembershipRecord(layer_id="integ1", role=LayerRole.INTEGRATED_FACIES),
        LayerMembershipRecord(layer_id="note1", role=LayerRole.INTERPRETATION_ANNOTATION),
    )
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])
    summary = StaleSummary((
        _artifact("phase1_draft:draft1", FreshnessStatus.STALE,
                  culprits=("ver_raw_1",)),
        _artifact("factor:task1", FreshnessStatus.SUPERSEDED,
                  culprits=("ver_grid_1",)),
        _artifact("integrated:integ1", FreshnessStatus.MISSING_INPUT,
                  culprits=("phase1_draft:draft1", "factor:task1")),
    ))
    states = _states(document, ws, freshness_summary=summary)

    assert states["draft1"].freshness == "stale"
    assert states["draft1"].stale_count == 1
    assert states["grid1"].freshness == "superseded"
    assert states["grid1"].stale_count == 1
    assert states["integ1"].freshness == "missing_input"
    assert states["integ1"].stale_count == 2  # 传播：两个上游 culprit
    # 无对应成果的图层 → 诚实 unknown（摘要存在≠每层都有评估）。
    assert states["note1"].freshness == "unknown"
    assert states["note1"].stale_count == 0


def test_current_artifact_has_zero_stale_count():
    ws = _ws(LayerMembershipRecord(layer_id="draft1",
                                   role=LayerRole.INITIAL_FACIES_DRAFT))
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])
    summary = StaleSummary((
        _artifact("phase1_draft:draft1", FreshnessStatus.CURRENT),))
    state = _states(document, ws, freshness_summary=summary)["draft1"]
    assert state.freshness == "current" and state.stale_count == 0


# ---------------------------------------------------------------------------
# QC error 计数（最新报告 + 图层引用契约）
# ---------------------------------------------------------------------------

def test_qc_errors_counted_only_from_latest_report_and_layer_refs():
    ws = _ws(
        LayerMembershipRecord(layer_id="layerA", role=LayerRole.FAULT_CONSTRAINT),
        LayerMembershipRecord(layer_id="layerB", role=LayerRole.MASK_BOUNDARY),
    )
    old_report = SimpleNamespace(issues=[
        {"severity": "error", "feature_kind": "layer", "feature_id": "layerA"},
    ])
    latest = SimpleNamespace(issues=[
        # 引用 layerA 的三种形态各计 1。
        {"severity": "error", "feature_kind": "layer", "feature_id": "layerA"},
        {"severity": "error", "ref": "layerA"},
        {"severity": "error", "layer_id": "layerA"},
        # warning 不计；地图级 error 不摊派；其他图层不计。
        {"severity": "warning", "feature_kind": "layer", "feature_id": "layerA"},
        {"severity": "error", "feature_kind": "map", "ref": "map:doc1"},
        {"severity": "error", "feature_kind": "layer", "feature_id": "layerB",
         "status": "ignored"},
        # 前向兼容：severity 缺失时容忍 status 键。
        {"status": "error", "ref": "layerB"},
    ])
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[],
                               quality_reports=[old_report, latest])
    states = _states(document, ws)
    assert states["layerA"].qc_error_count == 3
    assert states["layerB"].qc_error_count == 2


def test_qc_errors_zero_without_reports():
    ws = _ws(LayerMembershipRecord(layer_id="layerA", role=LayerRole.FAULT_CONSTRAINT))
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])
    assert _states(document, ws)["layerA"].qc_error_count == 0


# ---------------------------------------------------------------------------
# missing
# ---------------------------------------------------------------------------

def test_missing_flagged_when_layer_absent_from_all_collections():
    ws = _ws(
        LayerMembershipRecord(layer_id="persisted", role=LayerRole.INTEGRATED_FACIES),
        LayerMembershipRecord(layer_id="referenced", role=LayerRole.BASE_REFERENCE),
        LayerMembershipRecord(layer_id="runtime_only", role=LayerRole.INITIAL_FACIES_SOURCE),
        LayerMembershipRecord(layer_id="ghost", role=LayerRole.INTEGRATED_BOUNDARY),
    )
    document = SimpleNamespace(
        user_vector_layers=[SimpleNamespace(id="persisted")],
        workstation_reference_layers=[SimpleNamespace(id="referenced")],
        factor_map_tasks=[], quality_reports=[],
    )
    states = _states(document, ws, present_layer_ids={"runtime_only"})
    assert states["persisted"].missing is False
    assert states["referenced"].missing is False
    assert states["runtime_only"].missing is False  # 运行时存在由调用方声明
    assert states["ghost"].missing is True


# ---------------------------------------------------------------------------
# visible（覆盖层 + 阶段组默认）
# ---------------------------------------------------------------------------

def test_visible_group_defaults_and_user_overrides():
    ws = _ws(LayerMembershipRecord(layer_id="prov1", role=LayerRole.PROVENANCE_LINE))
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])

    # phase2.constraints 阶段默认：P2 可见、P1 不可见。
    assert _states(document, ws, current_stage=P2)["prov1"].visible is True
    assert _states(document, ws, current_stage=P1)["prov1"].visible is False

    # 组覆盖层（用户勾选）赢过 profile 默认。
    ws.view_state(P1).record_group_visibility("phase2.constraints", True)
    assert _states(document, ws, current_stage=P1)["prov1"].visible is True

    # 图层覆盖层赢过组覆盖层。
    ws.view_state(P1).record_layer_visibility("prov1", False)
    assert _states(document, ws, current_stage=P1)["prov1"].visible is False


# ---------------------------------------------------------------------------
# group_id 路由（树放置优先，其次角色 home 组）
# ---------------------------------------------------------------------------

def test_group_id_prefers_persisted_tree_placement():
    ws = _ws(LayerMembershipRecord(layer_id="draft1", role=LayerRole.INITIAL_FACIES_DRAFT))
    ws.tree = LayerTreeSnapshot(children=(
        GroupNode(group_id="user.custom", name="我的组", kind="user",
                  children=(LayerRef(layer_id="draft1"),)),
    )).to_dict()
    document = SimpleNamespace(user_vector_layers=[SimpleNamespace(id="draft1")],
                               workstation_reference_layers=[], factor_map_tasks=[],
                               quality_reports=[])
    state = _states(document, ws)["draft1"]
    assert state.group_id == "user.custom"
    # 用户组不在阶段 profile：默认可见、无模板锁。
    assert state.visible is True and state.stage_locked is False


# ---------------------------------------------------------------------------
# maturity / version / dirty / active / degraded
# ---------------------------------------------------------------------------

def test_maturity_read_from_artifact_maturity_keys():
    ws = _ws(
        LayerMembershipRecord(layer_id="draft1", role=LayerRole.INITIAL_FACIES_DRAFT),
        LayerMembershipRecord(layer_id="integ1", role=LayerRole.INTEGRATED_FACIES),
    )
    ws.set_maturity("phase1_draft:draft1", "reviewed")
    ws.set_maturity("integrated:integ1", "published")
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])
    states = _states(document, ws)
    assert states["draft1"].maturity == "reviewed"
    assert states["integ1"].maturity == "published"


def test_version_falls_back_to_factor_grid_artifact_version():
    ws = _ws(
        LayerMembershipRecord(layer_id="grid1", role=LayerRole.FACTOR_GRID,
                              factor_task_id="task1"),
        LayerMembershipRecord(layer_id="note1", role=LayerRole.INTERPRETATION_ANNOTATION),
    )
    document = SimpleNamespace(
        user_vector_layers=[], workstation_reference_layers=[],
        factor_map_tasks=[SimpleNamespace(id="task1", grid_artifact_version_id="ver_g1")],
        quality_reports=[],
    )
    states = _states(document, ws)
    assert states["grid1"].version == "ver_g1"
    assert states["note1"].version == ""


def test_dirty_active_degraded_from_caller_inputs():
    ws = _ws(
        LayerMembershipRecord(layer_id="draft1", role=LayerRole.INITIAL_FACIES_DRAFT),
        LayerMembershipRecord(layer_id="prov1", role=LayerRole.PROVENANCE_LINE),
    )
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])

    # 缺省：不谎报（degraded 由 UI 分支拥有实时能力）。
    defaults = _states(document, ws)
    assert defaults["draft1"].dirty is False
    assert defaults["draft1"].active is False
    assert defaults["draft1"].degraded is False

    explicit = _states(
        document, ws,
        active_layer_ids=("draft1",),
        dirty_layer_ids={"draft1"},
        capability={"native_stack": False},
    )
    assert explicit["draft1"].active is True
    assert explicit["draft1"].dirty is True
    assert explicit["draft1"].degraded is True
    assert explicit["prov1"].degraded is True   # 能力是全局的
    assert explicit["prov1"].dirty is False

    native = _states(document, ws, capability={"native_stack": True})
    assert native["draft1"].degraded is False


def test_no_workspace_state_yields_empty_list():
    document = SimpleNamespace(user_vector_layers=[], workstation_reference_layers=[],
                               factor_map_tasks=[], quality_reports=[])
    assert build_presentation_states(document, None) == []


# ---------------------------------------------------------------------------
# 序列化回环
# ---------------------------------------------------------------------------

def test_serialization_roundtrip():
    original = LayerPresentationState(
        layer_id="L1", group_id="phase3.integrated",
        role=LayerRole.INTEGRATED_FACIES,
        visible=True, active=True, editable=True, dirty=True,
        raw_locked=False, stage_locked=True, maturity="reviewed",
        freshness="stale", stale_count=2, qc_error_count=1,
        missing=False, degraded=False, version="ver_9",
    )
    payload = original.to_dict()
    assert payload["role"] == "integrated_facies"
    restored = LayerPresentationState(
        **{**payload, "role": LayerRole(payload["role"])})
    assert restored == original
    # 派生状态绝不持久化：model 侧没有 from_dict 工程入口。
    assert not hasattr(LayerPresentationState, "from_dict")
