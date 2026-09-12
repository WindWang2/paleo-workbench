"""V11 LayerTreePlan：期望树的声明式构建（纯函数，无 Qt）。

设计（docs/development/qgis-cartography-runtime-v11/03-layer-tree-plan.md）：
``LayerTreeSnapshot`` 保持树载体；本模块是**产生期望快照的策略层**——
输入成员资格、用户放置、观察序与持久化排序键，输出带键的期望树 +
plan facts。``LayerGroupController.build_desired_tree`` 是它的薄包装。

顺序规则（04-ordering.md）：
* 容器内最终顺序 = 观察序（用户拖拽回写，D3-ws 修复）+ 新成员按默认
  科学序（factor 容器用 FACTOR_CHILD_ORDER 秩，其余用角色带）尾部并入；
  首见容器直接用默认科学序。
* 顺序 → 键经 :func:`layer_order.assign_keys_for_order`（LIS 保键，
  中点插入，绝不全表重编号）。
* 系统组顺序 = 模板声明序（键 = 全模板集上的固定索引键，空组显隐
  不改变其它组的键）；factor 组按任务 id 排序；用户组按持久化键，
  且 V11 起可嵌套（用户组内用户组）。

QC/辅助角色路由（D1-ws 修复）：统一使用成员资格记录的**创建阶段**
做 aux/qc 路由——树构建、呈现与编辑门禁从此同源。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from paleo_workbench.mapping_workspace.layer_groups import (
    BASE_REFERENCE_GROUP_ID,
    FACTOR_ROOT_GROUP_ID,
    SYSTEM_GROUP_TEMPLATES,
    factor_group_id,
    factor_task_of_group,
    home_group_for_role,
    system_group_template,
)
from paleo_workbench.mapping_workspace.layer_order import (
    assign_keys_for_order,
    factor_role_rank,
    key_for_index,
    role_band,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.layer_tree import (
    GroupNode,
    LayerRef,
    LayerTreeSnapshot,
)
from paleo_workbench.mapping_workspace.stages import MappingStage, stage_from_value

__all__ = [
    "PlanLayerRecord",
    "PlanUserGroup",
    "LayerTreePlanInput",
    "LayerTreePlanFacts",
    "build_plan",
    "effective_home_group",
]


@dataclass(frozen=True)
class PlanLayerRecord:
    """图层的 plan 输入记录（从成员资格 + 快照序派生）。"""

    layer_id: str
    role: LayerRole | str | None = None
    factor_task_id: str = ""
    constraint_kind: str = ""
    #: 创建阶段值（如 "phase1"）——QC/辅助角色 aux 路由用。
    created_stage: str = ""
    #: 科学子序（组成快照位置的稳定 tiebreak）。
    sub_order: int = 0


@dataclass(frozen=True)
class PlanUserGroup:
    """用户组（V11：可嵌套——parent 可为另一用户组或 root）。"""

    group_id: str
    name: str
    parent_group_id: str = ""


@dataclass(frozen=True)
class LayerTreePlanInput:
    records: tuple[PlanLayerRecord, ...] = ()
    #: 当前阶段（只影响空组显隐物化，不影响结构/顺序）。
    stage: MappingStage | None = None
    #: 用户放置覆盖（layer_id → group_id；"" = root）。
    user_placements: Mapping[str, str] = field(default_factory=dict)
    #: 观察序（group_id（""=root 松散层）→ 位置序列，含用户拖拽回写）。
    container_orders: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: 用户组表（含嵌套父指针）。
    user_groups: Mapping[str, PlanUserGroup] = field(default_factory=dict)
    #: 持久化排序键（node_id → key）。
    order_keys: Mapping[str, str] = field(default_factory=dict)
    factor_titles: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LayerTreePlanFacts:
    """plan 副产物：默认键（可丢弃重算）与覆盖键（用户意图，必须持久化）。"""

    default_keys: Mapping[str, str] = field(default_factory=dict)
    override_keys: Mapping[str, str] = field(default_factory=dict)
    group_kinds: Mapping[str, str] = field(default_factory=dict)
    #: 本次物化的空系统组（当前阶段可见/base.reference）。
    materialized_empty_groups: tuple[str, ...] = ()


def effective_home_group(
    role: LayerRole | str | None,
    created_stage: str = "",
    factor_task_id: str = "",
) -> str:
    """统一 home 路由：QC/辅助按创建阶段（记录值），其余按静态 home。

    树构建/呈现/编辑门禁共用本函数，杜绝 stage-aware 与 stage-None
    两种调用点分叉（D1-ws）。
    """
    stage = stage_from_value(created_stage) if created_stage else None
    return home_group_for_role(role, stage=stage, factor_task_id=factor_task_id)


def _default_layer_sort_key(record: PlanLayerRecord, factor_container: bool):
    if factor_container:
        return (factor_role_rank(record.role), record.sub_order, record.layer_id)
    return (role_band(record.role), record.sub_order, record.layer_id)


def _merge_container_order(
    container_id: str,
    members: list[PlanLayerRecord],
    observed: Sequence[str] | None,
    factor_container: bool,
) -> list[str]:
    """容器内最终顺序：观察序（存活成员）+ 新成员默认序尾部并入。"""
    by_id = {record.layer_id: record for record in members}
    ordered: list[str] = []
    if observed:
        seen = set()
        for node_id in observed:
            if node_id in by_id and node_id not in seen:
                ordered.append(node_id)
                seen.add(node_id)
        fresh = sorted(
            (r for r in members if r.layer_id not in seen),
            key=lambda r: _default_layer_sort_key(r, factor_container),
        )
        ordered.extend(r.layer_id for r in fresh)
        return ordered
    fresh = sorted(members, key=lambda r: _default_layer_sort_key(r, factor_container))
    return [r.layer_id for r in fresh]


def build_plan(plan_input: LayerTreePlanInput) -> tuple[LayerTreeSnapshot, LayerTreePlanFacts]:
    """构建期望树 + plan facts（纯函数、确定性：同输入 → 同输出）。"""
    system_ids = {t.group_id for t in SYSTEM_GROUP_TEMPLATES}
    template_index = {t.group_id: i for i, t in enumerate(SYSTEM_GROUP_TEMPLATES)}

    # 1) 成员路由：用户放置（容器存在时）→ 创建阶段 home → root。
    containers: dict[str, list[PlanLayerRecord]] = {}
    root_layers: list[PlanLayerRecord] = []
    # R1-P0：容器存在性只认三类真源（系统模板 / user_groups 注册表 /
    # factor 命名空间）。container_orders 是顺序提示，不是存在性证明——
    # 幽灵键（拼写错误/过期组）不得创建无挂载容器吞层。
    for record in plan_input.records:
        placement = plan_input.user_placements.get(record.layer_id)
        if placement is None:
            placement = effective_home_group(
                record.role,
                created_stage=record.created_stage,
                factor_task_id=record.factor_task_id,
            )
        known = (
            placement == ""
            or placement in system_ids
            or placement in plan_input.user_groups
            or placement.startswith("factor.")
        )
        if not known:
            placement = effective_home_group(
                record.role,
                created_stage=record.created_stage,
                factor_task_id=record.factor_task_id,
            )
            known = placement in system_ids or placement.startswith("factor.")
        if placement == "" or not known:
            root_layers.append(record)
        else:
            containers.setdefault(placement, []).append(record)

    # 2) 容器内顺序 + 键。
    keys: dict[str, str] = dict(plan_input.order_keys)
    orders: dict[str, list[str]] = {}
    for group_id, members in containers.items():
        factor_container = group_id.startswith("factor.")
        merged = _merge_container_order(
            group_id, members,
            plan_input.container_orders.get(group_id), factor_container)
        orders[group_id] = merged
        new_keys = assign_keys_for_order(merged, keys)
        keys.update(new_keys)

    # root 松散层（同样观察序优先）。
    root_ids = _merge_container_order(
        "", root_layers, plan_input.container_orders.get(""), False)
    keys.update(assign_keys_for_order(root_ids, keys))

    # 3) factor 子组（union：当前成员 + 观察到的历史 factor 组）。
    factor_ids = sorted(
        {gid for gid in containers if gid.startswith("factor.")}
        | {gid for gid in plan_input.container_orders if gid.startswith("factor.")}
    )

    # 4) 用户组树（嵌套）：子序 = 观察混合序（嵌套组 + 图层，键统一分配）。
    # R1-P0：parent 指针消毒——自环/成环/未知父一律回 root（否则无限递归）；
    # 观察序挂载只认「本组路由成员 + 已消毒的子组」，系统组内层/已删 id
    # 一律不过滤进用户组（防双挂载 + 幽灵）。
    member_of: dict[str, set[str]] = {}
    for group_id, members in containers.items():
        if group_id in plan_input.user_groups:
            member_of[group_id] = {record.layer_id for record in members}
    safe_parents: dict[str, str] = {}
    for group_id, info in plan_input.user_groups.items():
        parent = info.parent_group_id or ""
        if parent == group_id or parent not in plan_input.user_groups:
            # 自环 / 未知父（含系统组 id）→ root；成环由下面的访问集兜底。
            parent = ""
        safe_parents[group_id] = parent
    user_children_of: dict[str, list[str]] = {}
    for group_id, parent in safe_parents.items():
        if parent != group_id:
            user_children_of.setdefault(parent, []).append(group_id)
    for parent, children in user_children_of.items():
        children.sort(key=lambda gid: keys.get(gid, gid))
    # 成环组（从 root 不可达）提升到 root——结构保留、可展开，不消失。
    reachable: set[str] = set()
    frontier = list(user_children_of.get("", []))
    while frontier:
        node = frontier.pop()
        if node in reachable:
            continue
        reachable.add(node)
        frontier.extend(user_children_of.get(node, []))
    for group_id in sorted(set(safe_parents) - reachable):
        user_children_of.setdefault("", []).append(group_id)
        safe_parents[group_id] = ""
    user_children_of.get("", []).sort(key=lambda gid: keys.get(gid, gid))

    def make_user_group(group_id: str, _visiting: frozenset = frozenset()) -> GroupNode:
        info = plan_input.user_groups[group_id]
        if group_id in _visiting:
            # 成环兜底：环边不再展开（该组挂空，结构不断）。
            return GroupNode(group_id=group_id, name=info.name or group_id,
                             kind="user", children=(),
                             order_key=keys.get(group_id, ""))
        visiting = _visiting | {group_id}
        observed = plan_input.container_orders.get(group_id) or ()
        allowed_layers = member_of.get(group_id, set())
        placed: set[str] = set()
        children: list[GroupNode | LayerRef] = []
        for node_id in observed:
            if node_id in plan_input.user_groups:
                if node_id != group_id and safe_parents.get(node_id) == group_id \
                        and node_id not in placed:
                    children.append(make_user_group(node_id, visiting))
                    placed.add(node_id)
                # 非本组子组 / 自环 → 丢弃（不挂载，不幽灵）。
            elif node_id in allowed_layers and node_id not in placed:
                # 本组路由成员才挂载（系统组内层/已删 id 不进用户组）。
                children.append(LayerRef(
                    layer_id=node_id, order_key=keys.get(node_id, "")))
                placed.add(node_id)
        # 观察序未覆盖的成员：嵌套组（键序）+ 新图层（默认序）补齐。
        for child in user_children_of.get(group_id, []):
            if child not in placed:
                children.append(make_user_group(child, visiting))
                placed.add(child)
        member_ids = orders.get(group_id, [])
        for layer_id in member_ids:
            if layer_id not in placed:
                children.append(LayerRef(
                    layer_id=layer_id, order_key=keys.get(layer_id, "")))
                placed.add(layer_id)
        return GroupNode(
            group_id=group_id,
            name=info.name or group_id,
            kind="user",
            children=tuple(children),
            order_key=keys.get(group_id, ""),
        )

    def make_system_group(group_id: str) -> GroupNode:
        template = system_group_template(group_id)
        children: list[GroupNode | LayerRef] = []
        if group_id == FACTOR_ROOT_GROUP_ID:
            for factor_id in factor_ids:
                children.append(make_system_group(factor_id))
        for layer_id in orders.get(group_id, []):
            children.append(LayerRef(layer_id=layer_id, order_key=keys.get(layer_id, "")))
        if template is not None:
            return GroupNode(
                group_id=group_id, name=template.title, kind="system",
                children=tuple(children),
                order_key=key_for_index(template_index[group_id]),
            )
        # factor.<task>：动态系统组。
        task_id = factor_task_of_group(group_id) or ""
        title = plan_input.factor_titles.get(task_id, task_id or group_id)
        return GroupNode(
            group_id=group_id, name=title, kind="system",
            children=tuple(children),
            order_key=keys.get(group_id, ""),
        )

    # 5) 根组装：系统组（模板序；空组仅当前阶段/base 物化）→ root 级
    #    用户组 + 松散图层（统一键序）。系统组键锚定全模板索引（空组
    #    出现/消失不动其它组的键）。
    roots: list[GroupNode | LayerRef] = []
    materialized_empty: list[str] = []
    for template in SYSTEM_GROUP_TEMPLATES:
        group = make_system_group(template.group_id)
        if group.children:
            roots.append(group)
            continue
        if template.group_id == BASE_REFERENCE_GROUP_ID or (
            plan_input.stage is not None and template.stage_visible(plan_input.stage)):
            roots.append(group)
            materialized_empty.append(template.group_id)

    root_user_groups = sorted(
        user_children_of.get("", []),
        key=lambda gid: keys.get(gid, gid))
    root_mixed = [nid for nid in (plan_input.container_orders.get("") or ())
                  if nid in root_ids or nid in root_user_groups]
    for nid in root_ids + root_user_groups:
        if nid not in root_mixed:
            root_mixed.append(nid)
    keys.update(assign_keys_for_order(root_mixed, keys))
    by_key = sorted(
        root_mixed,
        key=lambda nid: (keys.get(nid, ""), nid))
    for nid in by_key:
        if nid in root_user_groups:
            roots.append(make_user_group(nid))
        else:
            roots.append(LayerRef(layer_id=nid, order_key=keys.get(nid, "")))

    snapshot = LayerTreeSnapshot(children=tuple(roots), source="domain")
    override_source = set(plan_input.order_keys)
    facts = LayerTreePlanFacts(
        default_keys={k: v for k, v in keys.items() if k not in override_source},
        override_keys={k: v for k, v in keys.items() if k in override_source},
        group_kinds={
            **{t.group_id: "system" for t in SYSTEM_GROUP_TEMPLATES},
            **{gid: "factor" for gid in factor_ids},
            **{gid: "user" for gid in plan_input.user_groups},
        },
        materialized_empty_groups=tuple(materialized_empty),
    )
    return snapshot, facts
