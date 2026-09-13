"""系统分组注册表：稳定组 id、阶段归属、角色路由与旧工程迁移。

组身份（group identity）不依赖显示名——``group_id`` 是稳定标识
（``phase1.initial_facies`` / ``factor.<task_id>`` …），显示名仅用于 UI。

**Union tree 设计**（V5 §38/§39 的 One Layer Identity 落地方式）：
QGIS 树是全阶段系统组 + 用户组 + factor 组的**联合树**；一个图层只出现
一次（归属其 home group），阶段切换只做组可见性增量（V5 §70），绝不
重建树/重开工程。跨阶段证据（如 Phase 2 的「上阶段成果」= Phase 1 的
``phase1.interpretation`` 组在本阶段的锁定可见形态）通过组的多阶段
membership + 阶段锁定表达，而非复制图层。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from paleo_workbench.mapping_workspace.layer_roles import (
    ConstraintKind,
    LayerRole,
    layer_role_from_value,
)
from paleo_workbench.mapping_workspace.stages import MappingStage

#: 共享基础组：三个阶段都可见（井位/工区边界/地震工区/参考地理数据）。
BASE_REFERENCE_GROUP_ID = "base.reference"
#: 旧工程保守归类的兜底组。
LEGACY_GROUP_ID = "legacy.unclassified"
#: factor 子组的父组。
FACTOR_ROOT_GROUP_ID = "phase2.factors"

#: 已知的基础工区图层 id 前缀（``workarea_map_snapshot``，非显示名判断）。
BASE_LAYER_ID_PREFIXES = ("home_workarea:",)

#: UserVectorLayer.template → ConstraintKind（模板键是 machine-readable
#: 元数据，不是显示名——用于旧工程约束线的保守归类）。
_TEMPLATE_CONSTRAINT_KINDS: dict[str, ConstraintKind] = {
    "provenance": ConstraintKind.PROVENANCE_LINE,
    "物源线": ConstraintKind.PROVENANCE_LINE,
    "物源": ConstraintKind.PROVENANCE_LINE,
    "distribution": ConstraintKind.DISTRIBUTION_LINE,
    "展布线": ConstraintKind.DISTRIBUTION_LINE,
    "shoreline": ConstraintKind.PALEO_SHORELINE,
    "古岸线": ConstraintKind.PALEO_SHORELINE,
    "岸线": ConstraintKind.PALEO_SHORELINE,
    "facies_boundary": ConstraintKind.FACIES_BOUNDARY,
    "相带边界": ConstraintKind.FACIES_BOUNDARY,
    "fault": ConstraintKind.FAULT,
    "断层": ConstraintKind.FAULT,
    "断层线": ConstraintKind.FAULT,
    "boundary": ConstraintKind.INTERPOLATION_BOUNDARY,
    "成图范围": ConstraintKind.INTERPOLATION_BOUNDARY,
    "mask": ConstraintKind.MASK,
    "排除区": ConstraintKind.EXCLUSION_AREA,
}


@dataclass(frozen=True)
class GroupTemplate:
    """系统组模板（纯数据；实例化为 QGIS 组由 LayerGroupController 执行）。"""

    group_id: str
    title: str
    #: 联合树中的排序位置（小者在上；相邻间隔 10 便于插入）。
    order: int
    #: 该组在哪些阶段默认可见（阶段显隐 profile 的默认值来源）。
    stages: frozenset[MappingStage]
    #: 该组在哪些阶段默认锁定（禁止修改 child geometry；不影响显示）。
    locked_stages: frozenset[MappingStage] = frozenset()
    kind: str = "system"  # "system" | "user"
    #: 父组 id（"" = 根）；factor 子组挂在 FACTOR_ROOT_GROUP_ID 下。
    parent_id: str = ""
    description: str = ""

    def stage_visible(self, stage: MappingStage) -> bool:
        return stage in self.stages

    def stage_locked(self, stage: MappingStage) -> bool:
        return stage in self.locked_stages

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "title": self.title,
            "order": self.order,
            "stages": sorted(s.value for s in self.stages),
            "locked_stages": sorted(s.value for s in self.locked_stages),
            "kind": self.kind,
            "parent_id": self.parent_id,
            "description": self.description,
        }


P1 = MappingStage.FACIES_CALIBRATION
P2 = MappingStage.CONSTRAINT_FACTOR
P3 = MappingStage.INTEGRATED_COMPILATION
ALL_STAGES = frozenset((P1, P2, P3))

#: 系统组注册表。联合树排序（order 小者在上=渲染在上）：
#: 编图要素/QC 最上，综合解释次之，解释与约束居中，预测/相图靠下，
#: 基础参考垫底——同时满足三个阶段的纵向视觉顺序。
SYSTEM_GROUP_TEMPLATES: tuple[GroupTemplate, ...] = (
    GroupTemplate(
        group_id="phase3.cartography", title="编图要素", order=10, stages=frozenset({P3}),
        description="标题/图例/比例尺/指北针/注记/数据来源等成图组件",
    ),
    GroupTemplate(
        group_id="phase3.qc", title="QA / QC", order=20, stages=frozenset({P3}),
        description="冲突区域/低置信度/空洞/拓扑错误/过期输入/待审核",
    ),
    GroupTemplate(
        group_id="phase3.integrated", title="综合解释", order=30, stages=frozenset({P3}),
        description="综合沉积相/相带边界/沉积体系/物源体系/专家修编（可编辑）",
    ),
    GroupTemplate(
        group_id="phase3.geology", title="地质表达", order=40, stages=frozenset({P3}),
        description="井/断层/物源方向/相带符号/地质符号/专题标注",
    ),
    GroupTemplate(
        group_id="phase1.interpretation", title="人工解释与修编", order=50,
        stages=ALL_STAGES, locked_stages=frozenset({P2, P3}),
        description="沉积相解释面/相带边界/解释注记；在②③阶段作为上阶段证据锁定",
    ),
    GroupTemplate(
        group_id="phase2.constraints", title="地质约束", order=60,
        stages=frozenset({P2, P3}), locked_stages=frozenset({P3}),
        description="物源方向/物源线/展布线/古岸线/相带控制线/断层/插值边界/Mask",
    ),
    GroupTemplate(
        group_id=FACTOR_ROOT_GROUP_ID, title="单因素图", order=70,
        stages=frozenset({P2, P3}), locked_stages=frozenset({P3}),
        description="各单因素任务的 nested factor 组（输入/栅格/等值线/分级/QC）",
    ),
    GroupTemplate(
        group_id="phase1.well_predictions", title="测井预测相", order=80,
        stages=frozenset({P1}),
        description="测井预测相/预测概率/低置信度/QC（模型结果，不可编辑）",
    ),
    GroupTemplate(
        group_id="phase1.seismic_predictions", title="地震预测相", order=90,
        stages=frozenset({P1}),
        description="地震预测相/预测概率/低置信度/QC（模型结果，不可编辑）",
    ),
    GroupTemplate(
        group_id="phase2.analysis", title="分析辅助", order=100, stages=frozenset({P2}),
        description="插值残差/不确定性/异常点/数据覆盖范围",
    ),
    GroupTemplate(
        group_id="phase1.initial_facies", title="初始沉积相", order=110,
        stages=frozenset({P1, P2}),
        description="原始初始相图（RAW，锁定）与当前相图底图",
    ),
    GroupTemplate(
        group_id="phase1.aux", title="辅助图层", order=120, stages=frozenset({P1}),
        description="Phase 1 杂项辅助",
    ),
    GroupTemplate(
        group_id=BASE_REFERENCE_GROUP_ID, title="基础与参考", order=900,
        stages=ALL_STAGES,
        description="工区边界/井位/地震工区/参考地理数据（全阶段共享）",
    ),
    GroupTemplate(
        group_id=LEGACY_GROUP_ID, title="未分类（旧工程）", order=950,
        stages=ALL_STAGES,
        description="旧工程无法保守归类图层的兜底组；不猜测科学语义",
    ),
)

_SYSTEM_GROUPS_BY_ID: dict[str, GroupTemplate] = {
    template.group_id: template for template in SYSTEM_GROUP_TEMPLATES
}

#: factor 组内子层顺序（输入→栅格→等值线→分级→不确定性→QC）。
FACTOR_CHILD_ORDER: tuple[LayerRole, ...] = (
    LayerRole.FACTOR_INPUT,
    LayerRole.FACTOR_GRID,
    LayerRole.FACTOR_CONTOUR,
    LayerRole.FACTOR_CLASSIFICATION,
    LayerRole.FACTOR_UNCERTAINTY,
    LayerRole.FACTOR_QC,
)


def system_group_template(group_id: str) -> GroupTemplate | None:
    return _SYSTEM_GROUPS_BY_ID.get(group_id)


def system_group_templates_for_stage(stage: MappingStage) -> tuple[GroupTemplate, ...]:
    """该阶段默认可见的系统组（含共享组），按联合树顺序。"""
    return tuple(
        template for template in SYSTEM_GROUP_TEMPLATES if template.stage_visible(stage)
    )


def factor_group_id(factor_task_id: str) -> str:
    """factor 任务 → 稳定组 id（绑定 factor_task_id，与显示名解耦）。"""
    sanitized = str(factor_task_id or "").strip().replace(" ", "_")
    return f"factor.{sanitized}" if sanitized else ""


def factor_group_title(factor_name: str, factor_type: str = "") -> str:
    return str(factor_name or factor_type or "单因素").strip()


def is_factor_group(group_id: str) -> bool:
    return str(group_id or "").startswith("factor.")


def factor_task_of_group(group_id: str) -> str | None:
    if is_factor_group(group_id):
        return str(group_id)[len("factor."):]
    return None


#: 角色 → home group（图层在联合树中的唯一归属）。
#: QC/辅助类角色按「创建阶段的 aux/qc 组」路由，需带 stage 提示。
_ROLE_HOME_GROUP: dict[LayerRole, str] = {
    LayerRole.BASE_REFERENCE: BASE_REFERENCE_GROUP_ID,
    LayerRole.INITIAL_FACIES_SOURCE: "phase1.initial_facies",
    LayerRole.INITIAL_FACIES_DRAFT: "phase1.interpretation",
    LayerRole.WELL_FACIES_PREDICTION: "phase1.well_predictions",
    LayerRole.WELL_FACIES_CONFIDENCE: "phase1.well_predictions",
    LayerRole.SEISMIC_FACIES_PREDICTION: "phase1.seismic_predictions",
    LayerRole.SEISMIC_FACIES_CONFIDENCE: "phase1.seismic_predictions",
    LayerRole.INTERPRETATION_ANNOTATION: "phase1.interpretation",
    LayerRole.PENDING_REVIEW_AREA: "phase1.interpretation",
    LayerRole.PROVENANCE_DIRECTION: "phase2.constraints",
    LayerRole.PROVENANCE_LINE: "phase2.constraints",
    LayerRole.DISTRIBUTION_LINE: "phase2.constraints",
    LayerRole.PALEO_SHORELINE: "phase2.constraints",
    LayerRole.FACIES_BOUNDARY: "phase2.constraints",
    LayerRole.FAULT_CONSTRAINT: "phase2.constraints",
    LayerRole.INTERPOLATION_BOUNDARY: "phase2.constraints",
    LayerRole.MASK_BOUNDARY: "phase2.constraints",
    LayerRole.ANALYSIS_AID: "phase2.analysis",
    LayerRole.INTEGRATED_FACIES: "phase3.integrated",
    LayerRole.INTEGRATED_BOUNDARY: "phase3.integrated",
    LayerRole.MAP_ANNOTATION: "phase3.cartography",
    LayerRole.MAP_SYMBOL: "phase3.geology",
    LayerRole.MAP_REFERENCE: "phase3.geology",
    LayerRole.QC_WARNING: "phase3.qc",
    LayerRole.QC_CONFLICT: "phase3.qc",
    LayerRole.USER_GENERAL: LEGACY_GROUP_ID,
    LayerRole.LEGACY_UNCLASSIFIED: LEGACY_GROUP_ID,
}

#: QC/辅助角色在不同创建阶段的去处。
_STAGE_AUX_GROUP: dict[MappingStage, str] = {
    P1: "phase1.aux",
    P2: "phase2.analysis",
    P3: "phase3.qc",
}


def home_group_for_role(
    role: LayerRole | str | None,
    stage: MappingStage | None = None,
    factor_task_id: str = "",
) -> str:
    """角色 → home group id。

    factor 系角色在带 ``factor_task_id`` 时返回该任务的 factor 子组；
    QC/辅助角色带 ``stage`` 时按创建阶段路由。
    """
    resolved = layer_role_from_value(role)
    if resolved is None:
        return LEGACY_GROUP_ID
    if resolved in (LayerRole.FACTOR_INPUT, LayerRole.FACTOR_GRID,
                    LayerRole.FACTOR_CONTOUR, LayerRole.FACTOR_CLASSIFICATION,
                    LayerRole.FACTOR_UNCERTAINTY, LayerRole.FACTOR_QC):
        return factor_group_id(factor_task_id) or FACTOR_ROOT_GROUP_ID
    if resolved in (LayerRole.QC_WARNING, LayerRole.QC_CONFLICT, LayerRole.ANALYSIS_AID):
        if stage is not None:
            return _STAGE_AUX_GROUP.get(stage, _ROLE_HOME_GROUP[resolved])
    return _ROLE_HOME_GROUP.get(resolved, LEGACY_GROUP_ID)


def stages_for_role(role: LayerRole) -> frozenset[MappingStage]:
    """角色的阶段 membership（= 其 home 组的阶段集合；共享组=全阶段）。

    membership ≠ visibility：Sand Thickness 属于 P2/P3，但 P3 当前可以
    hidden（V5 §39）。
    """
    resolved = layer_role_from_value(role)
    if resolved is None:
        return ALL_STAGES
    if resolved in (LayerRole.FACTOR_INPUT, LayerRole.FACTOR_GRID,
                    LayerRole.FACTOR_CONTOUR, LayerRole.FACTOR_CLASSIFICATION,
                    LayerRole.FACTOR_UNCERTAINTY, LayerRole.FACTOR_QC):
        return frozenset({P2, P3})
    home = _ROLE_HOME_GROUP.get(resolved, LEGACY_GROUP_ID)
    template = _SYSTEM_GROUPS_BY_ID.get(home)
    return template.stages if template else ALL_STAGES


def movable_into_system_group(role: LayerRole | str | None, group_id: str) -> bool:
    """拖放校验：角色的图层能否移入目标系统组（V5 §51）。

    系统组的语义由角色路由管理：把 SandThickness Grid 拖进
    ``phase1.well_predictions`` 不会改变科学角色——因此**拒绝**进入
    语义不相容的系统组；用户自定义组始终允许（只改变视觉组织）。
    """
    resolved = layer_role_from_value(role)
    if resolved is None:
        return True
    template = _SYSTEM_GROUPS_BY_ID.get(group_id)
    if template is None or template.kind != "system":
        return True  # 用户组/未知组：自由组织
    if group_id in (BASE_REFERENCE_GROUP_ID, LEGACY_GROUP_ID):
        return True
    if is_factor_group(group_id):
        return resolved in (
            LayerRole.FACTOR_INPUT, LayerRole.FACTOR_GRID, LayerRole.FACTOR_CONTOUR,
            LayerRole.FACTOR_CLASSIFICATION, LayerRole.FACTOR_UNCERTAINTY,
            LayerRole.FACTOR_QC,
        )
    return home_group_for_role(resolved) == group_id


# ---------------------------------------------------------------------------
# 旧工程迁移（V5 §72/§73）：保守归类，绝不因猜测名字改变科学语义
# ---------------------------------------------------------------------------

#: 模板键 → 专业归属角色（classify 第 4 步；新建层按模板直接进工作流
#: 组——断层→地质约束、物源/展布/方向/打断→各约束线、测井点→地质表达、
#: 相带三级→人工解释与修编、成图范围→地质表达。无映射才落未分类）。
_TEMPLATE_ROLE_HOME: dict[str, LayerRole] = {
    "fault": LayerRole.FAULT_CONSTRAINT,
    "source": LayerRole.PROVENANCE_LINE,
    "spreading": LayerRole.DISTRIBUTION_LINE,
    "direction": LayerRole.PROVENANCE_DIRECTION,
    "break": LayerRole.INTERPOLATION_BOUNDARY,
    "well_point": LayerRole.MAP_SYMBOL,
    "facies_sub": LayerRole.INITIAL_FACIES_DRAFT,
    "facies_micro": LayerRole.INITIAL_FACIES_DRAFT,
    "extent": LayerRole.MAP_REFERENCE,
}


def classify_layer_for_migration(layer) -> tuple[LayerRole, str, str]:
    """旧工程图层 / 新建图层 → (role, home_group_id, constraint_kind)。

    只依据 **machine-readable** 信号保守归类：
    1. 新元数据 ``layer.metadata["layer_role"]``（已是 V5 工程）；
    2. ``home_workarea:`` id 前缀 → 基础参考；
    3. 参考图层（metadata.reference）→ 基础参考；
    4. 模板键（metadata.template 或 UserVectorLayer.template）→ 专业
       归属组（约束线/相带/测井点/成图范围各回各组——新建层立即可见
       于其工作流组，不再坠入底部「未分类」）；
    5. 全部未命中 → LEGACY_UNCLASSIFIED（进兜底组，不猜名字）。
    """
    metadata = dict(getattr(layer, "metadata", None) or {})
    explicit = layer_role_from_value(metadata.get("layer_role"))
    if explicit is not None:
        return explicit, home_group_for_role(explicit), ""

    layer_id = str(getattr(layer, "id", "") or "")
    if layer_id.startswith(BASE_LAYER_ID_PREFIXES):
        return LayerRole.BASE_REFERENCE, BASE_REFERENCE_GROUP_ID, ""

    if metadata.get("reference") == "true":
        return LayerRole.BASE_REFERENCE, BASE_REFERENCE_GROUP_ID, ""

    # 快照的模板键在 metadata.template（UserVectorLayer 持久化记录才是
    # .template 属性）——两处都读，缺一会让新建层误入未分类组。
    template_key = str(
        metadata.get("template") or getattr(layer, "template", "") or ""
    ).strip().lower()
    if template_key:
        kind = _TEMPLATE_CONSTRAINT_KINDS.get(template_key)
        if kind is not None:
            return kind.layer_role, "phase2.constraints", kind.value
        role = _TEMPLATE_ROLE_HOME.get(template_key)
        if role is not None:
            return role, home_group_for_role(role), ""
        if template_key in ("facies", "相图", "沉积相", "facies_polygon"):
            return LayerRole.INITIAL_FACIES_DRAFT, "phase1.interpretation", ""

    return LayerRole.LEGACY_UNCLASSIFIED, LEGACY_GROUP_ID, ""


def default_group_visibility(stage: MappingStage) -> dict[str, bool]:
    """阶段默认组显隐 profile（组 id → 可见；省略 = 保持模板默认）。

    首次进入阶段应用；用户随后的一切显隐修改记录在 StageViewState，
    切走再回不覆盖（V5 §37）。
    """
    return {
        template.group_id: template.stage_visible(stage)
        for template in SYSTEM_GROUP_TEMPLATES
    }
