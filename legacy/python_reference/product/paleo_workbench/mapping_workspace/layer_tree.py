"""``LayerTreeSnapshot``：图层树的可序列化领域表示。

**权威边界**（V5 §9）：运行时的显示/排序/组结构权威是 QGIS Layer Tree；
本模块只是：

1. 领域侧期望树的**纯数据描述**（驱动 reconcile 的目标状态）；
2. QGIS 树观察结果的**领域投影**（用户拖拽/勾选/改名事件回写）；
3. 工程持久化的**序列化载体**（``to_dict``/``from_dict``，无 numpy/Qt）。

它绝不能发展成第二棵运行时可变树——领域侧对它的每次修改都是
"重建新快照 → 增量 reconcile QGIS"，而不是就地长驻编辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LayerRef:
    """树中一个图层节点的领域引用（科学状态在图层本体，不在此重复）。"""

    layer_id: str
    #: 可选 stage membership 附加说明（调试/诊断；显隐在 StageViewState）。
    note: str = ""
    #: V11 稳定排序键（layer_order；空 = 未键化 legacy 节点，迁移时定宽派生）。
    order_key: str = ""

    def to_dict(self) -> dict:
        out = {"type": "layer", "id": self.layer_id}
        if self.order_key:
            out["order_key"] = self.order_key
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "LayerRef":
        return cls(
            layer_id=str(data.get("id") or ""),
            order_key=str(data.get("order_key") or ""),
        )


@dataclass(frozen=True)
class GroupNode:
    """树中一个分组节点（系统组或用户组）。

    ``group_id`` 是稳定标识（如 ``phase1.initial_facies`` 或
    ``factor.<task_id>``），与显示名 ``name`` 解耦——用户改名不改变 id，
    系统 UI 也不依赖显示名做语义判断。
    """

    group_id: str
    name: str
    #: system = 阶段流程语义组（role-managed，不可删除）；user = 用户组织组。
    kind: str = "system"  # "system" | "user"
    children: tuple["GroupNode | LayerRef", ...] = ()
    expanded: bool = True
    locked: bool = False
    #: 组可见性（QGIS 组勾选态的领域侧最近已知值）。
    visible: bool = True
    #: V11 稳定排序键（layer_order；空 = 未键化 legacy 节点。系统组键由
    #: 模板带派生（不可用户覆盖）；用户组键持久化拖拽序）。
    order_key: str = ""

    def iter_layers(self):
        for child in self.children:
            if isinstance(child, LayerRef):
                yield child.layer_id
            else:
                yield from child.iter_layers()

    def iter_groups(self):
        for child in self.children:
            if isinstance(child, GroupNode):
                yield child
                yield from child.iter_groups()

    def find_group(self, group_id: str) -> "GroupNode | None":
        if self.group_id == group_id:
            return self
        for child in self.children:
            if isinstance(child, GroupNode):
                found = child.find_group(group_id)
                if found is not None:
                    return found
        return None

    def find_layer_parent(self, layer_id: str) -> "GroupNode | None":
        for child in self.children:
            if isinstance(child, LayerRef) and child.layer_id == layer_id:
                return self
        for child in self.children:
            if isinstance(child, GroupNode):
                found = child.find_layer_parent(layer_id)
                if found is not None:
                    return found
        return None

    def to_dict(self) -> dict:
        out = {
            "type": "group",
            "id": self.group_id,
            "name": self.name,
            "kind": self.kind,
            "expanded": self.expanded,
            "locked": self.locked,
            "visible": self.visible,
            "children": [child.to_dict() for child in self.children],
        }
        if self.order_key:
            out["order_key"] = self.order_key
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "GroupNode":
        children: list[GroupNode | LayerRef] = []
        for child in data.get("children") or ():
            if not isinstance(child, dict):
                continue
            if child.get("type") == "group":
                children.append(GroupNode.from_dict(child))
            elif child.get("type") == "layer":
                children.append(LayerRef.from_dict(child))
        return cls(
            group_id=str(data.get("id") or ""),
            name=str(data.get("name") or data.get("id") or ""),
            kind=str(data.get("kind") or "system"),
            children=tuple(children),
            expanded=bool(data.get("expanded", True)),
            locked=bool(data.get("locked", False)),
            visible=bool(data.get("visible", True)),
            order_key=str(data.get("order_key") or ""),
        )


@dataclass(frozen=True)
class LayerTreeSnapshot:
    """整棵期望/观察树的快照（根级 children 即 QGIS 树根的孩子）。"""

    children: tuple[GroupNode | LayerRef, ...] = ()
    #: 观察快照可带来源标记（"domain" | "qgis"）；序列化时保留供诊断。
    source: str = "domain"

    # -- 查询 -----------------------------------------------------------------

    def iter_layers(self):
        for child in self.children:
            if isinstance(child, LayerRef):
                yield child.layer_id
            else:
                yield from child.iter_layers()

    def iter_groups(self):
        for child in self.children:
            if isinstance(child, GroupNode):
                yield child
                yield from child.iter_groups()

    def find_group(self, group_id: str) -> GroupNode | None:
        for child in self.children:
            if isinstance(child, GroupNode):
                found = child.find_group(group_id)
                if found is not None:
                    return found
        return None

    def find_layer_parent(self, layer_id: str) -> GroupNode | None:
        for child in self.children:
            if isinstance(child, LayerRef) and child.layer_id == layer_id:
                return None  # 顶层图层：parent = root
        for child in self.children:
            if isinstance(child, GroupNode):
                found = child.find_layer_parent(layer_id)
                if found is not None:
                    return found
        return None

    def layer_ids_top_first(self) -> tuple[str, ...]:
        """树遍历序（QGIS 语义：上面的图层先渲染在上面）。"""
        return tuple(self.iter_layers())

    def group_ids(self) -> tuple[str, ...]:
        return tuple(group.group_id for group in self.iter_groups())

    # -- 渲染兼容（V5 §48） ---------------------------------------------------

    def flatten_for_render(self, layer_snapshots) -> tuple:
        """把领域树展开为 flat ``MapLayerSnapshot`` 元组供现有 renderer 消费。

        显示顺序来自树遍历；不在树中的图层（新出现、尚未分组）保持传入
        顺序追加在尾部，绝不丢失。
        """
        by_id = {layer.id: layer for layer in layer_snapshots}
        ordered: list = []
        seen: set[str] = set()
        for layer_id in self.iter_layers():
            layer = by_id.get(layer_id)
            if layer is not None:
                ordered.append(layer)
                seen.add(layer_id)
        for layer in layer_snapshots:
            if layer.id not in seen:
                ordered.append(layer)
        return tuple(ordered)

    # -- 序列化 ---------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LayerTreeSnapshot":
        children: list[GroupNode | LayerRef] = []
        for child in data.get("children") or ():
            if not isinstance(child, dict):
                continue
            if child.get("type") == "group":
                children.append(GroupNode.from_dict(child))
            elif child.get("type") == "layer":
                children.append(LayerRef.from_dict(child))
        return cls(children=tuple(children), source=str(data.get("source") or "domain"))


def tree_from_nodes(nodes: list[dict]) -> LayerTreeSnapshot:
    """便捷构造：从桥回调的节点数组（每项 {type,id,...}）建观察快照。"""
    children: list[GroupNode | LayerRef] = []
    for node in nodes or ():
        if not isinstance(node, dict):
            continue
        if node.get("type") == "group":
            children.append(_group_from_bridge_node(node))
        elif node.get("type") == "layer":
            children.append(LayerRef(layer_id=str(node.get("id") or "")))
    return LayerTreeSnapshot(children=tuple(children), source="qgis")


def _group_from_bridge_node(node: dict) -> GroupNode:
    children = tuple(
        _group_from_bridge_node(child) if isinstance(child, dict) and child.get("type") == "group"
        else LayerRef(
            layer_id=str(child.get("id") or ""),
            order_key=str(child.get("order_key") or ""),
        )
        for child in node.get("children") or ()
        if isinstance(child, dict)
    )
    return GroupNode(
        group_id=str(node.get("id") or ""),
        name=str(node.get("name") or ""),
        kind=str(node.get("kind") or "system") if str(node.get("id") or "").startswith(
            ("phase", "factor", "root")) else "user",
        children=children,
        expanded=bool(node.get("expanded", True)),
        locked=bool(node.get("locked", False)),
        visible=bool(node.get("visible", True)),
        order_key=str(node.get("order_key") or ""),
    )
