"""``StageProfile``：阶段的编排配置（纯数据注册表，便于单元测试）。

Stage 与 ``WorkstationLayoutPreset`` 严格解耦（V5 §6）：

* ``StageProfile`` 描述**工作上下文**（默认组显隐、默认编辑对象、
  工具集合、推荐 dock 配置）；
* ``WorkstationLayoutPreset`` 仍是用户窗口布局偏好（通用工作区形态）；
* 实际 dock 布局 = ``StageProfile.recommended_docks`` + 用户阶段布局
  override（QSettings）→ 有效布局；阶段只「建议」首次 dock 组合，
  绝不锁死用户布局。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from paleo_workbench.mapping_workspace.layer_groups import (
    SYSTEM_GROUP_TEMPLATES,
    default_group_visibility,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import STAGE_ORDER, MappingStage
from paleo_workbench.mapping_workspace.stage_vocabulary import (
    stage_context_action_ids,
)


@dataclass(frozen=True)
class StageToolProfile:
    """阶段工具集合（基础 pan/zoom/select/identify 永远保留，不在此列）。

    ``edit_actions`` 是综合编修工具条的阶段过滤真源（V6 §4：composite
    toolbar 按此隐藏非本阶段的数字化/编辑动作；基础导航/识别/选择动作
    不经过该过滤。V7 D3 删除了零消费者的 ``command_groups``——分组 IA
    由 mapping.tool_availability.TOOL_GROUPS 承担（V8 起 canonical；
    ui.workstation.tool_surface 仅 re-export）。
    """

    #: 本阶段可用的数字化/编辑动作 id（existing MapActionController ids）。
    edit_actions: tuple[str, ...] = ()
    #: 阶段专属上下文动作 id（V10 起从 ``stage_vocabulary`` 派生——
    #: profile 与 panel/palette/dispatcher 共用同一份词表，结构上不再
    #: 漂移；此前三处手维护表互不推导）。
    context_actions: tuple[str, ...] = ()

    def allows_edit_action(self, action_id: str) -> bool:
        """该编辑/数字化动作在本阶段是否可用（空集合 = 不做阶段过滤）。"""
        if not self.edit_actions:
            return True
        return action_id in self.edit_actions


@dataclass(frozen=True)
class StageProfile:
    """一个编图阶段的完整编排配置。"""

    stage: MappingStage
    #: 阶段标题/说明（来自 MappingStage；此处冗余存储便于 profile 自足）。
    label: str
    description: str
    #: 首次进入该阶段的组显隐默认（组 id → bool）。
    group_visibility: dict[str, bool] = field(default_factory=dict)
    #: 默认激活的编辑目标角色（按优先级；首个已有图层的角色胜出）。
    active_editing_roles: tuple[LayerRole, ...] = ()
    #: 工具 profile。
    tools: StageToolProfile = StageToolProfile()
    #: 推荐 dock 配置（dock key → bool；只建议，不锁死）。
    recommended_docks: dict[str, bool] = field(default_factory=dict)
    #: 就绪度检查项 id（readiness.py 中按 id 实现）。
    readiness_checks: tuple[str, ...] = ()
    #: 阶段切换时需要保护/锁定的组（证据锁定；显示不受影响）。
    locked_groups: tuple[str, ...] = ()

    def default_visible_groups(self) -> dict[str, bool]:
        return dict(self.group_visibility)

    def default_locked_groups(self) -> tuple[str, ...]:
        return tuple(self.locked_groups)


def _profile(stage: MappingStage, **kwargs) -> StageProfile:
    defaults = dict(
        stage=stage,
        label=stage.label,
        description=stage.description,
        group_visibility=default_group_visibility(stage),
    )
    defaults.update(kwargs)
    return StageProfile(**defaults)


_STAGE_PROFILES: dict[MappingStage, StageProfile] = {
    MappingStage.FACIES_CALIBRATION: _profile(
        MappingStage.FACIES_CALIBRATION,
        active_editing_roles=(LayerRole.INITIAL_FACIES_DRAFT,),
        tools=StageToolProfile(
            edit_actions=(
                "add_polygon", "move_feature", "vertex", "split", "merge",
                "delete_selected", "undo", "redo",
            ),
            context_actions=stage_context_action_ids("facies_calibration"),
        ),
        recommended_docks={
            "composite_input": True,   # 左：输入与结果
            "composite_layer": True,   # 右：图层管理
            "inspector": True,         # 右：Inspector
            "well": False,             # 底：测井轨道（点击井预测时快速打开）
            "seismic": False,
            "composite_linked": False,
        },
        readiness_checks=(
            "target_horizon",
            "initial_facies_present", "initial_facies_crs", "initial_facies_geometry",
            "well_prediction_linked", "seismic_prediction_confidence",
            "interpretation_saved",
        ),
        locked_groups=("phase1.initial_facies",),
    ),
    MappingStage.CONSTRAINT_FACTOR: _profile(
        MappingStage.CONSTRAINT_FACTOR,
        active_editing_roles=(
            LayerRole.PROVENANCE_LINE, LayerRole.PROVENANCE_DIRECTION,
            LayerRole.DISTRIBUTION_LINE, LayerRole.PALEO_SHORELINE,
            LayerRole.FACIES_BOUNDARY, LayerRole.FAULT_CONSTRAINT,
            LayerRole.MASK_BOUNDARY, LayerRole.INTERPOLATION_BOUNDARY,
        ),
        tools=StageToolProfile(
            edit_actions=(
                "add_line", "add_polygon", "move_feature", "vertex", "split",
                "merge", "delete_selected", "undo", "redo",
            ),
            context_actions=stage_context_action_ids("constraint_factor"),
        ),
        recommended_docks={
            "composite_layer": True,
            "inspector": True,
            "composite_input": False,
            "well": False,
            "seismic": False,
            "composite_linked": False,
        },
        readiness_checks=(
            "target_horizon",
            "phase1_interpretation", "constraints_present", "factors_complete",
            "factor_staleness",
        ),
        locked_groups=("phase1.interpretation", "phase1.initial_facies"),
    ),
    MappingStage.INTEGRATED_COMPILATION: _profile(
        MappingStage.INTEGRATED_COMPILATION,
        active_editing_roles=(LayerRole.INTEGRATED_FACIES, LayerRole.INTEGRATED_BOUNDARY),
        tools=StageToolProfile(
            edit_actions=(
                "add_polygon", "add_line", "move_feature", "vertex", "split",
                "merge", "delete_selected", "undo", "redo",
            ),
            context_actions=stage_context_action_ids("integrated_compilation"),
        ),
        recommended_docks={
            "composite_layer": True,
            "inspector": True,
            "composite_input": True,    # 证据选择
            "well": False,
            "seismic": False,
            "composite_linked": False,
        },
        readiness_checks=(
            "target_horizon",
            "evidence_available", "evidence_staleness", "integrated_draft",
            "qa_geometry_errors",
        ),
        locked_groups=(
            "phase1.interpretation", "phase1.initial_facies",
            "phase2.constraints", "phase2.factors",
        ),
    ),
}


def stage_profile(stage: MappingStage) -> StageProfile:
    """取阶段 profile（未知阶段回落第一阶段——宽容但不静默：调用方应已校验）。"""
    return _STAGE_PROFILES[MappingStage(stage)]


def stage_profiles() -> tuple[StageProfile, ...]:
    """全部阶段 profile，按工作流顺序。"""
    return tuple(_STAGE_PROFILES[stage] for stage in STAGE_ORDER)


def governed_edit_actions() -> frozenset[str]:
    """受阶段过滤治理的编辑动作全集 = 各阶段 ``edit_actions`` 并集。

    不在并集内的动作（如 add_point）与基础导航/识别/选择动作一样，
    不做阶段隐藏——profile 只约束它显式声明的动作。
    """
    union: set[str] = set()
    for profile in _STAGE_PROFILES.values():
        union.update(profile.tools.edit_actions)
    return frozenset(union)


def profile_group_order() -> tuple[str, ...]:
    """联合树中系统组的稳定排序（order 升序）。"""
    return tuple(
        template.group_id
        for template in sorted(SYSTEM_GROUP_TEMPLATES, key=lambda t: t.order)
    )
