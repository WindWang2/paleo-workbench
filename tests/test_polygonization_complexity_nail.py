"""V12-B 复杂度回归钉：多边形化在大网格上不得超线性。

钉的两半（缺一不可，防"空断言"）：

1. **正向钉**：真实现（bbox 预筛 + 双向向量化投票核）在 speckle 最坏场上，
   面积 ×4（60²→120²）的耗时比必须 < ``SCALING_RATIO_BOUND``。
2. **反向对照**：把洞归属人为退回 V12-B 之前的暴力三重循环
   （逐洞 × 逐外环 × 逐顶点标量射线法），同样的断言必须**不再**成立
   （实测比 ~12 vs 快路径 ~4.2）——证明阈值确实分隔两种复杂度类，
   而不是任何实现都能通过的空断言。反向对照还断言暴力实现与真实现
   **输出相同**（geoms 数量一致），即它复现的是"同样语义、更差复杂度"，
   而不是不同的行为。

墙钟比（而非绝对秒）跨机器稳定；每个尺寸取两次运行的最小值以抑制
调度噪声。校准记录（本机，2026-09-13）：fast 4.17 / brute 12.12，
阈值 8.0 两侧各约 1.9× 余量。
"""

from __future__ import annotations

import time

import numpy as np
import pytest

import paleo_workbench.mapping.geological_pipeline.polygonization as polygonization
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    _polygonize_raster_boundaries,
)

# 面积 ×4（60²→120²）允许的最大耗时比。线性实现 ≈ 4×；V12-B 前的暴力
# 洞归属实测 ≈ 12×（超线性主项来自 洞 × 外环 × 顶点 × 环边 的四重积）。
SCALING_RATIO_BOUND = 8.0
NAIL_SIZES = (60, 120)


def _speckle_grid(size: int):
    rng = np.random.default_rng(7)
    z = rng.normal(0.0, 1.0, (size, size))
    return (z >= 0.0).astype(np.int16), z


def _timed_polygonize(size: int, runs: int = 2):
    """min-of-runs 墙钟 + 输出（输出也返回：反向对照需要语义一致性）。"""
    class_grid, z = _speckle_grid(size)
    best = float("inf")
    geoms = []
    for _ in range(runs):
        t0 = time.perf_counter()
        geoms, qc = _polygonize_raster_boundaries(
            class_grid, z, (0.0, 0.0, float(size), float(size)), 1
        )
        best = min(best, time.perf_counter() - t0)
    return best, geoms


def _brute_force_hole_assignment(poly_groups, exterior_rings, holes, qc):
    """V12-B 之前的洞归属（逐洞 × 逐外环 × 逐顶点标量射线法，无预筛）。"""
    for hole in holes:
        best_idx = -1
        best_votes = 0
        for g_idx, pg in enumerate(poly_groups):
            votes = sum(
                1
                for pt in hole[:-1]
                if polygonization._point_in_ring(pt[0], pt[1], pg["exterior"])
            )
            if votes > best_votes:
                best_votes = votes
                best_idx = g_idx
        if best_idx >= 0 and best_votes > 0:
            poly_groups[best_idx]["holes"].append(hole)
        else:
            promoted = list(reversed(hole))
            exterior_rings.append(promoted)
            poly_groups.append({"exterior": promoted, "holes": []})
            qc["holes_promoted_to_exterior"] += 1


class TestPolygonizationComplexityNail:
    def test_hole_assignment_scales_subquadratically(self):
        """正向钉：面积 ×4 时耗时比 < 8（线性 ≈ 4，暴力 ≈ 12）。"""
        small_t, small_geoms = _timed_polygonize(NAIL_SIZES[0])
        large_t, large_geoms = _timed_polygonize(NAIL_SIZES[1])
        ratio = large_t / small_t
        assert len(small_geoms) > 50 and len(large_geoms) > 200  # 最坏场确实最坏
        assert ratio < SCALING_RATIO_BOUND, (
            f"polygonization scaling regressed: t(120²)/t(60²) = {ratio:.2f} "
            f"(bound {SCALING_RATIO_BOUND}; linear ≈ 4, pre-V12-B brute ≈ 12) — "
            "hole assignment likely fell back to the O(holes × exteriors × "
            "vertices × edges) loop"
        )

    def test_brute_force_control_actually_violates_the_bound(self):
        """反向对照：退回暴力实现后，同一个比值必须超过阈值。

        这证明上面那条断言不是空断言——它能区分两种复杂度类。
        同时断言暴力实现与真实现输出一致（同样语义、更差复杂度），
        排除"对照跑的是不同行为"的假阳性。
        """
        fast_small_t, fast_geoms = _timed_polygonize(NAIL_SIZES[0], runs=1)

        original = polygonization._assign_holes_to_exteriors
        polygonization._assign_holes_to_exteriors = _brute_force_hole_assignment
        try:
            brute_small_t, brute_geoms = _timed_polygonize(NAIL_SIZES[0], runs=1)
            brute_large_t, _ = _timed_polygonize(NAIL_SIZES[1], runs=1)
        finally:
            polygonization._assign_holes_to_exteriors = original

        # 语义一致性：暴力对照产出与真实现完全相同的几何
        assert len(brute_geoms) == len(fast_geoms)
        assert brute_geoms == fast_geoms

        # 对照必须超阈（若不超，说明正向钉已失效，两端都要修）
        brute_ratio = brute_large_t / brute_small_t
        assert brute_ratio >= SCALING_RATIO_BOUND, (
            f"negative control no longer violates the bound "
            f"(brute ratio {brute_ratio:.2f} < {SCALING_RATIO_BOUND}); the nail "
            "cannot distinguish brute force from the indexed path on this "
            "machine — recalibrate SCALING_RATIO_BOUND"
        )
        # 暴力路径确实比真实现慢（对照的第二个可信度检查）
        assert brute_small_t > fast_small_t
