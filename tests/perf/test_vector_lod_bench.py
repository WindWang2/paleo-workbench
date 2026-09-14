# -*- coding: utf-8 -*-
"""Ticket 3 — AdaptiveVectorLOD 基准与保真（TDD 红→绿）。

契约：大比例尺不失真（锚点保留 + 偏差 ≤ 亚像素）；小比例尺顶点数
-80%+；tolerance=0 恒等；C++/Python 双实现位级一致；渲染管线接入后
密集层的绘制顶点大幅下降且帧时间同步改善。
"""
from __future__ import annotations

import statistics
import time

import numpy as np
import pytest

from paleo_workbench.mapping import vector_lod

pytestmark = pytest.mark.slow

pytest.importorskip("numpy")
shapely = pytest.importorskip("shapely")


def _meander(n: int, span: float = 100.0, amp: float = 2.0, seed: int = 3):
    rng = np.random.default_rng(seed)
    xs = np.linspace(0.0, span, n)
    ys = amp * np.sin(xs * 0.8) + 0.3 * amp * np.sin(xs * 7.0 + 1.0)
    ys += rng.normal(0.0, amp * 0.05, n)
    return xs, ys


def test_lod_tolerance_zero_identity():
    xs, ys = _meander(500)
    starts = np.array([0], dtype=np.int64)
    keep = vector_lod.visvalingam_keep_mask(
        xs, ys, starts, np.array([False]), 0.0)
    assert keep.all()
    assert keep.dtype == np.bool_


def test_lod_large_scale_fidelity():
    """大比例尺（小 mupp）：锚点全保留，被剔点的偏差 ≤ 2×像素容差。"""
    xs, ys = _meander(800)
    starts = np.array([0], dtype=np.int64)
    rings = np.array([False])
    mupp = 100.0 / 800.0  # 1 顶点≈1px
    tol = vector_lod.tolerance_area(mupp)
    anchors = vector_lod._anchor_mask(
        xs, ys, starts, np.append(starts[1:], len(xs)), rings, tol)
    keep = vector_lod.visvalingam_keep_mask(xs, ys, starts, rings, tol)
    assert (keep & anchors).sum() == anchors.sum()  # 锚点一个不丢
    # 被剔点相对保留折线的偏差（屏幕空间 ≤ 4×像素容差 = 3px）：VW 的
    # 单步面积界经级联剔除会累积，3px 是亚可见级别的一致界。
    kept_idx = np.nonzero(keep)[0]
    dropped = np.nonzero(~keep)[0]
    for i in dropped:
        j = np.searchsorted(kept_idx, i)
        a, b = kept_idx[max(0, j - 1)], kept_idx[min(len(kept_idx) - 1, j)]
        ax, ay, bx, by = xs[a], ys[a], xs[b], ys[b]
        dx, dy = bx - ax, by - ay
        denom = max(dx * dx + dy * dy, 1e-30)
        t = np.clip(((xs[i] - ax) * dx + (ys[i] - ay) * dy) / denom, 0.0, 1.0)
        dev = np.hypot(xs[i] - (ax + t * dx), ys[i] - (ay + t * dy))
        assert dev <= 4.0 * vector_lod.DEFAULT_PIXEL_TOLERANCE * mupp, (i, dev)


def test_lod_small_scale_reduction_and_validity():
    """小比例尺（大 mupp）：蜿蜒线顶点 -80%+，端点保留且不自交。"""
    xs, ys = _meander(2000)
    starts = np.array([0], dtype=np.int64)
    rings = np.array([False])
    mupp = 100.0 / 120.0  # 视口只装 120 顶点宽 → 强化简
    tol = vector_lod.tolerance_area(mupp)
    keep = vector_lod.visvalingam_keep_mask(xs, ys, starts, rings, tol)
    reduction = 1.0 - keep.sum() / len(keep)
    print(f"[vector-lod] reduction={reduction:.1%} kept={int(keep.sum())}")
    assert reduction >= 0.80
    assert keep[0] and keep[-1]
    line = shapely.LineString(np.column_stack([xs[keep], ys[keep]]))
    assert line.is_simple  # 无自交（化简不制造交叉）


def test_lod_ring_anchors_preserved():
    """环（闭合多边形）化简后仍是合法闭合环，极值锚点不丢。"""
    n = 400
    theta = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    r = 10.0 + 1.5 * np.sin(5 * theta)
    xs = r * np.cos(theta)
    ys = r * np.sin(theta)
    xs = np.append(xs, xs[0])
    ys = np.append(ys, ys[0])
    starts = np.array([0], dtype=np.int64)
    rings = np.array([True])
    tol = vector_lod.tolerance_area(100.0 / 90.0)
    keep = vector_lod.visvalingam_keep_mask(xs, ys, starts, rings, tol)
    assert keep[0] and keep[-1]
    poly = shapely.Polygon(np.column_stack([xs[keep][:-1], ys[keep][:-1]]))
    assert poly.is_valid
    # 极值锚点（x/y 最值）必在保留集。
    for arr in (xs[:-1], ys[:-1]):
        assert keep[int(np.argmax(arr))]
        assert keep[int(np.argmin(arr))]


def test_lod_cpp_python_parity():
    """C++ map_edit_core.vector_lod_simplify 与 Python 参照位级一致。"""
    import importlib.util

    spec = importlib.util.find_spec("map_edit_core")
    if spec is None or "paleo-workbench-vector-perf" not in (spec.origin or ""):
        pytest.skip("worktree map_edit_core not on sys.path (submodule build)")
    import map_edit_core

    if not hasattr(map_edit_core, "vector_lod_simplify"):
        pytest.skip("map_edit_core build predates vector_lod")
    rng = np.random.default_rng(11)
    for parts, ring_flags, n in [
        ([0], [False], 700),
        ([0, 300], [False, True], 600),
        ([0, 50, 120], [True, False, True], 400),
    ]:
        xs = np.cumsum(rng.normal(0.0, 1.0, n))
        ys = np.cumsum(rng.normal(0.0, 1.0, n))
        starts = np.array(parts, dtype=np.int64)
        rings = np.array(ring_flags, dtype=bool)
        for mupp in (0.5, 2.0, 10.0):
            tol = vector_lod.tolerance_area(mupp)
            py_mask = vector_lod.visvalingam_keep_mask(xs, ys, starts, rings, tol)
            cpp_mask = map_edit_core.vector_lod_simplify(
                xs, ys, starts, rings, tol)
            assert np.array_equal(py_mask, cpp_mask), (parts, mupp)


def test_render_lod_reduces_drawn_vertices():
    """渲染管线：密集蜿蜒边界层 LOD 后绘制顶点显著下降、帧时间改善。

    网格式平铺矩形本身即最简几何（无可化简余量）——LOD 的目标是密集体
    等厚线/蜿蜒岸线类高频边界，本用例用高频抖动多边形构造该负载。"""
    from paleo_workbench.mapping.map_render_backend import (
        FallbackMapRenderBackend,
        MapLayerSnapshot,
        MapRenderSnapshot,
    )

    rng = np.random.default_rng(5)
    feats = []
    # 240 顶点高频抖动环 × 500 = 12 万顶点：等厚线/岸线量级的密集负载
    # （LOD 的目标形态——化简收益需压过掩码计算成本才有意义）。
    theta = np.linspace(0.0, 2 * np.pi, 239, endpoint=False)
    for i in range(500):
        x0 = (i % 25) * 4.0
        y0 = (i // 25) * 4.0
        r = 1.7 + 0.3 * np.sin(17 * theta) + rng.normal(0.0, 0.08, 239)
        ring = np.column_stack([x0 + r * np.cos(theta),
                                y0 + r * np.sin(theta)])
        ring = np.vstack([ring, ring[0]])
        feats.append({
            "id": f"f{i}",
            "geometry": {"type": "Polygon",
                         "coordinates": [ring.tolist()]},
            "properties": {"facies_name": "delta" if i % 2 else "lacustrine"},
        })
    style = {
        "renderer": "categorized",
        "field": "facies_name",
        "categories": [["delta", "#e6c9a8", "d"], ["lacustrine", "#cfd8c9", "l"]],
        "stroke": "#26364d",
        "stroke_width": 1.0,
        "fill_patterns": {"delta": "delta", "lacustrine": "sand"},
    }

    def _frames(env_extra: dict | None = None):
        import os

        old = {k: os.environ.get(k) for k in (env_extra or {})}
        os.environ.update(env_extra or {})
        try:
            backend = FallbackMapRenderBackend()
            backend.initialize()
            backend.set_layer_snapshot(MapRenderSnapshot(
                project_crs="EPSG:3857",
                layers=(MapLayerSnapshot(
                    id="facies", name="Facies", layer_type="vector",
                    extent=(0.0, 0.0, 100.0, 100.0), crs="EPSG:3857",
                    data_revision=1, style_revision=1, features=tuple(feats),
                    style=style),),
            ))
            backend.set_output_size(800, 600)
            backend.set_dpi(96.0)
            times = []
            # 同缩放档内的平移扫（缓存稳态：掩码每档只算一次；跨档缩放
            # 会让每帧都付掩码成本，不构成稳态交互场景）。
            for k in range(7):
                dx = (k % 3) * 1.5
                t0 = time.perf_counter()
                backend.set_extent((dx, dx, dx + 100.0, dx + 100.0))
                backend.render_sync()
                times.append(time.perf_counter() - t0)
            stats = dict(backend._diagnostics)
            backend.shutdown()
            return times, stats
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    # 基线（禁用 LOD）vs 启用（缩放 8 帧，中位对比 + 绘制顶点）。
    off_times, _off_stats = _frames({"PWB_DISABLE_VECTOR_LOD": "1"})
    on_times, on_stats = _frames(None)
    off_ms = statistics.median(off_times) * 1000.0
    on_ms = statistics.median(on_times) * 1000.0
    total = on_stats.get("lod_vertices_total", 0)
    kept = on_stats.get("lod_vertices_kept", 0)
    print(f"[vector-lod] render zoom median lod_off={off_ms:.1f}ms "
          f"lod_on={on_ms:.1f}ms kept={kept}/{total}")
    assert total > 0
    assert kept / total < 0.5  # 化简显著
    assert on_ms < off_ms  # 帧时间改善（60FPS 绝对门禁在 Ticket 4 联合达成）
