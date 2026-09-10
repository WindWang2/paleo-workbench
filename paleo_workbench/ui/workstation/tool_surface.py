"""上下文驱动工具面（V8）：canonical evaluator 的**呈现层适配器**。

业务真源已收敛到 ``paleo_workbench.mapping.tool_availability``（Goal V8
M1）：本模块不再持有任何门禁规则，只保留：

* canonical 符号 re-export（``ToolAvailability`` / ``ToolContext`` /
  ``evaluate_tool`` / ``availability_for_context`` / ``TOOL_GROUPS`` /
  ``stage_group_visibility`` / ``LAYER_CAPTION``）；
* ``QgisCapabilitySnapshot``：**运行期画布后端**三态呈现（native /
  degraded / unavailable / unknown）——与 ``mapping.capability_model`` 的
  编译期桥 manifest 权威（status + native_tools…）是两个概念，本类型只
  描述「当前画布后端跑在什么状态」；
* ``LayerCapabilitySnapshot``：活动图层的呈现事实（角色/几何/成熟度/
  门禁结论），供状态条 / app_shell provider / inspector 消费，并可经
  ``layer_facts()`` 扁平化喂给 canonical ``build_tool_context``；
* ``tool_context_from_ui_snapshot``：``UIContextSnapshot``（V6 palette
  上下文，鸭子类型）→ canonical ``ToolContext`` 适配；
* ``derived_context``：测试/适配辅助。

约束（Goal V8 M1）：**禁止在本模块重新出现第二套 enabled/visible/reason
业务判断**；呈现差异（工具条隐藏 vs palette 禁用）由消费方基于
``visible``/``disabled_reason`` 选择，reason 字符串原样透传。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from paleo_workbench.mapping.tool_availability import (  # noqa: F401 — re-export surface
    LAYER_CAPTION,
    TOOL_GROUPS,
    TOOL_IDS,
    ToolAvailability,
    ToolContext,
    evaluate_all,
    evaluate_tool,
    stage_group_visibility,
)

__all__ = [
    "LAYER_CAPTION",
    "TOOL_GROUPS",
    "TOOL_IDS",
    "LayerCapabilitySnapshot",
    "LayerMenuFacts",
    "QgisCapabilitySnapshot",
    "ToolAvailability",
    "ToolContext",
    "availability_for_context",
    "derived_context",
    "evaluate_all",
    "evaluate_tool",
    "stage_group_visibility",
    "tool_context_from_ui_snapshot",
]


def availability_for_context(ctx: ToolContext) -> dict[str, ToolAvailability]:
    """全工具面可用性（工具条/菜单一次刷新；dict 差分消费）。"""
    return evaluate_all(ctx)


# ---------------------------------------------------------------------------
# 呈现快照（UI 侧协议；结论型字段来自域权威，不在此处推导业务判定）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QgisCapabilitySnapshot:
    """QGIS 运行期画布后端三态（native / degraded / unavailable / unknown）。

    权威输入：``CompositeDocument.uses_native_stack``、画布
    ``backend_status`` 降级串、``qgis_bridge_available()`` 探测。None 不
    允许——未知必须显式 ``mode="unknown"``（fail-closed）。
    """

    mode: str  # native | degraded | unavailable | unknown
    reason: str = ""

    @property
    def native_ready(self) -> bool:
        return self.mode == "native"


@dataclass(frozen=True, slots=True)
class LayerCapabilitySnapshot:
    """活动图层的呈现相关事实（结论型字段来自域权威）。

    ``editable``/``block_reason`` 是 ``_role_allows_editing`` 的结论；
    ``kind`` 是 ``GEOMETRY_KINDS``（point/line/polygon）值；``maturity``
    是 ArtifactMaturity 语义值（raw/draft/reviewed/frozen/published）。
    本类型是呈现投影（状态条/Provider/Inspector 消费）——求值输入经
    ``layer_facts()`` 扁平化进入 canonical ``ToolContext``。
    """

    layer_id: str | None = None
    name: str | None = None
    role: str | None = None
    role_label: str | None = None
    kind: str | None = None
    maturity: str | None = None
    editable: bool | None = None
    block_reason: str | None = None
    frozen: bool = False
    missing: bool = False
    degraded: bool = False

    def layer_facts(self) -> dict:
        """扁平图层事实（canonical ``build_tool_context(layer_facts=...)`` 输入）。"""
        return {
            "active_layer_id": self.layer_id or "",
            "active_layer_kind": self.kind or "",
            "layer_name": self.name or "",
            "layer_role": self.role or "",
            "layer_role_label": self.role_label or "",
            "artifact_maturity": self.maturity or "",
            "layer_frozen": self.frozen,
            "layer_missing": self.missing,
            "layer_degraded": self.degraded,
        }


@dataclass(frozen=True, slots=True)
class LayerMenuFacts:
    """图层级菜单呈现事实（V10 M5：树右键菜单消费 canonical evaluator）。

    宿主（CompositeDocument）把目标图层的事实投影进 ToolContext 后经
    ``evaluate_tool`` 求值，产出本冻结快照——面板只据此呈现，不再自建
    第二业务 gate（此前编辑入口只看 metadata.editable 旗标，RAW/冻结/
    组锁/阻塞的禁用原因无法进入菜单）。``raw_protected`` 是菜单**编排**
    事实（RAW 图层显示「复制为草稿」工作流入口），不是新的门禁。
    """

    toggle_editing: ToolAvailability | None = None
    repair_geometry: ToolAvailability | None = None
    raw_protected: bool = False


# ---------------------------------------------------------------------------
# UIContextSnapshot 适配（palette / 状态条共用单一求值）
# ---------------------------------------------------------------------------


def tool_context_from_ui_snapshot(snap: object) -> ToolContext:
    """UIContextSnapshot（鸭子类型）→ canonical ToolContext（palette 用）。

    快照缺少的输入（选择数/撤销栈/dirty 等运行细节）按保守值处理——
    palette applicability 只需要「为什么不可用」级别的精度；执行侧由
    CompositeDocument 的 execution re-gate 用完整上下文二次判定。
    """
    s = snap

    def _get(name: str, default=None):
        return getattr(s, name, default)

    bridge = _get("qgis_bridge_available", None)
    mode = _get("capability_mode", None)
    if mode is None:
        if bridge is True:
            mode = "native"
        elif bridge is False:
            mode = "unavailable"
        else:
            mode = "unknown"
    native_canvas = _get("native_canvas_available", None)
    capability_flags = frozenset(
        str(flag) for flag in (_get("native_capability_flags", ()) or ())
    )
    editable = _get("active_layer_editable", None)
    layer_id = _get("active_layer_id", None)
    writable = _get("active_layer_writable", None)
    # V8 M6：快照携带的会话运行细节（provider 缺席时按保守值——palette
    # 宁可保守禁用，执行侧还有完整上下文的 re-gate 兜底）。
    dirty = _get("editing_dirty", None)
    selection_count = _get("selection_count", None)
    can_undo = _get("can_undo", None)
    can_redo = _get("can_redo", None)
    blocking_task = _get("blocking_task", None)
    # V10 M9：split/merge/reshape 会话几何前提（provider 缺席 = None →
    # 保守 False；执行侧 re-gate 用完整上下文兜底）。
    split_ready = _get("split_ready", None)
    merge_ready = _get("merge_ready", None)
    reshape_ready = _get("reshape_ready", None)
    queryable = _get("queryable_layer_count", None)
    if queryable is None:
        # provider 缺席的回落：有活动层 ≈ 至少一个可查询图层（执行侧
        # re-gate 会用完整计数二次判定，此处只保 palette 不假禁用）。
        queryable = 1 if layer_id else 0
    return ToolContext(
        project_open=bool(_get("project_open", False)),
        mapping_stage=_get("mapping_stage", None),
        backend_mode=str(mode),
        backend_reason=str(_get("capability_reason", "") or ""),
        active_layer_id=str(layer_id or ""),
        active_layer_kind=str(_get("active_layer_kind", None) or ""),
        layer_role=str(_get("active_layer_role", None) or ""),
        artifact_maturity=str(_get("active_layer_maturity", None) or ""),
        layer_frozen=bool(_get("active_layer_frozen", False)),
        layer_missing=bool(_get("active_layer_missing", False)),
        layer_degraded=bool(_get("active_layer_degraded", False)),
        qgis_layer_type=(
            "raster" if _get("active_layer_is_raster", False)
            else ("vector" if _get("active_layer_id", None) else "")
        ),
        edit_gate_open=(None if editable is None else bool(editable)),
        edit_gate_reason=str(_get("active_layer_block_reason", None) or ""),
        vector_writable=(
            bool(editable) if writable is None else bool(writable)
        ),
        editing=bool(_get("editing_active", False)),
        dirty=False if dirty is None else bool(dirty),
        selection_count=0 if selection_count is None else int(selection_count),
        can_undo=False if can_undo is None else bool(can_undo),
        can_redo=False if can_redo is None else bool(can_redo),
        split_ready=False if split_ready is None else bool(split_ready),
        merge_ready=False if merge_ready is None else bool(merge_ready),
        reshape_ready=False if reshape_ready is None else bool(reshape_ready),
        blocking_task="" if blocking_task is None else str(blocking_task),
        write_granted=bool(_get("write_granted", False)),
        queryable_layer_count=int(queryable or 0),
        native_canvas_available=bool(native_canvas),
        capability_flags=capability_flags,
    )


def derived_context(**changes) -> ToolContext:
    """测试/适配辅助：基于默认上下文替换字段。"""
    return replace(ToolContext(), **changes)
