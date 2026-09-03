"""树变更回调 → 文档模型写回的纯归并逻辑（Task 4 由面板消费）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TreeChangeSet:
    visibility: dict[str, bool] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    renames: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.visibility or self.order or self.renames)


def parse_tree_change(payload: str) -> TreeChangeSet:
    raw = json.loads(payload) if payload else {}
    if not isinstance(raw, dict):
        return TreeChangeSet()
    return TreeChangeSet(
        visibility={str(k): bool(v) for k, v in (raw.get("visibility") or {}).items()},
        order=tuple(str(v) for v in (raw.get("order") or [])),
        renames={str(k): str(v) for k, v in (raw.get("renames") or {}).items()},
    )
