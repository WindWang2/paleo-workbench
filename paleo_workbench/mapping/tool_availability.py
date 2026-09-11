"""ToolAvailability — THE canonical tool state machine (V8, Goal M1).

Single business authority for every command surface (toolbar / overflow /
context menu / palette / shortcuts / stage panel / status bar / inspector /
agent surface). Pure functions over :class:`ToolContext`; no Qt, no bridge
import, no I/O. Every disable carries a human-readable reason — never a bare
``setEnabled(False)``.

This module merges the two V7 evaluators into one contract:

* the authoring-kernel semantics (checked/preferred/conflicts, per-tool native
  manifest gates, blocking-task gate, dirty/undo/selection facts) and
* the workstation surface semantics (professional tool groups, stage group
  visibility, stage action whitelists, layer role/kind/maturity gates with
  honest reasons).

``ui/workstation/tool_surface.py`` is now a presentation adapter over this
module (re-exports + UIContextSnapshot adaptation) — it must never grow a
second gate rule.

Gate order (coarse → fine; the first blocker wins and its reason is the
answer to "为什么现在不能做")::

    unknown tool → blocking task (except cancel) → project (except cancel)
    → native-only capability → layer existence/missing/degraded
    → role gate (host verdict text wins) → stage (group hide → action
    whitelist → governed edit actions) → editing session
    → capture kind/role → native manifest → selection/input facts
    → extent history / selection commands

Interpretation notes carried over from the V7 decisions
(docs/development/qgis-native-authoring-v7/03-decisions.md):

* On the native canvas a *native* tool must exist in the capability manifest;
  on the fallback canvas the Python tool stays available (the fallback is the
  sanctioned headless path and does not gain features the native path lacks).
* ``split``/``merge`` are commands, not canvas interactions: they stay
  available on the fallback canvas (shapely execution, degraded engine choice
  recorded in the EditDelta); ``reshape`` is native-only.
* snapping/topology toggles need only an active layer (QGIS-desktop aligned,
  D4-5) — decoupled from the editing session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import stage_from_value

__all__ = [
    "LAYER_CAPTION",
    "TOOL_GROUPS",
    "TOOL_IDS",
    "ToolAvailability",
    "evaluate_all",
    "evaluate_tool",
    "stage_group_visibility",
    "stage_whitelist_reason",
]

Point = tuple[float, float]

@dataclass(frozen=True, slots=True)
class ToolAvailability:
    """一个工具在给定上下文下的业务结论（唯一契约）。

    ``disabled_reason`` 是权威判词（呈现层原样透传，不得改写或自拟）；
    ``reason`` 是 V7 workstation 侧的兼容别名（同值）。``visible=False``
    是阶段/图层组的呈现语义（工具条隐藏），palette 对同一动作选择
    disabled+同一 reason（可发现性）。
    """

    tool_id: str
    visible: bool = True
    enabled: bool = False
    checked: bool = False
    disabled_reason: str = ""
    preferred: bool = False
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.enabled and self.disabled_reason:
            raise ValueError("an enabled tool must not carry a disabled_reason")
        if not self.visible and self.enabled:
            raise ValueError("an invisible tool cannot be enabled")

    @property
    def reason(self) -> str:
        """Compat alias for :attr:`disabled_reason` (V7 workstation readers)."""
        return self.disabled_reason

    def to_dict(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id,
            "visible": self.visible,
            "enabled": self.enabled,
            "checked": self.checked,
            "disabled_reason": self.disabled_reason,
            "preferred": self.preferred,
            "conflicts": list(self.conflicts),
        }

def _ok(tool_id: str, *, visible: bool = True, preferred: bool = False) -> ToolAvailability:
    return ToolAvailability(tool_id=tool_id, visible=visible, enabled=True, preferred=preferred)

def _no(tool_id: str, reason: str, *, visible: bool = True) -> ToolAvailability:
    return ToolAvailability(tool_id=tool_id, visible=visible, enabled=False, disabled_reason=reason)

# ---------------------------------------------------------------------------
# Tool group IA — the tool id namespace. Group visibility is availability
# semantics (stage/layer driven), which is why it lives in the canonical
# module rather than in any UI layer.
# ---------------------------------------------------------------------------

TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "navigate": (
        "pan", "zoom_in", "zoom_out", "full_extent", "previous_extent",
        "next_extent", "refresh",
    ),
    "selection": (
        "select", "select_rectangle", "select_all", "invert_selection",
        "clear_selection",
    ),
    "inspection": ("identify", "measure_distance"),
    "edit_session": ("toggle_editing", "save_edits", "rollback"),
    "capture": ("add_point", "add_line", "add_polygon"),
    "geometry": (
        "move_feature", "vertex", "reshape", "undo", "redo", "delete_selected",
        "split", "merge", "repair_geometry",
        # V10：复杂几何/要素命令族（duplicate / 环 / 部件 / 单多部件转换）。
        "duplicate_selected", "add_ring", "add_part", "explode_multipart",
        "collect_multipart",
    ),
    "snapping": ("snapping", "topology", "cancel"),
    "layer": (
        "layer_new", "reference_import", "layer_properties",
        "attribute_table", "layer_zoom", "layer_export",
    ),
    "symbology": ("symbology", "style_manager"),
    "factor": ("factor_workbench", "factor_overlay"),
    "qa": ("qa_run", "map_product_assemble"),
    "layout_export": ("map_export",),
}

TOOL_IDS: tuple[str, ...] = tuple(
    tool for members in TOOL_GROUPS.values() for tool in members
)

_GROUP_OF: dict[str, str] = {
    tool: group for group, members in TOOL_GROUPS.items() for tool in members
}

_KIND_LABELS = {"point": "点", "line": "线", "polygon": "面"}

def LAYER_CAPTION(kind: str | None) -> str:  # noqa: N802 — 呈现词汇函数
    """几何类型的中文呈现（未知 = 「未知」，不猜）。"""
    return _KIND_LABELS.get(str(kind or ""), "未知")

#: 线角色（Add Line 为主捕获工具的角色集）
_LINE_ROLES = frozenset({
    LayerRole.PROVENANCE_LINE.value,
    LayerRole.PROVENANCE_DIRECTION.value,
    LayerRole.DISTRIBUTION_LINE.value,
    LayerRole.PALEO_SHORELINE.value,
    LayerRole.FACIES_BOUNDARY.value,
    LayerRole.FAULT_CONSTRAINT.value,
})
#: 面角色（插值边界/掩膜：Add Polygon 可用，线捕获按角色禁用）
_POLYGON_ROLES = frozenset({
    LayerRole.INTERPOLATION_BOUNDARY.value,
    LayerRole.MASK_BOUNDARY.value,
})

#: 需要 QGIS 原生后端的工具（桥缺失/降级时禁用 + 原因；不隐藏能力假象）
_NATIVE_ONLY_TOOLS = frozenset({"style_manager", "reshape", "add_ring", "add_part"})

#: 需要活动图层（矢量或任意）的工具
_NEEDS_ANY_LAYER = frozenset({
    "identify", "select", "select_rectangle", "measure_distance",
    "clear_selection", "select_all", "invert_selection",
    "layer_properties", "layer_zoom", "layer_export", "symbology",
})
# attribute_table 是只读查看（QGIS 语义）——只要求图层存在，不要求
# 可编辑（RAW 层连查看都被禁是假限制）。
_NEEDS_EDITABLE_LAYER = frozenset({"toggle_editing"})

#: 需要已开启编辑会话的工具（会话内进一步受选择/撤销栈约束）。
#: snapping/topology 只需活动图层（D4-5），不在本集合。
_NEEDS_EDITING = frozenset({
    "save_edits", "rollback", "add_point", "add_line", "add_polygon",
    "move_feature", "vertex", "reshape", "undo", "redo", "delete_selected",
    "split", "merge", "repair_geometry",
    "duplicate_selected", "add_ring", "add_part", "explode_multipart",
    "collect_multipart",
})

#: 需要活动图层的组（无活动图层时整组隐藏，layer_new/reference_import 除外）
_NEEDS_LAYER_GROUPS = frozenset({"layer", "symbology"})

#: 受「图层缺失/降级」事实门禁的工具（源缺失/数据不完整时以宿主判词
#: 或默认文案禁用，不给假可用）。
_LAYER_FACT_GATED = _NEEDS_ANY_LAYER | _NEEDS_EDITABLE_LAYER | _NEEDS_EDITING

#: 阶段专属组（其余组全阶段可见）
_STAGE_GROUP_VISIBILITY: dict[str, dict[str, bool]] = {
    "facies_calibration": {"factor": False, "layout_export": False},
    "constraint_factor": {"factor": True, "layout_export": False},
    "integrated_compilation": {"factor": False, "layout_export": True},
}

#: 非编辑动作的阶段白名单
_STAGE_ACTION_WHITELIST: dict[str, frozenset[str]] = {
    "factor_workbench": frozenset({"constraint_factor"}),
    "factor_overlay": frozenset({"constraint_factor"}),
    "map_product_assemble": frozenset({"integrated_compilation"}),
    "map_export": frozenset({"integrated_compilation"}),
}

#: 未知阶段值时保留的基础组（fail-closed）
_BASIC_GROUPS = frozenset({"navigate", "selection", "inspection", "layer"})

#: 画布交互工具（checked 跟随 current_tool）
_CHECKED_CANVAS_TOOLS = frozenset({
    "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
    "measure_distance", "add_point", "add_line", "add_polygon",
    "move_feature", "vertex", "reshape",
})

# ---------------------------------------------------------------------------
# Shared gating helpers. Each returns either None (gate passed) or a reason.
# ---------------------------------------------------------------------------

def _project_gate(ctx: ToolContext) -> str | None:
    if not ctx.project_open:
        return "未打开工程"
    return None

def _blocking_gate(ctx: ToolContext) -> str | None:
    if ctx.blocking_task:
        return f"后台任务进行中：{ctx.blocking_task}"
    return None

def _layer_gate(ctx: ToolContext) -> str | None:
    if not ctx.has_active_layer:
        return "没有活动的矢量图层"
    return None


def _queryable_gate(ctx: ToolContext) -> str | None:
    """identify 门禁：工程已打开且存在可查询图层（不过问活动层）。"""
    if ctx.queryable_layer_count <= 0:
        return "没有可查询的图层"
    return None


def _vector_layer_gate(ctx: ToolContext) -> str | None:
    if not ctx.has_active_vector_layer:
        return "没有活动的矢量图层"
    return None

def _writable_gate(ctx: ToolContext) -> str | None:
    if not ctx.vector_writable:
        return "图层不可写"
    return None

def _role_gate(ctx: ToolContext) -> str | None:
    # 拒绝判定的优先序：宿主门禁的具体判词（RAW/冻结/组锁语义的权威文本，
    # 最具体）→ 事实分类文案（frozen/raw_locked/stage_locked）→ 未知 → 兜底。
    if ctx.edit_gate_open is False:
        if ctx.edit_gate_reason:
            return ctx.edit_gate_reason
        if ctx.layer_frozen:
            return "当前结果已冻结——需先解除冻结或另存草稿"
        if ctx.raw_locked:
            return "RAW 图层不可变，请创建 DERIVED 草稿后编辑"
        if ctx.stage_locked:
            return "当前阶段的证据组已锁定，禁止编辑"
        return "图层被编辑门禁锁定"
    if ctx.edit_gate_open is None:
        return "当前图层可编辑性未知"
    return None

def _editing_gate(ctx: ToolContext) -> str | None:
    if not ctx.editing:
        return "需要先开始编辑"
    return None

def _native_tool_gate(ctx: ToolContext, kind: str, native_name: str) -> str | None:
    """Native-canvas-only requirement; the fallback canvas runs the Python tool."""
    if ctx.native_canvas_available and kind not in {
        flag.removeprefix("qgis.native_tool.") for flag in ctx.capability_flags
    }:
        return f"原生 {native_name} 工具在当前桥版本不可用（重建 qgis_render_bridge）"
    return None

def _backend_gate(ctx: ToolContext) -> str | None:
    """Runtime-backend gate for native-only surface tools (style_manager)."""
    mode = ctx.backend_mode
    if mode == "native":
        return None
    if mode == "degraded":
        return f"QGIS 原生后端降级（{ctx.backend_reason or '同步异常'}）——该功能暂不可用"
    reason = ctx.backend_reason or ("能力未知" if mode == "unknown" else "桥不可用")
    return f"需要 QGIS 原生编辑后端（{reason}）"

_KIND_REQUIRED = {"add_point": "point", "add_line": "line", "add_polygon": "polygon"}

def _kind_gate(ctx: ToolContext, tool_id: str) -> str | None:
    expected = _KIND_REQUIRED[tool_id]
    kind = ctx.active_layer_kind
    if not kind:
        # fail-closed：未知几何类型不放开捕获工具（空图层/快照未就绪时
        # 启用三支捕获工具是假可用）。
        return "活动图层几何类型未知——不能确定可用的捕获工具"
    if kind != expected:
        return (
            f"仅对{LAYER_CAPTION(expected)}图层有效"
            f"（活动图层为{LAYER_CAPTION(kind)}图层，不能使用添加{LAYER_CAPTION(expected)}）"
        )
    # 角色与几何相符时的「抢主位」防护（线角色面层用添加线）。
    if expected == "polygon" and ctx.layer_role in _LINE_ROLES:
        return f"当前编辑目标为线要素角色（{ctx.layer_role_label or '线约束'}），应使用添加线"
    if expected == "line" and ctx.layer_role in _POLYGON_ROLES:
        return f"当前编辑目标为面要素角色（{ctx.layer_role_label or '边界/掩膜'}），应使用添加面"
    return None

# ---------------------------------------------------------------------------
# Stage gating — derived here from the domain StageToolProfile (single
# derivation; the host never pre-computes hidden sets).
# ---------------------------------------------------------------------------

def _stage_label(value: str | None) -> str:
    stage = stage_from_value(value or "")
    return stage.label if stage is not None else str(value or "阶段未知")

def _stage_group_visibility_for(ctx: ToolContext) -> dict[str, bool] | None:
    """组可见性映射；None = 表面无阶段语义，不做组过滤。"""
    if ctx.mapping_stage is None:
        return None
    if stage_from_value(ctx.mapping_stage) is None:
        # 未知阶段值：fail-closed，仅基础组。
        return {group: group in _BASIC_GROUPS for group in TOOL_GROUPS}
    overrides = _STAGE_GROUP_VISIBILITY.get(ctx.mapping_stage, {})
    return {group: overrides.get(group, True) for group in TOOL_GROUPS}

def stage_group_visibility(stage_value: str | None) -> dict[str, bool]:
    """该阶段的组可见性（全组条目；None = 无阶段语义全可见）。

    注：``cancel`` 豁免阶段隐藏（evaluate_tool 内 _stage_group_gate 的
    全局逃生口语义），因此 snapping 组在未知阶段显示为 False 时 cancel
    仍可见——组级映射描述组呈现，不覆盖该逐工具豁免（V10 review 记录）。
    """
    if stage_value is None:
        return {group: True for group in TOOL_GROUPS}
    if stage_from_value(stage_value) is None:
        return {group: group in _BASIC_GROUPS for group in TOOL_GROUPS}
    overrides = _STAGE_GROUP_VISIBILITY.get(stage_value, {})
    return {group: overrides.get(group, True) for group in TOOL_GROUPS}

def _stage_group_gate(ctx: ToolContext, tool_id: str) -> str | None:
    """组隐藏（hidden）判据；返回 None 表示该门放行。调用方负责区分 hidden。

    ``cancel`` 豁免：取消是全局逃生口（Esc 语义），任何阶段裁决（含
    fail-closed 的未知阶段）都不得把它藏掉——否则未知阶段下 Esc/取消
    按钮全部失效（V10 状态矩阵发现的 P1）。
    """
    if tool_id == "cancel":
        return None
    if ctx.mapping_stage is None:
        return None
    visibility = _stage_group_visibility_for(ctx)
    if visibility is None:
        return None
    group = _GROUP_OF.get(tool_id, "")
    if not visibility.get(group, True):
        if stage_from_value(ctx.mapping_stage) is None:
            return "当前编图阶段未知——仅保留基础工具组"
        return f"当前阶段不提供该工具组（{_stage_label(ctx.mapping_stage)}）"
    return None

def _stage_whitelist_gate(ctx: ToolContext, tool_id: str) -> str | None:
    whitelist = _STAGE_ACTION_WHITELIST.get(tool_id)
    if whitelist is None or ctx.mapping_stage is None:
        return None
    if ctx.mapping_stage not in whitelist:
        return stage_whitelist_reason(whitelist)
    return None


def stage_whitelist_reason(stage_values) -> str:
    """阶段白名单禁用判词（V10 M10：单一措辞真源）。

    palette 的 ``CommandSpec.stages`` 白名单与 evaluator 的
    ``_STAGE_ACTION_WHITELIST`` 对同一语义此前有两套文案（「当前编图
    阶段不可用（限 …）」vs「当前阶段不允许该操作（限 …）」）——本函数
    是唯一措辞，两侧共用（reason 字符串不改写原则的措辞面）。
    """
    return f"当前阶段不允许该操作（限 {'/'.join(_stage_label(v) for v in stage_values)}）"

def _edit_action_stage_gate(ctx: ToolContext, tool_id: str) -> str | None:
    """编辑/数字化动作的阶段过滤（真源 StageToolProfile.edit_actions）。

    受治理全集外的动作不受阶段限制；阶段外动作在工具条隐藏、palette 禁用
    （同一 reason，呈现分工由表面决定）。``mapping_stage=None``（表面无阶段
    语义）不过滤；未知阶段值 fail-closed。
    """
    from paleo_workbench.mapping_workspace.stage_profiles import (
        governed_edit_actions,
        stage_profile,
    )

    if tool_id not in governed_edit_actions():
        return None
    if ctx.mapping_stage is None:
        return None
    stage = stage_from_value(ctx.mapping_stage) if ctx.mapping_stage else None
    if stage is None:
        return "当前编图阶段未知"
    if not stage_profile(stage).tools.allows_edit_action(tool_id):
        return f"当前阶段不允许此编辑动作（限 {_stage_label(stage.value)}）"
    return None

# ---------------------------------------------------------------------------
# Rules — one per tool id. Gate order inside each rule is deliberate:
# coarse → fine so the reason shown is the most fundamental blocker.
# ---------------------------------------------------------------------------

Rule = Callable[[ToolContext], ToolAvailability]

def _rule_navigation(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _project_gate(ctx)
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_extent_history(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _project_gate(ctx)
    if reason is None and tool_id == "previous_extent" and not ctx.can_previous_extent:
        reason = "没有上一视图"
    if reason is None and tool_id == "next_extent" and not ctx.can_next_extent:
        reason = "没有下一视图"
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_inspection(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    # identify 对任意可查询图层合法（栅格/基础/引用皆可识别，不问活动层）；
    # select* 只对矢量活动层；measure 仍要活动层。
    if tool_id == "identify":
        reason = _project_gate(ctx) or _queryable_gate(ctx)
    else:
        reason = _project_gate(ctx) or (
            _vector_layer_gate(ctx) if tool_id in {"select", "select_rectangle"}
            else _layer_gate(ctx)
        )
    if reason is None and tool_id == "identify":
        reason = _native_tool_gate(ctx, "identify", "识别")
    if reason is None and tool_id in {"select", "select_rectangle"}:
        reason = _native_tool_gate(ctx, "select", "选择")
    # measure：原生画布上 PwbMeasureTool 与视口路由 fallback 双执行体
    # （shim 按 capability manifest 运行期选择），evaluator 不做能力门。
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_selection_commands(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _project_gate(ctx) or _vector_layer_gate(ctx)
    if reason is None and tool_id != "select_all" and ctx.selection_count <= 0:
        reason = "没有选中的要素"
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_toggle_editing(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _writable_gate(ctx)

    )
    return (
        _ok("toggle_editing", preferred=ctx.editing)
        if reason is None
        else _no("toggle_editing", reason)
    )

def _rule_save_edits(ctx: ToolContext) -> ToolAvailability:
    # 门序遵循总则（project → layer → editing）：无工程/无图层是更根本的
    # 结构性前提，判词必须先于会话状态（V8 M1 契约）。
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and not ctx.dirty:
        reason = "编辑会话没有未保存的修改"
    if reason is None and ctx.edit_gate_open is not True:
        reason = ctx.edit_gate_reason or (
            "当前图层可编辑性未知" if ctx.edit_gate_open is None
            else "图层被编辑门禁锁定")
    # 拓扑/科学阻断在保存时校验并回报（校验代价高，不进状态机）；
    # 状态机只保证结构性前提。
    return _ok("save_edits") if reason is None else _no("save_edits", reason)

def _rule_rollback(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and not ctx.dirty:
        reason = "编辑会话没有可回滚的修改"
    return _ok("rollback") if reason is None else _no("rollback", reason)

def _rule_cancel(ctx: ToolContext) -> ToolAvailability:
    return _ok("cancel")

def _rule_capture(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)
        or _kind_gate(ctx, tool_id)

    )
    if reason is None:
        native_kind = {"add_point": "addPoint", "add_line": "addLine", "add_polygon": "addPolygon"}[tool_id]
        reason = _native_tool_gate(ctx, native_kind, "采点")
    # Kind match is enforced by the gate; the matching capture tool is the
    # suggested one for the active layer.
    return _ok(tool_id, preferred=True) if reason is None else _no(tool_id, reason)

def _rule_edit_tool(ctx: ToolContext, tool_id: str, native_kind: str) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None:
        reason = _native_tool_gate(ctx, native_kind, {"move_feature": "移动", "vertex": "节点编辑"}[tool_id])
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_delete_selected(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and ctx.selection_count <= 0:
        reason = "没有选中的要素"
    return _ok("delete_selected") if reason is None else _no("delete_selected", reason)

def _rule_split(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and not ctx.split_ready:
        reason = "分割需要：一个正在编辑且选中了多边形的面图层 + 一条选中的切割线"
    return _ok("split") if reason is None else _no("split", reason)

def _rule_merge(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and ctx.topology_error_count > 0:
        reason = "当前编辑会话存在拓扑错误，不能合并"
    if reason is None and not ctx.merge_ready:
        reason = "合并需要至少两个选中的兼容面要素"
    return _ok("merge") if reason is None else _no("merge", reason)

def _rule_reshape(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and not ctx.native_canvas_available:
        # 重塑的采线输入依赖原生数字化器——fallback 画布无输入路径
        # （ReshapeTool 无鼠标方法），绝不能启用一个点了没反应的工具。
        reason = "重塑需要原生 QGIS 画布（无回退实现）"
    if reason is None and ctx.active_layer_kind not in {"line", "polygon"}:
        reason = "重塑仅支持线/面图层"
    if reason is None and ctx.selection_count != 1:
        reason = "重塑需要恰好选中一个要素"
    if reason is None:
        # 原生路径 = addLine 数字化器（采重塑线）+ 桥 geometry.reshape
        # 算子（QgsGeometry::reshapeGeometry，无 shapely 等价）——两者都
        # 必须在位，fallback 画布不提供 reshape。
        if "qgis.native_tool.addLine" not in ctx.capability_flags:
            reason = "重塑需要原生数字化工具（无回退实现）"
        elif "qgis.geometry_op.reshape" not in ctx.capability_flags:
            reason = "重塑需要 QGIS reshape 几何算子（重建 qgis_render_bridge）"
    return _ok("reshape") if reason is None else _no("reshape", reason)

def _rule_repair(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _writable_gate(ctx)
        or _role_gate(ctx)

    )
    if reason is None and ctx.active_layer_kind != "polygon":
        reason = "几何修复针对面图层"
    return _ok("repair_geometry") if reason is None else _no("repair_geometry", reason)

def _rule_duplicate_selected(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and ctx.selection_count <= 0:
        reason = "没有选中的要素"
    return _ok("duplicate_selected") if reason is None else _no("duplicate_selected", reason)


def _rule_add_ring(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and ctx.active_layer_kind != "polygon":
        reason = "添加环需要面图层"
    if reason is None and ctx.selection_count != 1:
        reason = "添加环需要恰好选中一个面要素"
    if reason is None:
        # 环捕获走原生 addPolygon 数字化器（native-only，与 reshape 同规）
        if not ctx.native_canvas_available:
            reason = "添加环需要原生 QGIS 画布（无回退实现）"
        elif "qgis.native_tool.addPolygon" not in ctx.capability_flags:
            reason = "添加环需要原生数字化工具（无回退实现）"
    return _ok("add_ring") if reason is None else _no("add_ring", reason)


def _rule_add_part(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and not ctx.active_layer_kind:
        reason = "未知图层几何类型"
    if reason is None and ctx.selection_count != 1:
        reason = "添加部件需要恰好选中一个要素"
    if reason is None:
        # 部件捕获走原生数字化器（随图层 kind）；几何执行需桥 add_part 算子
        # （单部件自动升多部件的语义由 QGIS 定义）。
        if not ctx.native_canvas_available:
            reason = "添加部件需要原生 QGIS 画布（无回退实现）"
        elif "qgis.geometry_op.add_part" not in ctx.capability_flags:
            reason = "添加部件需要 QGIS add_part 几何算子（重建 qgis_render_bridge）"
        else:
            kind = {"point": "addPoint", "line": "addLine", "polygon": "addPolygon"}.get(
                ctx.active_layer_kind, "")
            if kind and f"qgis.native_tool.{kind}" not in ctx.capability_flags:
                reason = "添加部件需要原生数字化工具（无回退实现）"
    return _ok("add_part") if reason is None else _no("add_part", reason)


def _rule_explode_multipart(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and ctx.selection_multipart_count < 1:
        reason = "拆分多部件需要选中至少一个多部件要素"
    return _ok("explode_multipart") if reason is None else _no("explode_multipart", reason)


def _rule_collect_multipart(ctx: ToolContext) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _role_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and ctx.topology_error_count > 0:
        reason = "当前编辑会话存在拓扑错误，不能合并部件"
    if reason is None and not ctx.collect_ready:
        reason = "组合多部件需要至少两个同类型的单部件要素"
    return _ok("collect_multipart") if reason is None else _no("collect_multipart", reason)


def _rule_history(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = (
        _project_gate(ctx)
        or _layer_gate(ctx)
        or _editing_gate(ctx)

    )
    if reason is None and tool_id == "undo" and not ctx.can_undo:
        reason = "没有可撤销的操作"
    if reason is None and tool_id == "redo" and not ctx.can_redo:
        reason = "没有可重做的操作"
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_snapping(ctx: ToolContext) -> ToolAvailability:
    # D4-5：捕捉/拓扑只需活动图层（与编辑会话解耦，QGIS desktop 对齐）。
    # V9 W1：可用性来自桥 manifest 派生（原生路径）或回退画布的既定事实，
    # 不再是硬编码 True。
    reason = _project_gate(ctx) or _layer_gate(ctx)
    if reason is None and not ctx.snapping_available:
        reason = "当前环境的捕捉引擎不可用（桥缺少 snapping 配置通道）"
    return _ok("snapping") if reason is None else _no("snapping", reason)

def _rule_topology(ctx: ToolContext) -> ToolAvailability:
    reason = _project_gate(ctx) or _layer_gate(ctx)
    if reason is None and not ctx.topology_available:
        reason = "拓扑校验引擎不可用（需 QGIS 桥 validate 或 Shapely）"
    if reason is None and not ctx.crs_valid:
        reason = "工程 CRS 无效，拓扑校验不可用"
    return _ok("topology") if reason is None else _no("topology", reason)

def _rule_layer_management(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    # layer_new / reference_import：工程级动作，不需要活动图层。
    reason = _project_gate(ctx)
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_layer_scoped(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    # 图层泛用动作（属性/属性表/缩放/导出/符号）：任意活动图层即可，
    # 不要求矢量（参考栅格层的属性/缩放/导出同样合法）。
    reason = _project_gate(ctx)
    if reason is None and not ctx.has_active_layer:
        reason = "当前无活动图层"
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_style_manager(ctx: ToolContext) -> ToolAvailability:
    # 门序遵循总则：blocking task 先于 native-only 能力门（后台任务进行中
    # 是更根本的全局阻断，V8 M1 契约）。
    reason = (
        _project_gate(ctx)
        or _backend_gate(ctx)
        or _layer_gate(ctx)
    )
    return _ok("style_manager") if reason is None else _no("style_manager", reason)

def _rule_factor(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _project_gate(ctx) or _stage_whitelist_gate(ctx, tool_id)
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

def _rule_qa(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _project_gate(ctx)
    if tool_id == "map_product_assemble":
        reason = reason or _stage_whitelist_gate(ctx, tool_id)
    return _ok(tool_id) if reason is None else _no(tool_id, reason)

_RULE_TABLE: dict[str, Rule] = {
    "pan": lambda ctx: _rule_navigation(ctx, "pan"),
    "zoom_in": lambda ctx: _rule_navigation(ctx, "zoom_in"),
    "zoom_out": lambda ctx: _rule_navigation(ctx, "zoom_out"),
    "full_extent": lambda ctx: _rule_navigation(ctx, "full_extent"),
    "previous_extent": lambda ctx: _rule_extent_history(ctx, "previous_extent"),
    "next_extent": lambda ctx: _rule_extent_history(ctx, "next_extent"),
    "refresh": lambda ctx: _rule_navigation(ctx, "refresh"),
    "identify": lambda ctx: _rule_inspection(ctx, "identify"),
    "select": lambda ctx: _rule_inspection(ctx, "select"),
    "select_rectangle": lambda ctx: _rule_inspection(ctx, "select_rectangle"),
    "measure_distance": lambda ctx: _rule_inspection(ctx, "measure_distance"),
    "clear_selection": lambda ctx: _rule_selection_commands(ctx, "clear_selection"),
    "select_all": lambda ctx: _rule_selection_commands(ctx, "select_all"),
    "invert_selection": lambda ctx: _rule_selection_commands(ctx, "invert_selection"),
    "toggle_editing": _rule_toggle_editing,
    "save_edits": _rule_save_edits,
    "rollback": _rule_rollback,
    "cancel": _rule_cancel,
    "add_point": lambda ctx: _rule_capture(ctx, "add_point"),
    "add_line": lambda ctx: _rule_capture(ctx, "add_line"),
    "add_polygon": lambda ctx: _rule_capture(ctx, "add_polygon"),
    "move_feature": lambda ctx: _rule_edit_tool(ctx, "move_feature", "move"),
    "vertex": lambda ctx: _rule_edit_tool(ctx, "vertex", "vertex"),
    "delete_selected": _rule_delete_selected,
    "split": _rule_split,
    "merge": _rule_merge,
    "reshape": _rule_reshape,
    "repair_geometry": _rule_repair,
    "duplicate_selected": _rule_duplicate_selected,
    "add_ring": _rule_add_ring,
    "add_part": _rule_add_part,
    "explode_multipart": _rule_explode_multipart,
    "collect_multipart": _rule_collect_multipart,
    "undo": lambda ctx: _rule_history(ctx, "undo"),
    "redo": lambda ctx: _rule_history(ctx, "redo"),
    "snapping": _rule_snapping,
    "topology": _rule_topology,
    "layer_new": lambda ctx: _rule_layer_management(ctx, "layer_new"),
    "reference_import": lambda ctx: _rule_layer_management(ctx, "reference_import"),
    "layer_properties": lambda ctx: _rule_layer_scoped(ctx, "layer_properties"),
    "attribute_table": lambda ctx: _rule_layer_scoped(ctx, "attribute_table"),
    "layer_zoom": lambda ctx: _rule_layer_scoped(ctx, "layer_zoom"),
    "layer_export": lambda ctx: _rule_layer_scoped(ctx, "layer_export"),
    "symbology": lambda ctx: _rule_layer_scoped(ctx, "symbology"),
    "style_manager": _rule_style_manager,
    "factor_workbench": lambda ctx: _rule_factor(ctx, "factor_workbench"),
    "factor_overlay": lambda ctx: _rule_factor(ctx, "factor_overlay"),
    "qa_run": lambda ctx: _rule_qa(ctx, "qa_run"),
    "map_product_assemble": lambda ctx: _rule_qa(ctx, "map_product_assemble"),
    "map_export": lambda ctx: _rule_factor(ctx, "map_export"),
}

def _coarsely_blocked(ctx: ToolContext, tool_id: str) -> bool:
    """该工具是否被比阶段更粗的门禁挡住（其判词优先于阶段呈现）。

    优先于阶段的判词：工程未开；以及**存在于具体图层之上**的角色/事实
    门禁（RAW/冻结/组锁/源缺失——这些是权威业务结论）。无活动图层不是
    ——阶段外动作概念上不存在（QGIS 惯例整条隐藏），无图层判词无从谈起。
    """
    if not ctx.project_open:
        return True
    needs_role = tool_id in (_NEEDS_EDITABLE_LAYER | _NEEDS_EDITING)
    if needs_role and ctx.has_active_layer and ctx.edit_gate_open is not True:
        return True
    return False


def evaluate_tool(tool_id: str, ctx: ToolContext) -> ToolAvailability:
    """Evaluate one tool. Unknown ids are invisible+disabled (fail-honest)."""
    rule = _RULE_TABLE.get(tool_id)
    if rule is None:
        return ToolAvailability(
            tool_id=tool_id, visible=False, enabled=False,
            disabled_reason=f"未知工具 {tool_id!r}",
        )
    # -- 表面存在性裁决（组级隐藏）------------------------------------------
    # 隐藏是呈现语义，不参与「最根本 blocker」的原因竞争：被收纳/阶段外
    # 的动作整条不显示。必须在 blocking/规则之前裁决——否则后台任务期间
    # 阶段隐藏的组会以 disabled 闪现（review R3-P2）。
    group = _GROUP_OF.get(tool_id, "")
    if (
        group in _NEEDS_LAYER_GROUPS
        and not ctx.has_active_layer
        and tool_id not in {"layer_new", "reference_import"}
    ):
        return ToolAvailability(
            tool_id=tool_id, visible=False, enabled=False,
            disabled_reason="当前无活动图层——该工具组未显示",
        )
    if not _coarsely_blocked(ctx, tool_id):
        # 阶段裁决（组隐藏 → 受治理编辑动作），单一推导自 StageToolProfile。
        # 门序总则：工程未开、以及存在于图层之上的角色/事实判词（RAW/
        # 冻结/组锁/源缺失）优先于阶段呈现；更细的门禁（会话/几何/选择）
        # 被阶段隐藏覆盖（阶段外动作整条隐藏，QGIS 惯例）。cancel 豁免
        # 阶段隐藏（_stage_group_gate 内裁决——Esc 语义不可按阶段下线）。
        stage_reason = _stage_group_gate(ctx, tool_id)
        if stage_reason is None:
            stage_reason = _edit_action_stage_gate(ctx, tool_id)
        if stage_reason is not None:
            return ToolAvailability(
                tool_id=tool_id, visible=False, enabled=False,
                disabled_reason=stage_reason,
            )

    # -- 全局门禁（集中裁决，优先于具体规则）--------------------------------
    # 1) blocking task —— 模态全局状态（A 语义：除 cancel 外全部阻断）；
    #    reason 固定可解释，且 toolbar/palette 同因。
    if tool_id != "cancel":
        blocking = _blocking_gate(ctx)
        if blocking is not None:
            return _no(tool_id, blocking)
    # 2) 图层事实门禁：源缺失 / 降级（宿主判词优先，默认文案兜底）。
    #    仅在工程已打开时裁决——无工程是更根本的 blocker（门序总则）。
    if tool_id in _LAYER_FACT_GATED and ctx.project_open and ctx.has_active_layer:
        if ctx.layer_missing:
            return _no(
                tool_id,
                ctx.edit_gate_reason or "图层源缺失（文件被移动或删除）",
            )
        if ctx.layer_degraded and ctx.edit_gate_open is False:
            return _no(
                tool_id,
                ctx.edit_gate_reason or "图层处于降级状态（数据不完整）",
            )
    availability = rule(ctx)

    # -- checked follows the actual tool/session/toggle state ---------------
    checked: bool | None = None
    if tool_id == "toggle_editing":
        checked = ctx.editing
    elif tool_id == "snapping":
        checked = ctx.snapping_enabled
    elif tool_id == "topology":
        checked = ctx.topology_enabled
    elif tool_id in _CHECKED_CANVAS_TOOLS:
        checked = ctx.current_tool == tool_id and availability.enabled
    if checked is not None:
        availability = ToolAvailability(
            tool_id=tool_id, visible=availability.visible, enabled=availability.enabled,
            checked=checked, disabled_reason=availability.disabled_reason,
            preferred=availability.preferred, conflicts=availability.conflicts,
        )
    return availability

def evaluate_all(ctx: ToolContext) -> dict[str, ToolAvailability]:
    """Evaluate the full matrix (stable ordering by TOOL_IDS)."""
    return {tool_id: evaluate_tool(tool_id, ctx) for tool_id in TOOL_IDS}
