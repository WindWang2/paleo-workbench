"""V10 Milestone N：SnappingService 状态快照/恢复的序列化契约。

snapshot_state/restore_state 是工程文档持久化的序列化面：快照必须纯
数据、可 JSON 序列化且完整；恢复必须通过 schema_version 门禁、对旧工
程文件的裸 dict 不抛错、缺失字段保持默认、未知图层 id 原样存活（清
理过期 id 归调用方）。
"""

from __future__ import annotations

import json

from paleo_workbench.mapping.map_interaction import SnappingService


def _configured_service() -> SnappingService:
    # 全局 + 恰好 3 个图层覆盖（各自走不同覆盖通道）+ 网格 + 参考点。
    snapping = SnappingService(pixel_tolerance=14.0)
    snapping.enabled = True
    snapping.modes = {"vertex", "segment", "grid", "reference"}
    snapping.current_layer_only = True
    snapping.layer_enabled["facies"] = False
    snapping.layer_priority["facies"] = 2
    snapping.layer_modes["faults"] = {"vertex", "endpoint"}
    snapping.layer_tolerance["wells"] = 22.5
    snapping.set_grid((2.5, 1.5), origin=(0.5, -0.5))
    snapping.set_reference_points([(1.0, 2.0), (3.5, 4.25)])
    return snapping


def test_snapshot_restore_round_trip_is_lossless() -> None:
    original = _configured_service()
    snapshot = original.snapshot_state()

    assert snapshot["schema_version"] == 1
    assert set(snapshot["layer_overrides"]) == {"facies", "faults", "wells"}

    restored = SnappingService()
    assert restored.restore_state(snapshot) is True

    assert restored.snapshot_state() == snapshot
    assert restored.enabled is True
    assert restored.pixel_tolerance == 14.0
    assert restored.modes == {"vertex", "segment", "grid", "reference"}
    assert restored.current_layer_only is True
    assert restored.layer_enabled == {"facies": False}
    assert restored.layer_modes == {"faults": {"vertex", "endpoint"}}
    assert restored.layer_tolerance == {"wells": 22.5}
    assert restored.layer_priority == {"facies": 2}
    assert restored.grid_spacing == (2.5, 1.5)
    assert restored.grid_origin == (0.5, -0.5)
    assert restored.reference_points == ((1.0, 2.0), (3.5, 4.25))


def test_snapshot_of_fresh_service_lists_no_layer_overrides() -> None:
    snapshot = SnappingService().snapshot_state()

    assert snapshot["layer_overrides"] == {}
    assert snapshot["grid_spacing"] is None
    assert snapshot["reference_points"] == []
    assert snapshot["schema_version"] == 1


def test_restore_rejects_unknown_schema_version() -> None:
    snapping = SnappingService(pixel_tolerance=8.0)
    snapshot = _configured_service().snapshot_state()

    assert snapping.restore_state({**snapshot, "schema_version": 99}) is False
    # 拒绝时不得改动当前状态（回退策略由调用方决定）。
    assert snapping.snapshot_state() == SnappingService(pixel_tolerance=8.0).snapshot_state()


def test_restore_empty_or_partial_dict_keeps_defaults_and_never_raises() -> None:
    # 空 dict：无版本 → 走版本门禁返回 False，状态保持默认且不抛错。
    fresh = SnappingService(pixel_tolerance=8.0)
    before = fresh.snapshot_state()
    assert fresh.restore_state({}) is False
    assert fresh.snapshot_state() == before

    # 部分 dict（带合法版本）：只应用存在的字段，其余保持默认。
    partial = SnappingService(pixel_tolerance=8.0)
    assert partial.restore_state({"schema_version": 1, "pixel_tolerance": 25.0}) is True
    assert partial.pixel_tolerance == 25.0
    assert partial.enabled is False
    assert partial.layer_tolerance == {}
    assert partial.grid_spacing is None

    # 旧工程文件式的裸 dict（类型不符字段）同样不得抛错，坏字段跳过。
    legacy = SnappingService(pixel_tolerance=8.0)
    assert legacy.restore_state({"schema_version": 1, "enabled": "yes", "modes": "vertex", "pixel_tolerance": "big"}) is True
    assert legacy.enabled is False
    assert legacy.modes == {"vertex", "segment", "midpoint"}
    assert legacy.pixel_tolerance == 8.0


def test_unknown_layer_ids_survive_round_trip() -> None:
    snapshot = _configured_service().snapshot_state()
    snapshot["layer_overrides"]["ghost-layer"] = {"modes": ["vertex"], "priority": -3}

    restored = SnappingService()
    assert restored.restore_state(snapshot) is True

    # 未知图层 id 照常恢复（图层稍后重挂载；清理由调用方负责）。
    assert restored.layer_modes["ghost-layer"] == {"vertex"}
    assert restored.layer_priority["ghost-layer"] == -3
    assert restored.snapshot_state() == snapshot


def test_snapshot_is_json_serializable_and_survives_json_round_trip() -> None:
    snapshot = _configured_service().snapshot_state()

    encoded = json.dumps(snapshot)
    decoded = json.loads(encoded)

    restored = SnappingService()
    assert restored.restore_state(decoded) is True
    assert restored.snapshot_state() == snapshot
