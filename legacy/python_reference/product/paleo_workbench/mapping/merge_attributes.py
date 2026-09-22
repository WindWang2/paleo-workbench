"""合并属性计划（拓扑编辑迁移 M3 §4 无缝合并）。

对话框预填「面积最大要素」属性，并标出字段冲突（相分类字段优先）。
纯逻辑：无 Qt、无桥。
"""
from __future__ import annotations

from typing import Iterable, Mapping

__all__ = ["plan_merge_attributes"]


def _ring_area(ring) -> float:
    if not isinstance(ring, (list, tuple)) or len(ring) < 4:
        return 0.0
    area = 0.0
    for index in range(len(ring) - 1):
        node = ring[index]
        nxt = ring[index + 1]
        if not isinstance(node, (list, tuple)) or not isinstance(nxt, (list, tuple)):
            continue
        if len(node) < 2 or len(nxt) < 2:
            continue
        area += float(node[0]) * float(nxt[1]) - float(nxt[0]) * float(node[1])
    return area / 2.0


def polygon_area(geometry: Mapping[str, object] | None) -> float:
    """多边形面积（绝对 shoelace；MultiPolygon 累加外环）。"""
    if not isinstance(geometry, Mapping):
        return 0.0
    kind = str(geometry.get("type") or "")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon" and isinstance(coords, (list, tuple)) and coords:
        return abs(_ring_area(coords[0]))
    if kind == "MultiPolygon" and isinstance(coords, (list, tuple)):
        total = 0.0
        for polygon in coords:
            if isinstance(polygon, (list, tuple)) and polygon:
                total += abs(_ring_area(polygon[0]))
        return total
    return 0.0


def plan_merge_attributes(
    records: Iterable[Mapping[str, object]],
    *,
    facies_fields: Iterable[str] = ("facies",),
) -> dict[str, object]:
    """预填最大面积要素属性，并列出字段冲突。

    ``records`` 项形如 ``{id, geometry, properties}``。返回
    ``{target_id, attributes, conflicts, facies_fields}``；
    ``conflicts`` 为字段 → 互异值列表（出现顺序）。
    """
    facies = tuple(str(name) for name in facies_fields)
    items: list[tuple[str, float, dict]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        feature_id = str(record.get("id") or "")
        if not feature_id:
            continue
        geometry = record.get("geometry") if isinstance(record.get("geometry"), Mapping) else {}
        properties = record.get("properties") if isinstance(record.get("properties"), Mapping) else {}
        items.append((feature_id, polygon_area(geometry), dict(properties)))
    if not items:
        return {
            "target_id": "",
            "attributes": {},
            "conflicts": {},
            "facies_fields": facies,
        }
    items.sort(key=lambda item: (-item[1], item[0]))
    target_id, _area, target_props = items[0]
    keys: list[str] = []
    for _fid, _area, props in items:
        for key in props:
            if key not in keys:
                keys.append(str(key))
    conflicts: dict[str, list] = {}
    for key in keys:
        values: list = []
        for _fid, _area, props in items:
            value = props.get(key)
            if value not in values:
                values.append(value)
        if len(values) > 1:
            conflicts[key] = values
    return {
        "target_id": target_id,
        "attributes": dict(target_props),
        "conflicts": conflicts,
        "facies_fields": facies,
    }
