"""Action Metadata Registry（V10 Milestone B）——45 个工具的正式动作元数据。

本登记处只描述动作的**静态身份**：图标、分组、风险级、呈现面偏好、
是否画布交互、是否原生专属。它**不是**第二可用性求值器——enabled/
visible/reason 永远来自 :mod:`paleo_workbench.mapping.tool_availability`
（Metadata ≠ availability）。

数据合并来源（V10 前散落三处，已收敛到此单一登记处）：

* ``tool_help.TOOL_LABELS`` / ``TOOL_SHORTCUTS`` —— 名称与快捷键（保留
  原模块作为数据叶子，本模块组合引用，不复制值）；
* ``tool_availability.TOOL_GROUPS`` —— 分组 IA（分组即语义，留在求值器）；
* ``map_action_controller._SURFACE_ICONS`` —— 扩展面图标别名（V10 起
  图标注册进入本登记处，controller 只消费）。

新增字段：

* ``risk`` —— read / selection / write / structural（Agent 面板与评审
  用；与可用性无关）；
* ``surfaces`` —— 该动作偏好的呈现面（toolbar / palette / layer_menu /
  canvas_menu / stage / shortcut）。呈现面可以超出此集合（如 palette
  额外收录），但**收敛**必须经此登记（防止 surface-only 幽灵动作）；
* ``canvas_interaction`` —— 是否为画布 MapTool（checkable，checked 跟随
  current_tool）；
* ``requires_native`` —— 是否原生后端专属（桥缺失时 disabled 而非隐藏，
  保持能力可发现）。

完整性由 ``tests/test_action_registry_v10.py`` 钉住：TOOL_IDS 全覆盖、
无重复、无 surface-only 残留。
"""
from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.mapping.tool_availability import TOOL_GROUPS, TOOL_IDS
from paleo_workbench.mapping.tool_help import TOOL_LABELS, TOOL_SHORTCUTS

__all__ = [
    "ACTION_SPECS",
    "ActionSpec",
    "action_spec",
    "surface_tools",
]


#: 风险级词表（呈现/Agent 评审用；非门禁）。
RISK_READ = "read"
RISK_SELECTION = "selection"
RISK_WRITE = "write"
RISK_STRUCTURAL = "structural"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """一个动作的静态身份登记（无可用性判断）。"""

    tool_id: str
    label: str
    group: str
    icon: str                      # assets/icons/{icon}.svg 名（map/ 优先）
    risk: str
    shortcut: str = ""
    #: 偏好呈现面（元数据；不限制 palette 的补充收录）。
    surfaces: tuple[str, ...] = ("toolbar", "palette")
    canvas_interaction: bool = False
    requires_native: bool = False


def _specs() -> dict[str, ActionSpec]:
    group_of = {
        tool: group for group, members in TOOL_GROUPS.items() for tool in members
    }
    surface_icons = {
        "layer_new": "tree-add-layer", "reference_import": "btn-import",
        "layer_properties": "tree-properties", "attribute_table": "attribute_table",
        "layer_zoom": "tree-zoom", "layer_export": "tree-export",
        "symbology": "rb-colorbar", "style_manager": "rb-settings",
        "factor_workbench": "rb-grid", "factor_overlay": "btn-contour-draft",
        "qa_run": "rb-qc", "map_product_assemble": "rb-finalize",
        "map_export": "rb-export", "repair_geometry": "btn-health",
    }
    # 画布交互工具（checked ← current_tool；与求值器 _CHECKED_CANVAS_TOOLS
    # 同集，测试钉一致）。
    canvas_tools = {
        "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
        "measure_distance", "add_point", "add_line", "add_polygon",
        "move_feature", "vertex", "reshape",
    }
    # 原生专属（桥缺失/降级时 disabled + 原因；不隐藏能力假象）。
    native_only = {"style_manager", "reshape"}
    # 写风险动作（修改图层/工程数据；Agent WRITE 授权与评审语义）。
    write_tools = {
        "toggle_editing", "save_edits", "rollback", "add_point", "add_line",
        "add_polygon", "move_feature", "vertex", "reshape", "delete_selected",
        "split", "merge", "repair_geometry", "undo", "redo", "topology",
        "layer_new", "factor_overlay", "map_product_assemble",
    }
    # 选择集动作（改选择集，不改数据）。
    selection_tools = {
        "select", "select_rectangle", "select_all", "invert_selection",
        "clear_selection",
    }
    # 结构性动作（图层/工程结构变更，不属于数据编辑会话）。
    structural_tools = {"layer_export", "reference_import", "map_export"}
    # 各面偏好的补充（默认 toolbar+palette；这里只登记例外）。
    layer_menu_tools = {
        "layer_properties", "attribute_table", "layer_zoom", "layer_export",
        "symbology", "toggle_editing", "repair_geometry", "layer_new",
        "reference_import",
    }
    canvas_menu_tools = {
        "pan", "identify", "select", "select_rectangle", "measure_distance",
        "zoom_in", "zoom_out", "full_extent", "previous_extent", "next_extent",
        "select_all", "invert_selection", "clear_selection", "toggle_editing",
        "save_edits", "snapping", "topology", "layer_properties",
        "attribute_table",
    }
    specs: dict[str, ActionSpec] = {}
    for tool_id in TOOL_IDS:
        group = group_of[tool_id]
        if tool_id in write_tools:
            risk = RISK_WRITE
        elif tool_id in selection_tools:
            risk = RISK_SELECTION
        elif tool_id in structural_tools:
            risk = RISK_STRUCTURAL
        else:
            risk = RISK_READ
        surfaces = ["toolbar", "palette"]
        if tool_id in layer_menu_tools:
            surfaces.append("layer_menu")
        if tool_id in canvas_menu_tools:
            surfaces.append("canvas_menu")
        specs[tool_id] = ActionSpec(
            tool_id=tool_id,
            label=TOOL_LABELS.get(tool_id, tool_id),
            group=group,
            icon=surface_icons.get(tool_id, tool_id),
            risk=risk,
            shortcut=TOOL_SHORTCUTS.get(tool_id, ""),
            surfaces=tuple(surfaces),
            canvas_interaction=tool_id in canvas_tools,
            requires_native=tool_id in native_only,
        )
    return specs


#: 全部动作登记（tool_id → ActionSpec；构建一次，冻结语义靠 frozen dataclass）。
ACTION_SPECS: dict[str, ActionSpec] = _specs()


def action_spec(tool_id: str) -> ActionSpec | None:
    """取一个动作的登记元数据（未知 id → None，fail-honest）。"""
    return ACTION_SPECS.get(tool_id)


def surface_tools(surface: str) -> tuple[str, ...]:
    """偏好某呈现面的动作 id（按 TOOL_IDS 稳定序）。"""
    return tuple(
        tool_id for tool_id in TOOL_IDS
        if surface in ACTION_SPECS[tool_id].surfaces
    )
