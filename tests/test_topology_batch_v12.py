# -*- coding: utf-8 -*-
"""V12-C 拓扑校验批量化：``geometry.validate_many`` 能力探针 + 逐要素回退。

契约（docs/development/render-increment-v12/02-design.md §C）：
- 桥提供 ``validate_many(geometries)``（signature 或 pybind doc 声明）→
  本层可校验几何**一次**过桥，N 次跨语言往返 → 1 次；
- 批量异常 / 返回形状不符 → 警告一次，整批回退 Shapely（P2-2/P2-6 纪律）；
- 老桥（无批量签名，含 BASE 真桥）→ 逐要素路径零行为变化；
- 校验规则、issues 顺序（含 ring-closure）逐字不变。
"""

from __future__ import annotations

import sys
import types

import pytest

from paleo_workbench.mapping.topology import TopologyService


# ---------------------------------------------------------------- helpers ----

def _square(ox: float, oy: float) -> list[list[float]]:
    return [[ox, oy], [ox + 30, oy], [ox + 30, oy + 30], [ox, oy + 30], [ox, oy]]


def _bowtie(ox: float, oy: float) -> list[list[float]]:
    return [[ox, oy], [ox + 30, oy + 30], [ox + 30, oy], [ox, oy + 30], [ox, oy]]


def _record(index: int) -> dict:
    ox, oy = (index % 10) * 40.0, (index // 10) * 40.0
    if index % 10 == 0:
        geometry = {"type": "Polygon", "coordinates": [_bowtie(ox, oy)]}
    else:
        geometry = {"type": "Polygon", "coordinates": [_square(ox, oy)]}
    return {"feature_id": f"f{index}", "geometry": geometry}


def _records(count: int) -> list[dict]:
    return [_record(index) for index in range(count)]


def _fake_geometry_module(*, with_many, many_behaviour="aligned"):
    """假桥 geometry 子模块：validate/validate_many 计数 + 与 GEOS 同形返回。"""
    module = types.ModuleType("qgis_render_bridge.geometry")
    state = {"validate_calls": 0, "many_calls": 0}

    def detect(geometry: dict) -> list[dict]:
        ring = (geometry.get("coordinates") or [[]])[0]
        if len(ring) >= 5 and ring[1] == [ring[0][0] + 30, ring[0][1] + 30]:
            return [{"where": [15.0, 15.0], "message": "Self-intersection"}]
        return []

    def validate(geometry):
        state["validate_calls"] += 1
        return detect(geometry)

    module.validate = validate

    if with_many:

        def validate_many(geometries):
            state["many_calls"] += 1
            if many_behaviour == "raise":
                raise RuntimeError("bridge exploded")
            results = [detect(geometry) for geometry in geometries]
            if many_behaviour == "short":
                return results[:-1]
            if many_behaviour == "not_list":
                return {"count": len(results)}
            return results

        module.validate_many = validate_many

    return module, state


@pytest.fixture
def install_bridge(monkeypatch):
    def install(geometry_module):
        bridge = types.ModuleType("qgis_render_bridge")
        bridge.geometry = geometry_module
        monkeypatch.setitem(sys.modules, "qgis_render_bridge", bridge)
        return bridge

    return install


@pytest.fixture
def no_bridge(monkeypatch):
    monkeypatch.setitem(sys.modules, "qgis_render_bridge", None)


class _PybindLikeMany:
    """pybind11 builtin 模拟：无 inspect 签名，声明只在 __doc__ 首行。"""

    def __init__(self, behaviour="aligned"):
        self.__doc__ = (
            "validate_many(self: qgis_render_bridge.geometry.Geometry, "
            "geometries: list[dict]) -> list[list[dict]]"
        )
        self._behaviour = behaviour
        self.calls = 0

    @property
    def __signature__(self):
        raise ValueError("no signature found for builtin")

    def __call__(self, geometries):
        self.calls += 1
        return [[] for _ in geometries]


# ----------------------------------------------------------------- tests ----

def test_batch_bridge_single_call_for_many_records(install_bridge):
    geometry, state = _fake_geometry_module(with_many=True)
    install_bridge(geometry)

    issues = TopologyService().validate_records("l1", _records(50))

    assert state["many_calls"] == 1      # N 次跨语言往返 → 1 次
    assert state["validate_calls"] == 0  # 逐要素路径完全未用
    assert len([i for i in issues if i["feature_id"] == "f0"]) == 1  # bow-tie found
    assert all(i["layer_id"] == "l1" for i in issues)


def test_batch_and_per_feature_paths_issue_identical_results(install_bridge):
    geometry_many, _ = _fake_geometry_module(with_many=True)
    install_bridge(geometry_many)
    batched = TopologyService().validate_records("l1", _records(30))

    geometry_single, _ = _fake_geometry_module(with_many=False)
    install_bridge(geometry_single)
    looped = TopologyService().validate_records("l1", _records(30))

    assert batched == looped  # 同输入同判词（含顺序、ring 消息、feature_id）


def test_batch_result_shape_mismatch_falls_back(install_bridge, caplog):
    geometry, state = _fake_geometry_module(with_many=True, many_behaviour="short")
    install_bridge(geometry)

    issues = TopologyService().validate_records("l1", _records(20))

    # 批量形状不符 → 一次警告 + 整批回退 Shapely（不走逐要素桥重试）。
    assert state["many_calls"] == 1
    assert state["validate_calls"] == 0
    assert any("批量" in record.message for record in caplog.records)
    assert len([i for i in issues if i["feature_id"] == "f0"]) == 1  # bow-tie still found


def test_batch_result_not_a_list_falls_back(install_bridge):
    geometry, state = _fake_geometry_module(with_many=True, many_behaviour="not_list")
    install_bridge(geometry)

    issues = TopologyService().validate_records("l1", _records(20))

    assert state["many_calls"] == 1
    assert len([i for i in issues if i["feature_id"] == "f0"]) == 1


def test_batch_exception_falls_back_with_single_warning(install_bridge, caplog):
    geometry, state = _fake_geometry_module(with_many=True, many_behaviour="raise")
    install_bridge(geometry)

    issues = TopologyService().validate_records("l1", _records(20))

    assert state["many_calls"] == 1
    warnings = [r for r in caplog.records if "批量" in r.message]
    assert len(warnings) == 1  # P2-6：只报一次
    assert len([i for i in issues if i["feature_id"] == "f0"]) == 1


def test_legacy_bridge_without_batch_keeps_per_record_path(install_bridge):
    geometry, state = _fake_geometry_module(with_many=False)
    install_bridge(geometry)

    issues = TopologyService().validate_records("l1", _records(50))

    assert state["many_calls"] == 0
    assert state["validate_calls"] == 50  # BASE 行为：N 次往返
    assert len([i for i in issues if i["feature_id"] == "f0"]) == 1


def test_probe_rejects_validate_many_without_geometries_param(install_bridge):
    geometry = types.ModuleType("qgis_render_bridge.geometry")
    geometry.validate = lambda geometry: (
        [{"message": "Self-intersection"}]
        if (geometry.get("coordinates") or [[]])[0][1]
        == [(geometry["coordinates"][0][0][0] + 30), (geometry["coordinates"][0][0][1] + 30)]
        else []
    )
    many_calls = {"count": 0}

    def wrong_param_name(items):  # 参数名不是 geometries
        many_calls["count"] += 1
        return [[] for _ in items]

    geometry.validate_many = wrong_param_name
    install_bridge(geometry)

    issues = TopologyService().validate_records("l1", _records(10))

    # 探针拒绝（参数名不符）→ 批量从未被调用，逐要素路径照常工作。
    assert many_calls["count"] == 0
    assert len([i for i in issues if i["feature_id"] == "f0"]) == 1
    assert TopologyService._bridge_validate_many_fn() is None


def test_probe_accepts_pybind_doc_style_declaration(install_bridge):
    geometry = types.ModuleType("qgis_render_bridge.geometry")
    pybind_like = _PybindLikeMany()
    geometry.validate = lambda geometry: []
    geometry.validate_many = pybind_like
    install_bridge(geometry)

    issues = TopologyService().validate_records("l1", _records(10))

    assert pybind_like.calls == 1  # doc 声明命中 → 批量路径启用
    assert issues == []


def test_no_bridge_no_shapely_reports_validator_unavailable(no_bridge, monkeypatch):
    monkeypatch.setitem(sys.modules, "shapely", None)
    monkeypatch.setitem(sys.modules, "shapely.geometry", None)
    monkeypatch.setitem(sys.modules, "shapely.validation", None)

    issues = TopologyService().validate_records("l1", _records(5))

    assert len(issues) == 1
    assert issues[0]["code"] == "validator_unavailable"


def test_unclosed_ring_message_order_unchanged_in_batch_path(install_bridge):
    geometry, _ = _fake_geometry_module(with_many=True)
    install_bridge(geometry)

    unclosed = {
        "feature_id": "u1",
        "geometry": {"type": "Polygon", "coordinates": [
            [[0.0, 0.0], [30.0, 0.0], [30.0, 30.0], [0.1, 0.1]],  # 未闭合且缺第 4 点
        ]},
    }
    issues = TopologyService().validate_records("l1", [unclosed])

    # ring-closure 消息仍在（纯 Python 侧），且 feature_id 正确归属。
    assert [i["message"] for i in issues] == ["polygon ring 0 is not closed"]
    assert issues[0]["feature_id"] == "u1"


def test_real_bridge_without_batch_uses_fallback():
    """本机预构建桥（BASE，无 validate_many）→ 探针 None，逐要素路径照常。

    无桥环境自动跳过；该用例在「有 BASE 版预构建 .so + PYTHONPATH」的
    机器上给出真桥回退路径的实测证据（见 03-verification.md）。
    """
    try:
        import qgis_render_bridge as native  # noqa: F401
    except ImportError:
        pytest.skip("qgis_render_bridge not importable in this environment")

    probe = TopologyService._bridge_validate_many_fn()
    assert probe is None  # BASE 桥没有 validate_many（hasattr 实测为 False）

    bowtie = _record(0)
    issues = TopologyService().validate_records("l1", [bowtie])
    assert any(i["feature_id"] == "f0" for i in issues)  # 真桥 GEOS 判词照常工作
