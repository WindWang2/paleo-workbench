"""V7/V8 tool surface：可用性矩阵（goal §4/§5）单元测试。

纯 Python（无 Qt）——evaluator 是可用性唯一真源，工具条/palette/菜单/
状态条只渲染其输出。V8 M1：上下文为 canonical ``ToolContext``（扁平
图层事实 + ``mapping_stage`` 三态 + ``backend_mode``），不再有嵌套的
呈现快照输入。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.tool_context import build_tool_context
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.ui.workstation.tool_surface import (
    LAYER_CAPTION,
    TOOL_GROUPS,
    LayerCapabilitySnapshot,
    ToolAvailability,
    ToolContext,
    availability_for_context,
    derived_context,
    evaluate_tool,
    stage_group_visibility,
    tool_context_from_ui_snapshot,
)


def _ctx(**overrides) -> ToolContext:
    """默认：phase2、可编辑线图层（物源线）、编辑会话开启、原生后端。"""
    base = dict(
        project_open=True,
        mapping_stage=MappingStage.CONSTRAINT_FACTOR.value,
        active_layer_id="composite:L1",
        layer_name="物源线",
        layer_role=LayerRole.PROVENANCE_LINE.value,
        layer_role_label="物源线",
        active_layer_kind="line",
        artifact_maturity="draft",
        edit_gate_open=True,
        edit_gate_reason="",
        layer_frozen=False,
        layer_missing=False,
        layer_degraded=False,
        vector_writable=True,
        editing=True,
        dirty=False,
        selection_count=0,
        compatible_polygon_count=0,
        can_undo=False,
        can_redo=False,
        can_previous_extent=True,
        can_next_extent=False,
        backend_mode="native",
        backend_reason="",
        write_granted=False,
    )
    base.update(overrides)
    return derived_context(**base)


# ---------------------------------------------------------------------------
# 基础求值
# ---------------------------------------------------------------------------


def test_enabled_tool_has_empty_reason() -> None:
    avail = evaluate_tool("pan", _ctx())
    assert avail.enabled and avail.visible
    assert avail.disabled_reason == ""
    assert avail.reason == avail.disabled_reason  # 别名同值


def test_unknown_tool_id_disabled_with_reason() -> None:
    avail = evaluate_tool("no_such_tool", _ctx())
    assert not avail.visible
    assert not avail.enabled
    assert avail.disabled_reason == "未知工具 'no_such_tool'"


def test_no_project_disables_everything_except_nothing() -> None:
    avail = availability_for_context(_ctx(project_open=False))
    assert not avail["pan"].enabled
    assert "工程" in avail["pan"].disabled_reason


def test_reason_single_source_of_truth() -> None:
    """RAW 阻断原因来自角色门禁（edit_gate_reason），不另行编造第二套话术。"""
    ctx = _ctx(
        active_layer_id="composite:L9",
        layer_name="初始沉积相",
        layer_role=LayerRole.INITIAL_FACIES_SOURCE.value,
        layer_role_label="初始沉积相（原始）",
        active_layer_kind="polygon",
        edit_gate_open=False,
        edit_gate_reason=(
            "图层角色为「初始沉积相（原始）」（RAW/模型结果）——不可直接编辑；"
            "请创建 DERIVED 草稿后编辑"
        ),
        editing=False,
    )
    avail = evaluate_tool("toggle_editing", ctx)
    assert not avail.enabled
    assert avail.reason == ctx.edit_gate_reason


# ---------------------------------------------------------------------------
# §4.1 Phase 1 — 初始相图校正
# ---------------------------------------------------------------------------


def test_phase1_primary_tools_enabled() -> None:
    ctx = _ctx(
        mapping_stage=MappingStage.FACIES_CALIBRATION.value,
        active_layer_id="composite:D1",
        layer_name="沉积相解释草稿",
        layer_role=LayerRole.INITIAL_FACIES_DRAFT.value,
        layer_role_label="沉积相解释（草稿）",
        active_layer_kind="polygon",
        artifact_maturity="draft",
        dirty=True,  # save_edits/rollback 受 dirty 门禁（V8 canonical）
    )
    avail = availability_for_context(ctx)
    for tool in (
        "identify", "select", "layer_properties", "toggle_editing",
        "add_polygon", "move_feature", "vertex",
        "save_edits", "rollback", "qa_run",
    ):
        assert avail[tool].enabled, f"{tool} 应在 phase1 可用"
        assert avail[tool].visible, f"{tool} 应在 phase1 可见"
    # split/merge 属 phase1 主工具面（可见），但启用仍受选择条件约束。
    assert avail["split"].visible and avail["merge"].visible
    assert not avail["split"].enabled  # selection_count=0 / split_ready=False


def test_phase1_add_line_hidden() -> None:
    ctx = _ctx(mapping_stage=MappingStage.FACIES_CALIBRATION.value)
    avail = evaluate_tool("add_line", ctx)
    assert not avail.visible
    assert not avail.enabled
    assert "阶段" in avail.reason


def test_phase1_factor_group_hidden() -> None:
    ctx = _ctx(mapping_stage=MappingStage.FACIES_CALIBRATION.value)
    groups = stage_group_visibility(MappingStage.FACIES_CALIBRATION.value)
    assert "factor" not in groups or not groups["factor"]
    avail = evaluate_tool("factor_workbench", ctx)
    assert not avail.visible


def test_phase1_layout_export_hidden_phase3_visible() -> None:
    p1 = stage_group_visibility(MappingStage.FACIES_CALIBRATION.value)
    p3 = stage_group_visibility(MappingStage.INTEGRATED_COMPILATION.value)
    assert not p1.get("layout_export", False)
    assert p3.get("layout_export", False)


# ---------------------------------------------------------------------------
# §4.2 Phase 2 — 约束与单因素
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [
    LayerRole.PROVENANCE_LINE,
    LayerRole.PROVENANCE_DIRECTION,
    LayerRole.DISTRIBUTION_LINE,
    LayerRole.PALEO_SHORELINE,
    LayerRole.FACIES_BOUNDARY,
    LayerRole.FAULT_CONSTRAINT,
])
def test_phase2_line_role_add_line_primary(role: LayerRole) -> None:
    ctx = _ctx(
        active_layer_id="composite:C1",
        layer_name=role.label,
        layer_role=role.value,
        layer_role_label=role.label,
        active_layer_kind="line",
    )
    avail = availability_for_context(ctx)
    assert avail["add_line"].enabled
    assert not avail["add_polygon"].enabled
    assert "线" in avail["add_polygon"].reason or "面" in avail["add_polygon"].reason

@pytest.mark.parametrize("role", [LayerRole.INTERPOLATION_BOUNDARY, LayerRole.MASK_BOUNDARY])
def test_phase2_polygon_role_add_polygon_usable_line_disabled(role: LayerRole) -> None:
    ctx = _ctx(
        active_layer_id="composite:B1",
        layer_name=role.label,
        layer_role=role.value,
        layer_role_label=role.label,
        active_layer_kind="polygon",
    )
    avail = availability_for_context(ctx)
    assert avail["add_polygon"].enabled
    assert not avail["add_line"].enabled
    assert avail["add_line"].reason

@pytest.mark.parametrize("role", [
    LayerRole.FACTOR_GRID,
    LayerRole.FACTOR_CLASSIFICATION,
    LayerRole.FACTOR_UNCERTAINTY,
    LayerRole.FACTOR_QC,
])
def test_phase2_factor_raster_vector_editing_disabled(role: LayerRole) -> None:
    ctx = _ctx(
        active_layer_id="composite:F1",
        layer_name=role.label,
        layer_role=role.value,
        layer_role_label=role.label,
        active_layer_kind="polygon",
        edit_gate_open=False,
        edit_gate_reason=(
            "图层角色为「%s」（RAW/模型结果）——不可直接编辑；请创建 DERIVED 草稿后编辑"
            % role.label
        ),
        editing=False,
    )
    avail = availability_for_context(ctx)
    for tool in ("toggle_editing", "add_polygon", "add_line", "move_feature", "vertex"):
        assert not avail[tool].enabled, f"{tool} 对 factor raster 必须禁用"
        assert avail[tool].reason
    # 呈现面仍可用：属性/符号/导出/QC
    for tool in ("layer_properties", "symbology", "layer_export", "qa_run"):
        assert avail[tool].enabled, f"{tool} 对 factor raster 应可用"


def test_phase2_factor_group_visible() -> None:
    groups = stage_group_visibility(MappingStage.CONSTRAINT_FACTOR.value)
    assert groups.get("factor")


# ---------------------------------------------------------------------------
# §4.3 Phase 3 — 综合编图
# ---------------------------------------------------------------------------


def test_phase3_integrated_editing_and_product_tools() -> None:
    ctx = _ctx(
        mapping_stage=MappingStage.INTEGRATED_COMPILATION.value,
        active_layer_id="composite:I1",
        layer_name="综合沉积相",
        layer_role=LayerRole.INTEGRATED_FACIES.value,
        layer_role_label="综合沉积相",
        active_layer_kind="polygon",
        artifact_maturity="draft",
    )
    avail = availability_for_context(ctx)
    for tool in (
        "add_polygon", "move_feature", "vertex", "qa_run", "symbology",
        "layer_properties", "map_product_assemble", "map_export",
    ):
        assert avail[tool].enabled, f"{tool} 应在 phase3 可用"


# ---------------------------------------------------------------------------
# 编辑会话 / 选择 / 撤销 / 快照记忆门禁
# ---------------------------------------------------------------------------


def test_editing_gate_needs_session() -> None:
    ctx = _ctx(editing=False)
    avail = availability_for_context(ctx)
    for tool in ("save_edits", "rollback", "add_line", "move_feature", "vertex"):
        assert not avail[tool].enabled
        assert "编辑" in avail[tool].reason
    # D4-5：捕捉/拓扑只需活动图层，与编辑会话解耦（QGIS desktop 对齐）。
    assert avail["snapping"].enabled


def test_selection_gate_delete_split_merge() -> None:
    ctx = _ctx(selection_count=0, compatible_polygon_count=1)
    avail = availability_for_context(ctx)
    assert not avail["delete_selected"].enabled
    assert avail["delete_selected"].reason
    ctx2 = _ctx(selection_count=2, compatible_polygon_count=1)
    avail2 = availability_for_context(ctx2)
    assert avail2["delete_selected"].enabled
    assert not avail2["merge"].enabled  # 只有 1 个兼容多边形
    assert "合并" in avail2["merge"].reason or "多边形" in avail2["merge"].reason


def test_split_inputs_override() -> None:
    """综合编修 split 特殊条件（切割线选集）覆盖通用选择规则。"""
    ctx = _ctx(selection_count=3, split_ready=False)
    assert not evaluate_tool("split", ctx).enabled
    ctx2 = _ctx(selection_count=3, split_ready=True)
    assert evaluate_tool("split", ctx2).enabled


def test_undo_redo_extent_history() -> None:
    ctx = _ctx(can_undo=True, can_redo=False, can_previous_extent=True, can_next_extent=False)
    avail = availability_for_context(ctx)
    assert avail["undo"].enabled
    assert not avail["redo"].enabled
    assert avail["previous_extent"].enabled
    assert not avail["next_extent"].enabled


def test_cancel_always_enabled() -> None:
    assert evaluate_tool("cancel", _ctx(project_open=False)).enabled


def test_frozen_layer_blocks_editing_with_reason() -> None:
    ctx = _ctx(
        active_layer_id="composite:FZ",
        layer_name="已冻结成果",
        layer_role=LayerRole.INTEGRATED_FACIES.value,
        layer_role_label="综合沉积相",
        active_layer_kind="polygon",
        artifact_maturity="frozen",
        layer_frozen=True,
        edit_gate_open=False,
        edit_gate_reason="当前结果已冻结（FROZEN）——需先解除冻结或另存草稿",
    )
    avail = availability_for_context(ctx)
    assert not avail["toggle_editing"].enabled
    assert "冻结" in avail["toggle_editing"].reason


# ---------------------------------------------------------------------------
# 能力 / 授权门禁
# ---------------------------------------------------------------------------


def test_style_manager_needs_native_capability() -> None:
    ctx = _ctx(backend_mode="unavailable", backend_reason="QGIS 桥不可用")
    avail = evaluate_tool("style_manager", ctx)
    assert not avail.enabled
    assert "QGIS" in avail.reason


def test_symbology_fallback_available_without_bridge() -> None:
    """符号系统入口在 fallback 下仍可用（自有属性对话框），不缺桥即禁。"""
    ctx = _ctx(backend_mode="unavailable", backend_reason="QGIS 桥不可用")
    assert evaluate_tool("symbology", ctx).enabled
    assert evaluate_tool("layer_properties", ctx).enabled


def test_degraded_capability_reason_visible() -> None:
    ctx = _ctx(backend_mode="degraded", backend_reason="镜像同步失败 ×2")
    avail = evaluate_tool("style_manager", ctx)
    assert not avail.enabled
    assert "降级" in avail.reason or "镜像" in avail.reason


def test_no_active_layer_reasons() -> None:
    ctx = _ctx(
        active_layer_id="",
        layer_name="",
        layer_role="",
        layer_role_label="",
        active_layer_kind="",
        artifact_maturity="",
        vector_writable=False,
        editing=False,
    )
    avail = availability_for_context(ctx)
    assert not avail["identify"].enabled
    assert "图层" in avail["identify"].reason
    assert not avail["toggle_editing"].enabled
    assert avail["toggle_editing"].reason
    # V8 M1：会话工具无图层时可见 + 禁用（不隐藏能力假象）。
    assert avail["save_edits"].visible
    assert avail["save_edits"].reason == "没有活动的矢量图层"
    assert avail["undo"].visible
    assert avail["undo"].reason == "没有活动的矢量图层"
    # layer/symbology 组整组隐藏（layer_new/reference_import 除外）。
    assert not avail["layer_properties"].visible
    assert avail["layer_new"].visible
    assert avail["layer_new"].enabled


def test_missing_layer_degraded_reason() -> None:
    ctx = _ctx(
        active_layer_id="composite:M1",
        layer_name="缺失引用",
        layer_missing=True,
        edit_gate_open=False,
        edit_gate_reason="图层源缺失（文件被移动或删除）",
    )
    avail = availability_for_context(ctx)
    assert not avail["toggle_editing"].enabled
    assert "缺失" in avail["toggle_editing"].reason


# ---------------------------------------------------------------------------
# 分组 / 全量
# ---------------------------------------------------------------------------


def test_tool_groups_cover_goal_sections() -> None:
    expected = {
        "navigate", "selection", "inspection", "edit_session", "capture",
        "geometry", "snapping", "layer", "symbology", "factor", "qa",
        "layout_export",
    }
    assert set(TOOL_GROUPS) == expected
    assert "repair_geometry" in TOOL_GROUPS["geometry"]


def test_every_map_action_controller_id_evaluated() -> None:
    """MapActionController 30 个动作 id 全部在 evaluator 覆盖内（无假按钮）。"""
    from paleo_workbench.ui.map_action_controller import MapActionController

    ids = set(MapActionController._TOOL_IDS) | {
        "full_extent", "previous_extent", "next_extent", "refresh",
        "clear_selection", "select_all", "invert_selection", "toggle_editing",
        "save_edits", "rollback", "delete_selected", "undo", "redo",
        "split", "merge", "snapping", "topology", "cancel",
    }
    ctx = _ctx()
    avail = availability_for_context(ctx)
    missing = ids - set(avail)
    assert not missing, f"evaluator 缺少动作: {missing}"


def test_all_group_members_evaluated() -> None:
    ctx = _ctx()
    avail = availability_for_context(ctx)
    declared = {tool for members in TOOL_GROUPS.values() for tool in members}
    assert declared == set(avail), declared ^ set(avail)


# ---------------------------------------------------------------------------
# UIContextSnapshot 适配（palette 单一来源）
# ---------------------------------------------------------------------------


class _Snap:
    """UIContextSnapshot 鸭子类型（避免 Qt 导入）。"""

    def __init__(self, **kw) -> None:
        self.project_open = kw.get("project_open", True)
        self.mapping_stage = kw.get("mapping_stage")
        self.active_layer_id = kw.get("active_layer_id")
        self.active_layer_role = kw.get("active_layer_role")
        self.active_layer_editable = kw.get("active_layer_editable")
        self.active_layer_block_reason = kw.get("active_layer_block_reason")
        self.active_layer_kind = kw.get("active_layer_kind")
        self.active_layer_maturity = kw.get("active_layer_maturity")
        self.active_layer_frozen = kw.get("active_layer_frozen", False)
        self.editing_active = kw.get("editing_active", False)
        self.editing_dirty = kw.get("editing_dirty")
        self.selection_count = kw.get("selection_count")
        self.can_undo = kw.get("can_undo")
        self.can_redo = kw.get("can_redo")
        self.capability_mode = kw.get("capability_mode")
        self.capability_reason = kw.get("capability_reason")
        self.write_granted = kw.get("write_granted", False)
        self.qgis_bridge_available = kw.get("qgis_bridge_available")


def test_tool_context_from_ui_snapshot_roundtrip() -> None:
    snap = _Snap(
        mapping_stage=MappingStage.CONSTRAINT_FACTOR.value,
        active_layer_id="composite:L1",
        active_layer_role=LayerRole.PROVENANCE_LINE.value,
        active_layer_editable=True,
        active_layer_kind="line",
        editing_active=True,
        qgis_bridge_available=False,
    )
    ctx = tool_context_from_ui_snapshot(snap)
    assert ctx.active_layer_kind == "line"
    assert ctx.layer_role == LayerRole.PROVENANCE_LINE.value
    assert ctx.editing is True
    assert ctx.backend_mode == "unavailable"


def test_tool_context_from_ui_snapshot_conservative_session_details() -> None:
    """快照缺席的会话运行细节按保守值进入 canonical ctx（V8 M6）。"""
    ctx = tool_context_from_ui_snapshot(_Snap())
    assert ctx.dirty is False
    assert ctx.selection_count == 0
    assert ctx.can_undo is False
    assert ctx.can_redo is False
    ctx2 = tool_context_from_ui_snapshot(_Snap(
        editing_dirty=True, selection_count=3, can_undo=True, can_redo=True,
    ))
    assert ctx2.dirty is True and ctx2.selection_count == 3
    assert ctx2.can_undo is True and ctx2.can_redo is True


def test_palette_reason_matches_toolbar_reason() -> None:
    """palette（经 UIContext 适配）与工具条（直连）对同一动作给同一原因。"""
    snap = _Snap(
        mapping_stage=MappingStage.FACIES_CALIBRATION.value,
        active_layer_id="composite:L1",
        active_layer_role=LayerRole.INITIAL_FACIES_DRAFT.value,
        active_layer_editable=True,
        active_layer_kind="polygon",
        editing_active=False,
    )
    palette_reason = evaluate_tool(
        "save_edits", tool_context_from_ui_snapshot(snap)
    ).reason
    toolbar_reason = evaluate_tool(
        "save_edits",
        _ctx(
            mapping_stage=MappingStage.FACIES_CALIBRATION.value,
            active_layer_id="composite:L1",
            layer_role=LayerRole.INITIAL_FACIES_DRAFT.value,
            active_layer_kind="polygon",
            editing=False,
        ),
    ).reason
    assert palette_reason == toolbar_reason != ""


# ---------------------------------------------------------------------------
# 呈现快照适配（LayerCapabilitySnapshot → canonical layer_facts）
# ---------------------------------------------------------------------------


def test_layer_capability_snapshot_flattens_into_layer_facts() -> None:
    """呈现快照经 layer_facts() 扁平化进入 canonical build_tool_context。"""
    snapshot = LayerCapabilitySnapshot(
        layer_id="composite:L1",
        name="物源线",
        role=LayerRole.PROVENANCE_LINE.value,
        role_label="物源线",
        kind="line",
        maturity="draft",
        editable=False,
        block_reason="RAW 图层不可变",
        frozen=True,
        missing=False,
        degraded=True,
    )
    ctx = build_tool_context(layer_facts=snapshot.layer_facts())
    assert ctx.active_layer_id == "composite:L1"
    assert ctx.layer_name == "物源线"
    assert ctx.layer_role == LayerRole.PROVENANCE_LINE.value
    assert ctx.layer_role_label == "物源线"
    assert ctx.active_layer_kind == "line"
    assert ctx.artifact_maturity == "draft"
    assert ctx.layer_frozen and ctx.layer_degraded and not ctx.layer_missing
    assert ctx.qgis_layer_type == "vector"


# ---------------------------------------------------------------------------
# 呈现细节
# ---------------------------------------------------------------------------


def test_layer_caption() -> None:
    assert LAYER_CAPTION("polygon") == "面"
    assert LAYER_CAPTION("line") == "线"
    assert LAYER_CAPTION("point") == "点"
    assert LAYER_CAPTION("") == "未知"


def test_tool_availability_defaults() -> None:
    avail = ToolAvailability(tool_id="pan", enabled=True)
    assert avail.visible and avail.reason == ""


def test_none_stage_is_free_surface_unknown_stage_fails_closed() -> None:
    """mapping_stage=None = 表面无阶段语义（legacy 编图页：不做阶段过滤）。

    未知阶段**值**仍 fail-closed（组降级到基础组，编辑动作隐藏）。
    """
    free = availability_for_context(_ctx(mapping_stage=None))
    assert free["add_polygon"].visible
    assert free["toggle_editing"].enabled
    assert free["factor_workbench"].enabled  # 无阶段语义不受白名单约束

    unknown = availability_for_context(_ctx(mapping_stage="not_a_stage"))
    groups = stage_group_visibility("not_a_stage")
    assert not groups["capture"]
    assert not unknown["add_polygon"].visible
    assert not unknown["add_polygon"].enabled
    assert unknown["add_polygon"].reason
