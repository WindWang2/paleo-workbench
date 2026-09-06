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
    FACTOR_CHILD_ORDER,
    FACTOR_ROOT_GROUP_ID,
    SYSTEM_GROUP_TEMPLATES,
    classify_layer_for_migration,
    factor_group_id,
    factor_task_of_group,
    home_group_for_role,
    movable_into_system_group,
    system_group_template,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.layer_tree import (
    GroupNode,
    LayerRef,
    LayerTreeSnapshot,
    tree_from_nodes,
)
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
        self._group_orders: dict[str, list[str]] = {}   # group_id → [layer_id]
        self._root_order: list[str] = []
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
        """从持久化树恢复放置表（layer→group / 组内顺序 / 用户组）。"""
        tree_data = self.state.tree or {}
        snapshot = LayerTreeSnapshot.from_dict(tree_data) if tree_data else None
        self._placements.clear()
        self._group_orders.clear()
        self._root_order = []
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

    def _collect_group(self, group: GroupNode, group_id: str) -> None:
        order: list[str] = []
        for child in group.children:
            if isinstance(child, LayerRef):
                self._placements[child.layer_id] = group_id
                order.append(child.layer_id)
            else:
                if child.kind == "user":
                    self._user_groups[child.group_id] = child
                self._collect_group(child, child.group_id)
        self._group_orders[group_id] = order

    # -- 成员资格与迁移 -----------------------------------------------------------

    def ensure_memberships(self, layer_snapshots: Iterable) -> list[str]:
        """为缺少成员资格的图层做保守归类（旧工程迁移 / 新图层）。

        返回新增 membership 的 layer_id 列表。
        """
        added: list[str] = []
        for layer in layer_snapshots:
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
        """由模板 + 成员资格 + 用户放置构建期望树（纯函数式，不触碰桥）。"""
        layers = list(layer_snapshots)
        known_ids = [str(getattr(l, "id", "") or "") for l in layers]
        # group_id → [layer_id]（快照序，组内保持稳定顺序）
        buckets: dict[str, list[str]] = {}
        root_layers: list[str] = []
        for layer_id in known_ids:
            placement = self._placements.get(layer_id, None)
            if placement is None:
                record = self.state.membership(layer_id)
                if record is None:
                    placement = ""  # 未注册图层留 root（ensure_memberships 先行）
                else:
                    placement = home_group_for_role(
                        record.role,
                        stage=None,
                        factor_task_id=record.factor_task_id,
                    )
            if placement and (system_group_template(placement)
                              or placement in self._user_groups
                              or placement.startswith("factor.")
                              or placement in self._group_orders):
                buckets.setdefault(placement, []).append(layer_id)
            elif placement == "":
                root_layers.append(layer_id)
            else:
                # 指向不存在组的放置（组已删）→ 回 home 组
                record = self.state.membership(layer_id)
                home = home_group_for_role(
                    record.role, factor_task_id=record.factor_task_id or "") if record else ""
                buckets.setdefault(home or "", []).append(layer_id)

        # factor 组内按 FACTOR_CHILD_ORDER 角色排序。
        for group_id, order in list(buckets.items()):
            if group_id.startswith("factor."):
                role_rank = {}
                for layer_id in order:
                    record = self.state.membership(layer_id)
                    role = record.role if record else None
                    rank = (FACTOR_CHILD_ORDER.index(role)
                            if role in FACTOR_CHILD_ORDER else len(FACTOR_CHILD_ORDER))
                    role_rank[layer_id] = rank
                buckets[group_id] = sorted(
                    order, key=lambda lid: (role_rank[lid], known_ids.index(lid)))

        def group_children(group_id: str) -> tuple:
            children: list[GroupNode | LayerRef] = []
            # factor 子组（factor.<task_id>）统一挂在 FACTOR_ROOT 下；
            # 它们是动态系统组（不在 SYSTEM_GROUP_TEMPLATES 里，经
            # factor_titles / 成员资格发现），按任务 id 稳定排序。
            if group_id == FACTOR_ROOT_GROUP_ID:
                factor_ids = sorted({
                    gid for gid in buckets
                    if gid.startswith("factor.")
                } | {
                    gid for gid in self._group_orders if gid.startswith("factor.")
                })
                for factor_id in factor_ids:
                    children.append(make_group(factor_id))
            for layer_id in buckets.get(group_id, []):
                children.append(LayerRef(layer_id=layer_id))
            # 用户组挂在 root（V5 首版：用户组仅 root 级）
            if group_id == "":
                for user_group in self._user_groups.values():
                    children.append(user_group)
            return tuple(children)

        def make_group(group_id: str) -> GroupNode:
            template = system_group_template(group_id)
            if template is not None:
                return GroupNode(
                    group_id=group_id,
                    name=template.title,
                    kind="system",
                    children=group_children(group_id),
                )
            if group_id.startswith("factor."):
                task_id = factor_task_of_group(group_id) or ""
                title = self.factor_titles.get(task_id, task_id or group_id)
                return GroupNode(
                    group_id=group_id, name=title, kind="system",
                    children=group_children(group_id))
            user = self._user_groups.get(group_id)
            if user is not None:
                return GroupNode(
                    group_id=group_id, name=user.name, kind="user",
                    children=tuple(
                        LayerRef(layer_id=lid) for lid in self._group_orders.get(group_id, [])
                    ))
            return GroupNode(group_id=group_id, name=group_id, kind="user",
                             children=())

        roots: list[GroupNode | LayerRef] = []
        for template in SYSTEM_GROUP_TEMPLATES:
            roots.append(make_group(template.group_id))
        for user_group in self._user_groups.values():
            roots.append(user_group)
        for layer_id in root_layers:
            roots.append(LayerRef(layer_id=layer_id))
        return LayerTreeSnapshot(children=tuple(roots), source="domain")

    # -- 增量 reconcile ----------------------------------------------------------

    def reconcile(self, layer_snapshots: Iterable, *, force: bool = False) -> None:
        """把期望树增量应用到 QGIS 树（桥无 group 能力时诚实 no-op）。"""
        if self._stack is None or not self.groups_available:
            return
        desired = self.build_desired_tree(layer_snapshots)
        try:
            self._apply_tree(desired, force=force)
            self._last_applied = desired
            self.state.tree = desired.to_dict()
        except Exception:
            # reconcile 失败绝不能吞：记日志 + 保持 last_applied 不变，
            # 下一次 reconcile 重试（V5 §78 error handling）。
            logger.exception("layer group reconcile failed")
            raise

    def _apply_tree(self, desired: LayerTreeSnapshot, *, force: bool = False) -> None:
        stack = self._stack
        last = self._last_applied

        # 1) 组集合增量：upsert 全部期望组（幂等：重命名/挂载校验内含），
        #    remove 未列组（子图层自动上提，绝不删层）。
        desired_groups = {g.group_id: g for g in desired.iter_groups()}
        for group_id, group in desired_groups.items():
            template = system_group_template(group_id)
            parent = template.parent_id if template is not None else (
                FACTOR_ROOT_GROUP_ID if group_id.startswith("factor.") else "")
            stack.upsert_group(group_id, group.name, parent)
        keep_ids = sorted({g.group_id for g in desired.iter_groups()})
        stack.remove_groups_except(keep_ids)

        # 2) 组间顺序（root 级）与组内放置增量。
        if last is None or force:
            self._place_all(desired)
        else:
            self._place_delta(last, desired)

        # 3) 更新运行时放置表。
        self._placements.clear()
        self._group_orders.clear()
        self._root_order = []
        for child in desired.children:
            if isinstance(child, LayerRef):
                self._placements[child.layer_id] = ""
                self._root_order.append(child.layer_id)
            else:
                self._collect_group(child, child.group_id)

    def _placements_of(self, desired: LayerTreeSnapshot) -> list[dict]:
        """期望树 → 扁平放置指令（node/parent/index，深度优先）。"""
        placements: list[dict] = []

        def walk(children, parent_id):
            for index, child in enumerate(children):
                if isinstance(child, GroupNode):
                    placements.append({
                        "node": f"group:{child.group_id}",
                        "parent": parent_id,
                        "index": index,
                    })
                    walk(child.children, child.group_id)
                else:
                    placements.append({
                        "node": child.layer_id,
                        "parent": parent_id,
                        "index": index,
                    })

        walk(desired.children, "")
        return placements

    def _place_all(self, desired: LayerTreeSnapshot) -> None:
        # 批量放置（桥 O(N) 路径）；旧桥回落逐个 move（兼容，规模小可接受）。
        batch = getattr(self._stack, "apply_tree_placements", None)
        if callable(batch):
            import json as _json

            batch(_json.dumps(self._placements_of(desired)))
            return
        root_children = list(desired.children)
        for index, child in enumerate(root_children):
            if isinstance(child, GroupNode):
                self._stack.move_group(child.group_id, "", index)
                self._place_group_children(child)
            else:
                self._stack.move_layer_to_group(child.layer_id, "", index)

    def _place_group_children(self, group: GroupNode) -> None:
        for index, child in enumerate(group.children):
            if isinstance(child, GroupNode):
                self._stack.move_group(child.group_id, group.group_id, index)
                self._place_group_children(child)
            else:
                self._stack.move_layer_to_group(
                    child.layer_id, group.group_id, index)

    def _place_delta(self, last: LayerTreeSnapshot, desired: LayerTreeSnapshot) -> None:
        def walk(last_group_children, desired_group_children, group_id):
            last_ids = [c.group_id if isinstance(c, GroupNode) else c.layer_id
                        for c in last_group_children]
            desired_ids = [c.group_id if isinstance(c, GroupNode) else c.layer_id
                           for c in desired_group_children]
            if last_ids != desired_ids:
                for index, child in enumerate(desired_group_children):
                    if isinstance(child, GroupNode):
                        self._stack.move_group(child.group_id, group_id, index)
                        self._place_group_children(child)  # 子树全量校正（低频）
                    else:
                        self._stack.move_layer_to_group(child.layer_id, group_id, index)
            else:
                for last_child, desired_child in zip(last_group_children,
                                                     desired_group_children):
                    if isinstance(desired_child, GroupNode):
                        walk(getattr(last_child, "children", ()),
                             desired_child.children, desired_child.group_id)

        walk(list(last.children), list(desired.children), "")

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
        for node_id, expanded in (expanded_map or {}).items():
            try:
                self._stack.set_group_expanded(
                    self._tree_view_address, str(node_id), bool(expanded))
            except Exception:
                pass

    # -- 用户组管理 ---------------------------------------------------------------

    def create_user_group(self, name: str) -> str:
        import time

        group_id = f"user.{int(time.time() * 1000) & 0xffffffff:08x}"
        self._user_groups[group_id] = GroupNode(
            group_id=group_id, name=name or "新建组", kind="user")
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
                pass

    def remove_user_group(self, group_id: str, *, keep_layers: bool = True) -> None:
        """删除用户组；keep_layers=True 时图层上提到 root（绝不删层）。"""
        group = self._user_groups.pop(group_id, None)
        if group is None:
            return
        moved = list(self._group_orders.get(group_id, []))
        self._group_orders.pop(group_id, None)
        for layer_id in moved:
            self._placements[layer_id] = ""
            if layer_id not in self._root_order:
                self._root_order.append(layer_id)

    # -- 用户树事件回写 -------------------------------------------------------------

    def observe_tree_nodes(self, nodes: list[dict]) -> bool:
        """用户结构变更（拖拽/建组/删组）回写期望树。

        返回 True 表示变更被接受；False 表示存在非法放置（角色路由冲突，
        期望树保持原状——下一次 reconcile 会把 QGIS 树拉回正确位置）。
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
        # 放置回写（含角色校验）。
        rejected = False
        placements: dict[str, str] = {}
        orders: dict[str, list[str]] = {}
        root_order: list[str] = []

        def walk(children, parent_id):
            nonlocal rejected
            for child in children:
                if isinstance(child, GroupNode):
                    walk(child.children, child.group_id)
                else:
                    layer_id = child.layer_id
                    record = self.state.membership(layer_id)
                    if parent_id and parent_id in system_ids and record is not None:
                        if not movable_into_system_group(record.role, parent_id):
                            rejected = True
                            continue
                    placements[layer_id] = parent_id
                    if parent_id:
                        orders.setdefault(parent_id, []).append(layer_id)
                    else:
                        root_order.append(layer_id)

        walk(observed.children, "")
        if rejected:
            self.last_observe_rejected = True
            if self.on_invalid_move is not None:
                try:
                    self.on_invalid_move("", "")
                except Exception:
                    pass
            return False
        self.last_observe_rejected = False
        self._user_groups.update(discovered_user_groups)
        self._placements = placements
        self._group_orders = orders
        self._root_order = root_order
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
        """图层归属组（运行时放置表 → 成员资格路由兜底，degraded 同样有效）。"""
        layer_id = str(layer_id)
        if layer_id in self._placements:
            return self._placements[layer_id]
        record = self.state.membership(layer_id)
        if record is not None:
            return home_group_for_role(
                record.role, factor_task_id=record.factor_task_id)
        return ""

    def group_summary(self, group_id: str) -> dict[str, int]:
        """组内状态聚合（真实新鲜度统计；宿主经 ``apply_freshness`` 推送）。

        stale = 组内成员命中过期/缺失/被取代的成果数；
        errors = 其中输入缺失（MISSING_INPUT）数。未推送过 freshness 或
        成员无成员资格 → 诚实 0（此前硬编码 0/0，V6 修复）。
        """
        from paleo_workbench.mapping_workspace.dependencies import FreshnessStatus

        order = self._group_orders.get(group_id, [])
        stale = 0
        errors = 0
        for layer_id in order:
            artifact = self.layer_freshness(layer_id)
            if artifact is not None and artifact.is_problem:
                stale += 1
                if artifact.status == FreshnessStatus.MISSING_INPUT:
                    errors += 1
        return {"layers": len(order), "stale": stale, "errors": errors}

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
        candidate_keys: list[str] = []
        if record.factor_task_id:
            candidate_keys.append(f"factor:{record.factor_task_id}")
        if record.role == LayerRole.INITIAL_FACIES_DRAFT:
            candidate_keys.append(f"phase1_draft:{layer_id}")
        if record.role in (LayerRole.INTEGRATED_FACIES, LayerRole.INTEGRATED_BOUNDARY):
            candidate_keys.append(f"integrated:{layer_id}")
        for key in candidate_keys:
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
