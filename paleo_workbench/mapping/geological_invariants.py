"""地质拓扑规则形式化守卫（geotopo Ticket 4）。

提交门禁的地质语义校验器：相律邻接（Walther 相律秩差编码，D7）、
相带内部未封闭悬挂断层、等厚线跨越剥蚀边界未断开。纯 Python +
shapely，零桥依赖——快速 CI 全矩阵可跑（契约 §4.2）。

资源：``resources/facies_adjacency.json``（内置默认）；工程级覆盖走
``ProjectDocument.facies_adjacency``（整树替换，与 facies_taxonomy 同
覆盖哲学）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "FaciesAdjacency",
    "InvariantViolation",
    "run_geology_gate",
    "validate_dangling_faults",
    "validate_facies_adjacency",
    "validate_isopath_continuity",
]

_BUILTIN_PATH = Path(__file__).parent.parent / "resources" / "facies_adjacency.json"

ROLE_FACIES_POLYGON = "facies_polygon"
ROLE_FAULT_LINE = "fault_line"
ROLE_ISOPATH_LINE = "isopath_line"
ROLE_EROSION_BOUNDARY = "erosion_boundary"


@dataclass(frozen=True)
class InvariantViolation:
    code: str
    severity: str          # "error" blocks the commit; "warning" reports only
    message: str
    layer_id: str
    feature_ids: tuple[str, ...] = ()
    hint: str = ""


class FaciesAdjacency:
    """Walther 相律邻接矩阵：``may_touch(a, b) -> (allowed, missing_hint)``。

    秩差编码（``ranks`` + ``max_rank_distance``）+ 盆地特殊对白名单
    （``allowed_pairs``）。未知名一律拒绝（宁可误拦，不留静默漏放）。
    """

    def __init__(self, *, ranks: Mapping[str, int], allowed_pairs: Iterable[Sequence[str]] = (),
                 max_rank_distance: int = 1, rank_labels: Mapping[str, str] | None = None) -> None:
        self._ranks: dict[str, int] = {str(k): int(v) for k, v in ranks.items()}
        self._allowed = {frozenset((str(pair[0]), str(pair[1]))) for pair in allowed_pairs}
        self._max_distance = int(max_rank_distance)
        self._rank_labels = dict(rank_labels or {})

    @classmethod
    def builtin(cls) -> "FaciesAdjacency":
        payload = json.loads(_BUILTIN_PATH.read_text(encoding="utf-8"))
        meta = payload.get("_meta", {})
        return cls(
            ranks=payload["ranks"],
            allowed_pairs=payload.get("allowed_pairs", ()),
            max_rank_distance=meta.get("max_rank_distance", 1),
            rank_labels=payload.get("rank_labels", {}),
        )

    @classmethod
    def from_project(cls, project: Any) -> "FaciesAdjacency | None":
        override = getattr(project, "facies_adjacency", None)
        if not isinstance(override, Mapping):
            return None
        return cls(
            ranks=override.get("ranks", {}),
            allowed_pairs=override.get("allowed_pairs", ()),
            max_rank_distance=override.get("max_rank_distance", 1),
            rank_labels=override.get("rank_labels", {}),
        )

    def _rank(self, name: str) -> int | None:
        return self._ranks.get(name)

    def _rank_names(self, rank: int) -> str:
        names = [name for name, value in self._ranks.items() if value == rank]
        if names:
            return "/".join(sorted(names))
        return self._rank_labels.get(str(rank), f"rank {rank}")

    def may_touch(self, a: str, b: str) -> tuple[bool, str]:
        ra, rb = self._rank(a), self._rank(b)
        if ra is None or rb is None:
            unknown = a if ra is None else b
            return False, f"未收录相「{unknown}」：不在相律邻接矩阵中，需在工程级 facies_adjacency 声明"
        if frozenset((a, b)) in self._allowed:
            return True, ""
        if abs(ra - rb) <= self._max_distance:
            return True, ""
        lo, hi = min(ra, rb), max(ra, rb)
        missing = [self._rank_names(rank) for rank in range(lo + 1, hi)]
        return False, "、".join(missing)


# ---------------------------------------------------------------------------
# 几何助手（shapely 延迟导入：模块导入本身保持轻量）


def _shapely_geometry(record: Mapping[str, Any]):
    from shapely.geometry import shape

    return shape(record["geometry"])


def _iter_records(records_by_layer: Mapping[str, Iterable[Mapping[str, Any]]]):
    for layer_id, records in records_by_layer.items():
        for record in records:
            yield layer_id, record


def _roles_or_default(roles: Mapping[str, str] | None) -> dict[str, str]:
    return dict(roles or {})


# ---------------------------------------------------------------------------
# 校验器一：相律邻接


def validate_facies_adjacency(
    records_by_layer: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    adjacency: FaciesAdjacency | None = None,
    min_shared_len: float | None = None,
    tolerance: float = 1e-6,
) -> list[InvariantViolation]:
    adjacency = adjacency or FaciesAdjacency.builtin()
    threshold = min_shared_len if min_shared_len is not None else 10.0 * tolerance
    polygons: list[tuple[str, str, Any, str]] = []  # (layer_id, feature_id, geom, facies)
    for layer_id, record in _iter_records(records_by_layer):
        geometry = record.get("geometry") or {}
        if geometry.get("type") != "Polygon":
            continue
        attributes = record.get("attributes") or {}
        facies = attributes.get("facies")
        if not facies:
            continue
        polygons.append((layer_id, str(record.get("feature_id", "?")),
                         _shapely_geometry(record), str(facies)))
    violations: list[InvariantViolation] = []
    for i in range(len(polygons)):
        for j in range(i + 1, len(polygons)):
            la, fa, ga, name_a = polygons[i]
            lb, fb, gb, name_b = polygons[j]
            if ga.disjoint(gb):
                continue  # bbox 级预过滤（审查 Standards#8）：免 GEOS 相交
            if ga.boundary.intersection(gb.boundary).length < threshold:
                continue  # 触点/针触共享边不足阈值：不算直接相邻
            allowed, reason = adjacency.may_touch(name_a, name_b)
            if allowed:
                continue
            violations.append(InvariantViolation(
                code="facies_adjacency_gap",
                severity="error",
                message=(f"「{name_a}」与「{name_b}」直接相邻违反 Walther 相律："
                         f"缺失过渡相带 {reason}"),
                layer_id=la if la == lb else f"{la}|{lb}",
                feature_ids=(fa, fb),
                hint="在两相带之间补绘过渡相带边界，或在工程 facies_adjacency 中声明特殊邻接",
            ))
    return violations


# ---------------------------------------------------------------------------
# 校验器二：悬挂断层


def validate_dangling_faults(
    records_by_layer: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    roles: Mapping[str, str] | None = None,
    envelope: Sequence[float] | None = None,
    tolerance: float = 1e-6,
) -> list[InvariantViolation]:
    """相带内部未封闭悬挂断层校验。

    封闭性按断层连通分量传递判定：任一断层端点抵达相带边界、交于
    其他断层（并查集连通）、或越出图框，即该分量视为封闭；分量内
    仍悬空于相带内部的断层报一条 ``dangling_fault_unsealed``（每要素
    一条，闸口消息粒度）。
    """
    from shapely.geometry import Point, Polygon, box

    role_map = _roles_or_default(roles)
    faults: list[tuple[str, str, Any]] = []
    polygon_boundaries: list[Any] = []
    frame = box(*envelope) if envelope is not None else None

    for layer_id, record in _iter_records(records_by_layer):
        role = role_map.get(layer_id)
        geometry = record.get("geometry") or {}
        if role == ROLE_FAULT_LINE and geometry.get("type") == "LineString":
            faults.append((layer_id, str(record.get("feature_id", "?")), _shapely_geometry(record)))
        elif geometry.get("type") == "Polygon":
            polygon_boundaries.append(_shapely_geometry(record).boundary)

    if not faults:
        return []

    # 每断层端点的即时封闭性 + 相带内部悬空性。
    sealed_flags: list[bool] = []
    dangling_inside: list[bool] = []
    endpoints_per_fault: list[list[Point]] = []
    for _layer_id, _fid, fault in faults:
        sealed = False
        dangling = False
        tips = [Point(fault.coords[0]), Point(fault.coords[-1])]
        for point in tips:
            if any(point.distance(boundary) <= tolerance for boundary in polygon_boundaries):
                sealed = True
            elif frame is not None and not frame.contains(point):
                sealed = True  # 越出图框（尖灭出图）
            elif any(Polygon(boundary).contains(point) for boundary in polygon_boundaries):
                dangling = True
        sealed_flags.append(sealed)
        dangling_inside.append(dangling)
        endpoints_per_fault.append(tips)

    # 并查集：端点落在其他断层线上（含交汇/穿越）即连通。
    parent = list(range(len(faults)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(faults)):
        for j in range(len(faults)):
            if i == j:
                continue
            connected = any(
                tip.distance(faults[j][2]) <= tolerance for tip in endpoints_per_fault[i])
            if connected:
                parent[find(i)] = find(j)

    component_sealed: dict[int, bool] = {}
    for i in range(len(faults)):
        root = find(i)
        component_sealed[root] = component_sealed.get(root, False) or sealed_flags[i]

    violations: list[InvariantViolation] = []
    for i, (layer_id, feature_id, fault) in enumerate(faults):
        if not dangling_inside[i] or component_sealed[find(i)]:
            continue
        tip = fault.coords[-1]
        violations.append(InvariantViolation(
            code="dangling_fault_unsealed",
            severity="error",
            message=(f"断层 {feature_id} 端点 ({tip[0]:.3f}, {tip[1]:.3f}) "
                     "悬空于相带内部：所在断层网络未抵达相带边界/图框、未与其他断层交汇封闭"),
            layer_id=layer_id,
            feature_ids=(feature_id,),
            hint="延长断层至相带边界/图框，或与相邻断层交汇封闭",
        ))
    return violations


# ---------------------------------------------------------------------------
# 校验器三：等厚线-剥蚀边界


def validate_isopath_continuity(
    records_by_layer: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    roles: Mapping[str, str] | None = None,
    tolerance: float = 1e-6,
) -> list[InvariantViolation]:
    from shapely.geometry import Point

    role_map = _roles_or_default(roles)
    isopaths: list[tuple[str, str, Any]] = []
    erosion_boundaries: list[Any] = []
    for layer_id, record in _iter_records(records_by_layer):
        role = role_map.get(layer_id)
        geometry = record.get("geometry") or {}
        if role == ROLE_ISOPATH_LINE and geometry.get("type") == "LineString":
            isopaths.append((layer_id, str(record.get("feature_id", "?")), _shapely_geometry(record)))
        elif role == ROLE_EROSION_BOUNDARY:
            geometry = record.get("geometry") or {}
            if geometry.get("type") == "LineString":
                # 线状剥蚀边界：取几何本身（.boundary 会退化为双端点）。
                erosion_boundaries.append(_shapely_geometry(record))
            else:
                erosion_boundaries.append(_shapely_geometry(record).boundary)

    violations: list[InvariantViolation] = []
    for layer_id, feature_id, line in isopaths:
        for boundary in erosion_boundaries:
            crossing = line.intersection(boundary)
            if crossing.is_empty:
                continue
            points = list(crossing.geoms) if crossing.geom_type.startswith("Multi") else [crossing]
            unbroken = [
                point for point in points
                if point.geom_type == "Point"
                and not any(Point(vertex).distance(point) <= tolerance
                            for vertex in line.coords)
            ]
            if not unbroken:
                continue  # 共线贴边或全部已断开
            first = unbroken[0]
            violations.append(InvariantViolation(
                code="isopath_crosses_unconformity",
                severity="error",
                message=(f"等厚线 {feature_id} 在 ({first.x:.3f}, {first.y:.3f}) 等处 "
                         f"跨越剥蚀边界 {len(unbroken)} 处但未断开（无顶点节点）"),
                layer_id=layer_id,
                feature_ids=(feature_id,),
                hint="在跨越点打断等厚线，使剥蚀区内外厚度场各自独立",
            ))
    return violations


# ---------------------------------------------------------------------------
# 汇总门


def run_geology_gate(
    records_by_layer: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    roles: Mapping[str, str] | None = None,
    project: Any = None,
    adjacency: FaciesAdjacency | None = None,
    envelope: Sequence[float] | None = None,
    min_shared_len: float | None = None,
    tolerance: float = 1e-6,
) -> list[InvariantViolation]:
    """提交门禁入口：按角色分发三类校验，返回全部违规（error 拦截 / warning 上报）。"""
    if adjacency is None:
        adjacency = FaciesAdjacency.from_project(project) or FaciesAdjacency.builtin()
    violations: list[InvariantViolation] = []
    violations.extend(validate_facies_adjacency(
        records_by_layer, adjacency=adjacency,
        min_shared_len=min_shared_len, tolerance=tolerance))
    violations.extend(validate_dangling_faults(
        records_by_layer, roles=roles, envelope=envelope, tolerance=tolerance))
    violations.extend(validate_isopath_continuity(
        records_by_layer, roles=roles, tolerance=tolerance))
    return violations
