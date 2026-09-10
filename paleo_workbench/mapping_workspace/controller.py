"""``MappingStageController``：阶段编排（Qt 信号层，领域逻辑在纯模块中）。

职责（V5 §75）：当前阶段、阶段切换、阶段视图状态、阶段 profile 应用、
图层组编排（经 ``LayerGroupController``）、活动编辑目标、就绪度与过期
摘要。**不负责**科学算法、QGIS 渲染、Catalog SQL。

阶段切换纪律（V5 §5/§55/§70）：

* 只做组可见性增量 + 阶段视图状态恢复 + dock 推荐 + 编辑目标重指派；
* 绝不重开 QGIS Project、绝不重载源数据、绝不触发科学重计算；
* 未提交编辑会话**绝不静默丢弃**——切换前交由宿主 flush（保存或保留）。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from paleo_workbench.mapping_workspace.dependencies import (
    MappingDependencyService,
    StaleSummary,
)
from paleo_workbench.mapping_workspace.layer_group_controller import LayerGroupController
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.readiness import (
    StageReadiness,
    StageReadinessStatus,
    evaluate_stage_readiness,
)
from paleo_workbench.mapping_workspace.stage_profiles import stage_profile
from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState
from paleo_workbench.mapping_workspace.stages import (
    STAGE_ORDER,
    MappingStage,
    stage_from_value,
)

logger = logging.getLogger(__name__)


class MappingStageController(QObject):
    """单实例挂在 Workstation 生命周期上（跨 CompositeDocument/Frame 协调）。"""

    current_stage_changed = Signal(str)          # stage.value
    readiness_changed = Signal(object)           # StageReadiness
    stale_summary_changed = Signal(object)       # StaleSummary
    #: 活动编辑目标变化（layer_id or None；跨阶段绝不继承，V5 §42/§88）。
    active_target_changed = Signal(object)
    #: 阶段切换时建议宿主应用 dock 推荐（dict[str,bool]；建议而非强制）。
    dock_recommendation = Signal(dict)
    #: 顶部提示（如「1 个输入成果已过期」，V5 §56）。
    stage_notification = Signal(str)

    def __init__(
        self,
        workspace_state: MappingWorkspaceState | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.state = workspace_state or MappingWorkspaceState()
        self.group_controller = LayerGroupController(self.state)
        self.dependency_service = MappingDependencyService()
        self._document: Any = None
        self._catalog: Any = None
        #: 图层快照提供者（CompositeDocument 注入：() -> list[MapLayerSnapshot]）。
        self._layer_snapshot_provider: Callable[[], list] | None = None
        #: 编辑目标解析回调（role → layer_id；宿主按角色查现有图层）。
        self._target_resolver: Callable[[LayerRole], str | None] | None = None
        #: 活动编辑目标（stage-aware；切换阶段时重指派）。
        self._active_target_layer_id: str | None = None
        self._readiness: StageReadiness | None = None
        self._stale: StaleSummary | None = None
        #: 首次进入某阶段时才应用 dock 推荐（此后尊重用户布局，V5 §7/§37）。
        self._dock_recommendation_applied: set[str] = set()

    # -- 装配 -------------------------------------------------------------------

    def attach_document(self, document: Any, catalog: Any = None) -> None:
        """绑定 ProjectDocument（与可选 CatalogPort）——工程打开/切换时调用。"""
        self._document = document
        self._catalog = catalog
        # 注意：这里不预跑 ensure_memberships——装载早期 snapshot provider
        # 可能返回上一工程的图层列表（bind 之前）；迁移归类统一在
        # sync_composition（组合同步后）执行。
        self.refresh_evaluation()

    def set_snapshot_provider(self, provider: Callable[[], list]) -> None:
        self._layer_snapshot_provider = provider

    def set_target_resolver(self, resolver: Callable[[LayerRole], str | None]) -> None:
        self._target_resolver = resolver

    # -- 阶段 -------------------------------------------------------------------

    @property
    def current_stage(self) -> MappingStage:
        return self.state.current_stage

    def set_stage(self, stage: MappingStage | str, *, apply_docks: bool = True) -> bool:
        """切换阶段（瞬时：只做显隐增量与上下文切换；绝不触发重计算）。

        未提交编辑由宿主在调用前 flush（``CompositeDocument.flush_edit_sessions``）。
        """
        target = stage_from_value(stage)
        if target is None:
            logger.warning("unknown stage requested: %r", stage)
            return False
        if target == self.state.current_stage:
            return False
        self.state.set_current_stage(target)
        # 组可见性增量（profile 默认 + 用户覆盖）。
        self.group_controller.apply_stage_visibility(target)
        # 编辑目标重指派：绝不跨阶段继承（P0/P1 业务风险，V5 §88）。
        self._reassign_active_target()
        # 首次进入该阶段时建议 dock 配置（建议，不锁死）。
        if apply_docks and target.value not in self._dock_recommendation_applied:
            profile = stage_profile(target)
            self._dock_recommendation_applied.add(target.value)
            self.dock_recommendation.emit(dict(profile.recommended_docks))
        self.current_stage_changed.emit(target.value)
        self.refresh_evaluation()
        self._notify_stage_stale(target)
        return True

    def _notify_stage_stale(self, stage: MappingStage) -> None:
        """进入阶段时的过期提示（按本阶段口径，不用全工作区计数误导）。"""
        if self._stale is None:
            return
        count = self._stale.stage_stale_count(stage)
        if count:
            self.stage_notification.emit(
                f"{stage.label}：{count} 项输入成果已过期（旧结果保留可查）")

    def _reassign_active_target(self) -> None:
        """按阶段 profile 的编辑角色重指派活动编辑目标。

        解析顺序：profile.active_editing_roles 中首个有现存图层的角色；
        全部缺省 → None（编辑动作禁用并显示原因，绝不悄悄指向上一个
        可编辑图层——「画物源线写进相带边界」级业务风险）。
        """
        profile = stage_profile(self.state.current_stage)
        target_id: str | None = None
        if self._target_resolver is not None:
            for role in profile.active_editing_roles:
                resolved = self._target_resolver(role)
                if resolved:
                    target_id = resolved
                    break
        if target_id != self._active_target_layer_id:
            self._active_target_layer_id = target_id
            self.state.view_state(self.state.current_stage).active_layer_id = target_id
            self.active_target_changed.emit(target_id)

    @property
    def active_target_layer_id(self) -> str | None:
        return self._active_target_layer_id

    def set_active_target(self, layer_id: str | None) -> None:
        """用户显式选择活动图层（记录到当前阶段视图状态；仅在变化时发信号）。"""
        layer_id = layer_id or None
        self.state.view_state(self.state.current_stage).active_layer_id = layer_id
        if layer_id != self._active_target_layer_id:
            self._active_target_layer_id = layer_id
            self.active_target_changed.emit(layer_id)

    def restore_stage_view(self) -> None:
        """工程打开后恢复当前阶段上下文（可见性 + 展开态 + 编辑目标 + 评估）。"""
        stage = self.state.current_stage
        self.group_controller.apply_stage_visibility(stage)
        self.group_controller.apply_group_expanded(
            self.group_controller.expand_states.get(stage.value, {}))
        self._reassign_active_target()
        self.refresh_evaluation()

    # -- 组展开态（UI 偏好 → QSettings，V5 §45） ----------------------------------

    _EXPAND_SETTINGS_PREFIX = "mapping_workspace/expanded"

    def save_expand_prefs(self, project_key: str = "") -> None:
        """组展开态 → QSettings（按工程键分域；纯 UI 偏好不进科学工程）。"""
        try:
            from PySide6.QtCore import QSettings

            from paleo_workbench.ui.layout_persistence import (
                SETTINGS_APP,
                SETTINGS_ORG,
            )

            settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
            prefix = f"{self._EXPAND_SETTINGS_PREFIX}/{project_key or 'default'}"
            for stage_value, expanded_map in (
                    self.group_controller.expand_states.items()):
                settings.setValue(
                    f"{prefix}/{stage_value}",
                    {k: bool(v) for k, v in expanded_map.items()})
        except Exception:
            logger.debug("save expand prefs failed", exc_info=True)

    def load_expand_prefs(self, project_key: str = "") -> None:
        """QSettings → 组展开态（工程打开时）。"""
        try:
            from PySide6.QtCore import QSettings

            from paleo_workbench.ui.layout_persistence import (
                SETTINGS_APP,
                SETTINGS_ORG,
            )

            settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
            prefix = f"{self._EXPAND_SETTINGS_PREFIX}/{project_key or 'default'}"
            for stage in STAGE_ORDER:
                value = settings.value(f"{prefix}/{stage.value}", {})
                if isinstance(value, dict) and value:
                    self.group_controller.expand_states[stage.value] = {
                        str(k): bool(v) for k, v in value.items()}
        except Exception:
            logger.debug("load expand prefs failed", exc_info=True)

    # -- 组合同步入口 --------------------------------------------------------------

    def sync_composition(self) -> None:
        """图层组合变化后：迁移归类 + 期望树 reconcile（增量）+ 阶段显隐。

        由 CompositeDocument 的组合同步路径调用（120ms debounce 之后）。
        """
        if self._layer_snapshot_provider is None:
            return
        snapshots = self._layer_snapshot_provider()
        self.group_controller.ensure_memberships(snapshots)
        self.group_controller.reconcile(snapshots)
        self.group_controller.apply_stage_visibility(self.state.current_stage)
        self.group_controller.apply_group_expanded(
            self.group_controller.expand_states.get(self.state.current_stage.value, {}))
        # 组合变化（建稿/约束/叠加/删除）后重算就绪度与过期——用户完成
        # 清单推荐的动作后，清单不得继续显示旧结论。
        self.refresh_evaluation()

    # -- 就绪度 / 过期 --------------------------------------------------------------

    def refresh_evaluation(self) -> None:
        """重算就绪度与过期摘要（切阶段/工程变更后）。"""
        document = self._document
        workspace_state = self.state if document is not None else None
        self._stale = self.dependency_service.evaluate(
            document, self.state, self._catalog)
        self._readiness = evaluate_stage_readiness(
            self.state.current_stage,
            document=document,
            workspace_state=workspace_state,
            freshness_summary=self._stale,
        )
        self.readiness_changed.emit(self._readiness)
        self.stale_summary_changed.emit(self._stale)

    @property
    def readiness(self) -> StageReadiness:
        if self._readiness is None:
            self._readiness = evaluate_stage_readiness(
                self.state.current_stage, document=self._document,
                workspace_state=self.state if self._document is not None else None)
        return self._readiness

    @property
    def stale_summary(self) -> StaleSummary:
        if self._stale is None:
            self._stale = self.dependency_service.evaluate(
                self._document, self.state, self._catalog)
        return self._stale

    def readiness_badge(self) -> str:
        """阶段切换控件的紧凑状态徽标。"""
        readiness = self.readiness
        stale = self.stale_summary
        parts: list[str] = []
        if readiness.status == StageReadinessStatus.NOT_READY:
            parts.append("!")
        elif readiness.status == StageReadinessStatus.READY_WITH_WARNINGS:
            parts.append("~")
        if stale.stale_count:
            parts.append(f"{stale.stale_count}↑")
        return "".join(parts) or "✓"

    # -- 持久化 -------------------------------------------------------------------

    def save_state(self) -> dict:
        return self.state.to_dict()

    def load_state(self, data: dict | None) -> None:
        self.state = MappingWorkspaceState.from_dict(data)
        self.group_controller.state = self.state
        self.group_controller.reload_from_state()
        self._dock_recommendation_applied.clear()
        # 真正的「首次进入」语义：工程此前用过阶段工作区（有持久化组结构
        # 或用户覆盖）→ 全部阶段视为已应用过，重开工程绝不重置用户布局。
        used_before = bool(self.state.tree) or any(
            state.customized or state.group_visibility
            for state in self.state.stage_states.values()
        )
        if used_before:
            self._dock_recommendation_applied = {
                stage.value for stage in STAGE_ORDER
            }

    # -- 工具 ---------------------------------------------------------------------

    def stage_order(self) -> tuple[MappingStage, ...]:
        return STAGE_ORDER
