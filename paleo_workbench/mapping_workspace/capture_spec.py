"""GeologicalCaptureSpec — 角色驱动的捕获语义（V9 W9，Goal §6/§12）.

用户选择「物源方向线」这类地质捕获目标时，Paleo 负责语义（LayerRole、
阶段绑定、模板字段默认值、捕捉推荐、样式提示），QGIS/会话层负责几何
捕获本身（逐点输入、rubber band、捕捉、undo、几何校验）。本模块是这
一分工的**单一派生点**：role → (template_key, 默认属性来源, snapping
profile, 拓扑提示, 约束语义)。

不做的事（防第二真源）：

* 不复制 ``GeoTemplate`` 的字段 schema——``template_key`` 指回 UI 注册表，
  默认属性由模板 ``field_defaults()`` 派生；
* 不新建 ToolAvailability/第二门禁——evaluator 只认 ``ToolContext``；
* 不替代 stage membership 的角色权威——spec 的 role 输入来自
  ``stage_controller.state.role_of``（经控制器 ``set_role_lookup`` 注入）。
"""
from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.mapping_workspace.layer_roles import (
    ConstraintKind,
    LayerRole,
)
from paleo_workbench.mapping_workspace.snapping_profiles import (
    SnappingProfile,
    recommended_profile_for_role,
)

__all__ = ["GeologicalCaptureSpec", "capture_spec_for_role"]


@dataclass(frozen=True, slots=True)
class GeologicalCaptureSpec:
    """一个角色目标的捕获语义（ Paleo 语义层；几何执行归 QGIS/会话）。"""

    role: LayerRole
    geometry_kind: str                      # "point" | "line" | "polygon"
    template_key: str                       # GeoTemplate 注册表键（"" = 无模板）
    snapping_profile: SnappingProfile | None
    #: 拓扑编辑建议（推荐值；开闭仍由用户/阶段状态决定）。
    recommend_topological_editing: bool
    constraint_kind: ConstraintKind | None = None

    @property
    def role_label(self) -> str:
        return self.role.label


#: 角色驱动的地质捕获目标词表（Goal §12 语义的机器可读形态）。
#: template_key 对齐 composite_editing.GEO_TEMPLATES 的键词汇——
#: 未列出的可编辑角色回落 kind 默认样式（template_key=""），仍获得
#: 捕捉推荐与拓扑提示。
_CAPTURE_SPECS: dict[LayerRole, GeologicalCaptureSpec] = {
    LayerRole.PROVENANCE_DIRECTION: GeologicalCaptureSpec(
        role=LayerRole.PROVENANCE_DIRECTION,
        geometry_kind="line",
        template_key="direction",
        snapping_profile=recommended_profile_for_role(LayerRole.PROVENANCE_DIRECTION),
        recommend_topological_editing=False,
        constraint_kind=ConstraintKind.SOURCE_DIRECTION,
    ),
    LayerRole.PROVENANCE_LINE: GeologicalCaptureSpec(
        role=LayerRole.PROVENANCE_LINE,
        geometry_kind="line",
        template_key="source",
        snapping_profile=recommended_profile_for_role(LayerRole.PROVENANCE_LINE),
        recommend_topological_editing=False,
        constraint_kind=ConstraintKind.PROVENANCE_LINE,
    ),
    LayerRole.DISTRIBUTION_LINE: GeologicalCaptureSpec(
        role=LayerRole.DISTRIBUTION_LINE,
        geometry_kind="line",
        template_key="spreading",
        snapping_profile=recommended_profile_for_role(LayerRole.DISTRIBUTION_LINE),
        recommend_topological_editing=False,
        constraint_kind=ConstraintKind.DISTRIBUTION_LINE,
    ),
    LayerRole.PALEO_SHORELINE: GeologicalCaptureSpec(
        role=LayerRole.PALEO_SHORELINE,
        geometry_kind="line",
        template_key="",
        snapping_profile=recommended_profile_for_role(LayerRole.PALEO_SHORELINE),
        recommend_topological_editing=False,
        constraint_kind=ConstraintKind.PALEO_SHORELINE,
    ),
    LayerRole.FACIES_BOUNDARY: GeologicalCaptureSpec(
        role=LayerRole.FACIES_BOUNDARY,
        geometry_kind="line",
        template_key="",
        snapping_profile=recommended_profile_for_role(LayerRole.FACIES_BOUNDARY),
        recommend_topological_editing=True,
        constraint_kind=ConstraintKind.FACIES_BOUNDARY,
    ),
    LayerRole.FAULT_CONSTRAINT: GeologicalCaptureSpec(
        role=LayerRole.FAULT_CONSTRAINT,
        geometry_kind="line",
        template_key="fault",
        snapping_profile=recommended_profile_for_role(LayerRole.FAULT_CONSTRAINT),
        recommend_topological_editing=False,
        constraint_kind=ConstraintKind.FAULT,
    ),
    LayerRole.INTERPOLATION_BOUNDARY: GeologicalCaptureSpec(
        role=LayerRole.INTERPOLATION_BOUNDARY,
        geometry_kind="polygon",
        template_key="extent",
        snapping_profile=recommended_profile_for_role(LayerRole.INTERPOLATION_BOUNDARY),
        recommend_topological_editing=True,
        constraint_kind=ConstraintKind.INTERPOLATION_BOUNDARY,
    ),
    LayerRole.MASK_BOUNDARY: GeologicalCaptureSpec(
        role=LayerRole.MASK_BOUNDARY,
        geometry_kind="polygon",
        template_key="",
        snapping_profile=recommended_profile_for_role(LayerRole.MASK_BOUNDARY),
        recommend_topological_editing=True,
        constraint_kind=ConstraintKind.MASK,
    ),
    LayerRole.INITIAL_FACIES_DRAFT: GeologicalCaptureSpec(
        role=LayerRole.INITIAL_FACIES_DRAFT,
        geometry_kind="polygon",
        template_key="facies",
        snapping_profile=recommended_profile_for_role(LayerRole.INITIAL_FACIES_DRAFT),
        recommend_topological_editing=True,
    ),
    LayerRole.INTEGRATED_FACIES: GeologicalCaptureSpec(
        role=LayerRole.INTEGRATED_FACIES,
        geometry_kind="polygon",
        template_key="facies",
        snapping_profile=recommended_profile_for_role(LayerRole.INTEGRATED_FACIES),
        recommend_topological_editing=True,
    ),
    LayerRole.USER_GENERAL: GeologicalCaptureSpec(
        role=LayerRole.USER_GENERAL,
        geometry_kind="line",
        template_key="",
        snapping_profile=recommended_profile_for_role(LayerRole.USER_GENERAL),
        recommend_topological_editing=False,
    ),
}


def capture_spec_for_role(role: object) -> GeologicalCaptureSpec | None:
    """角色 → 捕获语义；无编辑语义/未知角色返回 None（不猜）。"""
    parsed: LayerRole | None
    if isinstance(role, LayerRole):
        parsed = role
    else:
        text = str(role or "").strip().lower()
        if not text:
            return None
        try:
            parsed = LayerRole(text)
        except ValueError:
            return None
    return _CAPTURE_SPECS.get(parsed)
