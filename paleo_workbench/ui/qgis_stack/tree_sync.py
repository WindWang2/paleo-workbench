"""树变更回调 → 文档模型写回的解析层（legacy 平铺 + V5 schema 2）。

C++ 桥 ``set_tree_change_callback`` 的 payload 契约（见
``native/qgis_render_bridge/src/map_stack_service.cpp`` 的 flushTreeChange）：

legacy 键（平铺图层语义，既有消费者保持不变）：

    {"visibility": {doc_id: bool}, "order": [doc_id...],
     "renames": {doc_id: name}}

V5 schema 2 追加：

    {"schema": 2,
     "events": [{"type": "visibility"|"rename",
                 "node_type": "layer"|"group",
                 "node_id": str, "value": bool|str}, ...],
     "tree": [{"type": "group", "id": gid, "name": n, "visible": bool,
               "children": [...]},
              {"type": "layer", "id": doc_id, ...}]}

``tree`` 只在结构变化（拖拽/建组/删组）时携带，一次性覆盖
move/group-create/group-delete——Python 侧对结构化节点数组 diff，
不做字符串拼接解析。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TreeChangeSet:
    """legacy 平铺变更批次（旧语义，保留给既有消费者）。"""

    visibility: dict[str, bool] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    renames: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.visibility or self.order or self.renames)


@dataclass(frozen=True)
class TreeEvent:
    """V5 typed 树事件。"""

    type: str            # "visibility" | "rename"
    node_type: str       # "layer" | "group"
    node_id: str
    value: object        # bool（visibility）| str（rename）

    @property
    def is_group(self) -> bool:
        return self.node_type == "group"


@dataclass(frozen=True)
class TreeChangeBatch:
    """schema 2 完整批次：legacy 键 + typed events + 结构快照。"""

    changes: TreeChangeSet
    events: tuple[TreeEvent, ...] = ()
    #: 结构快照节点数组（结构变化时非空）：
    #: [{"type": "group"|"layer", "id": ..., "children": [...]}]。
    tree: tuple[dict, ...] = ()
    #: V11 树修订号（桥 0.7.0a0+ 携带；0 = 旧桥无修订号——不过期）。
    revision: int = 0

    @property
    def empty(self) -> bool:
        return self.changes.empty and not self.events and not self.tree

    @property
    def has_structure_change(self) -> bool:
        return bool(self.tree)

    def group_visibility(self) -> dict[str, bool]:
        return {
            event.node_id: bool(event.value)
            for event in self.events
            if event.type == "visibility" and event.is_group
        }

    def group_renames(self) -> dict[str, str]:
        return {
            event.node_id: str(event.value)
            for event in self.events
            if event.type == "rename" and event.is_group
        }


def parse_tree_change(payload: str) -> TreeChangeSet:
    """legacy 解析（既有行为保持不变；缺失键/坏 JSON 返回空集）。"""
    try:
        data = json.loads(payload) if payload else {}
    except (TypeError, ValueError):
        return TreeChangeSet()
    if not isinstance(data, dict):
        return TreeChangeSet()
    visibility = {
        str(key): bool(value)
        for key, value in (data.get("visibility") or {}).items()
    }
    order = tuple(str(item) for item in (data.get("order") or ()))
    renames = {
        str(key): str(value) for key, value in (data.get("renames") or {}).items()
    }
    return TreeChangeSet(visibility=visibility, order=order, renames=renames)


def parse_tree_events(payload: str) -> TreeChangeBatch:
    """schema 2 解析：legacy 键 + typed events + 结构快照。"""
    try:
        data = json.loads(payload) if payload else {}
    except (TypeError, ValueError):
        return TreeChangeBatch(changes=TreeChangeSet())
    if not isinstance(data, dict):
        return TreeChangeBatch(changes=TreeChangeSet())
    events: list[TreeEvent] = []
    for raw in data.get("events") or ():
        if not isinstance(raw, dict):
            continue
        event_type = str(raw.get("type") or "")
        node_type = str(raw.get("node_type") or "layer")
        node_id = str(raw.get("node_id") or "")
        if event_type not in ("visibility", "rename") or not node_id:
            continue
        value = raw.get("value")
        value = bool(value) if event_type == "visibility" else str(value)
        events.append(TreeEvent(event_type, node_type, node_id, value))
    tree = tuple(
        node for node in (data.get("tree") or ()) if isinstance(node, dict)
    )
    try:
        revision = int(data.get("tree_revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    return TreeChangeBatch(
        changes=parse_tree_change(payload),
        events=tuple(events),
        tree=tree,
        revision=revision,
    )
