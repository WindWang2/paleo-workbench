# -*- coding: utf-8 -*-
"""屏幕空间自适应矢量 LOD（vector-perf-increment Ticket 3）。

Visvalingam-Whyatt 有效面积化简的批量（向量化）实现：逐轮计算候选点
相对当前保留邻居的有效三角形面积，剔除低于容差的局部极小点，直至收
敛。地质形态特征点永不下桌（锚点）：

- 折线端点（环取首点；闭合点随环语义保留）；
- 拐点（相邻边叉积符号翻转处——蜿蜒岸线的折返特征）；
- 局部坐标极值（x/y 最小/最大——凸包意义上的形态支撑点）。

化简只作用于绘制管线（``_PreparedLayer`` 下游的显示几何），永不写回
要素几何——编辑拾取/拓扑始终在原始几何上进行（04-known-limitations
#4）。C++ 侧 ``map_edit_core.vector_lod_simplify`` 与本实现同运算序，
位级一致（tests/perf/test_vector_lod_bench.py 双实现互证）。

容差由视口比例推导：地图单位下的 ``pixel_tolerance × mupp`` 决定可剔
除三角形的有效面积上限（平方量纲）。
"""

from __future__ import annotations

import math

import numpy as np

#: 每顶点像素容差（0.75px：亚像素顶点对屏幕无贡献）。
DEFAULT_PIXEL_TOLERANCE = 0.75

#: 低于该顶点数的层不做数据集级化简（帧级像素量化已覆盖）。
MIN_VERTEX_COUNT = 4_000


def scale_bucket_mupp(mupp: float) -> float:
    """把 map-units-per-pixel 量化到 2 的幂档位（缓存键稳定性）。"""
    if mupp <= 0.0 or not math.isfinite(mupp):
        return 0.0
    return 2.0 ** math.floor(math.log2(mupp))


def tolerance_area(mupp: float,
                   pixel_tolerance: float = DEFAULT_PIXEL_TOLERANCE) -> float:
    """地图单位下的有效面积容差（三角形面积，平方量纲）。"""
    if mupp <= 0.0:
        return 0.0
    edge = pixel_tolerance * mupp
    return edge * edge


def _anchor_mask(
    xs: np.ndarray,
    ys: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    is_ring: np.ndarray,
    tolerance: float,
) -> np.ndarray:
    """逐 part 标记形态锚点（端点 / 可见拐点 / 坐标极值）。

    拐点锚定是刻度相关的：噪声级微折（有效面积 < tolerance，本就不可
    见）不锚，否则带噪声的实测线会锁死全部顶点；只有 |cross| ≥ 2×容差
    （可见的方向改变）才锚——拐点保真与化简率在此取得一致。
    """
    n = len(xs)
    anchors = np.zeros(n, dtype=bool)
    for part in range(len(starts)):
        s, e = int(starts[part]), int(ends[part])
        if e - s < 3:
            anchors[s:e] = True
            continue
        px = xs[s:e]
        py = ys[s:e]
        anchors[s] = True
        anchors[e - 1] = True
        if is_ring[part]:
            # 闭合环：末点==首点，候选域 [s+1, e-1)。
            ax, ay = px[:-1], py[:-1]
            lo, hi = s + 1, e - 1
        else:
            ax, ay = px, py
            lo, hi = s + 1, e - 1
        local = anchors[lo:hi]
        if local.size >= 3:
            d1x = ax[1:-1] - ax[:-2]
            d1y = ay[1:-1] - ay[:-2]
            d2x = ax[2:] - ax[1:-1]
            d2y = ay[2:] - ay[1:-1]
            cross = d1x * d2y - d1y * d2x
            # turns[t] ⟷ 顶点 ax[t+2] ⟷ local[t+1]（local[0] ⟷ ax[1]）。
            # 仅可见拐点（|cross| ≥ 2×容差，即面积 ≥ 容差的转向）锚定。
            visible = np.abs(cross) >= 2.0 * tolerance
            turns = (cross[:-1] * cross[1:] < 0.0) & visible[:-1] & visible[1:]
            local[1:1 + turns.size] |= turns
            # 坐标极值（形态支撑点；平局取首现，与 C++ 一致）。
            # local[i] ⟷ ax[i+1]：argmin(arr[1:-1]) 的绝对 ax 下标为
            # m+1，对应 local 槽位 m。
            for arr in (ax, ay):
                local[int(np.argmin(arr[1:-1]))] = True
                local[int(np.argmax(arr[1:-1]))] = True
    return anchors


def visvalingam_keep_mask(
    xs: np.ndarray,
    ys: np.ndarray,
    starts: np.ndarray,
    is_ring: np.ndarray,
    tolerance: float,
) -> np.ndarray:
    """批量 Visvalingam-Whyatt：返回等长保留掩码（True=保留顶点）。

    拼接布局：``xs/ys`` 全部顶点；``starts`` 各 part 起始下标（末 part
    到 ``len(xs)`` 结束）；``is_ring`` 闭合环标记。``tolerance <= 0``
    恒等（全保留）。

    逐轮：非锚内部点以其当前保留邻居计算有效三角形面积；低于容差的
    连续带只剔除局部极小（同轮互为邻居的剔除会破坏面积语义），直至
    无可剔除——剩余候选全部保留。邻居关系经保留掩码的前/后向累积索
    引重建；part 边界是锚点，链天然不跨界。
    """
    n = len(xs)
    if n == 0 or tolerance <= 0.0:
        return np.ones(n, dtype=bool)
    ends = np.append(starts[1:], n)
    anchors = _anchor_mask(xs, ys, starts, ends, is_ring, tolerance)
    # 经典 VW 语义：三角形面积相对“当前存活邻居”链评估——keep 从全
    # True 起步随剔除收缩（若从锚点起步，首轮邻居即远距锚点，三角形
    # 面积巨大，什么都剔不掉）。
    keep = np.ones(n, dtype=bool)
    pending = np.ones(n, dtype=bool)
    pending &= ~anchors  # 候选 = 非锚内部点（锚点已定为保留）
    idx = np.arange(n)
    part_of = np.searchsorted(starts, idx, side="right") - 1
    interior_pos = (idx > starts[part_of]) & (idx < ends[part_of] - 1)
    pending &= interior_pos

    while True:
        if not pending.any():
            break
        # 严格 j<i / j>i 的最近保留邻居（含自身的退化三角形面积为 0）。
        accum = np.maximum.accumulate(np.where(keep, idx, -1))
        prev_kept = np.concatenate(([-1], accum[:-1]))
        rev_min = np.minimum.accumulate(
            np.where(keep[::-1], idx[::-1], n).reshape(-1))[::-1]
        nxt = np.concatenate((rev_min[1:], [n]))
        has_both = (prev_kept >= 0) & (nxt < n)
        pv = np.where(has_both, prev_kept, idx)
        nx = np.where(has_both, nxt, idx)
        ax_ = xs - xs[pv]
        ay_ = ys - ys[pv]
        bx_ = xs[nx] - xs[pv]
        by_ = ys[nx] - ys[pv]
        areas = np.abs(ax_ * by_ - ay_ * bx_) * 0.5
        below = pending & has_both & (areas < tolerance)
        if not below.any():
            keep |= pending  # 无可剔除：剩余候选全部保留
            break
        remove = below.copy()
        rolled_left = np.roll(areas, 1)
        rolled_right = np.roll(areas, -1)
        left_below = np.zeros(n, dtype=bool)
        right_below = np.zeros(n, dtype=bool)
        left_below[1:] = below[:-1]
        right_below[:-1] = below[1:]
        # 连续低于带只剔除严格局部极小：对比项取 >=（非极小被排除）。
        remove &= ~(left_below & (areas >= rolled_left))
        remove &= ~(right_below & (areas >= rolled_right))
        if not remove.any():
            remove = below & ~(left_below | right_below)
        if not remove.any():
            # 整带同面积平局：每条连续 below 带内隔点剔除（每轮 O(带数)
            # 进度，避免「全局只剔 1 点」在万级顶点上退化成 O(n²) 帧挂死
            # ——CI render threaded/cancel 与大图层交互的根因）。
            below_idx = np.nonzero(below)[0]
            remove = np.zeros(n, dtype=bool)
            if below_idx.size:
                run_starts = np.empty(below_idx.size, dtype=bool)
                run_starts[0] = True
                if below_idx.size > 1:
                    run_starts[1:] = np.diff(below_idx) > 1
                # 带内位置：相对本带起点的偏移。
                start_pos = np.maximum.accumulate(
                    np.where(run_starts, np.arange(below_idx.size), 0))
                pos_in_run = np.arange(below_idx.size) - start_pos
                remove[below_idx[pos_in_run % 2 == 0]] = True
        # remove 本轮剔除：落 keep 位 + 退出候选；带内非极小点留待下轮
        # 以新邻居重算——仍候选。
        keep &= ~remove
        pending &= ~remove
    return keep
