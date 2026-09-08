"""M4 — Contextual Help / Explainability：从 canonical contract 派生的帮助系统。

设计约束（Goal V8 M4）：

* **全部动态事实来自 evaluator**：availability / disabled reason / checked
  由 ``evaluate_tool`` 求值，本模块绝不维护第二份状态表、绝不改写判词；
* **静态事实登记处在 ``mapping.tool_help``**（纯数据叶子模块，避免
  workstation 包 __init__ 的 import 环）——名称/前置条件/执行影响/是否改
  数据/新版本/后台任务/快捷键/适用阶段与图层类型；
* 消费面：toolbar tooltip / statusTip / palette details / Inspector hint /
  空态引导 / Agent 动作发现——统一经 :func:`explain` / 格式化函数。
"""
from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.mapping.tool_availability import (
    ToolAvailability,
    evaluate_tool,
)
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.mapping.tool_help import (
    TOOL_HELP,
    TOOL_LABELS,
    TOOL_SHORTCUTS,
    ToolHelpSpec,
)

__all__ = [
    "ActionExplanation",
    "TOOL_HELP",
    "TOOL_LABELS",
    "TOOL_SHORTCUTS",
    "explain",
    "format_details",
    "format_status",
    "format_tooltip",
]


@dataclass(frozen=True, slots=True)
class ActionExplanation:
    """某上下文下某动作的完整可解释记录（全部字段可渲染）。"""

    tool_id: str
    label: str
    availability: ToolAvailability
    requirements: str
    missing: str            # 当前缺失条件（= evaluator 判词；可用时空）
    impact: str
    modifies_data: bool
    creates_version: bool
    background_task: bool
    shortcut: str
    stages: str
    layer_kinds: str
    current_layer: str      # 当前活动图层名（呈现）
    current_stage: str      # 当前阶段（呈现）

    @property
    def available(self) -> bool:
        return self.availability.enabled


def _stage_caption(value: str | None) -> str:
    if value is None:
        return "无阶段语义（legacy 表面）"
    from paleo_workbench.mapping_workspace.stages import stage_from_value

    stage = stage_from_value(value)
    return stage.label if stage is not None else f"未知阶段（{value!r}）"


def explain(tool_id: str, ctx: ToolContext, *, layer_name: str = "") -> ActionExplanation:
    """组装一个动作的上下文帮助（动态结论全部来自 canonical evaluator）。"""
    spec = TOOL_HELP.get(tool_id)
    if spec is None:
        spec = ToolHelpSpec(
            label=tool_id, requirements="未知工具", impact="—",
            modifies_data=False, creates_version=False, background_task=False,
            stages="—", layer_kinds="—",
        )
    availability = evaluate_tool(tool_id, ctx)
    return ActionExplanation(
        tool_id=tool_id,
        label=spec.label,
        availability=availability,
        requirements=spec.requirements,
        missing=availability.disabled_reason,
        impact=spec.impact,
        modifies_data=spec.modifies_data,
        creates_version=spec.creates_version,
        background_task=spec.background_task,
        shortcut=TOOL_SHORTCUTS.get(tool_id, ""),
        stages=spec.stages,
        layer_kinds=spec.layer_kinds,
        current_layer=layer_name or ctx.layer_name,
        current_stage=_stage_caption(ctx.mapping_stage),
    )


# ---------------------------------------------------------------------------
# 格式化（tooltip / statusTip / palette details / inspector hint 共用）
# ---------------------------------------------------------------------------


def format_tooltip(explanation: ActionExplanation) -> str:
    """工具条 tooltip：名称 + 状态 + 原因（+快捷键）。"""
    parts = [explanation.label]
    if explanation.shortcut:
        parts[0] = f"{explanation.label}（{explanation.shortcut}）"
    if not explanation.available:
        parts.append(f"不可用：{explanation.missing}")
        parts.append(f"需要：{explanation.requirements}")
    return "\n".join(parts)


def format_status(explanation: ActionExplanation) -> str:
    """状态条/statusTip 一行式。"""
    if explanation.available:
        return f"{explanation.label}：{explanation.impact}"
    return f"{explanation.label}（不可用：{explanation.missing}）"


def format_details(explanation: ActionExplanation) -> str:
    """palette details / Inspector hint 的多行完整解释。"""
    lines = [
        f"{explanation.label} —— {'可用' if explanation.available else '不可用'}",
        f"影响：{explanation.impact}",
        f"前置条件：{explanation.requirements}",
    ]
    if not explanation.available:
        lines.append(f"当前缺失：{explanation.missing}")
    lines.append(f"适用阶段：{explanation.stages}｜图层：{explanation.layer_kinds}")
    flags = []
    if explanation.modifies_data:
        flags.append("修改数据")
    if explanation.creates_version:
        flags.append("生成新版本")
    if explanation.background_task:
        flags.append("后台任务")
    lines.append("属性：" + ("、".join(flags) if flags else "只读操作"))
    if explanation.current_layer:
        lines.append(f"当前图层：{explanation.current_layer}")
    lines.append(f"当前阶段：{explanation.current_stage}")
    if explanation.shortcut:
        lines.append(f"快捷键：{explanation.shortcut}")
    return "\n".join(lines)
