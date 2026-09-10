"""V9 W1/W2/W3 — 交互事实权威、拓扑计数生产者、CRS 契约。

覆盖：

* ToolContext v3：``project_crs``/``layer_crs``/``scale_denominator`` 事实、
  snapping/topology 可用性从桥 manifest 派生（原生门控 / 回退恒真）；
* TopologyService 错误计数缓存（record/refresh/cached/forget + 会话终结
  语义）——merge 门禁 ``topology_error_count`` 的运行时生产者；
* ``crs_contract``：normalize/geographic 单谓词、resolve_crs 永不静默
  4326、metre 轴判定、Geod、诚实比例尺分母（度轴 = 0）；
* qgis_mirror：地理谓词去重后的 CGCS2000 覆盖 + CRS 丢弃诊断。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.crs_contract import (
    crs_axis_unit_metres,
    crs_is_geographic,
    geod_for_crs,
    normalize_crs,
    resolve_crs,
    scale_denominator_from_pixels,
)
from paleo_workbench.mapping.tool_context import (
    TOOL_CONTEXT_CONTRACT_VERSION,
    build_tool_context,
)
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _layer(layer_id: str = "L1", *, kind: str = "polygon") -> VectorLayer:
    layer = VectorLayer(id=layer_id, name=layer_id, crs="EPSG:4326")
    return layer


def _add_bad_polygon(layer: VectorLayer) -> None:
    session = layer.start_editing()
    session.add_feature(
        VectorFeature(
            "f1",
            {"type": "Polygon",
             "coordinates": [[[0, 0], [1, 0], [1, 1]]]},  # ring unclosed
            {},
        )
    )


def _add_good_polygon(layer: VectorLayer) -> None:
    session = layer.start_editing()
    session.add_feature(
        VectorFeature(
            "f1",
            {"type": "Polygon",
             "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            {},
        )
    )


class _FakeQgis:
    """build_tool_context 的 qgis 快照假体（避免真桥探测）。"""

    def __init__(self, *, available: bool, features: frozenset[str]) -> None:
        self.available = available
        self._features = features

    def capability_flags(self) -> frozenset[str]:
        if not self.available:
            return frozenset()
        return frozenset(f"qgis.{name}" for name in self._features)


# --------------------------------------------------------------------------- #
# ToolContext v3 — CRS / scale facts
# --------------------------------------------------------------------------- #

def test_contract_version_bumped_to_3():
    assert TOOL_CONTEXT_CONTRACT_VERSION == 3


def test_context_carries_crs_and_scale_facts():
    ctx = build_tool_context(
        controller_state={
            "project_crs": "EPSG:4326",
            "layer_crs": "EPSG:4326",
            "scale_denominator": 50_000.0,
        },
        qgis=_FakeQgis(available=False, features=frozenset()),
    )
    assert ctx.project_crs == "EPSG:4326"
    assert ctx.layer_crs == "EPSG:4326"
    assert ctx.scale_denominator == 50_000.0


def test_context_crs_and_scale_default_to_honest_unknown():
    ctx = build_tool_context(
        qgis=_FakeQgis(available=False, features=frozenset())
    )
    assert ctx.project_crs == ""
    assert ctx.layer_crs == ""
    assert ctx.scale_denominator == 0.0


def test_context_scale_negative_clamps_to_unknown():
    ctx = build_tool_context(
        controller_state={"scale_denominator": -3.0},
        qgis=_FakeQgis(available=False, features=frozenset()),
    )
    assert ctx.scale_denominator == 0.0


# --------------------------------------------------------------------------- #
# availability derivation from the bridge manifest
# --------------------------------------------------------------------------- #

def test_snapping_availability_derived_from_manifest_on_native():
    ctx = build_tool_context(
        native_canvas_available=True,
        qgis=_FakeQgis(available=True, features=frozenset({"snapping_push"})),
    )
    assert ctx.snapping_available is True

    ctx_old_bridge = build_tool_context(
        native_canvas_available=True,
        qgis=_FakeQgis(available=True, features=frozenset()),
    )
    assert ctx_old_bridge.snapping_available is False


def test_snapping_availability_true_on_fallback_canvas():
    ctx = build_tool_context(
        native_canvas_available=False,
        qgis=_FakeQgis(available=True, features=frozenset()),
    )
    assert ctx.snapping_available is True


def test_topology_availability_follows_validation_engine():
    # 回退画布：shapely 在测试环境可用 → topology_available 真
    ctx = build_tool_context(
        native_canvas_available=False,
        qgis=_FakeQgis(available=False, features=frozenset()),
    )
    shapely = pytest.importorskip("shapely.geometry")
    assert ctx.topology_available is True

    # 原生画布 + 桥有 validate 算子 → 真（经 manifest 派生）
    ctx_native = build_tool_context(
        native_canvas_available=True,
        qgis=_FakeQgis(
            available=True,
            features=frozenset(),
        ),
        controller_state={},  # validate flag 走 geometry_ops 合成
    )
    # manifest fake 不含 geometry_op.validate → shapely 回退决定
    assert ctx_native.topology_available is True


def test_evaluator_gates_snapping_on_availability():
    from paleo_workbench.mapping.tool_availability import evaluate_tool

    ctx = build_tool_context(
        native_canvas_available=True,
        qgis=_FakeQgis(available=True, features=frozenset()),
        controller_state={"active_layer_id": "L1"},
        layer_facts={"active_layer_id": "L1"},
    )
    verdict = evaluate_tool("snapping", ctx)
    assert not verdict.enabled
    assert "捕捉引擎不可用" in verdict.disabled_reason

    ok_ctx = build_tool_context(
        native_canvas_available=True,
        qgis=_FakeQgis(available=True, features=frozenset({"snapping_push"})),
        controller_state={"active_layer_id": "L1"},
        layer_facts={"active_layer_id": "L1"},
    )
    assert evaluate_tool("snapping", ok_ctx).enabled


# --------------------------------------------------------------------------- #
# TopologyService — runtime error count producer (W2)
# --------------------------------------------------------------------------- #

def test_error_count_cache_lifecycle():
    service = TopologyService(enabled=True)
    layer = _layer()
    _add_bad_polygon(layer)
    assert service.cached_error_count([layer]) == 0  # 未校验 = 0（不猜）
    count = service.refresh_error_count(layer)
    assert count >= 1  # unclosed ring 报错
    assert service.cached_error_count([layer]) == count


def test_error_count_only_counts_live_sessions():
    service = TopologyService(enabled=True)
    layer = _layer()
    _add_bad_polygon(layer)
    service.refresh_error_count(layer)
    assert service.cached_error_count([layer]) >= 1
    layer.edit_session.commit_changes()
    assert layer.edit_session is None
    assert service.cached_error_count([layer]) == 0  # 会话终结不计


def test_error_count_forget_on_layer_removal():
    service = TopologyService(enabled=True)
    layer = _layer()
    _add_bad_polygon(layer)
    service.refresh_error_count(layer)
    service.forget_error_count([layer.id])
    session = layer.edit_session
    assert session is not None
    assert service.cached_error_count([layer]) == 0


def test_merge_gate_consumes_live_error_count():
    from paleo_workbench.mapping.tool_availability import evaluate_tool

    service = TopologyService(enabled=True)
    layer = _layer()
    _add_bad_polygon(layer)
    _add_good_polygon(_layer("L2"))  # 另一层无会话
    service.refresh_error_count(layer)
    ctx = build_tool_context(
        qgis=_FakeQgis(available=False, features=frozenset()),
        controller_state={
            "active_layer_id": layer.id,
            "editing": True,
            "edit_gate_open": True,
            "merge_ready": True,
            "topology_error_count": service.cached_error_count([layer]),
        },
        layer_facts={"active_layer_id": layer.id},
    )
    verdict = evaluate_tool("merge", ctx)
    assert not verdict.enabled
    assert "拓扑错误" in verdict.disabled_reason


# --------------------------------------------------------------------------- #
# crs_contract (W3)
# --------------------------------------------------------------------------- #

def test_geographic_predicate_covers_cgcs2000():
    assert crs_is_geographic("EPSG:4490") is True
    assert crs_is_geographic("EPSG:4326") is True
    assert crs_is_geographic("EPSG:3857") is False
    assert crs_is_geographic("") is None


def test_normalize_crs_normalizes_user_input():
    assert normalize_crs("epsg:4326").upper().startswith("EPSG")
    assert normalize_crs("") == ""
    assert normalize_crs(None) == ""


def test_resolve_crs_declared_and_degraded():
    ok = resolve_crs("EPSG:4326", purpose="测试")
    assert ok.ok and ok.declared

    undeclared = resolve_crs("", purpose="测试")
    assert not undeclared.ok
    assert undeclared.crs == ""
    assert "未声明" in undeclared.degraded_reason

    fallback = resolve_crs("", purpose="测试", fallback="EPSG:4326")
    assert fallback.crs == "EPSG:4326"
    assert not fallback.declared  # 降级必须留痕
    assert "默认" in fallback.degraded_reason


def test_axis_unit_metres_truth():
    assert crs_axis_unit_metres("EPSG:32650") is True   # UTM 50N
    assert crs_axis_unit_metres("EPSG:4326") is False   # degrees
    assert crs_axis_unit_metres("") is None


def test_scale_denominator_metres_only():
    metric = scale_denominator_from_pixels(10.0, 96.0, "EPSG:32650")
    assert metric == pytest.approx(10.0 * 39.3700787 * 96.0)
    assert scale_denominator_from_pixels(10.0, 96.0, "EPSG:4326") == 0.0
    assert scale_denominator_from_pixels(10.0, 96.0, "") == 0.0
    assert scale_denominator_from_pixels(0.0, 96.0, "EPSG:32650") == 0.0


def test_geod_for_crs_geographic_only():
    geod = geod_for_crs("EPSG:4326")
    assert geod is not None
    _az1, _az2, distance = geod.inv(0.0, 0.0, 1.0, 0.0)
    assert distance == pytest.approx(111_195.0, rel=5e-3)  # ~111 km per degree
    assert geod_for_crs("EPSG:32650") is None
    assert geod_for_crs("") is None


def _snapshot(layers=()):
    from types import SimpleNamespace

    return SimpleNamespace(project_crs="EPSG:4326", layers=layers)


def test_mirror_geographic_predicate_delegates_to_contract():
    from paleo_workbench.mapping.qgis_mirror import _geographic_auth

    # V8 字面量集合漏掉的地理系现在被认出（extent 检查不再放行）
    assert _geographic_auth("EPSG:4490") is True
    assert _geographic_auth("EPSG:4214") is True
    assert _geographic_auth("EPSG:3857") is False
    assert _geographic_auth("garbage") is False  # 未知 = 非地理（fail-open 同旧约）


def test_mirror_crs_drop_records_diagnostic():
    from paleo_workbench.mapping import qgis_mirror

    dropped: list[tuple[str, str]] = []

    def on_drop(doc_id: str, message: str) -> None:
        dropped.append((doc_id, message))

    layer = type(
        "Layer",
        (),
        {
            "id": "L1",
            "crs": "EPSG:4326",
            "extent": (-200.0, 0.0, 200.0, 1.0),  # 超出度域
        },
    )()
    snapshot = _snapshot()
    assert qgis_mirror._qgis_crs_for_layer(layer, snapshot, on_drop=on_drop) == ""
    assert dropped and "degree domain" in dropped[0][1]
    assert dropped[0][0] == "L1"

    dropped.clear()
    snapshot_bad = _snapshot(layers=(layer,))
    assert qgis_mirror._qgis_crs_for_snapshot(
        snapshot_bad, on_drop=on_drop) == ""
    assert dropped
