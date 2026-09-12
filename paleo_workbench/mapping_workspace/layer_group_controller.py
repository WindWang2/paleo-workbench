"""``LayerGroupController``：领域组状态 ↔ QGIS Layer Tree 的增量 reconcile。

职责（V5 §76）：ensure system groups、图层成员资格指派、QGIS 树 reconcile、
组可见性、组排序、旧工程迁移。**不负责**几何编辑/科学算法/QGIS 渲染。

权威边界（V5 §9）：QGIS Layer Tree 是运行时显示/排序/组结构权威；本
controller 持有的是领域侧的**期望树**（由模板 + 成员资格 + 用户放置构成），
经 group API 做增量 reconcile，并在用户树事件（拖拽/勾选/改名）回写时
更新期望树——两侧永不对抗：程序化变更 suppress 回声，用户变更先落
期望树再等下一次 reconcile。

增量保证（V5 §68）：diff 期望树与最近应用树，只对差异发桥调用
（upsert_group / move_layer_to_group / set_group_visibility /
remove_groups_except），绝不全量重建。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from paleo_workbench.mapping_workspace.layer_groups import (
    BASE_REFERENCE_GROUP_ID,
    FACTOR_ROOT_GROUP_ID,
    SYSTEM_GROUP_TEMPLATES,
    classify_layer_for_migration,
    factor_group_id,
    factor_task_of_group,
    home_group_for_role,
    movable_into_system_group,
    system_group_template,
)
from paleo_workbench.mapping_workspace.layer_order import assign_keys_for_order
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.layer_tree import (
    GroupNode,
    LayerRef,
    LayerTreeSnapshot,
    tree_from_nodes,
)
from paleo_workbench.mapping_workspace.layer_tree_plan import (
    LayerTreePlanInput,
    PlanLayerRecord,
    PlanUserGroup,
    build_plan,
    effective_home_group,
)
from paleo_workbench.mapping_workspace.layer_tree_diff import diff_trees
from paleo_workbench.mapping_workspace.tree_transaction import tree_transaction
from paleo_workbench.mapping_workspace.stage_profiles import stage_profile
from paleo_workbench.mapping_workspace.stage_state import (
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.mapping_workspace.stages import MappingStage

logger = logging.getLogger(__name__)


class LayerGroupController:
    """领域 ↔ QGIS 树的增量 reconcile（无 Qt 依赖；stack 为 duck-type 桥）。"""

    def __init__(self, workspace_state: MappingWorkspaceState):
        self.state = workspace_state
        self._canvas: Any = None
        self._stack: Any = None
        self._canvas_address: int = 0
        self._tree_view_address: int = 0
        #: 桥是否具备 group 能力（旧桥 → degraded mode，UI 必须明示）。
        self.groups_available: bool = False
        #: 完全 fallback 画布（无原生栈）——阶段显隐/分组全部不可用。
        self._fallback_canvas: bool = False
        #: 最近一次成功应用的期望树（增量 diff 基线）。
        self._last_applied: LayerTreeSnapshot | None = None
        #: 最近应用的组可见性（group_id → bool）。
        self._last_group_visibility: dict[str, bool] = {}
        #: factor 任务标题（宿主从 ProjectDocument 同步：task_id → title）。
        self.factor_titles: dict[str, str] = {}
        #: 用户结构变更回声后的通知（QString → 宿主持久化/刷新）。
        self.on_structure_changed: Callable[[], None] | None = None
        #: 非法拖放（角色路由冲突）通知宿主显示提示。
        self.on_invalid_move: Callable[[str, str], None] | None = None
        # 最近一次 observe_tree_nodes 是否拒绝了非法放置（宿主据此 force
        # reconcile 把 QGIS 树拉回领域权威位置）。
        self.last_observe_rejected: bool = False
        # 组展开态（阶段 → node_id → expanded；UI 偏好，宿主落 QSettings）。
        self.expand_states: dict[str, dict[str, bool]] = {}
        # 运行时放置表：layer_id → group_id（"" = root），从持久化树恢复。
        self._placements: dict[str, str] = {}
        # 混合子序表：group_id（""=root）→ [node_id]（图层与嵌套用户组）。
        self._group_orders: dict[str, list[str]] = {}
        self._root_order: list[str] = []
        # V11 稳定排序键：node_id（layer/group）→ key（持久化于 state.tree）。
        self._order_keys: dict[str, str] = {}
        # V11 已应用的树修订号（回声过期判定；0 = 未知/旧桥）。
        self._applied_tree_revision: int = 0
        # V11 最近一次 reconcile 的组成快照（阶段切换时空组重物化用）。
        self._last_snapshots: list | None = None
        self._user_groups: dict[str, GroupNode] = {}
        # V6：宿主推送的新鲜度索引（artifact_key → ArtifactFreshness）。
        self._freshness: dict[str, Any] = {}
        self._load_placements_from_state()

    # -- 装配 -------------------------------------------------------------------

    def attach_canvas(self, canvas: Any, tree_view_address: int = 0) -> None:
        """绑定画布（QgisCanvasShim）与其树视图地址。"""
        self._canvas = canvas
        self._stack = getattr(canvas, "stack", None)
        self._canvas_address = int(getattr(canvas, "canvas_address", 0) or 0)
        self._tree_view_address = int(tree_view_address or 0)
        self.groups_available = bool(self._stack) and all(
            hasattr(self._stack, name) for name in (
                "upsert_group", "remove_groups_except", "move_layer_to_group",
                "set_group_visibility", "tree_snapshot_json")
        )
        # 分组模式：镜像跳过 root 平铺顺序（组结构经本 controller）。
        if hasattr(canvas, "layer_groups_enabled"):
            canvas.layer_groups_enabled = self.groups_available
        if not self.groups_available:
            logger.warning(
                "qgis_render_bridge 缺少 group API——分组功能不可用"
                "（degraded mode：回退平铺图层树）")

    @property
    def degraded(self) -> bool:
        """True = 分组能力不可用（UI 必须显示，不得假装分组）。

        两种情形：完全 fallback 画布（无原生栈，宿主经 mark_fallback 标记）
        或旧桥（有栈但无 group API）。
        """
        if self._fallback_canvas:
            return True
        return self._stack is not None and not self.groups_available

    def mark_fallback(self) -> None:
        """宿主声明画布为完全降级（无原生栈；attach_canvas 不会被调用）。"""
        self._fallback_canvas = True

    def attach_tree_view(self, tree_view_address: int) -> None:
        """绑定 QgsLayerTreeView 地址并注册展开态回调（StageViewState 持久化）。"""
        self._tree_view_address = int(tree_view_address or 0)
        if self._stack is None or not self.groups_available:
            return
        if not self._tree_view_address:
            return
        try:
            self._stack.set_tree_expand_callback(
                self._tree_view_address, self._on_expand_event)
        except Exception:
            logger.debug("set_tree_expand_callback failed", exc_info=True)

    def _on_expand_event(self, node_id: str, expanded: bool) -> None:
        """用户展开/收起组 → 记录到当前阶段（QSettings 侧由宿主持久化）。"""
        self.expand_states[self.state.current_stage.value][str(node_id)] = bool(expanded)

    def reload_from_state(self) -> None:
        """工程状态重载后：重读放置表并作废增量基线（下次 reconcile 全量）。"""
        self._load_placements_from_state()
        self._last_applied = None
        self._last_group_visibility = {}

    def _load_placements_from_state(self) -> None:
        """从持久化树恢复放置表（layer→group / 组内顺序 / 排序键 / 用户组）。"""
        tree_data = self.state.tree or {}
        snapshot = LayerTreeSnapshot.from_dict(tree_data) if tree_data else None
        self._placements.clear()
        self._group_orders.clear()
        self._root_order = []
        self._order_keys.clear()
        self._user_groups.clear()
        if snapshot is None:
            return
        for child in snapshot.children:
            if isinstance(child, LayerRef):
                self._placements[child.layer_id] = ""
                self._root_order.append(child.layer_id)
            else:
                if child.kind == "user":
                    self._user_groups[child.group_id] = child
                self._collect_group(child, child.group_id)
        self._collect_keys(snapshot)

    def _collect_keys(self, snapshot: LayerTreeSnapshot) -> None:
        """收集快照内所有节点的排序键（layer/group 混合命名空间）。"""
        def walk(children) -> None:
            for child in children:
                if child.order_key:
                    node_id = (child.layer_id if isinstance(child, LayerRef)
                               else child.group_id)
                    self._order_keys[node_id] = child.order_key
                if isinstance(child, GroupNode):
                    walk(child.children)

        walk(snapshot.children)

    def _collect_group(self, group: GroupNode, group_id: str) -> None:
        order: list[str] = []
        for child in group.children:
            if isinstance(child, LayerRef):
                self._placements[child.layer_id] = group_id
                order.append(child.layer_id)
            else:
                # V11：嵌套用户组计入父组混合子序（系统/factor 组不嵌套）。
                if child.kind == "user":
                    self._user_groups[child.group_id] = child
                    order.append(child.group_id)
                self._collect_group(child, child.group_id)
        self._group_orders[group_id] = order

    # -- 成员资格与迁移 -----------------------------------------------------------

    def ensure_memberships(self, layer_snapshots: Iterable) -> list[str]:
        """为缺少成员资格的图层做保守归类（旧工程迁移 / 新图层）。

        返回新增 membership 的 layer_id 列表。V11（D13-ws）：组成里已
        消失的图层成员资格在此清理（非空组成才清理——空组成=加载中，
        不能误删），幽灵成员不再膨胀组计数。
        """
        added: list[str] = []
        snapshots = list(layer_snapshots)
        if snapshots:
            live_ids = {
                str(getattr(layer, "id", "") or "") for layer in snapshots}
            stale = [layer_id for layer_id in self.state.memberships
                     if layer_id and layer_id not in live_ids]
            for layer_id in stale:
                self.state.drop_membership(layer_id)
                self._placements.pop(layer_id, None)
                self._order_keys.pop(layer_id, None)
                if layer_id in self._root_order:
                    self._root_order.remove(layer_id)
                for order in self._group_orders.values():
                    if layer_id in order:
                        order.remove(layer_id)
        for layer in snapshots:
            layer_id = str(getattr(layer, "id", "") or "")
            if not layer_id or self.state.membership(layer_id) is not None:
                continue
            role, group, constraint_kind = classify_layer_for_migration(layer)
            record = LayerMembershipRecord(
                layer_id=layer_id, role=role,
                constraint_kind=constraint_kind,
                created_stage=self.state.current_stage.value)
            self.state.set_membership(record)
            added.append(layer_id)
        return added

    def register_layer(
        self,
        layer_id: str,
        role: LayerRole,
        *,
        factor_task_id: str = "",
        constraint_kind: str = "",
        source_version_id: str = "",
    ) -> None:
        """显式注册图层成员资格（RAW→DERIVED 建稿 / 约束创建 / factor 运行）。"""
        self.state.set_membership(LayerMembershipRecord(
            layer_id=str(layer_id),
            role=role,
            factor_task_id=str(factor_task_id),
            constraint_kind=str(constraint_kind),
            created_stage=self.state.current_stage.value,
            source_version_id=str(source_version_id),
        ))
        # 新图层直接进入 home 组（未观察到的旧放置不覆盖）。
        self._placements.pop(str(layer_id), None)

    def unregister_layer(self, layer_id: str) -> None:
        layer_id = str(layer_id)
        self.state.drop_membership(layer_id)
        self._placements.pop(layer_id, None)
        self._root_order = [x for x in self._root_order if x != layer_id]
        for order in self._group_orders.values():
            if layer_id in order:
                order.remove(layer_id)

    # -- 期望树构建 ---------------------------------------------------------------

    def build_desired_tree(self, layer_snapshots: Iterable) -> LayerTreeSnapshot:
        """由模板 + 成员资格 + 用户放置构建期望树（纯函数式，不触碰桥）。

        V11：委托 :mod:`layer_tree_plan`（顺序 = 观察序 + 稳定排序键，
        杜绝快照序覆盖用户重排；QC/辅助按创建阶段路由；用户组可嵌套）。
        """
        layers = list(layer_snapshots)
        records: list[PlanLayerRecord] = []
        for sub_order, layer in enumerate(layers):
            layer_id = str(getattr(layer, "id", "") or "")
            if not layer_id:
                continue
            record = self.state.membership(layer_id)
            records.append(PlanLayerRecord(
                layer_id=layer_id,
                role=record.role if record is not None else None,
                factor_task_id=(record.factor_task_id if record is not None else ""),
                constraint_kind=(record.constraint_kind if record is not None else ""),
                created_stage=(record.created_stage if record is not None
                               else self.state.current_stage.value),
                sub_order=sub_order,
            ))
        plan_input = LayerTreePlanInput(
            records=tuple(records),
            stage=self.state.current_stage,
            user_placements=dict(self._placements),
            container_orders={gid: list(order)
                              for gid, order in self._group_orders.items()}
            | {"": list(self._root_order)},
            user_groups=self._plan_user_groups(),
            order_keys=dict(self._order_keys),
            factor_titles=dict(self.factor_titles),
        )
        snapshot, _facts = build_plan(plan_input)
        return snapshot

    def _plan_user_groups(self) -> dict[str, PlanUserGroup]:
        """_user_groups（GroupNode 树）→ PlanUserGroup 平表（带父指针）。"""
        parent_of: dict[str, str] = {}

        def walk(children, parent_id: str) -> None:
            for child in children:
                if isinstance(child, GroupNode) and child.kind == "user":
                    parent_of[child.group_id] = parent_id
                    walk(child.children, child.group_id)

        walk(self._user_groups.values(), "")
        return {
            group_id: PlanUserGroup(
                group_id=group_id,
                name=group.name,
                parent_group_id=parent_of.get(group_id, ""),
            )
            for group_id, group in self._user_groups.items()
        }

    # -- 增量 reconcile ----------------------------------------------------------

    def reconcile(self, layer_snapshots: Iterable, *, force: bool = False) -> None:
        """把期望树增量应用到 QGIS 树（桥无 group 能力时诚实 no-op）。

        V11：整次应用包在原生树事务窗口内（桥 0.7.0a0+）——create/rename/
        清理/批量放置零中间画布同步，收口一次 sync+refresh；旧桥透明降级。
        """
        if self._stack is None or not self.groups_available:
            return
        self._last_snapshots = list(layer_snapshots)
        desired = self.build_desired_tree(layer_snapshots)
        try:
            with tree_transaction(self._stack) as window:
                self._apply_tree(desired, force=force)
            revision = window.get("revision")
            if isinstance(revision, int) and revision > 0:
                self._applied_tree_revision = revision
            self._last_applied = desired
            self.state.tree = desired.to_dict()
        except Exception:
            # reconcile 失败绝不能吞：记日志 + 保持 last_applied 不变，
            # 下一次 reconcile 重试（V5 §78 error handling）。
            logger.exception("layer group reconcile failed")
            raise

    def rematerialize_for_stage(self) -> bool:
        """V11（D11-ws）：阶段切换后重物化空系统组。

        期望树的空组显隐按**当前阶段**评估（当前阶段的组即使空也物化，
        形成可展开树），而 set_stage 本身不 reconcile——旧工程切换进
        「组全空」的阶段时看不到组，直到下一次组成变更。这里用最近一次
        的组成快照重算期望树：差异 = 新阶段的空组创建（diff 最小操作集，
        组内无 move）。无组成基线时诚实 False（首次 sync 后可用）。
        """
        if self._stack is None or not self.groups_available:
            return False
        if not self._last_snapshots:
            return False
        self.reconcile(self._last_snapshots)
        return True

    def note_applied_tree_revision(self, revision: int) -> None:
        """记录程序化应用后的树修订号（回声过期判定的基准）。"""
        if isinstance(revision, int) and revision > self._applied_tree_revision:
            self._applied_tree_revision = revision

    def echo_is_stale(self, revision: int) -> bool:
        """回声是否过期（≤ 已应用修订号；0 = 旧桥无修订号 → 永不过期）。

        02-authority-model 不变式 3：程序化应用携带修订号，用户回声携带
        事件时修订号；Python 丢弃 revision ≤ 已应用值的回声——这是语义
        级回声抑制（SuppressGuard 之外的第二道防线 + 窗口内竞态检测）。
        """
        if revision <= 0 or self._applied_tree_revision <= 0:
            return False
        return revision <= self._applied_tree_revision

    def _apply_tree(self, desired: LayerTreeSnapshot, *, force: bool = False) -> None:
        """diff 驱动的增量应用（V11：keyed LCS 最小操作集）。

        组集合（create/rename）→ keep-set 清理 → 放置（批量子集，一次
        桥调用；旧桥回落逐 move）。组显隐/展开不在本路径（分别由
        ``apply_stage_visibility``/``apply_group_expanded`` 专职管理，
        避免双写对抗）。
        """
        stack = self._stack
        last = self._last_applied
        current = (last if last is not None and not force
                   else LayerTreeSnapshot(children=(), source="qgis"))
        tree_diff = diff_trees(current, desired)

        # 1) 组创建（拓扑序：父先于子）与重命名。
        for op in tree_diff.group_creates:
            stack.upsert_group(op.group_id, op.name, op.parent)
        for op in tree_diff.group_renames:
            stack.rename_group(op.group_id, op.new_name)

        # 2) keep-set 清理（幂等自愈：一次性桥调用；子图层自动上提）。
        keep_ids = sorted({g.group_id for g in desired.iter_groups()})
        stack.remove_groups_except(keep_ids)

        # 3) 放置：diff 的 move 集（子集批应用，O(changed)）。
        if tree_diff.group_moves or tree_diff.layer_moves:
            batch = getattr(stack, "apply_tree_placements", None)
            if callable(batch):
                import json as _json

                placements = [
                    {"node": f"group:{op.group_id}", "parent": op.new_parent,
                     "index": op.new_index}
                    for op in tree_diff.group_moves
                ] + [
                    {"node": op.layer_id, "parent": op.new_parent,
                     "index": op.new_index}
                    for op in tree_diff.layer_moves
                ]
                batch(_json.dumps(placements))
            else:
                for op in tree_diff.group_moves:
                    stack.move_group(op.group_id, op.new_parent, op.new_index)
                for op in tree_diff.layer_moves:
                    stack.move_layer_to_group(
                        op.layer_id, op.new_parent, op.new_index)

        # 4) 更新运行时放置表 + 排序键（期望树是唯一事实源）。
        self._placements.clear()
        self._group_orders.clear()
        self._root_order = []
        for child in desired.children:
            if isinstance(child, LayerRef):
                self._placements[child.layer_id] = ""
                self._root_order.append(child.layer_id)
            else:
                if child.kind == "user":
                    self._user_groups[child.group_id] = child
                self._collect_group(child, child.group_id)
        self._order_keys.clear()
        self._collect_keys(desired)

    # -- 组可见性（阶段 profile + 用户覆盖） ---------------------------------------

    def apply_stage_visibility(self, stage: MappingStage) -> dict[str, bool]:
        """应用阶段有效组显隐（profile 默认 + 用户覆盖）→ 返回有效值表。"""
        if self._stack is None or not self.groups_available:
            return {}
        profile = stage_profile(stage)
        view_state = self.state.view_state(stage)
        effective = view_state.effective_group_visibility(profile.group_visibility)
        # 锁定语义：证据组在锁定阶段的组锁默认（用户可解锁）。
        for group_id in profile.locked_groups:
            if group_id in {t.group_id for t in SYSTEM_GROUP_TEMPLATES}:
                locked = view_state.group_locked.get(group_id)
                if locked is None:
                    view_state.group_locked[group_id] = True
        changed = 0
        for group_id, visible in effective.items():
            if group_id not in self._last_group_visibility or \
                    self._last_group_visibility[group_id] != visible:
                try:
                    self._stack.set_group_visibility(group_id, visible)
                    # 成功才记已应用：失败的显隐保持未应用态，后续重试
                    #（否则记忆表与 QGIS 实际显隐永久漂移）。
                    self._last_group_visibility[group_id] = visible
                    changed += 1
                except Exception:
                    logger.debug("set_group_visibility failed for %s", group_id,
                                 exc_info=True)
        return effective

    def set_group_visible(self, group_id: str, visible: bool,
                          *, record: bool = True) -> None:
        """程序化组显隐（记录到当前阶段视图状态）。"""
        if self._stack is not None and self.groups_available:
            try:
                self._stack.set_group_visibility(group_id, bool(visible))
                self._last_group_visibility[group_id] = bool(visible)
            except Exception:
                logger.debug("set_group_visibility failed for %s", group_id,
                             exc_info=True)
        if record:
            self.state.view_state(self.state.current_stage).record_group_visibility(
                group_id, bool(visible))

    def apply_group_expanded(self, expanded_map: dict[str, bool]) -> None:
        """恢复组展开态（QSettings 侧持久化，V5 §45）。"""
        if self._stack is None or not self.groups_available:
            return
        if not self._tree_view_address:
            return
        expanded = dict(expanded_map or {})
        expanded.setdefault(BASE_REFERENCE_GROUP_ID, True)
        for template in SYSTEM_GROUP_TEMPLATES:
            expanded.setdefault(template.group_id, True)
        for node_id, is_open in expanded.items():
            try:
                self._stack.set_group_expanded(
                    self._tree_view_address, str(node_id), bool(is_open))
            except Exception:
                pass

    # -- 用户组管理 ---------------------------------------------------------------

    def create_user_group(self, name: str, parent_group_id: str = "") -> str:
        """创建用户组（V11：parent 可为另一用户组——嵌套用户组）。

        parent 必须是用户组或 root（系统组/factor 组不可承载用户子组）。
        返回新组 id；父组非法时组创建在 root（保守回退，不抛）。
        """
        import time

        parent = str(parent_group_id or "")
        if parent and (parent.startswith(("phase", "factor"))
                       or system_group_template(parent) is not None
                       or parent not in self._user_groups):
            parent = ""
        group_id = f"user.{int(time.time() * 1000) & 0xffffffff:08x}"
        self._user_groups[group_id] = GroupNode(
            group_id=group_id, name=name or "新建组", kind="user")
        if parent:
            self._group_orders.setdefault(parent, []).append(group_id)
        else:
            self._root_order.append(group_id)
        return group_id

    def rename_user_group(self, group_id: str, name: str) -> None:
        group = self._user_groups.get(group_id)
        if group is None:
            return
        from dataclasses import replace as _replace
        self._user_groups[group_id] = _replace(group, name=name)
        if self._stack is not None and self.groups_available:
            try:
                self._stack.rename_group(group_id, name)
            except Exception:
                logger.debug("rename_group failed for %s", group_id, exc_info=True)

    def remove_user_group(self, group_id: str, *, keep_layers: bool = True) -> None:
        """删除用户组；子图层与嵌套用户组上提一级（绝不删层/删组内容）。"""
        group = self._user_groups.pop(group_id, None)
        if group is None:
            return
        # 找父容器（root 或嵌套父组）。
        parent_id = ""
        for candidate_id, order in self._group_orders.items():
            if group_id in order:
                parent_id = candidate_id
                break
        moved = list(self._group_orders.pop(group_id, []))
        target_order = (self._root_order if parent_id == ""
                        else self._group_orders.setdefault(parent_id, []))
        insert_at = target_order.index(group_id) if group_id in target_order else len(target_order)
        target_order[insert_at:insert_at + 1] = moved
        for node_id in moved:
            if node_id in self._user_groups:
                continue  # 嵌套用户组整体上提（其成员表不动）
            self._placements[node_id] = parent_id
        self._order_keys.pop(group_id, None)
        for order in self._group_orders.values():
            if group_id in order:
                order.remove(group_id)
        if group_id in self._root_order:
            self._root_order.remove(group_id)

    # -- 用户树事件回写 -------------------------------------------------------------

    def observe_tree_nodes(self, nodes: list[dict]) -> bool:
        """用户结构变更（拖拽/建组/删组）回写期望树。

        返回 True 表示变更被接受；False 表示存在非法放置（角色路由冲突，
        期望树保持原状——下一次 reconcile 会把 QGIS 树拉回正确位置）。
        V11：观察序直接转化为稳定排序键（LIS 保键 + 中点插入）；非法
        放置携带 (layer_id, group_id) 反馈，不再丢 id。
        """
        observed = tree_from_nodes(nodes)
        # 用户组发现：观察树中不在系统模板/factor 集中的组 → 用户组。
        system_ids = {t.group_id for t in SYSTEM_GROUP_TEMPLATES}
        # 先收集，全部校验通过才提交（拒绝时回滚，不留幽灵组）。
        discovered_user_groups: dict[str, GroupNode] = {}
        for group in observed.iter_groups():
            gid = group.group_id
            if gid and gid not in system_ids and not gid.startswith("factor.") \
                    and gid not in self._user_groups:
                discovered_user_groups[gid] = GroupNode(
                    group_id=gid, name=group.name or gid, kind="user")
        # 放置回写（含角色校验 + 非法放置 id 捕获）。
        rejected_with: tuple[str, str] | None = None
        placements: dict[str, str] = {}
        orders: dict[str, list[str]] = {}
        root_order: list[str] = []

        def walk(children, parent_id):
            nonlocal rejected_with
            for child in children:
                if isinstance(child, GroupNode):
                    if parent_id:
                        orders.setdefault(parent_id, []).append(child.group_id)
                    else:
                        root_order.append(child.group_id)
                    walk(child.children, child.group_id)
                else:
                    layer_id = child.layer_id
                    record = self.state.membership(layer_id)
                    if parent_id and parent_id in system_ids and record is not None:
                        if not movable_into_system_group(record.role, parent_id):
                            if rejected_with is None:
                                rejected_with = (layer_id, parent_id)
                            continue
                    placements[layer_id] = parent_id
                    if parent_id:
                        orders.setdefault(parent_id, []).append(layer_id)
                    else:
                        root_order.append(layer_id)

        walk(observed.children, "")
        if rejected_with is not None:
            self.last_observe_rejected = True
            if self.on_invalid_move is not None:
                try:
                    self.on_invalid_move(*rejected_with)
                except Exception:
                    pass
            return False
        self.last_observe_rejected = False
        self._user_groups.update(discovered_user_groups)
        self._placements = placements
        self._group_orders = orders
        self._root_order = root_order
        # 观察序 → 键（含嵌套用户组混合序；最小扰动，用户拖动只改少数键）。
        self._order_keys.update(assign_keys_for_order(root_order, self._order_keys))
        for order in orders.values():
            self._order_keys.update(assign_keys_for_order(order, self._order_keys))
        # 用户组内成员同步到用户组节点（保持 group_orders 为准）。
        if self.on_structure_changed is not None:
            try:
                self.on_structure_changed()
            except Exception:
                pass
        return True

    def record_group_visibility_event(self, group_id: str, visible: bool) -> None:
        """用户在树上勾选组（QGIS tri-state 解析后的有效态）→ 记录阶段视图状态。"""
        self._last_group_visibility[group_id] = bool(visible)
        self.state.view_state(self.state.current_stage).record_group_visibility(
            group_id, bool(visible))

    # -- 查询 ---------------------------------------------------------------------

    def placement_of(self, layer_id: str) -> str:
        """图层归属组（运行时放置表 → 成员资格路由兜底，degraded 同样有效）。

        V11：路由统一走 :func:`effective_home_group`（QC/辅助按创建阶段
        aux 路由）——树构建、呈现与编辑门禁同源，杜绝 D1-ws 分叉。
        """
        layer_id = str(layer_id)
        if layer_id in self._placements:
            return self._placements[layer_id]
        record = self.state.membership(layer_id)
        if record is not None:
            return effective_home_group(
                record.role,
                created_stage=record.created_stage,
                factor_task_id=record.factor_task_id,
            )
        return ""

    def _group_members(self, group_id: str) -> list[str]:
        """组成员（reconcile 序 + 未观察到的成员资格派生；fallback 画布
        无 reconcile 时聚合仍真实）。V11：混合子序表过滤嵌套组 id。"""
        order = [nid for nid in self._group_orders.get(group_id, [])
                 if nid not in self._user_groups]
        seen = set(order)
        for layer_id in self.state.memberships:
            if layer_id not in seen and self.placement_of(layer_id) == group_id:
                order.append(layer_id)
                seen.add(layer_id)
        return order

    def group_summary(self, group_id: str) -> dict[str, int]:
        """组内状态聚合（真实新鲜度统计；宿主经 ``apply_freshness`` 推送）。

        stale = 组内成员命中过期/缺失/被取代的成果数；
        errors = 其中输入缺失（MISSING_INPUT）数。未推送过 freshness 或
        成员无成员资格 → 诚实 0（此前硬编码 0/0，V6 修复）。

        V7 §7 追加 frozen/published：组内成员成熟度计数（经
        ``set_maturity_provider`` 注入的回调；未注入 → 诚实 0，不猜）。
        """
        from paleo_workbench.mapping_workspace.dependencies import FreshnessStatus

        order = self._group_members(group_id)
        stale = 0
        errors = 0
        for layer_id in order:
            artifact = self.layer_freshness(layer_id)
            if artifact is not None and artifact.is_problem:
                stale += 1
                if artifact.status == FreshnessStatus.MISSING_INPUT:
                    errors += 1
        frozen = published = 0
        maturity_of = getattr(self, "_maturity_of", None)
        if maturity_of is not None:
            for layer_id in order:
                maturity = str(maturity_of(layer_id) or "")
                if maturity == "frozen":
                    frozen += 1
                elif maturity == "published":
                    published += 1
        return {
            "layers": len(order), "stale": stale, "errors": errors,
            "frozen": frozen, "published": published,
        }

    def group_ids(self) -> tuple[str, ...]:
        """已知组 id（reconcile 序 + 成员资格派生；fallback 画布同样真实）。"""
        ids = list(self._group_orders.keys())
        for layer_id in self.state.memberships:
            group_id = self.placement_of(layer_id)
            if group_id and group_id not in ids:
                ids.append(group_id)
        return tuple(ids)

    def artifact_freshness(self, artifact_key: str):
        """按 artifact key 取新鲜度评估（mapproduct 等非图层工件；未评估 → None）。"""
        return self._freshness.get(str(artifact_key)) if self._freshness else None

    def set_maturity_provider(self, callback) -> None:
        """注入成熟度回调（``layer_id -> str | None``；组聚合用）。

        权威在 MappingWorkspaceState.artifact_maturity（宿主适配）；本
        controller 不解析 artifact key——键解析与宿主的
        ``_layer_maturity_value`` 同源，不在两处重复。
        """
        self._maturity_of = callback

    def apply_freshness(self, summary) -> None:
        """宿主推送 ``StaleSummary``（阶段控制器 stale_summary_changed 接线）。"""
        self._freshness = {
            str(artifact.artifact_key): artifact
            for artifact in (getattr(summary, "artifacts", None) or ())
        }

    def layer_freshness(self, layer_id: str):
        """图层级新鲜度（成员资格 → artifact_key 解析；无 → None=未知）。"""
        if not self._freshness:
            return None
        record = self.state.membership(layer_id)
        if record is None:
            return None
        from paleo_workbench.mapping_workspace.artifact_keys import (
            candidate_artifact_keys,
        )

        for key in candidate_artifact_keys(layer_id, record):
            artifact = self._freshness.get(key)
            if artifact is not None:
                return artifact
        return None

    def sync_factor_titles(self, titles: dict[str, str]) -> None:
        self.factor_titles = {str(k): str(v) for k, v in (titles or {}).items()}

    def snapshot_bridge_tree(self) -> LayerTreeSnapshot | None:
        """读取桥侧树快照（观察/对账用；桥不可用返回 None）。"""
        if self._stack is None or not self.groups_available:
            return None
        try:
            import json as _json

            payload = self._stack.tree_snapshot_json()
            data = _json.loads(payload) if payload else {}
            return tree_from_nodes(list(data.get("children") or ()))
        except Exception:
            logger.debug("tree_snapshot_json failed", exc_info=True)
            return None
