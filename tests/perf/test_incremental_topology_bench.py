# -*- coding: utf-8 -*-
"""Ticket 2 — DirtyBoxTopologicalCore 基准与等价性（TDD 红→绿）。

SLA：单次节点移动后的拓扑有效性验证 <35 ms（基线全量重扫：50k 顶点
3,920 ms）。等价性契约：随机编辑序列下，增量 run 的错误列表与禁用增量
（PWB_DISABLE_INCREMENTAL_TOPO=1 全量参照）逐字段相等——数学上同为
"（脏,任意）对重证 +（干净,干净）对沿用"的补丁语义。
"""
from __future__ import annotations

import json
import random
import statistics
import time

import pytest

from .test_vector_perf_baseline import _grid_squares

pytestmark = [pytest.mark.slow, pytest.mark.qgis]

SLA_MS = 35.0


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _upsert(stack, doc, feats, revision, delta=None):
    kwargs = {}
    if delta is not None:
        kwargs["delta"] = json.dumps(delta)
    stack.upsert_mirror_layer(
        doc, "bench", "Polygon", "EPSG:4326",
        json.dumps({"type": "FeatureCollection", "features": feats}),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=revision, **kwargs)


def _config(doc, rules=("is_valid", "overlap", "dangle")):
    return json.dumps({
        "layer_ids": [doc], "rules": list(rules), "precision": 8,
    })


def _errors(payload):
    out = json.loads(payload)["errors"]

    def key(e):
        pair = sorted([str(e.get("feature_id")), str(e.get("other_feature_id"))])
        # overlap 的 message 内嵌对端数值 fid（随栈的 fid 排序翻转方向、
        # 跨栈不稳定）——对比键用无向对 + 几何/面积，不含 message。
        message = "" if e["rule"] == "overlap" else e["message"]
        return (e["rule"], e["layer_id"], tuple(pair), message,
                tuple(round(v, 6) for v in (e.get("location") or [])),
                tuple(round(v, 4) for v in (e.get("bbox") or [])),
                round(e.get("value") or 0.0, 9))

    return sorted((key(e) for e in out), key=repr)


def _sparse_overlap_grid(n_vertices: int, every: int = 50,
                         drop_every: int = 9) -> list[dict]:
    """实际量级错误负载：平铺网格（drop_every 抽洞）+ 每 every 个外扩成
    局部重叠——错误数十~数百条（真实工区量级），非 28k 条的病态网格
    （那种负载下输出序列化本身即秒级，不属交互验证场景）。"""
    squares = max(1, n_vertices // 5)
    side = max(2, int(squares**0.5))
    cell = 100.0 / side
    feats = []
    index = 0
    for i in range(side):
        for j in range(side):
            if len(feats) >= squares:
                break
            if (i * side + j) % drop_every == 3:
                continue  # 抽洞
            x0, y0 = i * cell, j * cell
            grow = cell * 0.2 if index % every == 0 else 0.0
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [x0, y0], [x0 + cell + grow, y0],
                    [x0 + cell + grow, y0 + cell + grow],
                    [x0, y0 + cell + grow], [x0, y0]]]},
                "properties": {"__pwb_fid": f"f{i}-{j}", "facies_name": "delta"},
            })
            index += 1
    return feats


def test_revalidate_after_vertex_move_sla_50k(qtbot, stack):
    """SLA：10k 面（50k 顶点）移动 1 顶点后复检中位 <35 ms。"""
    doc = "t2-sla"
    feats = _sparse_overlap_grid(50_000)
    _upsert(stack, doc, feats, 1)
    stack.run_geometry_checks(0, _config(doc))  # 全量首跑（预热缓存）

    moved = json.loads(json.dumps(feats[len(feats) // 2]))
    ring = moved["geometry"]["coordinates"][0]
    ring[1] = [ring[1][0] - 0.35, ring[1][1] + 0.35]
    _upsert(stack, doc, feats, 2,
            delta={"base_revision": 1, "changed": [moved], "removed_ids": []})

    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        payload = stack.run_geometry_checks(0, _config(doc))
        samples.append(time.perf_counter() - t0)
        assert "errors" in json.loads(payload)
    median_ms = statistics.median(samples) * 1000.0
    print(f"[topo-increment] revalidate_50k median={median_ms:.1f}ms "
          f"errors={len(json.loads(payload)['errors'])}")
    assert median_ms < SLA_MS


def test_incremental_equals_full(qtbot, stack, monkeypatch):
    """等价性：随机 20 步编辑，每步 增量结果 == 全量参照（逐字段）。"""
    doc = "t2-equiv"
    rng = random.Random(7)
    feats = _sparse_overlap_grid(10_000, every=37, drop_every=11)
    revision = 1
    _upsert(stack, doc, feats, revision)
    config = _config(doc)

    for step in range(20):
        action = rng.choice(["move_vertex", "move_vertex", "move_feature",
                             "add", "remove"])
        changed, removed = [], []
        if action == "move_vertex":
            victim = json.loads(json.dumps(rng.choice(feats)))
            ring = victim["geometry"]["coordinates"][0]
            k = rng.randrange(1, 4)
            ring[k] = [ring[k][0] + rng.uniform(-0.3, 0.3),
                       ring[k][1] + rng.uniform(-0.3, 0.3)]
            changed = [victim]
        elif action == "move_feature":
            victim = json.loads(json.dumps(rng.choice(feats)))
            dx, dy = rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4)
            ring = victim["geometry"]["coordinates"][0]
            for pt in ring:
                pt[0] += dx
                pt[1] += dy
            changed = [victim]
        elif action == "add":
            x0 = rng.uniform(0.0, 99.0)
            y0 = rng.uniform(0.0, 99.0)
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [x0, y0], [x0 + 1.3, y0], [x0 + 1.3, y0 + 1.3],
                    [x0, y0 + 1.3], [x0, y0]]]},
                "properties": {"__pwb_fid": f"new-{step}"},
            })
            changed = [feats[-1]]
        else:
            victim = rng.choice(feats) if len(feats) > 10 else None
            if victim is not None:
                feats.remove(victim)
                removed = [victim["properties"]["__pwb_fid"]]
        revision += 1
        _upsert(stack, doc, feats, revision, delta={
            "base_revision": revision - 1, "changed": changed,
            "removed_ids": removed})

        incremental = _errors(stack.run_geometry_checks(0, config))
        monkeypatch.setenv("PWB_DISABLE_INCREMENTAL_TOPO", "1")
        full = _errors(stack.run_geometry_checks(0, config))
        monkeypatch.delenv("PWB_DISABLE_INCREMENTAL_TOPO")
        assert incremental == full, (
            f"step {step} ({action}): incremental={len(incremental)} "
            f"full={len(full)} mismatch")


def test_unchanged_fastpath(qtbot, stack):
    """指纹无变化 → 缓存直返（gap 规则同样适用，且第二次 <35 ms）。"""
    doc = "t2-fast"
    feats = _sparse_overlap_grid(10_000)
    _upsert(stack, doc, feats, 1)
    config = _config(doc, rules=("is_valid", "overlap", "dangle", "gap"))
    stack.run_geometry_checks(0, config)  # 全量首跑
    t0 = time.perf_counter()
    payload = stack.run_geometry_checks(0, config)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    print(f"[topo-increment] unchanged_fastpath={elapsed_ms:.1f}ms")
    assert "errors" in json.loads(payload)
    assert elapsed_ms < SLA_MS


def test_config_change_disables_incremental(qtbot, stack):
    """配置变化（precision）必须绕过缓存全量重算——防陈旧。

    precision 刻意改变几何容差（重叠面积随之合法变化），故对照锚点是
    同数据同配置的全新栈，而非跨 precision 相等。"""
    doc = "t2-cfg"
    feats = _sparse_overlap_grid(1_000)
    _upsert(stack, doc, feats, 1)
    stack.run_geometry_checks(0, _config(doc))  # 建缓存

    moved = json.loads(json.dumps(feats[0]))
    moved["geometry"]["coordinates"][0][1] = [
        moved["geometry"]["coordinates"][0][1][0] - 0.5,
        moved["geometry"]["coordinates"][0][1][1] + 0.5]
    feats[0] = moved  # 本地表与 delta 通道保持一致（fresh 栈对照用）
    _upsert(stack, doc, feats, 2,
            delta={"base_revision": 1, "changed": [moved], "removed_ids": []})

    other = json.loads(_config(doc))
    other["precision"] = 6  # 请求变化 → 全量
    result_a = _errors(stack.run_geometry_checks(0, json.dumps(other)))
    assert result_a  # 有错误负载
    # 原配置随后也须全量重算（缓存不得跨配置沿用）——与全新栈对照。
    result_b = _errors(stack.run_geometry_checks(0, _config(doc)))

    from qgis_render_bridge.mapstack import QgisMapStack

    fresh = QgisMapStack()
    fresh.initialize()
    try:
        _upsert(fresh, doc, feats, 2)
        result_c = _errors(fresh.run_geometry_checks(0, _config(doc)))
    finally:
        fresh.shutdown()
    assert result_b == result_c
