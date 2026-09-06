"""图层角色（``LayerRole``）与约束类型（``ConstraintKind``）稳定词表。

图层角色是 machine-readable 的科学语义，不由用户 rename 改变；图层组
归属（visual placement）可以调整，但角色本身只能由明确的领域动作
（如 RAW→DERIVED 建稿、factor 运行）产生。

约束类型满足 V5 目标 §22：约束对象共享 geometry 存储
（``project.models.ConstraintLine`` / ``UserVectorLayer``），但必须带
``constraint_type``；不允许把所有约束都当 generic polyline。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LayerRole(str, Enum):
    """图层科学角色（稳定 machine-readable 标识）。"""

    # 基础参考
    BASE_REFERENCE = "base_reference"
    # Phase 1
    INITIAL_FACIES_SOURCE = "initial_facies_source"      # RAW 初始沉积相图（不可编辑）
    INITIAL_FACIES_DRAFT = "initial_facies_draft"        # DERIVED 校正草稿（可编辑）
    WELL_FACIES_PREDICTION = "well_facies_prediction"    # 测井预测相（模型结果）
    WELL_FACIES_CONFIDENCE = "well_facies_confidence"    # 测井预测概率/置信度
    SEISMIC_FACIES_PREDICTION = "seismic_facies_prediction"
    SEISMIC_FACIES_CONFIDENCE = "seismic_facies_confidence"
    INTERPRETATION_ANNOTATION = "interpretation_annotation"
    PENDING_REVIEW_AREA = "pending_review_area"
    # Phase 2 约束（线/面）
    PROVENANCE_DIRECTION = "provenance_direction"        # 物源方向
    PROVENANCE_LINE = "provenance_line"                  # 物源线
    DISTRIBUTION_LINE = "distribution_line"              # 沉积体系展布线
    PALEO_SHORELINE = "paleo_shoreline"                  # 古岸线
    FACIES_BOUNDARY = "facies_boundary"                  # 相带边界/控制线
    FAULT_CONSTRAINT = "fault_constraint"                # 断层/限制边界
    INTERPOLATION_BOUNDARY = "interpolation_boundary"    # 插值限制边界
    MASK_BOUNDARY = "mask_boundary"                      # 掩膜/排除区
    # Phase 2 单因素
    FACTOR_INPUT = "factor_input"                        # 输入井点/标注
    FACTOR_GRID = "factor_grid"                          # 插值栅格
    FACTOR_CONTOUR = "factor_contour"                    # 等值线
    FACTOR_CLASSIFICATION = "factor_classification"      # 分级区
    FACTOR_UNCERTAINTY = "factor_uncertainty"            # 不确定性
    FACTOR_QC = "factor_qc"                              # QC
    ANALYSIS_AID = "analysis_aid"                        # 残差/异常点/覆盖范围
    # Phase 3
    INTEGRATED_FACIES = "integrated_facies"              # 综合沉积相（可编辑）
    INTEGRATED_BOUNDARY = "integrated_boundary"          # 综合相带边界（可编辑）
    MAP_ANNOTATION = "map_annotation"                    # 专题标注/注记
    MAP_SYMBOL = "map_symbol"                            # 相带/地质符号
    MAP_REFERENCE = "map_reference"                      # 编图参考（井/断层表达）
    # QC
    QC_WARNING = "qc_warning"
    QC_CONFLICT = "qc_conflict"
    # 用户自定义/未分类
    USER_GENERAL = "user_general"
    LEGACY_UNCLASSIFIED = "legacy_unclassified"

    @property
    def label(self) -> str:
        return ROLE_LABELS.get(self, self.value)

    @property
    def editable_by_default(self) -> bool:
        """角色默认是否允许人工几何编辑（RAW/模型结果/QC 一律 False）。"""
        return self in ROLE_EDITABLE

    @property
    def is_prediction(self) -> bool:
        return self in (LayerRole.WELL_FACIES_PREDICTION,
                        LayerRole.WELL_FACIES_CONFIDENCE,
                        LayerRole.SEISMIC_FACIES_PREDICTION,
                        LayerRole.SEISMIC_FACIES_CONFIDENCE)

    @property
    def is_raw_protected(self) -> bool:
        """RAW 不可变保护：这些角色承载原始输入或模型输出，禁止直接编辑。"""
        return self in ROLE_RAW_PROTECTED


ROLE_LABELS: dict[LayerRole, str] = {
    LayerRole.BASE_REFERENCE: "基础与参考",
    LayerRole.INITIAL_FACIES_SOURCE: "初始沉积相（原始）",
    LayerRole.INITIAL_FACIES_DRAFT: "沉积相解释（草稿）",
    LayerRole.WELL_FACIES_PREDICTION: "测井预测相",
    LayerRole.WELL_FACIES_CONFIDENCE: "测井预测置信度",
    LayerRole.SEISMIC_FACIES_PREDICTION: "地震预测相",
    LayerRole.SEISMIC_FACIES_CONFIDENCE: "地震预测置信度",
    LayerRole.INTERPRETATION_ANNOTATION: "解释注记",
    LayerRole.PENDING_REVIEW_AREA: "待确认区域",
    LayerRole.PROVENANCE_DIRECTION: "物源方向",
    LayerRole.PROVENANCE_LINE: "物源线",
    LayerRole.DISTRIBUTION_LINE: "沉积体系展布线",
    LayerRole.PALEO_SHORELINE: "古岸线",
    LayerRole.FACIES_BOUNDARY: "相带边界",
    LayerRole.FAULT_CONSTRAINT: "断层约束",
    LayerRole.INTERPOLATION_BOUNDARY: "插值限制边界",
    LayerRole.MASK_BOUNDARY: "掩膜/排除区",
    LayerRole.FACTOR_INPUT: "单因素输入井点",
    LayerRole.FACTOR_GRID: "单因素插值栅格",
    LayerRole.FACTOR_CONTOUR: "单因素等值线",
    LayerRole.FACTOR_CLASSIFICATION: "单因素分级区",
    LayerRole.FACTOR_UNCERTAINTY: "单因素不确定性",
    LayerRole.FACTOR_QC: "单因素 QC",
    LayerRole.ANALYSIS_AID: "分析辅助",
    LayerRole.INTEGRATED_FACIES: "综合沉积相",
    LayerRole.INTEGRATED_BOUNDARY: "综合相带边界",
    LayerRole.MAP_ANNOTATION: "地图注记",
    LayerRole.MAP_SYMBOL: "地图符号",
    LayerRole.MAP_REFERENCE: "编图参考",
    LayerRole.QC_WARNING: "QC 提醒",
    LayerRole.QC_CONFLICT: "QC 冲突",
    LayerRole.USER_GENERAL: "用户图层",
    LayerRole.LEGACY_UNCLASSIFIED: "未分类（旧工程）",
}

#: 默认允许人工几何编辑的角色（草稿/约束/综合解释）。
ROLE_EDITABLE: frozenset[LayerRole] = frozenset({
    LayerRole.INITIAL_FACIES_DRAFT,
    LayerRole.PROVENANCE_DIRECTION,
    LayerRole.PROVENANCE_LINE,
    LayerRole.DISTRIBUTION_LINE,
    LayerRole.PALEO_SHORELINE,
    LayerRole.FACIES_BOUNDARY,
    LayerRole.FAULT_CONSTRAINT,
    LayerRole.INTERPOLATION_BOUNDARY,
    LayerRole.MASK_BOUNDARY,
    LayerRole.INTEGRATED_FACIES,
    LayerRole.INTEGRATED_BOUNDARY,
    LayerRole.INTERPRETATION_ANNOTATION,
    LayerRole.USER_GENERAL,
})

#: RAW 不可变保护（V5 §14/§15：原始相图与模型预测绝不直接编辑，
#: 人工解释必须走 DERIVED 草稿）。
ROLE_RAW_PROTECTED: frozenset[LayerRole] = frozenset({
    LayerRole.INITIAL_FACIES_SOURCE,
    LayerRole.WELL_FACIES_PREDICTION,
    LayerRole.WELL_FACIES_CONFIDENCE,
    LayerRole.SEISMIC_FACIES_PREDICTION,
    LayerRole.SEISMIC_FACIES_CONFIDENCE,
    LayerRole.FACTOR_GRID,
    LayerRole.FACTOR_CLASSIFICATION,
})


class ConstraintKind(str, Enum):
    """typed geological constraint（V5 §22）。

    与 ``ConstraintLine.role``（break/direction/boundary/other，插值引擎
    语义）正交：``ConstraintKind`` 是地质语义，经
    :data:`CONSTRAINT_INTERPOLATION_ROLE` 映射到插值引擎角色。
    """

    SOURCE_DIRECTION = "source_direction"
    PROVENANCE_LINE = "provenance_line"
    DISTRIBUTION_LINE = "distribution_line"
    PALEO_SHORELINE = "paleo_shoreline"
    FACIES_BOUNDARY = "facies_boundary"
    FAULT = "fault"
    INTERPOLATION_BOUNDARY = "interpolation_boundary"
    MASK = "mask"
    EXCLUSION_AREA = "exclusion_area"
    TREND_LINE = "trend_line"

    @property
    def label(self) -> str:
        return CONSTRAINT_KIND_LABELS[self]

    @property
    def geometry_kind(self) -> str:
        """线/面几何亲和（约束存储建议）。"""
        return "polygon" if self in _POLYGON_CONSTRAINTS else "line"

    @property
    def layer_role(self) -> LayerRole:
        return CONSTRAINT_KIND_ROLE[self]

    @property
    def interpolation_role(self) -> str:
        """映射到 ``ConstraintLine.role`` 插值引擎语义。"""
        return CONSTRAINT_INTERPOLATION_ROLE[self]


CONSTRAINT_KIND_LABELS: dict[ConstraintKind, str] = {
    ConstraintKind.SOURCE_DIRECTION: "物源方向",
    ConstraintKind.PROVENANCE_LINE: "物源线",
    ConstraintKind.DISTRIBUTION_LINE: "沉积体系展布线",
    ConstraintKind.PALEO_SHORELINE: "古岸线",
    ConstraintKind.FACIES_BOUNDARY: "相带控制线",
    ConstraintKind.FAULT: "断层",
    ConstraintKind.INTERPOLATION_BOUNDARY: "插值限制边界",
    ConstraintKind.MASK: "掩膜",
    ConstraintKind.EXCLUSION_AREA: "排除区",
    ConstraintKind.TREND_LINE: "趋势线",
}

_POLYGON_CONSTRAINTS: frozenset[ConstraintKind] = frozenset({
    ConstraintKind.MASK,
    ConstraintKind.EXCLUSION_AREA,
})

CONSTRAINT_KIND_ROLE: dict[ConstraintKind, LayerRole] = {
    ConstraintKind.SOURCE_DIRECTION: LayerRole.PROVENANCE_DIRECTION,
    ConstraintKind.PROVENANCE_LINE: LayerRole.PROVENANCE_LINE,
    ConstraintKind.DISTRIBUTION_LINE: LayerRole.DISTRIBUTION_LINE,
    ConstraintKind.PALEO_SHORELINE: LayerRole.PALEO_SHORELINE,
    ConstraintKind.FACIES_BOUNDARY: LayerRole.FACIES_BOUNDARY,
    ConstraintKind.FAULT: LayerRole.FAULT_CONSTRAINT,
    ConstraintKind.INTERPOLATION_BOUNDARY: LayerRole.INTERPOLATION_BOUNDARY,
    ConstraintKind.MASK: LayerRole.MASK_BOUNDARY,
    ConstraintKind.EXCLUSION_AREA: LayerRole.MASK_BOUNDARY,
    ConstraintKind.TREND_LINE: LayerRole.DISTRIBUTION_LINE,
}

#: ConstraintKind → ConstraintLine.role（插值引擎兼容语义）。
CONSTRAINT_INTERPOLATION_ROLE: dict[ConstraintKind, str] = {
    ConstraintKind.SOURCE_DIRECTION: "direction",
    ConstraintKind.TREND_LINE: "direction",
    ConstraintKind.PROVENANCE_LINE: "direction",
    ConstraintKind.DISTRIBUTION_LINE: "direction",
    ConstraintKind.PALEO_SHORELINE: "boundary",
    ConstraintKind.FACIES_BOUNDARY: "boundary",
    ConstraintKind.FAULT: "break",
    ConstraintKind.INTERPOLATION_BOUNDARY: "boundary",
    ConstraintKind.MASK: "boundary",
    ConstraintKind.EXCLUSION_AREA: "boundary",
}


@dataclass(frozen=True)
class RoleRule:
    """角色的编排规则（组路由与拖放校验的领域依据）。"""

    role: LayerRole
    #: 各阶段默认归属的系统组 id（``mapping_workspace.layer_groups``）。
    stage_groups: tuple[tuple[str, str], ...]  # (stage.value, group_id)
    #: 允许人工移动到的系统组（空 = 仅允许所属系统组；用户组始终允许）。
    movable_to: frozenset[str] = frozenset()
    locked_by_default: bool = False


def layer_role_from_value(value: object) -> LayerRole | None:
    """宽容解析角色；未知返回 None（调用方决定 LEGACY_UNCLASSIFIED 兜底）。"""
    if isinstance(value, LayerRole):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return None
    try:
        return LayerRole(text)
    except ValueError:
        return None


def constraint_kind_from_value(value: object) -> ConstraintKind | None:
    if isinstance(value, ConstraintKind):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return None
    try:
        return ConstraintKind(text)
    except ValueError:
        return None
