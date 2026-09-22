"""geotopo 双引擎一致性矩阵（阶段三 §F / 计划 03-tdd-test-plan）。

桥 geotopo 原生核 ↔ shapely fallback 对同一数据的契约一致性：面数、
面积多重集、共边弧长、重塑守恒（容差 1e-9）。桥缺席自动跳过。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.qgis


def _bridge_geotopo():
    from paleo_workbench.qgis_runtime import loader

    loader.prepare_bridge_load()
    import qgis_render_bridge as native

    if not hasattr(native, "geotopo"):
        pytest.skip("bridge geotopo submodule missing")
    return native.geotopo


def _fallback_polygonize(lines, tolerance=1e-6):
    """直接驱动 shapely 路径：临时屏蔽桥探测。"""
    from paleo_workbench.mapping import geotopo_service as gt

    saved = gt._BRIDGE_PROBE
    gt._BRIDGE_PROBE = False
    try:
        return gt.polygonize_control_lines(lines, tolerance=tolerance)
    finally:
        gt._BRIDGE_PROBE = saved


def _area_multiset(polygons) -> list[float]:
    return sorted(round(float(p.area), 6) for p in polygons)


CASES = {
    "cross": [
        {"id": "frame", "path": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]},
        {"id": "shore", "path": [[0, 5], [10, 5]]},
        {"id": "boundary", "path": [[5, 0], [5, 10]]},
    ],
    "t": [
        {"id": "frame", "path": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]},
        {"id": "graben", "path": [[5, 0], [5, 10]]},
    ],
    "collinear": [
        {"id": "bottom", "path": [[0, 0], [10, 0]]},
        {"id": "partial", "path": [[4, 0], [10, 0]]},
        {"id": "loop", "path": [[0, 0], [0, 6], [10, 6], [10, 0], [0, 0]]},
    ],
    "grid-10": [
        *[{"id": f"h{i}", "path": [[float(x), float(i)] for x in range(11)]}
          for i in range(11)],
        *[{"id": f"v{i}", "path": [[float(i), float(y)] for y in range(11)]}
          for i in range(11)],
    ],
}


@pytest.mark.xfail(reason="自交 8 字环在框内围出真孔洞：原生核按 04-"
                    "known-limitations 不建模 hole（环形余量以外环近似，"
                    "面积 100 vs shapely 带孔面 82）——本期显式限制非回归",
                    strict=True)
def test_polygonize_parity_figure_eight_hole_approximation():
    """孔洞近似差异的显式钉子：差异恰好等于 8 字环占据面积（18）。"""
    geotopo = _bridge_geotopo()
    lines = [
        {"id": "frame", "path": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]},
        {"id": "fold", "path": [[2, 2], [8, 8], [8, 2], [2, 8], [2, 2]]},
    ]
    native_payload = json.loads(geotopo.polygonize_control_lines(
        json.dumps({"lines": lines})))
    fallback = _fallback_polygonize(lines)
    assert native_areas_equal(native_payload, fallback)


def native_areas_equal(native_payload, fallback) -> bool:
    native_areas = sorted(round(float(p["area"]), 4)
                          for p in native_payload["polygons"])
    fallback_areas = sorted(round(p.area, 4) for p in fallback.polygons)
    return native_areas == fallback_areas


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_polygonize_parity(case):
    geotopo = _bridge_geotopo()
    native_payload = json.loads(geotopo.polygonize_control_lines(
        json.dumps({"lines": case})))
    assert native_payload["status"] == "ok"
    fallback = _fallback_polygonize(case)
    assert len(native_payload["polygons"]) == len(fallback.polygons)
    native_areas = sorted(round(float(p["area"]), 4)
                          for p in native_payload["polygons"])
    fallback_areas = sorted(round(p.area, 4) for p in fallback.polygons)
    assert native_areas == fallback_areas


SQUARE_A = {"type": "Polygon", "coordinates": [[
    [0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]}
SQUARE_B = {"type": "Polygon", "coordinates": [[
    [10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0], [10.0, 0.0]]]}


def test_shared_arcs_parity():
    geotopo = _bridge_geotopo()
    payload = json.loads(geotopo.find_shared_arcs(
        json.dumps(SQUARE_A), json.dumps(SQUARE_B)))
    assert payload["status"] == "ok"
    from paleo_workbench.mapping import geotopo_service as gt

    gt._BRIDGE_PROBE = False
    try:
        arcs = gt.find_shared_arcs(SQUARE_A, SQUARE_B)
    finally:
        gt._BRIDGE_PROBE = None
    assert len(payload["arcs"]) == len(arcs)
    assert [round(a["length"], 6) for a in payload["arcs"]] == [
        round(a.length, 6) for a in arcs]


def test_reshape_conservation_parity():
    geotopo = _bridge_geotopo()
    curve = [[10.0, 0.0], [15.0, 5.0], [10.0, 10.0]]
    native_payload = json.loads(geotopo.reshape_shared_arc(
        json.dumps(SQUARE_A), json.dumps(SQUARE_B),
        json.dumps([[10.0, 0.0], [10.0, 10.0]]), json.dumps(curve)))
    assert native_payload["status"] == "ok", native_payload
    from paleo_workbench.mapping import geotopo_service as gt

    gt._BRIDGE_PROBE = False
    try:
        fallback = gt.reshape_shared_arc(
            SQUARE_A, SQUARE_B, [[10.0, 0.0], [10.0, 10.0]], curve)
    finally:
        gt._BRIDGE_PROBE = None
    assert native_payload["area_before"] == pytest.approx(fallback.area_before)
    assert native_payload["area_after"] == pytest.approx(fallback.area_after)
    assert abs(native_payload["area_residual"]) < 1e-9
    assert abs(fallback.area_residual) < 1e-9
