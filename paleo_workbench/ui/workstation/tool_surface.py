"""上下文驱动工具面（V7 §3–§6）：可用性求值的唯一真源。

设计约束（docs/development/workstation-ux-v7/02-architecture.md）：

* **纯 Python**：本模块不 import Qt——矩阵可以全量单测（无 QApplication）。
* **单一真源**：工具条、palette、右键菜单、状态条、Inspector 提示都渲染
  ``evaluate_tool`` / ``availability_for_context`` 的输出，不得自建第二套
  enable/visibility/reason 判断。
* **不复制域判断**：RAW/证据锁等角色门禁的**结论**经
  ``LayerCapabilitySnapshot.block_reason`` 进入（权威在
  ``CompositeDocument._role_allows_editing``）；本模块只做呈现层编排
  （阶段/几何/会话/选择/能力/授权的门禁次序与话术）。
* **诚实**：任何禁用必须带人类可读原因；未知阶段/未知能力 fail-closed。

门禁求值顺序（先到先得 = 优先级）：
存在性 → 工程 → QGIS 能力 → 图层存在/缺失 → 角色门禁（RAW/冻结/锁定）
→ 阶段（组隐藏 / 动作白名单）→ 几何类型（捕获工具）→ 编辑会话
→ 选择条件。

（WRITE 授权字段 ``write_granted`` 是 palette 适配器输入的保留位：
本应用中 WRITE grant 门控 Agent 动作而非地图工具——首个需要授权的
地图工具出现前，求值器不声称该门禁。评审 R1-P2/R2-F6 改为如实陈述。）
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage, stage_from_value

__all__ = [
    "LAYER_CAPTION",
    "TOOL_GROUPS",
    "LayerCapabilitySnapshot",
    "QgisCapabilitySnapshot",
    "ToolAvailability",
    "ToolContext",
    "availability_for_context",
    "evaluate_tool",
    "stage_group_visibility",
    "tool_context_from_ui_snapshot",
]


# ---------------------------------------------------------------------------
# goal §16 typing seams：能力/图层/上下文快照（UI 侧协议，权威在域侧）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QgisCapabilitySnapshot:
    """QGIS 原生后端能力三态（native / degraded / unavailable / unknown）。

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
    """活动图层的呈现相关能力（goal §16；结论型字段来自域权威）。

    ``editable``/``block_reason`` 是 ``_role_allows_editing`` 的结论；
    ``kind`` 是 ``GEOMETRY_KINDS``（point/line/polygon）值；``maturity``
    是 ArtifactMaturity 语义值（raw/draft/reviewed/frozen/published）。
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


@dataclass(frozen=True, slots=True)
class ToolContext:
    """``evaluate_tool`` 的全部输入（构造廉价；无 Qt 调用）。"""

    project_open: bool = True
    stage: str | None = None
    layer: LayerCapabilitySnapshot = field(default_factory=LayerCapabilitySnapshot)
    has_active_vector_layer: bool = False
    vector_layer_writable: bool = False
    editing: bool = False
    dirty: bool = False
    selected_count: int = 0
    compatible_polygon_count: int = 0
    can_undo: bool = False
    can_redo: bool = False
    can_previous_extent: bool = False
    can_next_extent: bool = False
    split_inputs_ready: bool | None = None
    topology_error_count: int = 0
    capability: QgisCapabilitySnapshot = field(
        default_factory=lambda: QgisCapabilitySnapshot(mode="unknown")
    )
    write_granted: bool = False


@dataclass(frozen=True, slots=True)
class ToolAvailability:
    """一个工具在给定上下文下的呈现结论。

    ``visible=False``（阶段外工具条隐藏，QGIS 惯例）时 ``enabled`` 必为
    False 且 ``reason`` 说明阶段限制；palette 侧对同一动作选择
    disabled+原因（可发现性）——两种呈现共用同一 reason 字符串。
    """

    enabled: bool
    visible: bool = True
    reason: str = ""


# ---------------------------------------------------------------------------
# 工具分组 IA（goal §6 专业分组）
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
        "split", "merge",
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

_ALL_TOOLS: tuple[str, ...] = tuple(
    tool for members in TOOL_GROUPS.values() for tool in members
)

_KIND_LABELS = {"point": "点", "line": "线", "polygon": "面"}

#: 线角色（goal §4.2：Add Line 为主捕获工具的角色集）
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
_NATIVE_ONLY_TOOLS = frozenset({"style_manager", "reshape"})

#: 需要活动图层（矢量或任意）的工具
_NEEDS_ANY_LAYER = frozenset({
    "identify", "select", "select_rectangle", "measure_distance",
    "clear_selection", "select_all", "invert_selection",
    "layer_properties", "layer_zoom", "layer_export", "symbology",
})
# attribute_table 是只读查看（QGIS 语义）——只要求图层存在，不要求
# 可编辑（R1-P2：此前与 toggle_editing 同门禁，RAW 层连查看都被禁）。
_NEEDS_EDITABLE_LAYER = frozenset({"toggle_editing"})

#: 需要已开启编辑会话的工具（会话内进一步受选择/撤销栈约束）
_NEEDS_EDITING = frozenset({
    "save_edits", "rollback", "add_point", "add_line", "add_polygon",
    "move_feature", "vertex", "reshape", "snapping", "topology",
})

#: 需要活动图层的组（goal §6「根据 active layer 切换组」：无活动图层
# 时整组不显示——比显示一排禁用按钮更专业；palette 侧同因禁用）。
_NEEDS_LAYER_GROUPS = frozenset({"layer", "symbology"})

#: 阶段专属组（其余组全阶段可见；goal §4/§6）
_STAGE_GROUP_VISIBILITY: dict[str, dict[str, bool]] = {
    MappingStage.FACIES_CALIBRATION.value: {"factor": False, "layout_export": False},
    MappingStage.CONSTRAINT_FACTOR.value: {"factor": True, "layout_export": False},
    MappingStage.INTEGRATED_COMPILATION.value: {"factor": False, "layout_export": True},
}

#: 非编辑动作的阶段白名单（编辑/数字化动作的阶段真源在
#: ``mapping_workspace.stage_profiles.StageToolProfile.edit_actions``）
_STAGE_ACTION_WHITELIST: dict[str, frozenset[str]] = {
    "factor_workbench": frozenset({MappingStage.CONSTRAINT_FACTOR.value}),
    "factor_overlay": frozenset({MappingStage.CONSTRAINT_FACTOR.value}),
    "map_product_assemble": frozenset({MappingStage.INTEGRATED_COMPILATION.value}),
    "map_export": frozenset({MappingStage.INTEGRATED_COMPILATION.value}),
}


def LAYER_CAPTION(kind: str | None) -> str:  # noqa: N802 — 呈现词汇函数
    """几何类型的中文呈现（未知 = 「未知」，不猜）。"""
    return _KIND_LABELS.get(str(kind or ""), "未知")


def _stage_label(value: str) -> str:
    stage = stage_from_value(value)
    return stage.label if stage is not None else value


def _no(reason: str) -> ToolAvailability:
    return ToolAvailability(enabled=False, visible=True, reason=reason)


def _hidden(reason: str) -> ToolAvailability:
    return ToolAvailability(enabled=False, visible=False, reason=reason)


# ---------------------------------------------------------------------------
# 求值器
# ---------------------------------------------------------------------------


def evaluate_tool(tool_id: str, ctx: ToolContext) -> ToolAvailability:
    """单一工具的可用性（先到先得的门禁链；禁用必带原因）。"""
    if tool_id not in _ALL_TOOLS:
        return _no("未知工具")
    if tool_id == "cancel":
        return ToolAvailability(enabled=True)

    # 1) 工程
    if not ctx.project_open:
        return _no("未打开工程")

    # 2) QGIS 能力（native-only 工具）
    if tool_id in _NATIVE_ONLY_TOOLS:
        cap = ctx.capability
        if cap.mode == "degraded":
            return _no(f"QGIS 原生后端降级（{cap.reason or '同步异常'}）——该功能暂不可用")
        if cap.mode != "native":
            reason = cap.reason or ("能力未知" if cap.mode == "unknown" else "桥不可用")
            return _no(f"需要 QGIS 原生编辑后端（{reason}）")

    layer = ctx.layer

    # 3) 图层存在性 / 缺失 / 降级
    if tool_id in _NEEDS_ANY_LAYER or tool_id in _NEEDS_EDITABLE_LAYER or tool_id in _NEEDS_EDITING:
        if layer.missing:
            return _no(layer.block_reason or "图层源缺失（文件被移动或删除）")
        if layer.degraded and layer.editable is False:
            return _no(layer.block_reason or "图层处于降级状态（数据不完整）")
        if layer.layer_id is None:
            # 图层/符号组整组跟随活动图层（goal §6）；选择/识别类保持
            # disabled+原因（可发现性）。
            if _group_of(tool_id) in _NEEDS_LAYER_GROUPS:
                return _hidden("当前无活动图层——该工具组未显示")
            if tool_id in _NEEDS_ANY_LAYER:
                return _no("当前无活动图层" if tool_id.startswith("layer_")
                           else "当前无活动矢量图层")
            if tool_id in _NEEDS_EDITABLE_LAYER:
                return _no("当前无活动矢量图层")

    # 4) 角色门禁（RAW / 冻结 / 证据锁；结论来自域权威 block_reason）
    if tool_id in _NEEDS_EDITABLE_LAYER or tool_id in _NEEDS_EDITING:
        if layer.frozen:
            return _no(layer.block_reason or "当前结果已冻结——需先解除冻结或另存草稿")
        if layer.editable is False:
            return _no(layer.block_reason or "当前图层不可编辑")
        if layer.editable is None and layer.layer_id is not None:
            return _no("当前图层可编辑性未知")

    # 5) 阶段（组隐藏 → 动作白名单）
    group = _group_of(tool_id)
    if (
        group in _NEEDS_LAYER_GROUPS
        and layer.layer_id is None
        and tool_id not in {"layer_new", "reference_import"}
    ):
        return _hidden("当前无活动图层——该工具组未显示")
    group_visibility = _stage_group_visibility_for(ctx.stage)
    group = _group_of(tool_id)
    if group_visibility is not None and not group_visibility.get(group, True):
        return _hidden(f"当前阶段不提供该工具组（{_stage_label(ctx.stage) if ctx.stage else '阶段未知'}）")
    whitelist = _STAGE_ACTION_WHITELIST.get(tool_id)
    if whitelist is not None:
        stage_avail = _stage_gate(ctx.stage, whitelist)
        if stage_avail is not None:
            return stage_avail
    stage_action_avail = _edit_action_stage_gate(tool_id, ctx.stage)
    if stage_action_avail is not None:
        return stage_action_avail

    # 6) 基础使能（导航历史 / 选择 / 图层泛用）
    if tool_id == "previous_extent" and not ctx.can_previous_extent:
        return _no("没有上一视图")
    if tool_id == "next_extent" and not ctx.can_next_extent:
        return _no("没有下一视图")
    if tool_id in {"select_all", "invert_selection"}:
        if not ctx.has_active_vector_layer:
            return _no("当前无活动矢量图层")
    if tool_id == "layer_new" or tool_id == "reference_import":
        return ToolAvailability(enabled=True)
    if tool_id in {"layer_properties", "symbology", "layer_zoom", "layer_export"}:
        return ToolAvailability(enabled=True)
    if tool_id == "qa_run":
        return ToolAvailability(enabled=True)

    # 7) 编辑会话
    if tool_id in _NEEDS_EDITING and not ctx.editing:
        return _no("需要先开始编辑")
    if tool_id == "toggle_editing":
        if not ctx.has_active_vector_layer:
            return _no("没有活动的矢量图层")
        if not ctx.vector_layer_writable:
            reason = (ctx.layer.block_reason if ctx.layer else None) or "活动图层为只读数据源，不能开启编辑会话"
            return _no(reason)
        return ToolAvailability(enabled=True)

    # 8) 几何类型（捕获工具 vs 活动图层 kind）
    kind_gate = _kind_gate(tool_id, layer)
    if kind_gate is not None:
        return kind_gate

    # 9) 选择 / 撤销栈 / 拓扑
    if tool_id in {"undo", "redo"}:
        if tool_id == "undo" and not ctx.can_undo:
            return _no("没有可撤销的操作")
        if tool_id == "redo" and not ctx.can_redo:
            return _no("没有可重做的操作")
    if tool_id == "delete_selected" and ctx.selected_count <= 0:
        return _no("当前选择不满足条件（未选中要素）")
    if tool_id == "split":
        ready = ctx.split_inputs_ready
        if ready is None:
            ready = ctx.selected_count > 0
        if not ready:
            return _no("当前选择不满足分割条件（需选中多边形与切割线）")
    if tool_id == "merge":
        if ctx.topology_error_count > 0:
            return _no("当前编辑会话存在拓扑错误，不能合并")
        if ctx.compatible_polygon_count < 2:
            return _no("当前选择不满足合并条件（需至少 2 个兼容多边形）")

    return ToolAvailability(enabled=True)


def availability_for_context(ctx: ToolContext) -> dict[str, ToolAvailability]:
    """全工具面可用性（工具条/菜单一次刷新；dict 差分消费）。"""
    return {tool: evaluate_tool(tool, ctx) for tool in _ALL_TOOLS}


def stage_group_visibility(stage_value: str | None) -> dict[str, bool]:
    """该阶段的组可见性（全组条目；None = 无阶段语义全可见）。"""
    overrides = _stage_group_visibility_for(stage_value)
    if overrides is None:
        # 未知阶段值：fail-closed，仅基础组。
        return {
            group: group in {"navigate", "selection", "inspection", "layer"}
            for group in TOOL_GROUPS
        }
    return {group: overrides.get(group, True) for group in TOOL_GROUPS}


# ---------------------------------------------------------------------------
# 内部门禁实现
# ---------------------------------------------------------------------------


def _stage_group_visibility_for(stage_value: str | None) -> dict[str, bool] | None:
    # None = 该表面没有阶段语义（legacy 编图页等）——不做组过滤。
    if stage_value is None:
        return {}
    if stage_from_value(stage_value) is None:
        return None  # 未知阶段值：组门禁交给动作门禁 fail-closed
    overrides = _STAGE_GROUP_VISIBILITY.get(stage_value, {})
    return {group: overrides.get(group, True) for group in TOOL_GROUPS}


def _stage_gate(stage_value: str | None, whitelist: frozenset[str]) -> ToolAvailability | None:
    if stage_value is None:
        return None  # 无阶段语义的表面不受白名单约束
    if stage_value not in whitelist:
        labels = "/".join(_stage_label(v) for v in whitelist)
        return _no(f"当前阶段不允许该操作（限 {labels}）")
    return None


def _edit_action_stage_gate(
    tool_id: str, stage_value: str | None
) -> ToolAvailability | None:
    """编辑/数字化动作的阶段过滤（真源 StageToolProfile.edit_actions）。

    受治理全集外的动作不受阶段限制；阶段外动作在工具条隐藏、palette 禁用
    （同一 reason，呈现分工由表面决定）。``stage=None``（表面无阶段语义，
    如 legacy 编图页）不过滤；未知阶段值 fail-closed。
    """
    from paleo_workbench.mapping_workspace.stage_profiles import (
        governed_edit_actions,
        stage_profile,
    )

    if tool_id not in governed_edit_actions():
        return None
    if stage_value is None:
        return None
    stage = stage_from_value(stage_value) if stage_value else None
    if stage is None:
        return _hidden("当前编图阶段未知")
    if not stage_profile(stage).tools.allows_edit_action(tool_id):
        return _hidden(f"当前阶段不允许此编辑动作（限 {_stage_label(stage.value)}）")
    return None


def _kind_gate(tool_id: str, layer: LayerCapabilitySnapshot) -> ToolAvailability | None:
    if tool_id not in {"add_point", "add_line", "add_polygon"}:
        return None
    expected = {"add_point": "point", "add_line": "line", "add_polygon": "polygon"}[tool_id]
    kind = str(layer.kind or "")
    if not kind:
        # fail-closed（R1-P2）：未知几何类型不放开捕获工具（空图层/快照
        # 未就绪时启用三支捕获工具是假可用）。
        return _no("活动图层几何类型未知——不能确定可用的捕获工具")
    if kind != expected:
        return _no(
            f"仅对{LAYER_CAPTION(expected)}图层有效（活动图层为{LAYER_CAPTION(kind)}图层，不能使用添加{LAYER_CAPTION(expected)}）"
        )
    # 线角色图层上的 add_polygon（kind 已匹配但角色为线角色）——防「抢主位」。
    if expected == "polygon" and layer.role in _LINE_ROLES and kind == "polygon":
        return _no(f"当前编辑目标为线要素角色（{layer.role_label or '线约束'}），应使用添加线")
    if expected == "line" and layer.role in _POLYGON_ROLES and kind == "line":
        return _no(f"当前编辑目标为面要素角色（{layer.role_label or '边界/掩膜'}），应使用添加面")
    return None


def _group_of(tool_id: str) -> str:
    for group, members in TOOL_GROUPS.items():
        if tool_id in members:
            return group
    return ""


# ---------------------------------------------------------------------------
# UIContextSnapshot 适配（palette / 状态条共用单一求值）
# ---------------------------------------------------------------------------


def tool_context_from_ui_snapshot(snap: object) -> ToolContext:
    """UIContextSnapshot（鸭子类型）→ ToolContext（palette applicability 用）。

    快照缺少的输入（选择数/撤销栈等）按保守值处理——palette 不提供这些
    动作，保守值只为 reason 服务，不影响正确性。
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
    layer = LayerCapabilitySnapshot(
        layer_id=_get("active_layer_id", None),
        role=_get("active_layer_role", None),
        kind=_get("active_layer_kind", None),
        maturity=_get("active_layer_maturity", None),
        editable=_get("active_layer_editable", None),
        block_reason=_get("active_layer_block_reason", None),
        frozen=bool(_get("active_layer_frozen", False)),
    )
    return ToolContext(
        project_open=bool(_get("project_open", False)),
        stage=_get("mapping_stage", None),
        layer=layer,
        has_active_vector_layer=_get("active_layer_id", None) is not None,
        vector_layer_writable=bool(_get("active_layer_editable", False)),
        editing=bool(_get("editing_active", False)),
        capability=QgisCapabilitySnapshot(
            mode=str(mode), reason=str(_get("capability_reason", "") or "")
        ),
        write_granted=bool(_get("write_granted", False)),
    )


def derived_context(**changes) -> ToolContext:
    """测试/适配辅助：基于默认上下文替换字段。"""
    return replace(ToolContext(), **changes)
