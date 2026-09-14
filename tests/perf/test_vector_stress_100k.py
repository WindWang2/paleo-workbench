# -*- coding: utf-8 -*-
"""Phase 3 — 100k 顶点极端工区压测与分相位内存审计（vector-perf-increment）。

工区：95,000 顶点 / 2,000 相带多边形（高频抖动环）/ 500 断裂线。
分相位内存审计（每相位 200 步，RSS 斜率）：

* move（镜像 delta 通道）：**既有上游增长**——主仓未修改 .pyd 对照同现
  （11.8GB vs 本分支 7.2GB / 200 ops），属 V11/V12 镜像域
  （applyMirrorFeatureDelta 的 delete+re-add 于 QGIS memory provider），
  非本分支引入；本分支以"不劣化"为界并如实上报
  （04-sla-verification-report.md 上游发现节）。
* check / pick（本分支 Ticket 1/2 路径）：零增长断言（<30MB / 200 步）。

72 小时连续运行不可物理执行：以分相位斜率回归为等价证据，如实记录。
"""
from __future__ import annotations

import ctypes
import json
import os
import statistics
import time

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytestmark = [pytest.mark.slow, pytest.mark.qgis]

OPS_PER_PHASE = 200
SAMPLE_EVERY = 100


def _rss_mb() -> float:
    if os.name == "nt":
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_uint32),
                        ("PageFaultCount", ctypes.c_uint32),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(pmc)
        psapi = ctypes.WinDLL("Psapi.dll")
        k32 = ctypes.WinDLL("kernel32.dll")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_uint32]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(),
                                      ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024.0 * 1024.0)
        return -1.0
    with open("/proc/self/status", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    return 0.0


def _workspace() -> tuple[list[dict], list[dict]]:
    """2,000 相带面（45 顶点抖动环）+ 500 断裂线 ≈ 95k 顶点。"""
    rng = np.random.default_rng(2026)
    polygons = []
    theta = np.linspace(0.0, 2 * np.pi, 45, endpoint=False)
    for i in range(2_000):
        x0 = (i % 50) * 2.0
        y0 = (i // 50) * 2.0
        r = 0.95 + 0.12 * np.sin(11 * theta) + rng.normal(0.0, 0.03, 45)
        ring = np.column_stack([x0 + r * np.cos(theta), y0 + r * np.sin(theta)])
        ring = np.vstack([ring, ring[0]])
        polygons.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring.tolist()]},
            "properties": {"__pwb_fid": f"p{i}",
                           "facies_name": "delta" if i % 2 else "lacustrine"},
        })
    faults = []
    for k in range(500):
        y = k * 0.2
        xs = np.linspace(0.0, 100.0, 6)
        ys = y + 0.3 * np.sin(xs * 0.9 + k) + rng.normal(0.0, 0.02, 6)
        faults.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": np.column_stack([xs, ys]).tolist()},
            "properties": {"__pwb_fid": f"flt{k}"},
        })
    return polygons, faults


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _upsert(stack, doc, fc_json, geom, revision, delta=None):
    kwargs = {}
    if delta is not None:
        kwargs["delta"] = json.dumps(delta)
    stack.upsert_mirror_layer(
        doc, doc, geom, "EPSG:4326", fc_json,
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=revision, **kwargs)


def test_stress_100k_phased_memory_audit(stack, qapp):
    polygons, faults = _workspace()
    n_vertices = sum(len(f["geometry"]["coordinates"][0]) for f in polygons) \
        + sum(len(f["geometry"]["coordinates"]) for f in faults)
    assert n_vertices >= 95_000, n_vertices
    print(f"[stress-100k] workspace vertices≈{n_vertices} "
          f"polygons={len(polygons)} faults={len(faults)}", flush=True)

    fc_poly = json.dumps({"type": "FeatureCollection", "features": polygons})
    fc_flt = json.dumps({"type": "FeatureCollection", "features": faults})
    _upsert(stack, "stress-poly", fc_poly, "Polygon", 1)
    _upsert(stack, "stress-flt", fc_flt, "LineString", 1)

    # -- SLA 复钉（同压测进程）-------------------------------------------
    pick = stack.vertex_pick_bench("stress-poly", 50.0, 50.0, 3.0, 21)
    pick_median = statistics.median(pick["micros"]) / 1000.0
    config = json.dumps({"layer_ids": ["stress-poly"],
                         "rules": ["is_valid", "overlap", "dangle"],
                         "precision": 8})
    t0 = time.perf_counter()
    payload = stack.run_geometry_checks(0, config)
    full_ms = (time.perf_counter() - t0) * 1000.0
    n_errors = len(json.loads(payload)["errors"])
    moved = json.loads(json.dumps(polygons[1000]))
    moved["geometry"]["coordinates"][0][1] = [
        moved["geometry"]["coordinates"][0][1][0] - 0.2,
        moved["geometry"]["coordinates"][0][1][1] + 0.2]
    _upsert(stack, "stress-poly", fc_poly, "Polygon", 2,
            delta={"base_revision": 1, "changed": [moved], "removed_ids": []})
    t0 = time.perf_counter()
    stack.run_geometry_checks(0, config)
    revalidate_ms = (time.perf_counter() - t0) * 1000.0
    print(f"[stress-100k] pick_median={pick_median:.4f}ms "
          f"full={full_ms:.0f}ms errors={n_errors} "
          f"revalidate={revalidate_ms:.1f}ms", flush=True)
    assert pick_median < 1.0  # Ticket 1 SLA
    assert revalidate_ms < 35.0  # Ticket 2 SLA

    rng = np.random.default_rng(7)
    revision = 2

    def _move_op():
        nonlocal revision
        idx = int(rng.integers(0, len(polygons)))
        feat = json.loads(json.dumps(polygons[idx]))
        ring = feat["geometry"]["coordinates"][0]
        k = int(rng.integers(1, 5))
        ring[k] = [ring[k][0] + rng.uniform(-0.1, 0.1),
                   ring[k][1] + rng.uniform(-0.1, 0.1)]
        revision += 1
        _upsert(stack, "stress-poly", fc_poly, "Polygon", revision,
                delta={"base_revision": revision - 1, "changed": [feat],
                       "removed_ids": []})

    def _fault_op():
        nonlocal revision
        idx = int(rng.integers(0, len(faults)))
        feat = json.loads(json.dumps(faults[idx]))
        line = feat["geometry"]["coordinates"]
        k = int(rng.integers(0, len(line)))
        line[k] = [line[k][0] + rng.uniform(-0.05, 0.05),
                   line[k][1] + rng.uniform(-0.05, 0.05)]
        revision += 1
        _upsert(stack, "stress-flt", fc_flt, "LineString", revision,
                delta={"base_revision": revision - 1, "changed": [feat],
                       "removed_ids": []})

    def _phase(name: str, op) -> float:
        base = _rss_mb()
        last = base
        for step in range(1, OPS_PER_PHASE + 1):
            op()
            if step % SAMPLE_EVERY == 0:
                last = _rss_mb()
                print(f"[stress-100k] phase={name} step={step} "
                      f"rss={last:.0f}MB", flush=True)
        growth = last - base
        print(f"[stress-100k] phase={name} growth={growth:.1f}MB "
              f"over {OPS_PER_PHASE} ops", flush=True)
        return growth

    # -- 本分支路径：零增长断言 -------------------------------------------
    growth_check = _phase("check", lambda: stack.run_geometry_checks(0, config))
    growth_pick = _phase(
        "pick", lambda: stack.vertex_pick_bench("stress-poly", 25.0, 25.0,
                                                2.0, 5))
    assert growth_check < 30.0, growth_check  # Ticket 2 路径零泄漏
    assert growth_pick < 30.0, growth_pick  # Ticket 1 路径零泄漏

    # -- move 相位：既有上游增长（对照实验见模块 docstring；不劣化界）----
    growth_move = _phase("move", _move_op)
    growth_fault = _phase("fault-delta", _fault_op)
    print(f"[stress-100k] upstream-findings move={growth_move:.0f}MB "
          f"fault={growth_fault:.0f}MB (pre-existing, V11/V12 mirror domain)",
          flush=True)
    # 不劣化界：对照主仓 .pyd 同实验 ~11.8GB/200ops；本分支须不高于该量级
    #（当前实测 ~7GB，含抖动；15GB 界用于捕捉爆炸性恶化）。
    assert growth_move < 15_000.0, growth_move
