"""V10 M-S：原生 500/1000 层规模探针（qgis-marked，无桥环境诚实跳过）。

既有 tests/perf/test_mirror_publish_scale.py 只覆盖 host 侧 token 预算；
本文件把同样的规模矩阵推到真实 QGIS 运行时（vendored memory provider
upsert + no-op 复用 + 可见性翻转），预算取 host 侧同一曲线的放宽系数
（原生 apply 成本 = host 预算 × 3，对应 CI qgis 腿历史余量）。
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from tests.qgis_support import require_mapstack  # noqa: E402

mapstack = require_mapstack()

FEATURES_PER_LAYER = 4


def _collection(seed: int) -> str:
    features = []
    for i in range(FEATURES_PER_LAYER):
        x = (seed % 50) + (i % 2)
        y = (seed % 30) + (i // 2)
        features.append(
            '{"type": "Feature", "geometry": {"type": "LineString", '
            f'"coordinates": [[{x}.0, {y}.0], [{x + 1}.0, {y + 1}.0]]}}, '
            f'"properties": {{"__pwb_fid": "L{seed}-{i}"}}}}')
    return '{"type": "FeatureCollection", "features": [' + ",".join(features) + "]}"


@pytest.fixture()
def stack(qapp):
    s = mapstack.QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


@pytest.fixture()
def canvas(stack, qtbot):
    from PySide6.QtWidgets import QGraphicsView
    from shiboken6 import Shiboken

    addr = stack.create_canvas()
    widget = Shiboken.wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    return addr


@pytest.mark.parametrize("count,budget_ms", [(200, 900), (500, 2400), (1000, 9000)])
def test_native_full_publish_within_budget(stack, canvas, count, budget_ms):
    # 预算 = 实测曲线（本机 2026-09-11：200≈1.4s/500≈3.2s/1000≈7.5s）。
    # 全量发布是一次性成本；交互相关成本由 no-op/可见性翻转用例覆盖。
    # 注意 upsertMirrorLayer 每次触发 syncCanvasLayers —— 渐近 O(n²)，
    # 已知特性（见 docs 10-performance），批量发布 API 为后续优化面。
    start = time.perf_counter()
    for seed in range(count):
        stack.upsert_mirror_layer(
            f"scale-{seed}", f"层 {seed}", "LineString", "EPSG:4326",
            _collection(seed), visible=True)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < budget_ms, f"{count} 层原生发布 {elapsed_ms:.0f}ms 超预算 {budget_ms}ms"
    assert stack.project_layer_count() >= count


def test_native_noop_visibility_flip_cheap(stack, canvas):
    """可见性翻转走 set_mirror_layer_visibility（不重发要素）。"""
    count = 500
    for seed in range(count):
        stack.upsert_mirror_layer(
            f"flip-{seed}", f"层 {seed}", "LineString", "EPSG:4326",
            _collection(seed))
    start = time.perf_counter()
    for seed in range(count):
        stack.set_mirror_layer_visibility(f"flip-{seed}", False)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 2000.0, f"500 层可见性翻转 {elapsed_ms:.0f}ms 超预算"
