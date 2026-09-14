# -*- coding: utf-8 -*-
"""Ticket 1 — SpatialIndexCore 基准与等价性（TDD 红→绿）。

SLA：20,000 多边形顶点下单次最近顶点吸附判定 <1.0 ms（基线线性扫描外推
~2.2 ms；50,000 ~5.5 ms）。断言走生产 `verticesNear` 同路径的诊断绑定
`vertex_pick_query` / `vertex_pick_bench`（无 Qt 事件投递面——手势级计时
被既有 vendor 崩溃阻断，见 docs 00-D8）。

反向对照：`PWB_DISABLE_VERTEX_INDEX=1` 时必须回退线性路径且 50k 规模
超预算——证明 SLA 断言非空转。
"""
from __future__ import annotations

import json
import random
import statistics

import pytest

from .test_vector_perf_baseline import _grid_squares

pytestmark = [pytest.mark.slow, pytest.mark.qgis]

SLA_US = 1000.0  # <1.0 ms


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _upsert(stack, doc, feats):
    stack.upsert_mirror_layer(
        doc, "bench", "Polygon", "EPSG:4326",
        json.dumps({"type": "FeatureCollection", "features": feats}),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=1)


def _hit_tuples(payload) -> list[tuple]:
    return sorted(
        (h["part"], h["ring"], h["nr"], round(h["x"], 9), round(h["y"], 9))
        for h in payload["hits"])


def test_vertex_pick_bench_sla_20k(stack):
    """20k 顶点：单次吸附判定中位 <1.0 ms（含命中）。"""
    _upsert(stack, "t1-20k", _grid_squares(20_000))
    result = stack.vertex_pick_bench("t1-20k", 5.0, 5.0, 2.0, 41)
    assert result["hits"] > 0
    median_us = statistics.median(result["micros"])
    print(f"[spatial-index] sla_20k median={median_us:.1f}us "
          f"indexed={result.get('indexed')}")
    assert median_us < SLA_US


def test_vertex_pick_equivalence_50k(stack, monkeypatch):
    """索引结果与线性参照逐字段等价（120 查询点 × 4 半径混合命中/不命中）。"""
    _upsert(stack, "t1-50k", _grid_squares(50_000))
    rng = random.Random(42)
    queries = [(rng.uniform(0.0, 100.0), rng.uniform(0.0, 100.0))
               for _ in range(120)]
    radii = [0.5, 1.25, 5.0, 1e-8]

    indexed = {}
    for radius in radii:
        for (x, y) in queries:
            indexed[(round(x, 9), round(y, 9), radius)] = _hit_tuples(
                stack.vertex_pick_query("t1-50k", x, y, radius))

    monkeypatch.setenv("PWB_DISABLE_VERTEX_INDEX", "1")
    for radius in radii:
        for (x, y) in queries:
            linear = _hit_tuples(
                stack.vertex_pick_query("t1-50k", x, y, radius))
            assert linear == indexed[(round(x, 9), round(y, 9), radius)], (
                f"index/linear mismatch at ({x:.3f},{y:.3f}) r={radius}")


def test_linear_fallback_exceeds_sla_50k(stack, monkeypatch):
    """反向对照：禁用索引（线性回退）时 50k 必须超预算——防断言空转。"""
    monkeypatch.setenv("PWB_DISABLE_VERTEX_INDEX", "1")
    _upsert(stack, "t1-fb", _grid_squares(50_000))
    result = stack.vertex_pick_bench("t1-fb", 5.0, 5.0, 2.0, 21)
    median_us = statistics.median(result["micros"])
    print(f"[spatial-index] linear_fallback_50k median={median_us:.1f}us")
    assert result.get("indexed") is False
    assert median_us > SLA_US


def test_index_invalidation_after_delta(stack):
    """顶点移动（镜像 delta）后索引不得陈旧：新坐标命中、旧坐标落空。"""
    feats = _grid_squares(5)  # 单要素（100×100 方形）——旧位置无邻要素角点
    _upsert(stack, "t1-inv", feats)
    assert _hit_tuples(
        stack.vertex_pick_query("t1-inv", 55.0, 0.0, 1e-8)) == []

    # 移动该要素的 (100,0) 角点到 (55.0, 0.0)。
    moved = json.loads(json.dumps(feats[0]))
    moved["geometry"]["coordinates"][0][1] = [55.0, 0.0]
    stack.upsert_mirror_layer(
        "t1-inv", "bench", "Polygon", "EPSG:4326",
        json.dumps({"type": "FeatureCollection", "features": feats}),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=2, delta=json.dumps({
            "base_revision": 1, "changed": [moved], "removed_ids": []}))

    hit = _hit_tuples(stack.vertex_pick_query("t1-inv", 55.0, 0.0, 1e-8))
    assert hit and hit[0][3] == 55.0 and hit[0][4] == 0.0
    stale = _hit_tuples(stack.vertex_pick_query("t1-inv", 100.0, 0.0, 1e-8))
    assert stale == []  # 旧位置不得再命中（#1257 同类陈旧对照）


def test_disabled_path_still_correct_small_layer(stack, monkeypatch):
    """禁用索引时小层行为不变（回退路径钉）。"""
    monkeypatch.setenv("PWB_DISABLE_VERTEX_INDEX", "1")
    feats = _grid_squares(50)
    _upsert(stack, "t1-small", feats)
    payload = stack.vertex_pick_query("t1-small", 0.0, 0.0, 1e-8)
    hits = _hit_tuples(payload)
    assert hits and hits[0] == (0, 0, 0, 0.0, 0.0)
