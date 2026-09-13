"""相 / 亚相 / 微相三级分类词表（Qt-free 核心）。

词表是编图工作流的配套资产：绘制相带要素完成时、以及属性表/检查器
编辑相字段时，选择项从词表级联生成（相 → 亚相 → 微相，任一级可停）。

两级来源（grill 共识 Q1-d）：
- 内置默认：``resources/facies_taxonomy.json``（源自参考相图 GeoJSON
  的三级体系，8 相 / 24 亚相 / 66 微相）；
- 工程覆盖：``ProjectDocument.facies_taxonomy``（从 GeoJSON 兄弟组
  导入重建），覆盖内置；清除即回落内置。

存储形态为嵌套名称树 ``{相: {亚相: {微相: {}}}}``——名称即身份（同父
内唯一，跨级可重名）；``parent_id``（要素属性，指向父级**要素**）是
三矢量模型（相/亚相/微相三张图层）的未来挂点，与词表的名称树无关。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

#: 级别键（与参考相图 GeoJSON 的 level 属性、facies_hierarchy_service 对齐）。
FACIES_LEVEL_KEYS: tuple[str, ...] = ("facies", "sub_facies", "micro_facies")
LEVEL_LABELS: dict[str, str] = {
    "facies": "相",
    "sub_facies": "亚相",
    "micro_facies": "微相",
}
#: 选到某级即停时写进要素 ``level`` 属性的值（最细已选级别）。
_BUILTIN_PATH = Path(__file__).parent.parent / "resources" / "facies_taxonomy.json"


def _normalize_tree(tree: Any) -> dict[str, dict]:
    """嵌套名称树规范化：剥掉非 dict 叶子、去空串键，返回纯 dict 树。"""
    if not isinstance(tree, Mapping):
        return {}
    normalized: dict[str, dict] = {}
    for key, value in tree.items():
        name = str(key).strip()
        if not name or name.startswith("_"):
            continue
        children = _normalize_tree(value)
        if name in normalized and children:
            # 同名兄弟合并（导入数据里偶发的分裂条目）：子树并集。
            for child, grand in children.items():
                normalized[name].setdefault(child, {}).update(grand)
        else:
            normalized[name] = children
    return normalized


class FaciesTaxonomy:
    """三级相分类词表（不可变快照；工程覆盖 = 新实例）。"""

    def __init__(self, tree: Mapping[str, Any], *, source: str = "builtin") -> None:
        self._tree = _normalize_tree(tree)
        self.source = str(source or "builtin")

    # -- 构造 ---------------------------------------------------------------

    @classmethod
    def builtin(cls) -> "FaciesTaxonomy":
        with open(_BUILTIN_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls(payload.get("tree") or {}, source="builtin")

    @classmethod
    def from_project(cls, project: Any) -> "FaciesTaxonomy":
        """工程词表：覆盖段存在且非空 → 覆盖实例；否则内置。"""
        override = getattr(project, "facies_taxonomy", None)
        if isinstance(override, Mapping) and override.get("tree"):
            return cls(override.get("tree") or {},
                       source=str(override.get("source") or "project"))
        return cls.builtin()

    @classmethod
    def from_geojson_features(
        cls, features: list[Mapping[str, Any]]
    ) -> "FaciesTaxonomy":
        """参考相图 GeoJSON 要素 → 词表（level + parent_id 属性链）。

        与 ``viz/facies_hierarchy_service`` 的层级探测同规则：属性带
        ``level``（facies/sub_facies/micro_facies）与 ``parent_id`` 的
        要素组建成三级树；孤儿（父缺失/父级不符）条目被跳过。
        """
        by_id: dict[str, tuple[str, str, str]] = {}
        for feature in features or []:
            props = feature.get("properties") if isinstance(feature, Mapping) else None
            if not isinstance(props, Mapping):
                continue
            fid = str(props.get("id") or "")
            level = str(props.get("level") or "")
            name = str(props.get("facies") or "").strip()
            if fid and name and level in FACIES_LEVEL_KEYS:
                by_id[fid] = (name, level, str(props.get("parent_id") or ""))

        tree: dict[str, dict] = {}
        for name, level, _parent in by_id.values():
            if level == "facies":
                tree.setdefault(name, {})
        for name, level, parent_id in by_id.values():
            if level != "sub_facies":
                continue
            parent = by_id.get(parent_id)
            if parent is not None and parent[1] == "facies":
                tree.setdefault(parent[0], {}).setdefault(name, {})
        for name, level, parent_id in by_id.values():
            if level != "micro_facies":
                continue
            parent = by_id.get(parent_id)
            if parent is None or parent[1] != "sub_facies":
                continue
            top = by_id.get(parent[2])
            if top is None or top[1] != "facies":
                continue
            tree[top[0]][parent[0]].setdefault(name, {})
        return cls(tree, source="project")

    # -- 查询 ---------------------------------------------------------------

    def names(self, level: str, parents: tuple[str, ...] = ()) -> list[str]:
        """某级的可选名称；``parents`` 为上级已选链（相[→亚相]）。

        父链不完整（上级未选，如属性表里相字段为空时选亚相）或父不在
        树中（词表覆盖后残留旧值）→ 返回该级**全部**名称：不猜、不静默
        清空调用方状态，跨父重名的少数情形由用户判断。
        """
        if level not in FACIES_LEVEL_KEYS:
            return []
        depth = FACIES_LEVEL_KEYS.index(level)
        chain = tuple(
            str(parent).strip() for parent in parents[:depth]
            if str(parent).strip()
        )
        if len(chain) < depth:
            return self._all_names(level)
        node: dict[str, dict] = self._tree
        for parent in chain:
            node = node.get(parent, {})
            if not isinstance(node, Mapping) or not node:
                return self._all_names(level)
        return sorted(node.keys())

    def _all_names(self, level: str) -> list[str]:
        depth = FACIES_LEVEL_KEYS.index(level)
        return sorted(set(self._iter_level(self._tree, depth)))

    def _iter_level(self, node: dict, depth: int):
        if depth == 0:
            yield from node.keys()
            return
        for child in node.values():
            if isinstance(child, Mapping):
                yield from self._iter_level(child, depth - 1)

    def has(self, name: str, level: str, parents: tuple[str, ...] = ()) -> bool:
        return str(name) in self.names(level, parents)

    # -- 选择结果 -----------------------------------------------------------

    @staticmethod
    def selection_level(selection: Mapping[str, Any]) -> str:
        """选到几级（最细已选；一个都没选 = facies 占位的空选）。"""
        if str(selection.get("micro_facies") or "").strip():
            return "micro_facies"
        if str(selection.get("sub_facies") or "").strip():
            return "sub_facies"
        return "facies"

    @staticmethod
    def selection_from_attributes(attributes: Mapping[str, Any]) -> dict[str, str]:
        """要素三字段 → 选择器初值（缺省空串）。"""
        return {
            "facies": str(attributes.get("facies") or ""),
            "sub_facies": str(attributes.get("sub_facies") or ""),
            "micro_facies": str(attributes.get("micro_facies") or ""),
        }

    # -- 持久化 -------------------------------------------------------------

    def to_project_dict(self) -> dict[str, Any]:
        return {"source": self.source, "tree": self._tree}

    def counts(self) -> tuple[int, int, int]:
        sub = sum(len(v) for v in self._tree.values())
        micro = sum(len(m) for v in self._tree.values() for m in v.values())
        return len(self._tree), sub, micro

    def __bool__(self) -> bool:
        return bool(self._tree)
