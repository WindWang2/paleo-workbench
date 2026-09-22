"""QC 快速修复动作（M4）——碎多边形吸附合并 / 未封闭边界切线闭合。

契约（00-decisions D8）：
- 一次修复 = **一个可撤销命令**（``begin_edit_command`` … ``end_edit_command``，
  失败 ``destroy_edit_command`` 后原异常上抛）；
- ``availability(issue, ctx) -> (ok, reason)`` 诚实判定（几何前提不满足 →
  False + 人类可读原因），UI 以禁用按钮 + tooltip 呈现；
- 碎多边形并入 **共享边界最长** 的相邻相（并列取面积大者），属性取优势相；
- 未封闭边界沿末端切线延伸（步长=容差×0.5，最大延伸=容差×8），端点进入
  容差后闭合；不可达判不可修。

纯域模块（Qt-free）：动作表 :data:`QUICK_FIX_ACTIONS` 供 QC Hub 消费。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from paleo_workbench.mapping.geometry_operations import intersection, union

#: 最大延伸 = 容差 × 系数（超出判不可修）。
MAX_EXTENSION_FACTOR = 8.0


@dataclass
class QuickFixContext:
    """修复上下文（图层 + 容差；session 可选）。

    ``session=None`` = 只读可用性判定（读 ``layer.features()``，不开编辑
    会话——选中 issue 仅显示按钮不得有写侧副作用，review P1-3）；``apply``
    路径由宿主先 ``ensure_layer_session`` 再携带真会话调用。
    """

    layer: Any
    session: Any = None
    tolerance: float = 1.0

    def _features(self):
        if self.session is not None:
            return self.session.features()
        return self.layer.features() if self.layer is not None else ()


@dataclass(frozen=True)
class QuickFixAction:
    """一个可注册的快速修复动作。"""

    action_id: str
    title: str
    description: str
    rules: tuple[str, ...]
    availability: Callable[[dict, QuickFixContext], tuple[bool, str]]
    apply: Callable[[dict, QuickFixContext], bool]


# ---------------------------------------------------------------------------
# 几何小工具（shapely 直接参与：mapping 域既有先例 geometry_operations）
# ---------------------------------------------------------------------------

def _shapely():
    import shapely.geometry as sgeom

    return sgeom


def _shape(geometry: dict):
    return _shapely().shape(dict(geometry))


def _geometry_bbox(geometry: Any) -> tuple[float, float, float, float] | None:
    """GeoJSON 几何 → 包围盒（纯递归；避免 GEOS 构造成本，review P1-2）。"""
    if not isinstance(geometry, dict):
        return None
    xs: list[float] = []
    ys: list[float] = []

    def _walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if (len(node) >= 2 and isinstance(node[0], (int, float))
                    and isinstance(node[1], (int, float))):
                xs.append(float(node[0]))
                ys.append(float(node[1]))
                return
            for child in node:
                _walk(child)

    _walk(geometry.get("coordinates"))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _bboxes_touch(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _plan_sliver_merge(issue: dict, ctx: QuickFixContext):
    """返回 (sliver, dominant, others) 或 (None, None, 原因)。"""
    features = ctx._features()
    sliver_id = str(issue.get("feature_id") or "")
    sliver = None
    for feature in features:
        if feature.feature_id == sliver_id:
            sliver = feature
            break
    if sliver is None:
        return None, None, "要素不存在或已被删除"
    if sliver.geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return None, None, "碎屑修复仅适用于面要素"
    sliver_geom = _shape(sliver.geometry)
    if not sliver_geom.is_valid:
        return None, None, "碎屑要素几何无效（先修复无效几何）"
    sliver_bbox = _geometry_bbox(sliver.geometry)
    best = None  # (shared_length, area, feature)
    for other in features:
        if other.feature_id == sliver_id:
            continue
        if other.geometry.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        # bbox 预过滤（P1-2）：不相交包络直接跳过，避免逐要素 GEOS 构造。
        if sliver_bbox is not None:
            other_bbox = _geometry_bbox(other.geometry)
            if other_bbox is None or not _bboxes_touch(sliver_bbox, other_bbox):
                continue
        other_geom = _shape(other.geometry)
        if not other_geom.is_valid or not other_geom.touches(sliver_geom):
            continue
        shared = intersection(sliver.geometry, other.geometry)
        shared_length = 0.0
        if shared.geometry:
            shared_length = float(getattr(_shape(shared.geometry), "length",
                                          0.0) or 0.0)
        if shared_length <= 0.0:
            continue
        candidate = (shared_length, float(other_geom.area), other)
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate
    if best is None:
        return None, None, "没有共享边界的相邻相（孤岛不相邻任何相）"
    return sliver, best[2], ""


def apply_sliver_merge(issue: dict, ctx: QuickFixContext) -> bool:
    """碎多边形吸附合并到相邻优势相（单一撤销命令）。"""
    if ctx.session is None:
        raise RuntimeError("无编辑会话（宿主须先 ensure_layer_session）")
    sliver, dominant, reason = _plan_sliver_merge(issue, ctx)
    if sliver is None or dominant is None:
        raise RuntimeError(reason or "不可修复")
    merged = union([sliver.geometry, dominant.geometry])
    if not merged.geometry:
        raise RuntimeError("几何合并失败")
    session = ctx.session
    session.begin_edit_command()
    try:
        session.set_geometry(dominant.feature_id, dict(merged.geometry))
        session.delete_feature(sliver.feature_id)
    except Exception:
        session.destroy_edit_command()
        raise
    session.end_edit_command()
    return True


def sliver_merge_availability(issue: dict, ctx: QuickFixContext):
    sliver, dominant, reason = _plan_sliver_merge(issue, ctx)
    if sliver is None or dominant is None:
        return False, reason
    return True, f"将并入相邻优势相 {dominant.feature_id}"


# ---------------------------------------------------------------------------
# 未封闭边界：沿切线延伸闭合
# ---------------------------------------------------------------------------

def _tangent_extend(coords: list, tolerance: float):
    """两端沿末端切线交替延伸；返回 (闭合坐标或 None, 原因)。"""
    points = [tuple(map(float, p)) for p in coords]
    if len(points) < 2 or points[0] == points[-1]:
        return None, "边界已闭合"
    step = max(float(tolerance) * 0.5, 1e-6)
    max_extension = float(tolerance) * MAX_EXTENSION_FACTOR

    def _tangent(end_points):
        (x1, y1), (x0, y0) = end_points[-1], end_points[-2]
        dx, dy = x1 - x0, y1 - y0
        norm = math.hypot(dx, dy)
        if norm <= 0.0:
            return None
        return dx / norm, dy / norm

    extended = {"head": 0.0, "tail": 0.0}
    # R2-11: the per-end budget (tolerance × MAX_EXTENSION_FACTOR) was
    # unreachable — int(factor*2)+1 iterations split the budget across both
    # ends. Double the iteration budget so the documented per-end reach is
    # actually attainable.
    for _ in range(int(MAX_EXTENSION_FACTOR * 2) * 2 + 1):
        head, tail = points[0], points[-1]
        if math.dist(head, tail) <= float(tolerance):
            mid = ((head[0] + tail[0]) / 2.0, (head[1] + tail[1]) / 2.0)
            return [mid, *points[1:-1], mid], ""
        # 轮流延伸离得更远的那一端（更快收敛）
        head_t = _tangent([points[1], points[0]])  # 首端切线（指向外）
        tail_t = _tangent([points[-2], points[-1]])
        extend_head = extended["head"] <= extended["tail"]
        if extend_head and head_t is not None and extended["head"] < max_extension:
            points[0] = (points[0][0] + head_t[0] * step,
                         points[0][1] + head_t[1] * step)
            extended["head"] += step
        elif not extend_head and tail_t is not None \
                and extended["tail"] < max_extension:
            points[-1] = (points[-1][0] + tail_t[0] * step,
                          points[-1][1] + tail_t[1] * step)
            extended["tail"] += step
        else:
            break
    head, tail = points[0], points[-1]
    if math.dist(head, tail) <= float(tolerance):
        mid = ((head[0] + tail[0]) / 2.0, (head[1] + tail[1]) / 2.0)
        return [mid, *points[1:-1], mid], ""
    remaining = math.dist(head, tail)
    return None, (
        f"端点距离 {remaining:.2f} 超出最大延伸距离"
        f"（容差 {tolerance:g}×{MAX_EXTENSION_FACTOR:g}）——需人工修编")


def _feature_of(ctx: QuickFixContext, feature_id: str):
    for feature in ctx._features():
        if feature.feature_id == str(feature_id):
            return feature
    return None


def tangent_close_availability(issue: dict, ctx: QuickFixContext):
    feature = _feature_of(ctx, str(issue.get("feature_id") or ""))
    if feature is None:
        return False, "要素不存在或已被删除"
    if feature.geometry.get("type") != "LineString":
        return False, "切线闭合仅适用于线要素"
    closed, reason = _tangent_extend(
        list(feature.geometry.get("coordinates") or []), ctx.tolerance)
    if closed is None:
        return False, reason
    return True, "端点将沿切线延伸并在容差内闭合"


def apply_tangent_close(issue: dict, ctx: QuickFixContext) -> bool:
    session = ctx.session
    if session is None:
        raise RuntimeError("无编辑会话（宿主须先 ensure_layer_session）")
    feature_id = str(issue.get("feature_id") or "")
    feature = _feature_of(ctx, feature_id)
    if feature is None or feature.geometry.get("type") != "LineString":
        raise RuntimeError("要素缺失或不是线要素")
    closed, reason = _tangent_extend(
        list(feature.geometry.get("coordinates") or []), ctx.tolerance)
    if closed is None:
        raise RuntimeError(reason)
    session.begin_edit_command()
    try:
        session.set_geometry(feature_id, {
            "type": "LineString",
            "coordinates": [[x, y] for x, y in closed],
        })
    except Exception:
        session.destroy_edit_command()
        raise
    session.end_edit_command()
    return True


#: 快速修复动作注册表（rule → 动作；hub 按 issue.rule 匹配）。
QUICK_FIX_ACTIONS: tuple[QuickFixAction, ...] = (
    QuickFixAction(
        action_id="sliver_merge",
        title="吸附合并到相邻优势相",
        description="把碎多边形并入共享边界最长的相邻相（并列取面积大者），"
                    "几何取并集、属性取优势相；单一撤销命令。",
        rules=("sliver_polygon", "gap", "geometry_invalid"),
        availability=sliver_merge_availability,
        apply=apply_sliver_merge,
    ),
    QuickFixAction(
        action_id="tangent_close",
        title="沿切线自动延伸闭合",
        description="未封闭边界两端沿末端切线方向延伸（步长=容差×0.5），"
                    "端点进入吸附容差后闭合；超出容差×8 判不可修。",
        rules=("unclosed_boundary", "dangle"),
        availability=tangent_close_availability,
        apply=apply_tangent_close,
    ),
)


def actions_for_rule(rule: str) -> tuple[QuickFixAction, ...]:
    return tuple(action for action in QUICK_FIX_ACTIONS
                 if str(rule) in action.rules)
