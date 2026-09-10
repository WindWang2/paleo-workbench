"""``MappingStage``：地质编图工作流阶段。

Stage 是 **工作流上下文**，不是页面：

- 同一个 QGIS Project / 同一个地图画布 / 同一个图层权威贯穿全部阶段；
- 阶段切换只改变：默认图层组显隐、默认编辑对象、默认 dock/panel、
  工具集合与工作上下文；
- 阶段切换绝不触发科学重计算（重新插值/预测/成图）——科学计算必须由
  明确动作触发；
- 阶段可自由往返（Phase 3 → Phase 2 → Phase 3），依赖经版本/血缘由
  :mod:`paleo_workbench.mapping_workspace.dependencies` 处理为 STALE，
  绝不静默覆盖下游成果。

显示名保持专业工作站用语（①②③前缀便于 UI 分段控件对齐），禁止
「页面1/页面2/页面3」。
"""
from __future__ import annotations

from enum import Enum


class MappingStage(str, Enum):
    """地质编图的三个核心工作阶段（Workflow Context，非 UI 页面）。"""

    FACIES_CALIBRATION = "facies_calibration"
    CONSTRAINT_FACTOR = "constraint_factor"
    INTEGRATED_COMPILATION = "integrated_compilation"

    @property
    def label(self) -> str:
        return STAGE_LABELS[self]

    @property
    def short_label(self) -> str:
        return STAGE_SHORT_LABELS[self]

    @property
    def order(self) -> int:
        return STAGE_ORDER.index(self)

    @property
    def description(self) -> str:
        return STAGE_DESCRIPTIONS[self]


#: 阶段顺序（工作流方向；切换允许任意方向往返）。
STAGE_ORDER: tuple[MappingStage, ...] = (
    MappingStage.FACIES_CALIBRATION,
    MappingStage.CONSTRAINT_FACTOR,
    MappingStage.INTEGRATED_COMPILATION,
)

STAGE_LABELS: dict[MappingStage, str] = {
    MappingStage.FACIES_CALIBRATION: "① 智能预测",
    MappingStage.CONSTRAINT_FACTOR: "② 约束与单因素",
    MappingStage.INTEGRATED_COMPILATION: "③ 综合编图",
}

STAGE_SHORT_LABELS: dict[MappingStage, str] = {
    MappingStage.FACIES_CALIBRATION: "智能预测",
    MappingStage.CONSTRAINT_FACTOR: "约束/单因素",
    MappingStage.INTEGRATED_COMPILATION: "综合编图",
}

STAGE_DESCRIPTIONS: dict[MappingStage, str] = {
    MappingStage.FACIES_CALIBRATION: (
        "先设定编图层位，再叠加该层位的地震相预测与测井相预测；"
        "测井预测支持由井点生成相面（点到面）。"
    ),
    MappingStage.CONSTRAINT_FACTOR: (
        "以上一阶段成果为背景，编辑物源/展布/岸线/相带边界/断层等线面约束，"
        "并组织各单因素图的输入、插值面、等值线、分类结果与不确定性/QC。"
    ),
    MappingStage.INTEGRATED_COMPILATION: (
        "以校正相图、约束与单因素成果为证据进行多因素综合解释、相带/古地理"
        "面编辑、图件符号与标注、QA/QC 与最终 MapProduct 成图。"
    ),
}


def next_stage(stage: MappingStage) -> MappingStage | None:
    """工作流方向的下一阶段；已是最后阶段返回 None（不循环）。"""
    index = STAGE_ORDER.index(stage)
    if index + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[index + 1]


def previous_stage(stage: MappingStage) -> MappingStage | None:
    """工作流反方向的上一阶段；已是第一阶段返回 None。"""
    index = STAGE_ORDER.index(stage)
    if index == 0:
        return None
    return STAGE_ORDER[index - 1]


def stage_display_label(stage: MappingStage) -> str:
    """阶段显示名（供非 Qt 上下文；UI 侧直接用 ``stage.label``）。"""
    return STAGE_LABELS[MappingStage(stage)]


def stage_from_value(value: object) -> MappingStage | None:
    """宽容解析：接受 MappingStage / 其 value / 已知别名；未知返回 None。"""
    if isinstance(value, MappingStage):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return MappingStage(text)
    except ValueError:
        return _STAGE_ALIASES.get(text.lower())


#: 历史别名 → 阶段（宽容解析用；不要在持久化里写别名）。
_STAGE_ALIASES: dict[str, MappingStage] = {
    "facies": MappingStage.FACIES_CALIBRATION,
    "phase1": MappingStage.FACIES_CALIBRATION,
    "phase 1": MappingStage.FACIES_CALIBRATION,
    "intelligent_prediction": MappingStage.FACIES_CALIBRATION,
    "智能预测": MappingStage.FACIES_CALIBRATION,
    "constraints": MappingStage.CONSTRAINT_FACTOR,
    "factor": MappingStage.CONSTRAINT_FACTOR,
    "phase2": MappingStage.CONSTRAINT_FACTOR,
    "phase 2": MappingStage.CONSTRAINT_FACTOR,
    "integrated": MappingStage.INTEGRATED_COMPILATION,
    "compilation": MappingStage.INTEGRATED_COMPILATION,
    "phase3": MappingStage.INTEGRATED_COMPILATION,
    "phase 3": MappingStage.INTEGRATED_COMPILATION,
}
