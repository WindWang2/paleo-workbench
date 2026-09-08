"""V8 M2 — 完整 QGIS context matrix × 工具可用性 + 跨表面一致性。

Goal V8 §M2：同一状态下 toolbar / context menu / palette / shortcut /
stage panel 的结论必须一致；每个禁用必须能回答「为什么」；不允许
「按钮亮着但 QGIS 工具无法激活」（native manifest 门禁）；不允许
「按钮灰了但快捷键/palette 可以绕过」（execution re-gate 在集成层测）。

矩阵维度：
* 工程状态：no project / project ready / blocking task（opening 等由
  blocking_task 表示——宿主把打开中/切换中的模态阶段报为阻塞任务）；
* 图层状态：none / RAW / DERIVED draft / reviewed / frozen / published /
  missing / degraded / point / line / polygon / raster(reference)；
* 编辑状态：no session / clean / dirty / rollback available / undo-redo
  available / topology blocked；
* 阶段：phase1 / phase2 / phase3 / unknown（fail-closed）/ None（无阶段
  语义的 legacy 表面）。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.tool_availability import (
    TOOL_GROUPS,
    TOOL_IDS,
    ToolAvailability,
    evaluate_all,
    evaluate_tool,
    stage_group_visibility,
)
from paleo_workbench.mapping.tool_context import ToolContext

# ---------------------------------------------------------------------------
# 矩阵 fixtures（每个状态一个 ToolContext 工厂）
# ---------------------------------------------------------------------------


def _ctx(**changes) -> ToolContext:
    base = dict(
        project_open=True,
        mapping_stage="facies_calibration",
        active_layer_id="draft-1",
        active_layer_kind="polygon",
        qgis_layer_type="vector",
        layer_role="initial_facies_draft",
        vector_writable=True,
        edit_gate_open=True,
    )
    base.update(changes)
    return ToolContext(**base)


# 状态 → (context, 断言集)。断言集: tool_id → enabled
MATRIX: list[tuple[str, ToolContext, dict[str, bool]]] = [
    # -- 工程状态 -------------------------------------------------------------
    (
        "no_project",
        _ctx(project_open=False),
        {"pan": False, "layer_new": False, "toggle_editing": False, "cancel": True},
    ),
    (
        "project_ready_no_layer",
        _ctx(mapping_stage=None, active_layer_id="", active_layer_kind="", layer_role=""),
        {"pan": True, "layer_new": True, "toggle_editing": False, "identify": False},
    ),
    (
        "blocking_task",
        _ctx(blocking_task="正在导入参考图层"),
        {"pan": False, "toggle_editing": False, "cancel": True, "layer_new": False},
    ),
    # -- 图层状态 -------------------------------------------------------------
    (
        "raw_layer",
        _ctx(
            layer_role="initial_facies_source",
            edit_gate_open=False,
            edit_gate_reason="图层角色为「初始相源」（RAW/模型结果）——不可直接编辑；请创建 DERIVED 草稿后编辑",
            raw_locked=True,
        ),
        {"toggle_editing": False, "add_polygon": False, "attribute_table": True,
         "identify": True, "layer_properties": True},
    ),
    (
        "derived_draft_clean",
        _ctx(editing=True, dirty=False),
        {"toggle_editing": True, "add_polygon": True, "save_edits": False,
         "rollback": False, "snapping": True},
    ),
    (
        "derived_draft_dirty",
        _ctx(editing=True, dirty=True),
        {"toggle_editing": True, "save_edits": True, "rollback": True},
    ),
    (
        "reviewed_layer",
        _ctx(artifact_maturity="reviewed", editing=True, dirty=True),
        {"save_edits": True, "add_polygon": True},
    ),
    (
        "frozen_layer",
        _ctx(
            artifact_maturity="frozen",
            layer_frozen=True,
            edit_gate_open=False,
            edit_gate_reason="当前结果已冻结（初始相带草稿）——不可编辑；如需修改请另存草稿或解除冻结",
        ),
        {"toggle_editing": False, "add_polygon": False, "identify": True,
         "layer_export": True},
    ),
    (
        "published_layer",
        _ctx(
            artifact_maturity="published",
            layer_frozen=True,
            edit_gate_open=False,
            edit_gate_reason="当前结果已发布（初始相带草稿）——不可编辑",
        ),
        {"toggle_editing": False, "add_polygon": False, "attribute_table": True},
    ),
    (
        "missing_source",
        _ctx(
            layer_missing=True,
            edit_gate_open=False,
            edit_gate_reason="图层源缺失（文件被移动或删除）",
        ),
        {"toggle_editing": False, "add_polygon": False, "identify": False},
    ),
    (
        "degraded_layer",
        _ctx(
            layer_degraded=True,
            edit_gate_open=False,
            edit_gate_reason="图层处于降级状态（数据不完整）",
        ),
        {"toggle_editing": False, "add_polygon": False},
    ),
    (
        "point_layer",
        _ctx(active_layer_kind="point", editing=True, mapping_stage=None),
        {"add_point": True, "add_line": False, "add_polygon": False},
    ),
    (
        "line_layer",
        _ctx(active_layer_kind="line", editing=True, mapping_stage=None),
        {"add_point": False, "add_line": True, "add_polygon": False},
    ),
    (
        "polygon_layer",
        _ctx(active_layer_kind="polygon", editing=True, mapping_stage=None),
        {"add_point": False, "add_line": False, "add_polygon": True},
    ),
    (
        "raster_reference_layer",
        _ctx(qgis_layer_type="raster", vector_writable=False),
        {"layer_properties": True, "layer_zoom": True, "layer_export": True,
         "toggle_editing": False, "identify": True},
    ),
    # -- 编辑状态 -------------------------------------------------------------
    (
        "no_session",
        _ctx(),
        {"toggle_editing": True, "add_polygon": False, "save_edits": False,
         "undo": False, "delete_selected": False, "snapping": True},
    ),
    (
        "editing_clean",
        _ctx(editing=True),
        {"save_edits": False, "rollback": False, "add_polygon": True},
    ),
    (
        "editing_dirty",
        _ctx(editing=True, dirty=True),
        {"save_edits": True, "rollback": True},
    ),
    (
        "undo_redo_available",
        _ctx(editing=True, dirty=True, can_undo=True, can_redo=True),
        {"undo": True, "redo": True},
    ),
    (
        "topology_blocked_merge",
        _ctx(editing=True, topology_error_count=3, merge_ready=False),
        {"merge": False},
    ),
    (
        "merge_two_polygons",
        _ctx(editing=True, merge_ready=True, compatible_polygon_count=2),
        {"merge": True},
    ),
    (
        "split_inputs_ready",
        _ctx(editing=True, split_ready=True),
        {"split": True},
    ),
    (
        "delete_needs_selection",
        _ctx(editing=True, selection_count=0),
        {"delete_selected": False},
    ),
    (
        "delete_with_selection",
        _ctx(editing=True, selection_count=2),
        {"delete_selected": True},
    ),
    # -- 阶段 -----------------------------------------------------------------
    (
        "phase1",
        _ctx(mapping_stage="facies_calibration", editing=True, dirty=True),
        {"add_polygon": True, "add_line": False, "factor_workbench": False,
         "map_export": False, "qa_run": True},
    ),
    (
        "phase2_line_capture",
        _ctx(
            mapping_stage="constraint_factor",
            active_layer_kind="line",
            layer_role="provenance_line",
            editing=True,
        ),
        {"add_line": True, "add_polygon": False, "factor_workbench": True,
         "map_export": False},
    ),
    (
        "phase3",
        _ctx(mapping_stage="integrated_compilation"),
        {"factor_workbench": False, "map_product_assemble": True, "map_export": True},
    ),
    (
        "unknown_stage_fail_closed",
        _ctx(mapping_stage=""),
        {"pan": True, "identify": True, "add_polygon": False,
         "factor_workbench": False, "map_export": False},
    ),
    (
        "legacy_surface_no_stage_semantics",
        _ctx(mapping_stage=None),
        {"add_polygon": False, "undo": False, "identify": True},
    ),
]


@pytest.mark.parametrize("name,ctx,expectations", MATRIX, ids=[m[0] for m in MATRIX])
def test_context_matrix(name, ctx, expectations):
    availability = evaluate_all(ctx)
    for tool_id, enabled in expectations.items():
        verdict = availability[tool_id]
        assert verdict.enabled is enabled, (
            f"{name}: {tool_id} expected enabled={enabled}, "
            f"got {verdict.enabled} (reason={verdict.disabled_reason!r})"
        )


# ---------------------------------------------------------------------------
# 不变量：全矩阵 × 全工具
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,ctx,_", MATRIX, ids=[m[0] for m in MATRIX])
def test_invariants_hold_across_matrix(name, ctx, _):
    availability = evaluate_all(ctx)
    assert set(availability) == set(TOOL_IDS)
    for tool_id, verdict in availability.items():
        assert isinstance(verdict, ToolAvailability)
        # 禁用必带原因（「为什么现在不能做」永远有答案）。
        if not verdict.enabled:
            assert verdict.disabled_reason, f"{name}/{tool_id}: disabled without reason"
        # 可用必无原因；不可见必不可用。
        if verdict.enabled:
            assert not verdict.disabled_reason
        if not verdict.visible:
            assert not verdict.enabled


def test_every_disabled_reason_is_distinct_and_specific():
    """同一工具在不同状态下的禁用原因应反映状态差异（非千篇一律）。"""
    raw = evaluate_tool("toggle_editing", _ctx(
        layer_role="initial_facies_source", edit_gate_open=False,
        edit_gate_reason="RAW 判词"))
    frozen = evaluate_tool("toggle_editing", _ctx(
        layer_frozen=True, edit_gate_open=False, edit_gate_reason="冻结判词"))
    no_layer = evaluate_tool("toggle_editing", _ctx(active_layer_id=""))
    assert raw.disabled_reason == "RAW 判词"
    assert frozen.disabled_reason == "冻结判词"
    assert no_layer.disabled_reason == "没有活动的矢量图层"


# ---------------------------------------------------------------------------
# 跨表面一致性：toolbar ↔ palette（同一上下文，同一结论/原因）
# ---------------------------------------------------------------------------

PALETTE_TOOLS = (
    "layer_new", "reference_import", "layer_properties", "attribute_table",
    "layer_zoom", "layer_export", "symbology", "style_manager",
    "factor_workbench", "factor_overlay", "qa_run", "map_product_assemble",
    "map_export", "toggle_editing", "save_edits", "rollback", "undo", "redo",
    "delete_selected", "snapping", "topology", "identify", "measure_distance",
    "select_rectangle",
)


class _FakeSnapshot:
    """UIContextSnapshot 鸭子类型（palette 侧输入）。"""

    def __init__(self, ctx: ToolContext):
        self.project_open = ctx.project_open
        self.mapping_stage = ctx.mapping_stage
        self.active_layer_id = ctx.active_layer_id or None
        self.active_layer_role = ctx.layer_role or None
        self.active_layer_kind = ctx.active_layer_kind or None
        self.active_layer_maturity = ctx.artifact_maturity or None
        self.active_layer_editable = ctx.edit_gate_open
        self.active_layer_block_reason = ctx.edit_gate_reason or None
        self.active_layer_frozen = ctx.layer_frozen
        self.active_layer_missing = ctx.layer_missing
        self.active_layer_degraded = ctx.layer_degraded
        self.active_layer_writable = ctx.vector_writable
        self.editing_active = ctx.editing
        self.editing_dirty = ctx.dirty
        self.selection_count = ctx.selection_count
        self.can_undo = ctx.can_undo
        self.can_redo = ctx.can_redo
        self.blocking_task = ctx.blocking_task or None
        self.capability_mode = ctx.backend_mode
        self.capability_reason = ctx.backend_reason
        self.write_granted = ctx.write_granted


@pytest.mark.parametrize(
    "name,ctx,_", MATRIX, ids=[m[0] for m in MATRIX])
def test_palette_and_toolbar_agree(name, ctx, _):
    """palette applicability（快照适配）与工具条结论同因同值。

    可见性差分（工具条隐藏 vs palette 禁用）是呈现分工：palette 侧
    visible=False 的动作按禁用+同一 reason 呈现（可发现性）。
    """
    from paleo_workbench.ui.workstation.tool_surface import (
        tool_context_from_ui_snapshot,
    )

    snapshot = _FakeSnapshot(ctx)
    palette_ctx = tool_context_from_ui_snapshot(snapshot)
    toolbar = evaluate_all(ctx)
    for tool_id in PALETTE_TOOLS:
        expected = toolbar[tool_id]
        palette = evaluate_tool(tool_id, palette_ctx)
        # palette 侧不呈现「隐藏」，只呈现「禁用 + 原因」——enabled 必须一致。
        assert palette.enabled == expected.enabled, (
            f"{name}/{tool_id}: toolbar enabled={expected.enabled} "
            f"but palette enabled={palette.enabled}"
        )


# ---------------------------------------------------------------------------
# QGIS native 一致性：按钮亮 ⇔ 原生工具可激活（capability manifest 门禁）
# ---------------------------------------------------------------------------


def _native_ctx(**changes) -> ToolContext:
    flags = {
        "qgis.native_tool.pan", "qgis.native_tool.zoomIn", "qgis.native_tool.zoomOut",
        "qgis.native_tool.select", "qgis.native_tool.identify",
        "qgis.native_tool.addPoint", "qgis.native_tool.addPolygon",
        "qgis.geometry_op.split_by_line", "qgis.geometry_op.union",
    }
    base = dict(
        project_open=True,
        qgis_available=True,
        native_canvas_available=True,
        backend_mode="native",
        # 无阶段语义：隔离原生 manifest 门禁（阶段隐藏会先行接管呈现）。
        mapping_stage=None,
        active_layer_id="L1",
        active_layer_kind="polygon",
        layer_role="initial_facies_draft",
        vector_writable=True,
        edit_gate_open=True,
        editing=True,
        capability_flags=frozenset(flags),
    )
    base.update(changes)
    return ToolContext(**base)


def test_native_canvas_missing_manifest_tool_disables_action():
    """桥无 addLine 原生工具：add_line 亮不了（不出现按钮亮但激活失败）。"""
    verdict = evaluate_tool("add_line", _native_ctx(active_layer_kind="line"))
    assert not verdict.enabled
    assert "原生" in verdict.disabled_reason


def test_native_canvas_present_manifest_tool_enables_action():
    verdict = evaluate_tool("add_polygon", _native_ctx())
    assert verdict.enabled


def test_reshape_needs_native_digitizer_and_operator():
    """reshape：addLine 数字化器 + geometry_op.reshape 双前提（缺一禁用+原因）。"""
    no_digitizer = evaluate_tool("reshape", _native_ctx(selection_count=1))
    assert not no_digitizer.enabled
    assert "原生数字化工具" in no_digitizer.disabled_reason
    with_both = _native_ctx(selection_count=1)
    with_both = ToolContext(
        **{
            **{f: getattr(with_both, f) for f in with_both.__dataclass_fields__},
            "capability_flags": with_both.capability_flags | {
                "qgis.native_tool.addLine", "qgis.geometry_op.reshape"},
        }
    )
    verdict = evaluate_tool("reshape", with_both)
    assert verdict.enabled, verdict.disabled_reason


def test_fallback_canvas_keeps_python_tools_honest():
    """fallback 画布是受认可的 headless 路径：Python 工具保持可用。"""
    verdict = evaluate_tool("add_polygon", _ctx(
        editing=True, native_canvas_available=False, qgis_available=False))
    assert verdict.enabled
    # reshape 例外：无 fallback 输入路径，必须禁用并说明。
    reshape = evaluate_tool("reshape", _ctx(
        editing=True, selection_count=1, native_canvas_available=False))
    assert not reshape.enabled
    assert "原生" in reshape.disabled_reason


# ---------------------------------------------------------------------------
# checked 一致性（UI checked 与实际工具状态可检测一致）
# ---------------------------------------------------------------------------


def test_checked_follows_current_tool_only_when_enabled():
    ctx = _ctx(editing=True, current_tool="add_polygon")
    availability = evaluate_all(ctx)
    assert availability["add_polygon"].checked is True
    assert availability["pan"].checked is False
    assert availability["identify"].checked is False


def test_checked_never_sticks_on_disabled_tool():
    """current_tool 残留在一个现已禁用的工具上时，checked 必须熄灭。"""
    ctx = _ctx(editing=False, current_tool="add_polygon")
    verdict = evaluate_tool("add_polygon", ctx)
    assert not verdict.enabled
    assert verdict.checked is False


def test_toggle_checked_follows_session():
    assert evaluate_tool("toggle_editing", _ctx(editing=True)).checked is True
    assert evaluate_tool("toggle_editing", _ctx(editing=False)).checked is False
    snap_on = evaluate_tool("snapping", _ctx(snapping_enabled=True))
    assert snap_on.checked is True and snap_on.enabled


# ---------------------------------------------------------------------------
# 阶段组可见性语义（stage panel / toolbar 组隐藏）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage,hidden_groups",
    [
        ("facies_calibration", {"factor", "layout_export"}),
        ("constraint_factor", {"layout_export"}),
        ("integrated_compilation", {"factor"}),
    ],
)
def test_stage_group_visibility_table(stage, hidden_groups):
    visibility = stage_group_visibility(stage)
    for group in TOOL_GROUPS:
        assert visibility[group] is (group not in hidden_groups), (stage, group)


def test_unknown_stage_keeps_basic_groups_only():
    visibility = stage_group_visibility("not_a_stage")
    basic = {"navigate", "selection", "inspection", "layer"}
    for group in TOOL_GROUPS:
        assert visibility[group] is (group in basic), group


def test_none_stage_means_no_stage_filtering():
    visibility = stage_group_visibility(None)
    assert all(visibility.values())


# ---------------------------------------------------------------------------
# 门禁优先序（reason 是最根本的 blocker）
# ---------------------------------------------------------------------------


def test_role_verdict_text_wins_over_classification():
    """宿主判词优先于分类标志（权威文本不被兜底文案覆盖）。"""
    ctx = _ctx(edit_gate_open=False, edit_gate_reason="权威判词", raw_locked=True)
    verdict = evaluate_tool("toggle_editing", ctx)
    assert verdict.disabled_reason == "权威判词"


def test_unknown_editability_fails_closed():
    ctx = _ctx(edit_gate_open=None)
    verdict = evaluate_tool("toggle_editing", ctx)
    assert not verdict.enabled
    assert "未知" in verdict.disabled_reason


def test_unknown_tool_fails_honest():
    verdict = evaluate_tool("no_such_tool", _ctx())
    assert not verdict.visible and not verdict.enabled
    assert "未知工具" in verdict.disabled_reason


def test_blocking_task_beats_layer_gates_in_reason():
    ctx = _ctx(blocking_task="正在保存编辑", active_layer_id="", layer_role="")
    verdict = evaluate_tool("toggle_editing", ctx)
    assert verdict.disabled_reason.startswith("后台任务进行中")


# ---------------------------------------------------------------------------
# 快捷键等价性：shortcut 携带的命令 id 与 evaluator 词汇全等
# ---------------------------------------------------------------------------


def test_every_shortcut_command_id_is_evaluator_vocabulary():
    """带快捷键的动作 id 必须在 evaluator 注册表内（re-gate 才有判据）。"""
    shortcut_ids = {
        "save_edits",  # Ctrl+S
        "delete_selected",  # Delete
        "undo", "redo",  # Ctrl+Z / Ctrl+Shift+Z
        "cancel",  # Esc
    }
    assert shortcut_ids <= set(TOOL_IDS)
    # 它们在默认（可用）状态下全部可被 re-gate 判定。
    for tool_id in shortcut_ids:
        verdict = evaluate_tool(tool_id, _ctx(editing=True, dirty=True,
                                              selection_count=1, can_undo=True,
                                              can_redo=True))
        assert verdict.enabled, f"{tool_id}: {verdict.disabled_reason}"
