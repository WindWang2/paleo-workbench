"""V11 TreeDiff：期望树 vs 当前树的最小操作集（keyed LCS）。

设计（docs/development/qgis-cartography-runtime-v11/05-tree-diff.md）：
替换"发现顺序不同 → 全 children 重排"的粗放路径。每个容器内对子 id
序列做最长公共子序列（LCS）匹配——已在 LCS 中的节点不动；不在 LCS 中
的节点按目标位置逐个 move。组集合差分 → create/remove；重命名与
显隐/展开/锁为独立键控操作。

输出操作为冻结 dataclass（可序列化、可在测试中断言数量），由
``LayerGroupController._apply_tree`` 消费并映射为桥调用（native
transaction 窗口内批量执行）。

复杂度：O(Σ|children|·log) （LCS via patience），无 list.index 热路径。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from paleo_workbench.mapping_workspace.layer_tree import (
    GroupNode,
    LayerRef,
    LayerTreeSnapshot,
)

__all__ = [
    "GroupCreate",
    "GroupRemove",
    "GroupRename",
    "GroupMove",
    "LayerMove",
    "GroupStateSet",
    "TreeDiff",
    "diff_trees",
    "lcs_indices",
]


@dataclass(frozen=True)
class GroupCreate:
    group_id: str
    name: str
    parent: str  # "" = root


@dataclass(frozen=True)
class GroupRemove:
    group_id: str


@dataclass(frozen=True)
class GroupRename:
    group_id: str
    new_name: str


@dataclass(frozen=True)
class GroupMove:
    group_id: str
    new_parent: str
    new_index: int


@dataclass(frozen=True)
class LayerMove:
    layer_id: str
    new_parent: str  # "" = root
    new_index: int


@dataclass(frozen=True)
class GroupStateSet:
    """组状态键控设置（kind ∈ visible/expanded/locked）。"""

    group_id: str
    kind: str
    value: bool


@dataclass(frozen=True)
class TreeDiff:
    group_creates: tuple[GroupCreate, ...] = ()
    group_removes: tuple[GroupRemove, ...] = ()
    group_renames: tuple[GroupRename, ...] = ()
    group_moves: tuple[GroupMove, ...] = ()
    layer_moves: tuple[LayerMove, ...] = ()
    group_states: tuple[GroupStateSet, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.group_creates or self.group_removes or self.group_renames
                    or self.group_moves or self.layer_moves or self.group_states)

    def op_count(self) -> int:
        return (len(self.group_creates) + len(self.group_removes)
                + len(self.group_renames) + len(self.group_moves)
                + len(self.layer_moves) + len(self.group_states))


def lcs_indices(a: Sequence[str], b: Sequence[str]) -> list[int]:
    """LCS：返回 ``a`` 中属于公共子序列的下标（升序）。

    O(n log n)（patience LIS 归约）；等长同序序列返回全部下标。
    """
    if list(a) == list(b):
        return list(range(len(a)))
    b_positions: dict[str, list[int]] = {}
    for idx, value in enumerate(b):
        b_positions.setdefault(value, []).append(idx)
    seq: list[int] = []
    a_index_of: list[int] = []
    for a_idx, value in enumerate(a):
        for pos in reversed(b_positions.get(value, ())):
            seq.append(pos)
            a_index_of.append(a_idx)
    import bisect

    tails: list[int] = []
    tails_pos: list[int] = []
    prev: list[int] = [-1] * len(seq)
    for idx, value in enumerate(seq):
        pos = bisect.bisect_left(tails, value)
        if pos == len(tails):
            tails.append(value)
            tails_pos.append(idx)
        else:
            tails[pos] = value
            tails_pos[pos] = idx
        prev[idx] = tails_pos[pos - 1] if pos > 0 else -1
    chosen: set[int] = set()
    node = tails_pos[-1] if tails_pos else -1
    while node >= 0:
        chosen.add(node)
        node = prev[node]
    return sorted({a_index_of[k] for k in chosen})


def _index_tree(snapshot: LayerTreeSnapshot):
    """(children_of: parent_id -> [node dict], parents: id -> parent_id,
    groups: id -> GroupNode)"""
    children_of: dict[str, list] = {}
    parents: dict[str, str] = {}
    groups: dict[str, GroupNode] = {}

    def walk(children, parent_id):
        children_of.setdefault(parent_id, [])
        for child in children:
            if isinstance(child, GroupNode):
                node_id = child.group_id
                groups[node_id] = child
            else:
                node_id = child.layer_id
            parents[node_id] = parent_id
            children_of[parent_id].append(child)
            if isinstance(child, GroupNode):
                walk(child.children, node_id)

    walk(snapshot.children, "")
    return children_of, parents, groups


def _child_ids(children) -> list[str]:
    return [c.group_id if isinstance(c, GroupNode) else c.layer_id for c in children]


def diff_trees(
    current: LayerTreeSnapshot,
    desired: LayerTreeSnapshot,
) -> TreeDiff:
    """最小操作集：current（观察/已应用）→ desired（期望）。

    约定：
    * 组删除不级联删除图层（C++ removeGroupsExcept 上提子节点——操作
      语义与桥一致）；组创建按拓扑序输出（父先于子）。
    * move 只对不在容器 LCS 中的节点发出（含跨容器移动）。
    * visible/expanded/locked 只对两侧都存在的组做键控比较。
    """
    cur_children, cur_parents, cur_groups = _index_tree(current)
    des_children, des_parents, des_groups = _index_tree(desired)

    creates: list[GroupCreate] = []
    removes: list[GroupRemove] = []
    renames: list[GroupRename] = []
    group_moves: list[GroupMove] = []
    layer_moves: list[LayerMove] = []
    states: list[GroupStateSet] = []

    # -- 组集合 + 重命名 + 状态 -------------------------------------------------
    for group_id, group in des_groups.items():
        if group_id not in cur_groups:
            creates.append(GroupCreate(
                group_id=group_id, name=group.name,
                parent=des_parents.get(group_id, "")))
        else:
            cur = cur_groups[group_id]
            if cur.name != group.name:
                renames.append(GroupRename(group_id, group.name))
            if cur.visible != group.visible:
                states.append(GroupStateSet(group_id, "visible", group.visible))
            if cur.expanded != group.expanded:
                states.append(GroupStateSet(group_id, "expanded", group.expanded))
            if cur.locked != group.locked:
                states.append(GroupStateSet(group_id, "locked", group.locked))
    for group_id in cur_groups:
        if group_id not in des_groups:
            removes.append(GroupRemove(group_id))

    # 创建按拓扑序（父先于子）：desired 树深度序即拓扑序的近似——用
    # 递归深度排序保证父组 create 排在子组之前。
    def _depth_of(group_id: str) -> int:
        depth = 0
        node = group_id
        while node:
            node = des_parents.get(node, "")
            depth += 1
        return depth

    creates.sort(key=lambda c: _depth_of(c.group_id))

    # -- 放置与顺序：容器并集上 LCS --------------------------------------------
    all_containers = set(cur_children) | set(des_children)
    for container in sorted(all_containers):
        cur_ids = _child_ids(cur_children.get(container, ()))
        des_ids = _child_ids(des_children.get(container, ()))
        # LCS 在「current 序列 vs desired 序列」上求：desired 中属于 LCS
        # 的位置已保序就位，无需 move。
        des_in_lcs = _lcs_membership(cur_ids, des_ids)
        for index, node_id in enumerate(des_ids):
            if des_in_lcs[index]:
                continue
            parent = des_parents.get(node_id, container)
            if node_id in des_groups:
                group_moves.append(GroupMove(node_id, parent, index))
            else:
                layer_moves.append(LayerMove(node_id, parent, index))

    return TreeDiff(
        group_creates=tuple(creates),
        group_removes=tuple(removes),
        group_renames=tuple(renames),
        group_moves=tuple(group_moves),
        layer_moves=tuple(layer_moves),
        group_states=tuple(states),
    )


def _lcs_membership(current_ids: Sequence[str], desired_ids: Sequence[str]) -> list[bool]:
    """desired 各位置是否属于 current↔desired 的公共子序列（保序不动集）。"""
    current_positions: dict[str, list[int]] = {}
    for idx, node_id in enumerate(current_ids):
        current_positions.setdefault(node_id, []).append(idx)
    # 归约为「desired 中存在且 current 中的位置序列」的 LIS：
    seq: list[int] = []
    for node_id in desired_ids:
        for pos in reversed(current_positions.get(node_id, ())):
            seq.append(pos)
    # patience LIS over seq，映射回 desired 下标
    import bisect

    tails: list[int] = []
    tails_pos: list[int] = []
    prev: list[int] = [-1] * len(seq)
    for idx, value in enumerate(seq):
        pos = bisect.bisect_left(tails, value)
        if pos == len(tails):
            tails.append(value)
            tails_pos.append(idx)
        else:
            tails[pos] = value
            tails_pos[pos] = idx
        prev[idx] = tails_pos[pos - 1] if pos > 0 else -1
    chosen: set[int] = set()
    node = tails_pos[-1] if tails_pos else -1
    while node >= 0:
        chosen.add(node)
        node = prev[node]
    membership = [False] * len(desired_ids)
    # seq 的构造顺序 = desired 顺序×current 位置倒序；chosen 的 seq 下标
    # 对应唯一的 desired 下标 = seq 下标 // 1？——seq 元素按 desired 顺序
    # 排列，其下标即 (desired_index, current_pos) 对的线性序；直接把
    # chosen 的 seq 下标映射回 desired 下标：seq[k] 属于 desired[k']，
    # k' = k // count(node) 不成立（每 desired 元素可有多个 current 位）。
    # 修正：LIS 选中的每个 seq 元素携带其 desired 下标。
    des_index_of: list[int] = []
    for di, node_id in enumerate(desired_ids):
        for _ in current_positions.get(node_id, ()):
            des_index_of.append(di)
    for k in chosen:
        membership[des_index_of[k]] = True
    return membership
