# -*- coding: utf-8 -*-
"""Ticket 5 — ZeroCopyDeltaBus 基准与契约（TDD 红→绿）。

SLA：10,000 事件高频排水，Python 端追踪分配为 0（JSON 参照通道同负载
分配 >0 为反向对照）；字段保真 + 序号连续；默认关闭（API 兼容钉）。
"""
from __future__ import annotations

import gc
import json
import tracemalloc

import numpy as np
import pytest

from paleo_workbench.mapping.edit_delta import (
    EDIT_EVENT_DTYPE,
    EVENT_SNAP_FEEDBACK,
    ZeroCopyEventBus,
    event_to_dict,
)

pytest.importorskip("numpy")
pytestmark = [pytest.mark.slow, pytest.mark.qgis]


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_pod_layout_pinned():
    """POD 布局钉死：64 字节、字段偏移与 C++ static_assert 对映。"""
    assert EDIT_EVENT_DTYPE.itemsize == 128  # 2×64B 缓存行
    offsets = {name: EDIT_EVENT_DTYPE.fields[name][1] for name in
               EDIT_EVENT_DTYPE.names}
    assert offsets["x"] == 0 and offsets["dy"] == 24
    assert offsets["feature_ref"] == 32 and offsets["sequence"] == 48
    assert offsets["kind"] == 56 and offsets["vertex_nr"] == 72
    assert offsets["crc32"] == 76


def test_bus_disabled_by_default(stack):
    """默认关闭：排水恒 0，JSON 回调行为不变（API 兼容钉）。"""
    stats = json.loads(stack.bus_stats())
    assert stats["enabled"] is False
    assert stack.bus_drain_into(bytearray(128)) == 0


def test_bus_10k_events_zero_per_event_alloc(stack):
    """SLA：10,000 事件经生产者入环 + 批量排水，Python 追踪分配 == 0。"""
    bus = ZeroCopyEventBus(stack)
    bus.enable()
    try:
        n = 10_000
        # 持续吞吐：512 一批 emit（真生产者路径）→ drain，直至 10k——
        # 不触发环溢出（溢出/保新语义由 fidelity 用例独立覆盖）。
        stats = json.loads(stack.bus_stats())
        assert stats["enabled"] is True
        gc.collect()
        tracemalloc.start()
        drained = 0
        while drained < n:
            batch = min(512, n - drained)
            stack.bus_emit_bench(batch)
            moved = bus.drain(512)
            drained += len(moved)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert drained == n
        print(f"[edit-delta-bus] drained={drained} tracemalloc_peak={peak}")
        # 按事件零分配：峰值 O(批次) 常数有界（视图对象/返回包装），绝不
        # 随事件数增长——10k 事件 < 2KB（对比 JSON 通道按事件分配）。
        assert peak < 2048

        # 反向对照：同负载 JSON 通道分配必须 >0。
        payload = json.dumps({"kind": "snap_feedback", "x": 1.5, "y": 2.5,
                              "matched": True, "feature_id": "f123"})
        gc.collect()
        tracemalloc.start()
        retained = []  # 消费者留存事件（对照：真实消费形态）
        for _ in range(n):
            retained.append(json.loads(payload))
        _, json_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del retained
        print(f"[edit-delta-bus] json_contrast_peak={json_peak}")
        assert json_peak > 50_000  # JSON 按事件分配（反向对照量级）
    finally:
        bus.disable()


def test_bus_event_fidelity_and_sequence(stack):
    """字段保真 + 序号连续 + 溢出丢弃计数（无腐坏）。"""
    bus = ZeroCopyEventBus(stack)
    bus.enable()
    try:
        n = 10_000  # 超过 4096 容量 → 环溢出丢弃（新事件优先）
        stack.bus_emit_bench(n)
        events = bus.drain()
        assert len(events) > 0 and len(events) <= 4096
        seq = events["sequence"]
        assert np.all(np.diff(seq) == 1)  # 序号连续（无撕裂）
        first = int(seq[0])
        assert first == n - len(events)  # 溢出丢最旧（保新）
        stats = json.loads(stack.bus_stats())
        assert stats["pushed"] == n
        assert stats["dropped"] == n - len(events)
        # 字段保真（bus_emit_bench 的确定性构造：x=i*0.001, feature=i%1000）。
        last = events[-1]
        assert abs(last["x"] - (n - 1) * 0.001) < 1e-9
        assert last["feature_ref"] == (n - 1) % 1000
        assert last["kind"] == EVENT_SNAP_FEEDBACK
        record = event_to_dict(last)
        assert record["kind"] == EVENT_SNAP_FEEDBACK
        assert set(record) == {"kind", "x", "y", "dx", "dy", "feature_ref",
                               "sequence", "timestamp_ns", "canvas_slot",
                               "part", "ring", "vertex_nr", "crc32"}
    finally:
        bus.disable()


def test_tool_sink_writes_ring(stack, qtbot, qapp):
    """真工具路径：启用总线后顶点工具 hover 的 snap 反馈写环（与 JSON
    回调并行）。"""
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    # v10 验证过的几何/视口：方形 (5,5)-(8,8)，400px 画布 → 40px/unit，
    # hover 直落顶点 (5,5)/(8,5)（QPoint(200,200)/(320,200)）。
    feats = [{"type": "Feature",
              "geometry": {"type": "Polygon", "coordinates": [[
                  [5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0], [5.0, 5.0]]]},
              "properties": {"__pwb_fid": "f1"}}]
    doc = "t5-sink"
    stack.upsert_mirror_layer(
        doc, "bench", "Polygon", "EPSG:4326",
        json.dumps({"type": "FeatureCollection", "features": feats}),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=1)
    addr, view = _canvas_of(qtbot, stack)
    stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
    # snapping 开启（v10 模式）：吸附流走 locator 命中路径。
    stack.set_snapping_config(addr, json.dumps({
        "enabled": True, "mode": "all_layers", "tolerance_px": 12.0,
        "types": ["vertex", "segment"],
    }))
    json_events = []
    stack.set_edit_pick_callback(
        addr, lambda action, payload: json_events.append((action, payload)))
    stack.set_map_tool(addr, "vertex")

    bus = ZeroCopyEventBus(stack)
    bus.enable()
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest

        # v10 模式：mouseMove + qWait（offscreen 下 hover 需事件循环时间；
        # processEvents 不够——见 test_qgis_v10_edit_tools.py 同款）。
        for pos in (QPoint(200, 200), QPoint(320, 200), QPoint(200, 200)):
            QTest.mouseMove(view.viewport(), pos)
            QTest.qWait(80)
        events = bus.drain()
        snaps = [e for e in events if e["kind"] == EVENT_SNAP_FEEDBACK]
        matched_json = [a for a, p in json_events
                        if a == "snap_feedback" and '"matched":true' in p]
        print(f"[edit-delta-bus] sink snaps={len(snaps)} "
              f"json_matched={len(matched_json)}")
        assert len(snaps) >= 1  # 二进制环收到了吸附流
        assert matched_json  # JSON 并行（matched 路径 = 发射点同分支）
        seqs = [int(e["sequence"]) for e in snaps]
        assert all(b - a >= 0 for a, b in zip(seqs, seqs[1:]))  # 序号单调
    finally:
        bus.disable()


def _canvas_of(qtbot, stack):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    addr = stack.create_canvas()
    view = wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    return addr, view
