"""Geological Mapping Stage Workspace V5 — 阶段化编图工作区领域包。

核心架构裁决（见 ``docs/development/geological-mapping-workspace-v5/``）：

* **Stage ≠ Page**：``MappingStage`` 是工作流上下文（Workflow Context），
  不是 QWidget 页面。阶段切换只改变默认图层组显隐、默认编辑对象、
  默认 dock/panel、工具集合和工作上下文，绝不销毁/替换中央
  ``CompositeDocument``/QGIS 地图画布，也不重开 QGIS Project。
* **ONE runtime layer authority**：QGIS Layer Tree 是显示/排序/组结构的
  运行时权威；本包保存稳定的逻辑组元数据、图层角色、阶段成员资格与
  持久化意图，经 ``LayerGroupController`` 与 QGIS 树做增量 reconcile，
  绝不另造一棵与 QGIS 平行的运行时可变树。
* **纯领域**：本包不 import Qt / QGIS —— 可独立单元测试。UI 装配在
  ``paleo_workbench/ui/workstation/``（stage bar / stage panel），Qt 侧
  controller 装配在 ``controller.py``/``layer_group_controller.py``。

模块地图：

- ``stages``: ``MappingStage`` 枚举与阶段序。
- ``layer_roles``: ``LayerRole``/``ConstraintKind`` 稳定角色词表。
- ``layer_tree``: ``LayerTreeSnapshot`` 可序列化领域表示（非运行时权威）。
- ``layer_groups``: 系统组注册表 + 角色路由 + factor 组工厂 + 旧工程迁移。
- ``stage_profiles``: ``StageProfile`` 纯数据注册表（组模板/显隐/工具/dock）。
- ``stage_state``: ``MappingWorkspaceState``/``StageViewState`` 持久化模型。
- ``readiness``: 阶段就绪度（READY/READY_WITH_WARNINGS/NOT_READY）。
- ``dependencies``: 跨阶段成果 freshness（CURRENT/STALE/…，读 Catalog lineage）。
- ``controller``: ``MappingStageController``（Qt 侧编排，延迟 import Qt）。
- ``layer_group_controller``: ``LayerGroupController``（QGIS 树 reconcile）。
"""

from __future__ import annotations

from paleo_workbench.mapping_workspace.dependencies import (
    ArtifactFreshness,
    FreshnessStatus,
    MappingDependencyService,
    StaleSummary,
)
from paleo_workbench.mapping_workspace.layer_groups import (
    GroupTemplate,
    factor_group_id,
    system_group_templates_for_stage,
)
from paleo_workbench.mapping_workspace.layer_roles import ConstraintKind, LayerRole
from paleo_workbench.mapping_workspace.layer_tree import (
    GroupNode,
    LayerRef,
    LayerTreeSnapshot,
)
from paleo_workbench.mapping_workspace.stage_profiles import (
    StageProfile,
    StageToolProfile,
    stage_profile,
    stage_profiles,
)
from paleo_workbench.mapping_workspace.stage_state import (
    LayerMembershipRecord,
    MappingWorkspaceState,
    StageViewState,
)
from paleo_workbench.mapping_workspace.stages import (
    MappingStage,
    next_stage,
    previous_stage,
    stage_display_label,
)

__all__ = [
    "ArtifactFreshness",
    "ConstraintKind",
    "FreshnessStatus",
    "GroupNode",
    "GroupTemplate",
    "LayerMembershipRecord",
    "LayerRef",
    "LayerRole",
    "LayerTreeSnapshot",
    "MappingDependencyService",
    "MappingStage",
    "MappingWorkspaceState",
    "StaleSummary",
    "StageProfile",
    "StageToolProfile",
    "StageViewState",
    "factor_group_id",
    "next_stage",
    "previous_stage",
    "stage_display_label",
    "stage_profile",
    "stage_profiles",
    "system_group_templates_for_stage",
]
