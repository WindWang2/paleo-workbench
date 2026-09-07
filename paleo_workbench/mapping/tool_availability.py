"""ToolAvailability — the single tool state machine for the authoring kernel.

Pure functions over :class:`ToolContext`; no Qt, no bridge import, no I/O.
Every disable carries a human-readable reason (never a bare ``setEnabled(False)``).

Matrix implemented (Goal V7 §4):

* Navigation: pan / zoom_in / zoom_out / full_extent / previous_extent /
  next_extent / refresh
* Inspection: identify / select / select_rectangle / clear_selection /
  select_all / invert_selection / measure_distance
* Session: toggle_editing / save_edits / rollback / cancel
* Capture: add_point / add_line / add_polygon
* Geometry: move_feature / vertex / delete_selected / split / merge /
  reshape / repair_geometry / undo / redo
* GIS state: snapping / topology

Interpretation notes (recorded in docs/development/qgis-native-authoring-v7/03-decisions.md):

* On the native canvas the *native* tool must exist in the capability
  manifest, otherwise the tool is disabled with the bridge reason. On the
  fallback canvas the Python tool stays available — the fallback is the
  sanctioned headless/minimal path and does not gain features the native
  path lacks (``reshape`` has no fallback and is therefore native-only).
* ``split``/``merge`` are commands (not canvas interactions): they stay
  available on the fallback canvas with shapely execution, degraded from the
  QGIS engine — availability itself is not the capability probe; the engine
  choice is recorded in the EditDelta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from paleo_workbench.mapping.tool_context import ToolContext

__all__ = ["ToolAvailability", "evaluate_tool", "evaluate_all", "TOOL_IDS"]

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ToolAvailability:
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
# Shared gating helpers. Each returns either None (gate passed) or a reason.
# ---------------------------------------------------------------------------


def _canvas_gate(ctx: ToolContext) -> str | None:
    if not ctx.project_open:
        return "没有打开的工程"
    return None


def _layer_gate(ctx: ToolContext) -> str | None:
    if not ctx.active_layer_id:
        return "没有活动的矢量图层"
    return None


def _writable_gate(ctx: ToolContext) -> str | None:
    if not ctx.vector_writable:
        return "图层不可写"
    return None


def _role_gate(ctx: ToolContext) -> str | None:
    # 拒绝判定的优先序：宿主门禁的具体判词（RAW/阶段锁语义权威文本，最
    # 具体）→ raw_locked/stage_locked 分类标志（门禁未同步文本时的绝对
    # 拒绝兜底）→ 无文本的门禁拒绝。
    if not ctx.edit_gate_open and ctx.edit_gate_reason:
        return ctx.edit_gate_reason
    if ctx.raw_locked:
        return "RAW 图层不可变，请创建 DERIVED 草稿后编辑"
    if ctx.stage_locked:
        return "当前阶段的证据组已锁定，禁止编辑"
    if not ctx.edit_gate_open:
        return "图层被编辑门禁锁定"
    return None


def _editing_gate(ctx: ToolContext) -> str | None:
    if not ctx.editing:
        return "未开始编辑（先开启编辑会话）"
    return None


def _blocking_gate(ctx: ToolContext) -> str | None:
    if ctx.blocking_task:
        return f"后台任务进行中：{ctx.blocking_task}"
    return None


def _native_tool_gate(ctx: ToolContext, kind: str, native_name: str) -> str | None:
    """Native-canvas-only requirement; the fallback canvas runs the Python tool."""
    if ctx.native_canvas_available and kind not in {
        flag.removeprefix("qgis.native_tool.") for flag in ctx.capability_flags
    }:
        return f"原生 {native_name} 工具在当前桥版本不可用（重建 qgis_render_bridge）"
    return None


_KIND_MATCH_REASON = {
    "add_point": "活动图层不是点图层",
    "add_line": "活动图层不是线图层",
    "add_polygon": "活动图层不是面图层",
}


def _capture_kind_gate(ctx: ToolContext, tool_id: str) -> str | None:
    kind_required = {"add_point": "point", "add_line": "line", "add_polygon": "polygon"}[tool_id]
    if ctx.active_layer_kind != kind_required:
        return _KIND_MATCH_REASON[tool_id]
    return None


# ---------------------------------------------------------------------------
# Rules — one per tool id. Order of gates is deliberate: coarse → fine so the
# reason shown is the most fundamental blocker.
# ---------------------------------------------------------------------------

Rule = Callable[[ToolContext], ToolAvailability]


def _rule_pan(ctx: ToolContext) -> ToolAvailability:
    reason = _canvas_gate(ctx) or _blocking_gate(ctx)
    return _ok("pan", preferred=ctx.current_tool == "pan") if reason is None else _no("pan", reason)


def _rule_zoom(ctx: ToolContext) -> ToolAvailability:
    tool_id = "zoom_in"
    reason = _canvas_gate(ctx) or _blocking_gate(ctx)
    return _ok(tool_id) if reason is None else _no(tool_id, reason)


def _rule_full_extent(ctx: ToolContext) -> ToolAvailability:
    reason = _canvas_gate(ctx)
    return _ok("full_extent") if reason is None else _no("full_extent", reason)


def _rule_refresh(ctx: ToolContext) -> ToolAvailability:
    reason = _canvas_gate(ctx)
    return _ok("refresh") if reason is None else _no("refresh", reason)


def _rule_previous_extent(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _canvas_gate(ctx)
    if reason is None and not ctx.can_previous_extent:
        reason = "没有可回退的视图历史"
    return _ok(tool_id) if reason is None else _no(tool_id, reason)


def _rule_next_extent(ctx: ToolContext) -> ToolAvailability:
    reason = _canvas_gate(ctx)
    if reason is None and not ctx.can_next_extent:
        reason = "没有可前进的视图历史"
    return _ok("next_extent") if reason is None else _no("next_extent", reason)


def _rule_inspection(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _canvas_gate(ctx) or _layer_gate(ctx) or _blocking_gate(ctx)
    if reason is None and tool_id == "identify":
        reason = _native_tool_gate(ctx, "identify", "识别")
    if reason is None and tool_id == "measure_distance":
        # Native canvas → native measure tool; fallback canvas keeps the
        # Python measure implementation.
        reason = _native_tool_gate(ctx, "measure", "测距")
    return _ok(tool_id) if reason is None else _no(tool_id, reason)


def _rule_selection_commands(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _layer_gate(ctx)
    if reason is None and tool_id != "select_all" and ctx.selection_count == 0:
        reason = "没有选中的要素"
    return _ok(tool_id) if reason is None else _no(tool_id, reason)


def _rule_toggle_editing(ctx: ToolContext) -> ToolAvailability:
    reason = _layer_gate(ctx) or _writable_gate(ctx) or _role_gate(ctx)
    return _ok("toggle_editing", preferred=ctx.editing) if reason is None else _no("toggle_editing", reason)


def _rule_save_edits(ctx: ToolContext) -> ToolAvailability:
    reason = _editing_gate(ctx)
    if reason is None and not ctx.dirty:
        reason = "编辑会话没有未保存的修改"
    if reason is None and not ctx.edit_gate_open:
        reason = ctx.edit_gate_reason or "图层被编辑门禁锁定"
    # 拓扑/科学阻断在保存时校验并回报（校验代价高，不进状态机）；
    # 状态机只保证结构性前提。
    return _ok("save_edits") if reason is None else _no("save_edits", reason)


def _rule_rollback(ctx: ToolContext) -> ToolAvailability:
    reason = _editing_gate(ctx)
    if reason is None and not ctx.dirty:
        reason = "编辑会话没有可回滚的修改"
    return _ok("rollback") if reason is None else _no("rollback", reason)


def _rule_cancel(ctx: ToolContext) -> ToolAvailability:
    return _ok("cancel")


def _rule_capture(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = (
        _canvas_gate(ctx)
        or _layer_gate(ctx)
        or _editing_gate(ctx)
        or _role_gate(ctx)
        or _capture_kind_gate(ctx, tool_id)
        or _blocking_gate(ctx)
    )
    if reason is None:
        native_kind = {"add_point": "addPoint", "add_line": "addLine", "add_polygon": "addPolygon"}[tool_id]
        reason = _native_tool_gate(ctx, native_kind, "采点")
    # Kind match is enforced by the gate; the matching capture tool is the
    # suggested one for the active layer.
    return _ok(tool_id, preferred=reason is None) if reason is None else _no(tool_id, reason)


def _rule_edit_tool(ctx: ToolContext, tool_id: str, native_kind: str) -> ToolAvailability:
    reason = (
        _canvas_gate(ctx)
        or _layer_gate(ctx)
        or _editing_gate(ctx)
        or _role_gate(ctx)
        or _blocking_gate(ctx)
    )
    if reason is None:
        reason = _native_tool_gate(ctx, native_kind, {"move_feature": "移动", "vertex": "节点编辑"}[tool_id])
    return _ok(tool_id) if reason is None else _no(tool_id, reason)


def _rule_delete_selected(ctx: ToolContext) -> ToolAvailability:
    reason = _layer_gate(ctx) or _editing_gate(ctx) or _role_gate(ctx)
    if reason is None and ctx.selection_count == 0:
        reason = "没有选中的要素"
    return _ok("delete_selected") if reason is None else _no("delete_selected", reason)


def _rule_split(ctx: ToolContext) -> ToolAvailability:
    reason = _layer_gate(ctx) or _editing_gate(ctx) or _role_gate(ctx)
    if reason is None and not ctx.split_ready:
        reason = (
            "分割需要：一个正在编辑且选中了多边形的面图层 + 一条选中的切割线"
        )
    return _ok("split") if reason is None else _no("split", reason)


def _rule_merge(ctx: ToolContext) -> ToolAvailability:
    reason = _layer_gate(ctx) or _editing_gate(ctx) or _role_gate(ctx)
    if reason is None and not ctx.merge_ready:
        reason = "合并需要至少两个选中的兼容面要素"
    return _ok("merge") if reason is None else _no("merge", reason)


def _rule_reshape(ctx: ToolContext) -> ToolAvailability:
    reason = _canvas_gate(ctx) or _layer_gate(ctx) or _editing_gate(ctx) or _role_gate(ctx) or _blocking_gate(ctx)
    if reason is None and ctx.active_layer_kind not in {"line", "polygon"}:
        reason = "重塑仅支持线/面图层"
    if reason is None and ctx.selection_count != 1:
        reason = "重塑需要恰好选中一个要素"
    if reason is None:
        # 原生路径 = addLine 数字化器（采重塑线）+ 桥 geometry.reshape
        # 算子（QgsGeometry::reshapeGeometry，无 shapely 等价）——两者都
        # 必须在位，fallback 画布不提供 reshape（无回退实现）。
        if "qgis.native_tool.addLine" not in ctx.capability_flags:
            reason = "重塑需要原生数字化工具（无回退实现）"
        elif "qgis.geometry_op.reshape" not in ctx.capability_flags:
            reason = "重塑需要 QGIS reshape 几何算子（重建 qgis_render_bridge）"
    return _ok("reshape") if reason is None else _no("reshape", reason)


def _rule_repair(ctx: ToolContext) -> ToolAvailability:
    reason = _layer_gate(ctx) or _writable_gate(ctx) or _role_gate(ctx)
    if reason is None and ctx.active_layer_kind != "polygon":
        reason = "几何修复针对面图层"
    return _ok("repair_geometry") if reason is None else _no("repair_geometry", reason)


def _rule_history(ctx: ToolContext, tool_id: str) -> ToolAvailability:
    reason = _editing_gate(ctx)
    if reason is None and tool_id == "undo" and not ctx.can_undo:
        reason = "没有可撤销的操作"
    if reason is None and tool_id == "redo" and not ctx.can_redo:
        reason = "没有可重做的操作"
    return _ok(tool_id) if reason is None else _no(tool_id, reason)


def _rule_snapping(ctx: ToolContext) -> ToolAvailability:
    reason = _layer_gate(ctx)
    return _ok("snapping") if reason is None else _no("snapping", reason)


def _rule_topology(ctx: ToolContext) -> ToolAvailability:
    reason = _layer_gate(ctx)
    if reason is None and not ctx.crs_valid:
        reason = "工程 CRS 无效，拓扑校验不可用"
    return _ok("topology") if reason is None else _no("topology", reason)


_RULE_TABLE: dict[str, Rule] = {
    "pan": _rule_pan,
    "zoom_in": _rule_zoom,
    "zoom_out": _rule_zoom,
    "full_extent": _rule_full_extent,
    "previous_extent": lambda ctx: _rule_previous_extent(ctx, "previous_extent"),
    "next_extent": _rule_next_extent,
    "refresh": _rule_refresh,
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
    "undo": lambda ctx: _rule_history(ctx, "undo"),
    "redo": lambda ctx: _rule_history(ctx, "redo"),
    "snapping": _rule_snapping,
    "topology": _rule_topology,
}

TOOL_IDS: tuple[str, ...] = tuple(_RULE_TABLE)

# Tool groups by visibility semantics (capture/editing tools vanish without a
# vector layer; pure navigation always shows).
_SESSION_TOOL_IDS = frozenset(
    {
        "toggle_editing", "save_edits", "rollback",
        "add_point", "add_line", "add_polygon",
        "move_feature", "vertex", "delete_selected",
        "split", "merge", "reshape", "repair_geometry",
        "undo", "redo",
    }
)


def evaluate_tool(tool_id: str, ctx: ToolContext) -> ToolAvailability:
    """Evaluate one tool. Unknown ids are invisible+disabled (fail-honest)."""
    rule = _RULE_TABLE.get(tool_id)
    if rule is None:
        return ToolAvailability(tool_id=tool_id, visible=False, enabled=False, disabled_reason=f"未知工具 {tool_id!r}")
    availability = rule(ctx)
    # Stage tool profiles hide buttons without touching logic.
    if tool_id in ctx.hidden_by_stage_profile:
        availability = ToolAvailability(
            tool_id=tool_id,
            visible=False,
            enabled=False,
            disabled_reason="当前制图阶段不使用该工具",
        )
    elif not ctx.active_layer_id and tool_id in _SESSION_TOOL_IDS:
        availability = ToolAvailability(
            tool_id=tool_id,
            visible=False,
            enabled=False,
            disabled_reason="没有活动的矢量图层",
        )
    # checked follows the active tool for canvas tools.
    checked_tools = {
        "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
        "measure_distance", "add_point", "add_line", "add_polygon",
        "move_feature", "vertex", "reshape",
    }
    if tool_id == "toggle_editing":
        availability = ToolAvailability(
            tool_id=tool_id, visible=availability.visible, enabled=availability.enabled,
            checked=ctx.editing, disabled_reason=availability.disabled_reason,
            preferred=availability.preferred,
        )
    elif tool_id == "snapping":
        availability = ToolAvailability(
            tool_id=tool_id, visible=availability.visible, enabled=availability.enabled,
            checked=ctx.snapping_enabled, disabled_reason=availability.disabled_reason,
        )
    elif tool_id == "topology":
        availability = ToolAvailability(
            tool_id=tool_id, visible=availability.visible, enabled=availability.enabled,
            checked=ctx.topology_enabled, disabled_reason=availability.disabled_reason,
        )
    elif tool_id in checked_tools:
        availability = ToolAvailability(
            tool_id=tool_id, visible=availability.visible, enabled=availability.enabled,
            checked=ctx.current_tool == tool_id, disabled_reason=availability.disabled_reason,
            preferred=availability.preferred,
        )
    return availability


def evaluate_all(ctx: ToolContext) -> dict[str, ToolAvailability]:
    """Evaluate the full matrix (stable ordering by TOOL_IDS)."""
    return {tool_id: evaluate_tool(tool_id, ctx) for tool_id in TOOL_IDS}
