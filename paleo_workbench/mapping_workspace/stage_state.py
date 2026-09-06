"""阶段工作区状态：持久化模型与恢复。

持久化分工（V5 §45）：

* **Project 科学状态**（本模块 → ``ProjectDocument.mapping_workspace``）：
  当前阶段、图层角色/成员资格、组结构、阶段成果身份、成熟度。
* **用户 UI 偏好**（QSettings，由 Qt 侧 controller 读写）：dock 尺寸/
  浮动位置、组展开态、不透明度滑条等纯呈现偏好。

绝不能把显示器坐标写进科学项目。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from paleo_workbench.mapping_workspace.layer_roles import (
    ConstraintKind,
    LayerRole,
    constraint_kind_from_value,
    layer_role_from_value,
)
from paleo_workbench.mapping_workspace.stages import (
    STAGE_ORDER,
    MappingStage,
    stage_from_value,
)


class ArtifactMaturity:
    """成果成熟度（与 Stage 正交，V5 §33：Phase ≠ maturity）。

    纯常量类： maturity 是字符串值（draft/reviewed/frozen/published），
    顺序由 :data:`MATURITY_ORDER` 定义。
    """

    DRAFT: str = "draft"
    REVIEWED: str = "reviewed"
    FROZEN: str = "frozen"
    PUBLISHED: str = "published"

    ALL: tuple[str, ...] = (DRAFT, REVIEWED, FROZEN, PUBLISHED)


MATURITY_ORDER: dict[str, int] = {
    ArtifactMaturity.DRAFT: 0,
    ArtifactMaturity.REVIEWED: 1,
    ArtifactMaturity.FROZEN: 2,
    ArtifactMaturity.PUBLISHED: 3,
}


@dataclass
class LayerMembershipRecord:
    """图层 → 角色/任务/约束类型的成员资格记录（领域元数据，非运行时树）。"""

    layer_id: str
    role: LayerRole = LayerRole.LEGACY_UNCLASSIFIED
    #: factor 系角色绑定的任务 id（factor 组身份来源）。
    factor_task_id: str = ""
    #: 约束系角色的 typed constraint kind（V5 §22）。
    constraint_kind: str = ""
    #: 创建该图层的阶段。
    created_stage: str = ""
    #: 溯源钉住的 catalog DataVersion（RAW→DERIVED 草稿链的输入版本）。
    source_version_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "layer_id": self.layer_id,
            "role": self.role.value,
            "factor_task_id": self.factor_task_id,
            "constraint_kind": self.constraint_kind,
            "created_stage": self.created_stage,
            "source_version_id": self.source_version_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LayerMembershipRecord":
        role = layer_role_from_value(data.get("role")) or LayerRole.LEGACY_UNCLASSIFIED
        kind = data.get("constraint_kind") or ""
        if constraint_kind_from_value(kind) is None:
            kind = ""
        return cls(
            layer_id=str(data.get("layer_id") or ""),
            role=role,
            factor_task_id=str(data.get("factor_task_id") or ""),
            constraint_kind=kind,
            created_stage=str(data.get("created_stage") or ""),
            source_version_id=str(data.get("source_version_id") or ""),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass
class StageViewState:
    """单阶段的视图状态（离开时保存，返回时恢复；V5 §7/§37）。

    用户的显隐修改是**覆盖层**：`None` = 未覆盖（用 profile 默认）；
    显式 bool = 用户决定。切走再回不覆盖用户值。
    """

    stage: MappingStage
    group_visibility: dict[str, bool | None] = field(default_factory=dict)
    group_locked: dict[str, bool | None] = field(default_factory=dict)
    layer_visibility: dict[str, bool | None] = field(default_factory=dict)
    layer_opacity: dict[str, float | None] = field(default_factory=dict)
    active_layer_id: str | None = None
    active_tool: str | None = None
    #: 用户是否显式恢复过默认（用于「Restore Stage Defaults」重置语义）。
    customized: bool = False

    def effective_group_visibility(self, defaults: dict[str, bool]) -> dict[str, bool]:
        """阶段 profile 默认 + 用户覆盖 → 有效组显隐。"""
        effective = dict(defaults)
        for group_id, override in self.group_visibility.items():
            if override is not None:
                effective[group_id] = override
        return effective

    def record_group_visibility(self, group_id: str, visible: bool) -> None:
        self.group_visibility[str(group_id)] = bool(visible)
        self.customized = True

    def record_layer_visibility(self, layer_id: str, visible: bool) -> None:
        self.layer_visibility[str(layer_id)] = bool(visible)
        self.customized = True

    def record_layer_opacity(self, layer_id: str, opacity: float) -> None:
        self.layer_opacity[str(layer_id)] = max(0.05, min(1.0, float(opacity)))
        self.customized = True

    def reset_to_defaults(self) -> None:
        """「Restore Stage Defaults」：清空覆盖层，回到 profile 默认。"""
        self.group_visibility.clear()
        self.group_locked.clear()
        self.layer_visibility.clear()
        self.layer_opacity.clear()
        self.active_layer_id = None
        self.active_tool = None
        self.customized = False

    def to_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "group_visibility": dict(self.group_visibility),
            "group_locked": dict(self.group_locked),
            "layer_visibility": dict(self.layer_visibility),
            "layer_opacity": {k: v for k, v in self.layer_opacity.items()
                              if v is not None},
            "active_layer_id": self.active_layer_id,
            "active_tool": self.active_tool,
            "customized": self.customized,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StageViewState":
        stage = stage_from_value(data.get("stage")) or MappingStage.FACIES_CALIBRATION
        return cls(
            stage=stage,
            group_visibility={
                str(k): (None if v is None else bool(v))
                for k, v in (data.get("group_visibility") or {}).items()
            },
            group_locked={
                str(k): (None if v is None else bool(v))
                for k, v in (data.get("group_locked") or {}).items()
            },
            layer_visibility={
                str(k): (None if v is None else bool(v))
                for k, v in (data.get("layer_visibility") or {}).items()
            },
            layer_opacity={
                str(k): (float(v) if v is not None else None)
                for k, v in (data.get("layer_opacity") or {}).items()
            },
            active_layer_id=(str(data["active_layer_id"])
                             if data.get("active_layer_id") else None),
            active_tool=(str(data["active_tool"]) if data.get("active_tool") else None),
            customized=bool(data.get("customized", False)),
        )

    def copy(self) -> "StageViewState":
        return replace(
            self,
            group_visibility=dict(self.group_visibility),
            group_locked=dict(self.group_locked),
            layer_visibility=dict(self.layer_visibility),
            layer_opacity=dict(self.layer_opacity),
        )


@dataclass
class MappingWorkspaceState:
    """整个阶段工作区的持久化科学状态（挂在 ProjectDocument 上）。"""

    current_stage: MappingStage = MappingStage.FACIES_CALIBRATION
    stage_states: dict[MappingStage, StageViewState] = field(default_factory=dict)
    memberships: dict[str, LayerMembershipRecord] = field(default_factory=dict)
    #: 组结构（含用户组/放置顺序）的持久化载体；系统组标题从模板重派生。
    tree: dict = field(default_factory=dict)
    #: 阶段成果成熟度（artifact_key → maturity）。
    artifact_maturity: dict[str, str] = field(default_factory=dict)
    #: 综合编图的输入证据版本选择（Compilation Input Set，V5 §57）。
    compilation_input_set: dict[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        for stage in STAGE_ORDER:
            self.stage_states.setdefault(stage, StageViewState(stage=stage))

    # -- 阶段视图状态 ----------------------------------------------------------

    def view_state(self, stage: MappingStage) -> StageViewState:
        state = self.stage_states.get(stage)
        if state is None:
            state = StageViewState(stage=stage)
            self.stage_states[stage] = state
        return state

    def set_current_stage(self, stage: MappingStage) -> None:
        self.current_stage = MappingStage(stage)

    # -- 成员资格 ---------------------------------------------------------------

    def membership(self, layer_id: str) -> LayerMembershipRecord | None:
        return self.memberships.get(str(layer_id))

    def role_of(self, layer_id: str) -> LayerRole:
        record = self.memberships.get(str(layer_id))
        return record.role if record is not None else LayerRole.LEGACY_UNCLASSIFIED

    def set_membership(self, record: LayerMembershipRecord) -> None:
        if not record.layer_id:
            return
        self.memberships[record.layer_id] = record

    def drop_membership(self, layer_id: str) -> None:
        self.memberships.pop(str(layer_id), None)
        for state in self.stage_states.values():
            state.layer_visibility.pop(str(layer_id), None)
            state.layer_opacity.pop(str(layer_id), None)

    def layers_with_role(self, role: LayerRole) -> list[str]:
        resolved = role.value if isinstance(role, LayerRole) else str(role)
        return [
            layer_id for layer_id, record in self.memberships.items()
            if record.role.value == resolved
        ]

    # -- 成熟度 -----------------------------------------------------------------

    def maturity_of(self, artifact_key: str) -> str:
        return self.artifact_maturity.get(str(artifact_key), ArtifactMaturity.DRAFT)

    def set_maturity(self, artifact_key: str, maturity: str) -> None:
        if maturity not in MATURITY_ORDER:
            raise ValueError(f"unknown maturity: {maturity}")
        self.artifact_maturity[str(artifact_key)] = maturity

    # -- 序列化 ---------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "current_stage": self.current_stage.value,
            "stage_states": {
                stage.value: state.to_dict() for stage, state in self.stage_states.items()
            },
            "memberships": {
                layer_id: record.to_dict()
                for layer_id, record in self.memberships.items()
            },
            "tree": dict(self.tree or {}),
            "artifact_maturity": dict(self.artifact_maturity),
            "compilation_input_set": dict(self.compilation_input_set),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "MappingWorkspaceState":
        if not isinstance(data, dict):
            return cls()
        state = cls()
        state.current_stage = (
            stage_from_value(data.get("current_stage"))
            or MappingStage.FACIES_CALIBRATION
        )
        raw_states = data.get("stage_states") or {}
        for stage in STAGE_ORDER:
            raw = raw_states.get(stage.value)
            if isinstance(raw, dict):
                state.stage_states[stage] = StageViewState.from_dict(raw)
        for layer_id, raw in (data.get("memberships") or {}).items():
            if isinstance(raw, dict):
                record = LayerMembershipRecord.from_dict(raw)
                record.layer_id = str(layer_id)
                state.memberships[str(layer_id)] = record
        tree = data.get("tree")
        state.tree = dict(tree) if isinstance(tree, dict) else {}
        for key, value in (data.get("artifact_maturity") or {}).items():
            if value in MATURITY_ORDER:
                state.artifact_maturity[str(key)] = value
        state.compilation_input_set = {
            str(k): str(v) for k, v in (data.get("compilation_input_set") or {}).items()
        }
        state.schema_version = int(data.get("schema_version") or 1)
        return state
