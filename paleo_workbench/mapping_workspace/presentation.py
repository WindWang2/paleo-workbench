"""``LayerPresentationState`` — 派生图层呈现状态（goal §8 / D9）。

**纯派生、绝不持久化**（03-decisions D9）：本模块按需把既有权威
（memberships + 依赖服务 freshness + QualityReports + FactorMapTask
版本钉住 + 阶段视图状态）投影成图层级呈现状态，供 UI 分支
（workstation-ux-v7）渲染图层装饰。不建新 DB、不复制 freshness 状态、
不 import Qt/QGIS——可独立单元测试。

各字段的权威来源（绝不发明值）：

* ``role`` / ``group_id`` —— ``MappingWorkspaceState.memberships``
  （``LayerMembershipRecord``）+ 持久化树放置（``workspace_state.tree``）
  → 兜底 ``layer_groups.home_group_for_role``；
* ``editable`` / ``raw_locked`` —— ``layer_roles.ROLE_EDITABLE`` /
  ``ROLE_RAW_PROTECTED``（角色词表权威）；
* ``stage_locked`` —— 图层所在组的 ``GroupTemplate.locked_stages``
  （``layer_groups.SYSTEM_GROUP_TEMPLATES``；factor 子组继承
  ``phase2.factors`` 根组锁定）；
* ``maturity`` —— ``workspace_state.artifact_maturity``（候选 key 与
  ``composite_document.layer_domain_status`` 一致：
  ``factor:<task>`` / ``phase1_draft:<layer>`` / ``integrated:<layer>``）；
  未记录时取 ``ArtifactMaturity.DRAFT``（``maturity_of`` 的领域默认）；
* ``freshness`` / ``stale_count`` —— ``MappingDependencyService.evaluate``
  的 ``StaleSummary``（artifact_key：``phase1_draft:<layer_id>`` /
  ``factor:<task_id>`` / ``integrated:<layer_id>``，与
  ``LayerGroupController.layer_freshness`` 的解析顺序一致）；无摘要或
  无匹配 → 诚实 ``"unknown"``；``stale_count`` = 问题成果的
  ``upstream_culprits`` 数（STALE/MISSING_INPUT/SUPERSEDED 传播计数）；
* ``qc_error_count`` —— **最新一份** QualityReport（历史报告已修复的
  问题不再永久报警，见 ``readiness.check_qa_geometry_errors``）中
  ``severity == "error"`` 且**引用了该图层**的 issue 数。issue dict 经
  ``workflow.qc.make_issue`` 产生，图层引用契约：``feature_kind ==
  "layer"`` 时 ``feature_id``/``ref`` 为 layer_id（如
  ``map_qa_rules._layer_crs_issues``），另容忍显式 ``layer_id`` 键
  （前向兼容）。地图级 issue（``feature_kind == "map"``）不归属任何
  图层，绝不摊派；
* ``dirty`` —— 活动编辑会话（调用方传入 ``dirty_layer_ids``；本模块
  不 import Qt 侧编辑会话代码）；
* ``missing`` —— 成员资格存在，但图层 id 不在
  ``document.user_vector_layers`` / ``document.workstation_reference_layers``
  / 调用方传入的 ``present_layer_ids``（运行时画布图层，如 RAW 叠加、
  factor 栅格镜像，只存活在宿主侧）中；
* ``degraded`` —— 桥/画布能力快照 ``capability``（UI 分支持有实时
  能力；``{"native_stack": bool}``，缺省 None → False=不谎报降级）；
* ``active`` —— ``active_layer_ids``（活动编辑目标）；
* ``visible`` —— ``StageViewState`` 覆盖层（layer → group 优先级）+
  ``layer_groups.default_group_visibility`` 阶段默认；
* ``version`` —— membership ``source_version_id``（钉住的 catalog
  DataVersion）；factor 系图层回落 ``FactorMapTask.grid_artifact_version_id``。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from paleo_workbench.mapping_workspace.dependencies import FreshnessStatus
from paleo_workbench.mapping_workspace.layer_groups import (
    FACTOR_ROOT_GROUP_ID,
    default_group_visibility,
    home_group_for_role,
    is_factor_group,
    system_group_template,
)
from paleo_workbench.mapping_workspace.layer_roles import (
    ROLE_EDITABLE,
    ROLE_RAW_PROTECTED,
    LayerRole,
)
from paleo_workbench.mapping_workspace.layer_tree import (
    GroupNode,
    LayerRef,
    LayerTreeSnapshot,
)
from paleo_workbench.mapping_workspace.stage_state import (
    ArtifactMaturity,
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.mapping_workspace.stages import MappingStage, stage_from_value

#: freshness 字段合法词表（``FreshnessStatus`` 值；契约防御漂移）。
FRESHNESS_VALUES: frozenset[str] = frozenset(
    status.value for status in FreshnessStatus
)


@dataclass(frozen=True)
class LayerPresentationState:
    """单个图层的派生呈现状态（goal §8 字段集，跨分支 UI 契约）。

    每个字段都派生自既有权威（见模块 docstring 的权威表）；本类型
    自身**绝不持久化**——UI 每次按需重建。缺失输入 → 诚实默认
    （freshness="unknown"、degraded=False），绝不发明值。
    """

    layer_id: str
    group_id: str = ""
    role: LayerRole = LayerRole.LEGACY_UNCLASSIFIED
    visible: bool = True
    active: bool = False
    editable: bool = False
    dirty: bool = False
    raw_locked: bool = False
    stage_locked: bool = False
    #: draft / reviewed / frozen / published（ArtifactMaturity 值）。
    maturity: str = ArtifactMaturity.DRAFT
    #: current / stale / missing_input / superseded / unknown。
    freshness: str = FreshnessStatus.UNKNOWN.value
    #: 该成果过期/缺输入/被取代的上游 culprit 数（传播计数）。
    stale_count: int = 0
    #: 最新 QA 报告中引用该图层的 error 级 issue 数。
    qc_error_count: int = 0
    #: 成员资格在、图层本体不在（工程集合与运行时均缺席）。
    missing: bool = False
    #: 桥/画布能力降级（UI 分支推送的 capability 快照；None → False）。
    degraded: bool = False
    #: 钉住的 catalog 版本 id（membership source_version_id；factor 系
    #: 回落任务 grid_artifact_version_id）；未钉住 = ""。
    version: str = ""

    def to_dict(self) -> dict:
        """序列化（UI/调试用；不是持久化权威，绝不写回工程）。"""
        return {
            "layer_id": self.layer_id,
            "group_id": self.group_id,
            "role": self.role.value,
            "visible": self.visible,
            "active": self.active,
            "editable": self.editable,
            "dirty": self.dirty,
            "raw_locked": self.raw_locked,
            "stage_locked": self.stage_locked,
            "maturity": self.maturity,
            "freshness": self.freshness,
            "stale_count": self.stale_count,
            "qc_error_count": self.qc_error_count,
            "missing": self.missing,
            "degraded": self.degraded,
            "version": self.version,
        }


# ---------------------------------------------------------------------------
# 派生辅助（全部只读既有权威）
# ---------------------------------------------------------------------------

def _resolve_stage(
    current_stage: Any,
    workspace_state: MappingWorkspaceState | None,
) -> MappingStage | None:
    """显式 current_stage 优先；否则用工作区持久化的当前阶段。"""
    if current_stage is not None:
        if isinstance(current_stage, MappingStage):
            return current_stage
        return stage_from_value(current_stage)
    if workspace_state is not None:
        return workspace_state.current_stage
    return None


def _tree_placements(tree: Any) -> dict[str, str]:
    """持久化树 → ``layer_id → group_id`` 放置表（root 放置 = ""）。"""
    if not isinstance(tree, dict) or not tree:
        return {}
    try:
        snapshot = LayerTreeSnapshot.from_dict(tree)
    except Exception:
        return {}

    placements: dict[str, str] = {}

    def walk(children, group_id: str) -> None:
        for child in children:
            if isinstance(child, LayerRef):
                placements.setdefault(child.layer_id, group_id)
            elif isinstance(child, GroupNode):
                walk(child.children, child.group_id)

    walk(snapshot.children, "")
    return placements


def _group_template_for(group_id: str):
    """组模板；factor 子组（动态组）继承 ``phase2.factors`` 根模板。"""
    template = system_group_template(group_id)
    if template is None and is_factor_group(group_id):
        template = system_group_template(FACTOR_ROOT_GROUP_ID)
    return template


def _candidate_artifact_keys(layer_id: str, record: LayerMembershipRecord) -> list[str]:
    """membership → 依赖服务/成熟度共用的 artifact_key 候选（有序）。

    与 ``LayerGroupController.layer_freshness`` 及
    ``composite_document.layer_domain_status`` 的解析顺序一致：
    factor 任务 > phase1 草稿 > 综合解释。
    """
    keys: list[str] = []
    if record.factor_task_id:
        keys.append(f"factor:{record.factor_task_id}")
    if record.role == LayerRole.INITIAL_FACIES_DRAFT:
        keys.append(f"phase1_draft:{layer_id}")
    if record.role in (LayerRole.INTEGRATED_FACIES, LayerRole.INTEGRATED_BOUNDARY):
        keys.append(f"integrated:{layer_id}")
    return keys


def _freshness_index(freshness_summary: Any) -> dict[str, Any]:
    """``StaleSummary`` → artifact_key 索引（无摘要 → 空表）。"""
    return {
        str(artifact.artifact_key): artifact
        for artifact in (getattr(freshness_summary, "artifacts", None) or ())
    }


def _freshness_for(
    layer_id: str,
    record: LayerMembershipRecord,
    index: dict[str, Any],
) -> tuple[str, int]:
    """→ (freshness, stale_count)；无摘要/无匹配 → ("unknown", 0)。"""
    for key in _candidate_artifact_keys(layer_id, record):
        artifact = index.get(key)
        if artifact is None:
            continue
        status = getattr(artifact, "status", None)
        value = (
            status.value if isinstance(status, FreshnessStatus)
            else str(status or FreshnessStatus.UNKNOWN.value)
        )
        culprits = 0
        if getattr(artifact, "is_problem", False):
            culprits = len(getattr(artifact, "upstream_culprits", None) or ())
        return value, culprits
    return FreshnessStatus.UNKNOWN.value, 0


def _maturity_for(
    layer_id: str,
    record: LayerMembershipRecord,
    workspace_state: MappingWorkspaceState,
) -> str:
    for key in _candidate_artifact_keys(layer_id, record):
        found = workspace_state.artifact_maturity.get(key)
        if found:
            return str(found)
    return ArtifactMaturity.DRAFT


def _issue_layer_refs(issue: dict) -> set[str]:
    """QC issue dict 引用的图层 id 集合（见模块 docstring 引用契约）。"""
    refs: set[str] = set()
    explicit = str(issue.get("layer_id") or "")
    if explicit:
        refs.add(explicit)
    if str(issue.get("feature_kind") or "") == "layer":
        feature_id = str(issue.get("feature_id") or "")
        if feature_id:
            refs.add(feature_id)
    ref = str(issue.get("ref") or "")
    if ref:
        refs.add(ref)
    return refs


def _qc_error_counts(document: Any) -> dict[str, int]:
    """最新 QA 报告 → ``layer_id → error 级 issue 数``。

    只看最新一份（历史报告已修复的问题不再永久报警——与
    ``readiness.check_qa_geometry_errors`` 同一裁决）；issue 的错误级别
    键是 ``severity``（``workflow.qc.make_issue`` 契约），容忍 ``status``
    作前向兼容。不带图层引用的 error（地图级问题）不摊派给任何图层。
    """
    reports = getattr(document, "quality_reports", None) or []
    if not reports:
        return {}
    latest = reports[-1]
    counts: dict[str, int] = {}
    for issue in getattr(latest, "issues", None) or ():
        if not isinstance(issue, dict):
            continue
        level = str(issue.get("severity") or issue.get("status") or "")
        if level != "error":
            continue
        for layer_id in _issue_layer_refs(issue):
            counts[layer_id] = counts.get(layer_id, 0) + 1
    return counts


def _document_layer_ids(document: Any) -> set[str]:
    """工程侧持久化图层集合（user_vector_layers + 引用图层）。"""
    ids: set[str] = set()
    for collection in ("user_vector_layers", "workstation_reference_layers"):
        for layer in getattr(document, collection, None) or []:
            layer_id = str(getattr(layer, "id", "") or "")
            if layer_id:
                ids.add(layer_id)
    return ids


def _pinned_version(record: LayerMembershipRecord, document: Any) -> str:
    """membership 钉住的版本 id；factor 系回落任务结果版本。"""
    if record.source_version_id:
        return str(record.source_version_id)
    if record.factor_task_id:
        for task in getattr(document, "factor_map_tasks", None) or []:
            if str(getattr(task, "id", "") or "") == str(record.factor_task_id):
                return str(getattr(task, "grid_artifact_version_id", "") or "")
    return ""


def _layer_visible(
    layer_id: str,
    group_id: str,
    view_state: Any,
    stage: MappingStage | None,
) -> bool:
    """显隐 = 图层覆盖 > 组覆盖（覆盖层）> 阶段组默认 profile。"""
    override = view_state.layer_visibility.get(layer_id)
    if override is not None:
        return bool(override)
    if stage is None:
        return True
    effective = view_state.effective_group_visibility(default_group_visibility(stage))
    if group_id in effective:
        return bool(effective[group_id])
    if group_id and is_factor_group(group_id):
        # factor 子组继承 phase2.factors 根组的阶段可见性。
        return bool(effective.get(FACTOR_ROOT_GROUP_ID, True))
    # 用户组 / root 放置：默认可见（显隐由覆盖层表达）。
    return True


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_presentation_states(
    document: Any,
    workspace_state: MappingWorkspaceState | None,
    freshness_summary: Any = None,
    current_stage: Any = None,
    active_layer_ids: Iterable[str] = (),
    *,
    dirty_layer_ids: Iterable[str] | None = None,
    capability: dict | None = None,
    present_layer_ids: Iterable[str] = (),
) -> list[LayerPresentationState]:
    """把既有权威投影为全部成员图层的呈现状态（纯函数，无副作用）。

    参数均为只读输入；``dirty_layer_ids``（活动编辑会话脏层）、
    ``capability``（桥/画布能力快照，如 ``{"native_stack": bool}``）与
    ``present_layer_ids``（运行时画布上实际存在的图层——RAW 叠加、
    factor 镜像等不落工程的层）由调用方推送，本模块绝不 import Qt 侧
    代码去自取。``current_stage`` 缺省时用
    ``workspace_state.current_stage``。
    """
    if workspace_state is None:
        return []

    stage = _resolve_stage(current_stage, workspace_state)
    view_state = workspace_state.view_state(stage) if stage is not None else None
    placements = _tree_placements(workspace_state.tree)
    freshness = _freshness_index(freshness_summary)
    qc_errors = _qc_error_counts(document)
    document_layer_ids = _document_layer_ids(document)
    known_ids = document_layer_ids | {str(x) for x in (present_layer_ids or ())}
    active_ids = {str(x) for x in (active_layer_ids or ())}
    dirty_ids = {str(x) for x in (dirty_layer_ids or ())}
    # 能力快照缺省 None → 不谎报降级（UI 分支拥有实时能力权威）；
    # 提供快照但未报 native_stack = 诚实降级。
    degraded = capability is not None and not bool(capability.get("native_stack", False))

    states: list[LayerPresentationState] = []
    for layer_id, record in workspace_state.memberships.items():
        layer_id = str(layer_id)
        role = record.role
        group_id = placements.get(layer_id)
        if group_id is None:
            group_id = home_group_for_role(
                role,
                stage=stage_from_value(record.created_stage),
                factor_task_id=record.factor_task_id,
            )
        template = _group_template_for(group_id)
        freshness_value, stale_count = _freshness_for(layer_id, record, freshness)
        visible = (
            _layer_visible(layer_id, group_id, view_state, stage)
            if view_state is not None else True
        )
        states.append(LayerPresentationState(
            layer_id=layer_id,
            group_id=group_id,
            role=role,
            visible=visible,
            active=layer_id in active_ids,
            editable=role in ROLE_EDITABLE,
            dirty=layer_id in dirty_ids,
            raw_locked=role in ROLE_RAW_PROTECTED,
            stage_locked=bool(
                template is not None and stage is not None
                and template.stage_locked(stage)
            ),
            maturity=_maturity_for(layer_id, record, workspace_state),
            freshness=freshness_value,
            stale_count=stale_count,
            qc_error_count=int(qc_errors.get(layer_id, 0)),
            missing=layer_id not in known_ids,
            degraded=degraded,
            version=_pinned_version(record, document),
        ))
    return states
