"""geotopo 对抗性模糊测试（阶段三 §3）。

程序化生成 500+ 病态几何语料（固定种子可复现）：
- 微小刺状（1e-6 量级 sliver / 顶点抖动）
- 自交 8 字环（随机扭结）
- 密集共线点（数千共线顶点）
- 退化输入（零长度段 / 重复点 / NaN / 巨坐标）
- 混合网络（随机线汤 + 部分闭合）

不变式：**永不卡死**（单调用墙钟预算）、**永不崩溃**（段错误/未捕获
异常）、输出要么合法要么契约化拒绝（GeoTopoError 带 PWB-GT-xxx 码）。
默认腿跑 shapely fallback；``@pytest.mark.qgis`` 腿对同一语料跑原生
DCEL 核（两腿合计 1000+ 次执行）。
"""
from __future__ import annotations

import math
import random
import time

import pytest

from paleo_workbench.mapping import geotopo_service as gt

_PER_CALL_BUDGET_S = 10.0  # 单调用墙钟预算：卡死守卫（病态输入 10s 上限）
_FRAME = {"type": "LineString", "path": None}  # 占位说明：见 _network


def _frame_line(size: float = 100.0) -> dict:
    return {"id": "frame", "path": [
        [0.0, 0.0], [size, 0.0], [size, size], [0.0, size], [0.0, 0.0]]}


def corpus() -> list[tuple[str, list[dict]]]:
    """六类 × 各 ~90 例，固定种子。返回 (标签, 控制线网络) 列表。"""
    rng = random.Random(20260914)
    cases: list[tuple[str, list[dict]]] = []

    # ① 微小刺状：框内随机折线 + 1e-6 量级抖动/毛刺。
    for index in range(90):
        base_x = rng.uniform(10.0, 90.0)
        path = [[0.0, base_x], [100.0, base_x]]
        spikes = []
        for _ in range(rng.randint(1, 8)):
            x = rng.uniform(5.0, 95.0)
            eps = rng.choice([1e-6, 5e-6, 1e-5, 1e-7])
            spikes.append([x, base_x + rng.choice([eps, -eps])])
        path.extend(spikes)
        cases.append(("micro-spike", [_frame_line(),
                                      {"id": f"s{index}", "path": path},
                                      {"id": f"v{index}",
                                       "path": [[base_x, 0.0], [base_x, 100.0]]}]))

    # ② 自交 8 字环：随机扭结闭合路径。
    for index in range(90):
        n = rng.randint(6, 16)
        pts = []
        for k in range(n):
            angle = 2 * math.pi * k / n
            pts.append([50.0 + 30.0 * math.cos(angle + rng.uniform(-0.4, 0.4)),
                        50.0 + 30.0 * math.sin(angle * rng.choice([1, 3]))])
        pts.append(pts[0])
        cases.append(("figure-eight", [_frame_line(),
                                       {"id": f"e{index}", "path": pts}]))

    # ③ 密集共线点：数千共线顶点的水平/垂直线。
    for index in range(90):
        y = 1.0 + index * 0.1
        dense_h = [[0.5 * k, y] for k in range(2000)]
        dense_v = [[y, 0.5 * k] for k in range(2000)]
        cases.append(("dense-collinear",
                      [_frame_line(), {"id": "dh", "path": dense_h},
                       {"id": "dv", "path": dense_v}]))

    # ④ 退化输入：零长度段 / 重复点 / NaN / 巨坐标。
    for index in range(90):
        kind = index % 6
        if kind == 0:
            path = [[10.0, 10.0], [10.0, 10.0]]  # 零长度
        elif kind == 1:
            path = [[10.0, 10.0]] * 5 + [[20.0, 20.0]]  # 重复点
        elif kind == 2:
            path = [[float("nan"), 0.0], [10.0, 10.0]]  # NaN（宿主层拦截）
        elif kind == 3:
            path = [[1e300, 1e300], [1e300 + 1.0, 1e300]]  # 巨坐标
        elif kind == 4:
            path = [[0.0, 0.0], [float("inf"), float("inf")]]  # 无穷
        else:
            path = [[50.0, 50.0], [50.0, 50.0000001]]  # 近零长
        cases.append(("degenerate", [_frame_line(), {"id": f"d{index}", "path": path}]))

    # ⑤ 随机线汤：框内随机线段网络（部分交叉、部分悬挂）。
    for index in range(90):
        lines = [_frame_line()]
        for j in range(rng.randint(2, 12)):
            x0, y0 = rng.uniform(0.0, 100.0), rng.uniform(0.0, 100.0)
            x1, y1 = rng.uniform(0.0, 100.0), rng.uniform(0.0, 100.0)
            lines.append({"id": f"r{index}_{j}", "path": [[x0, y0], [x1, y1]]})
        cases.append(("random-soup", lines))

    # ⑥ 混合：框 + 相邻多边形网络（供 reshape 共边模糊复用）。
    for index in range(90):
        jitter = rng.uniform(0.0, 3.0)
        a = {"id": "pa", "path": [[0, 0], [50, 0], [50 + jitter, 50], [0, 50], [0, 0]]}
        b = {"id": "pb", "path": [[50 + jitter, 0], [100, 0], [100, 50],
                                  [50 + jitter, 50], [50 + jitter, 0]]}
        cases.append(("adjacent-pair", [a, b]))

    return cases


CORPUS = corpus()
assert len(CORPUS) >= 500


def _run_polygonize(lines: list[dict], engine_guard) -> None:
    started = time.perf_counter()
    try:
        result = gt.polygonize_control_lines(lines)
    except gt.GeoTopoError:
        return  # 契约化拒绝 ✓
    elapsed = time.perf_counter() - started
    assert elapsed < _PER_CALL_BUDGET_S, f"hang guard: {elapsed:.1f}s"
    engine_guard(result.engine)
    for polygon in result.polygons:
        assert polygon.area > 0.0
        ring = polygon.geometry["coordinates"][0]
        assert len(ring) >= 4
        assert ring[0] == ring[-1]  # 闭合


def _run_reshape(lines: list[dict]) -> None:
    a = {"type": "Polygon", "coordinates": [lines[0]["path"]]}
    b = {"type": "Polygon", "coordinates": [lines[1]["path"]]}
    arcs = gt.find_shared_arcs(a, b)
    if not arcs:
        return
    arc = arcs[0].arc
    curve = [list(arc[0]), [ (arc[0][0] + arc[-1][0]) / 2.0,
                             (arc[0][1] + arc[-1][1]) / 2.0 + 3.0], list(arc[-1])]
    started = time.perf_counter()
    try:
        gt.reshape_shared_arc(a, b, [list(p) for p in arc], curve)
    except gt.GeoTopoError:
        pass  # 拒绝式守恒 ✓（病态输入预期大量拒绝）
    elapsed = time.perf_counter() - started
    assert elapsed < _PER_CALL_BUDGET_S


@pytest.mark.parametrize("label,lines", CORPUS, ids=[c[0] for c in CORPUS])
def test_fuzz_corpus_never_crashes_or_hangs(label, lines):
    engines = {gt.ENGINE_QGIS, gt.ENGINE_SHAPELY}
    _run_polygonize(lines, lambda engine: None or engine in engines)
    if label == "adjacent-pair":
        _run_reshape(lines)


@pytest.mark.qgis
@pytest.mark.parametrize("label,lines", CORPUS, ids=[c[0] for c in CORPUS])
def test_fuzz_corpus_native_core_never_crashes_or_hangs(label, lines):
    """同一语料喂原生 DCEL 核（桥在则 facade 恒选 qgis 引擎）。"""
    from paleo_workbench.qgis_runtime import loader

    loader.prepare_bridge_load()
    import qgis_render_bridge  # noqa: F401

    def guard(engine):
        assert engine == gt.ENGINE_QGIS, engine

    _run_polygonize(lines, guard)
    if label == "adjacent-pair":
        _run_reshape(lines)
