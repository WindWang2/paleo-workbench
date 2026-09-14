"""相带共有边界联动平滑重塑（geotopo Ticket 3）。

契约：docs/development/geotopo-editor/02-interface-contracts.md §1.2/§1.3。
宿主 facade（shapely fallback / 桥优先）+ 真桥镜像层重塑。
核心不变式：重塑后两面面积之和守恒、无重叠（overlap=0）、无裂隙。
"""
from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping import geotopo_service as gt

SQUARE_A = {"type": "Polygon", "coordinates": [[
    [0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]}
SQUARE_B = {"type": "Polygon", "coordinates": [[
    [10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0], [10.0, 0.0]]]}
SHARED_EDGE = [[10.0, 0.0], [10.0, 10.0]]


def _shapely(geometry: dict):
    from shapely.geometry import shape

    return shape(geometry)


def _area(geometry: dict) -> float:
    return abs(_shapely(geometry).area)


def test_find_shared_arcs_reports_the_shared_chain():
    arcs = gt.find_shared_arcs(SQUARE_A, SQUARE_B)
    assert len(arcs) == 1
    arc = arcs[0]
    assert arc.length == pytest.approx(10.0)
    assert [round(v, 6) for v in arc.start] == [10.0, 0.0]
    assert [round(v, 6) for v in arc.end] == [10.0, 10.0]


def test_reshape_conserves_total_area_without_gap_or_overlap():
    curve = [[10.0, 0.0], [15.0, 5.0], [10.0, 10.0]]  # 向 B 侧凸出
    result = gt.reshape_shared_arc(SQUARE_A, SQUARE_B, SHARED_EDGE, curve)
    total_before = _area(SQUARE_A) + _area(SQUARE_B)
    total_after = _area(result.polygon_a) + _area(result.polygon_b)
    assert total_after == pytest.approx(total_before, rel=1e-9)
    assert result.area_residual == pytest.approx(0.0, abs=1e-9)
    geom_a = _shapely(result.polygon_a)
    geom_b = _shapely(result.polygon_b)
    assert geom_a.is_valid and geom_b.is_valid
    assert geom_a.intersection(geom_b).area == pytest.approx(0.0, abs=1e-9)
    union = geom_a.union(geom_b)
    assert union.area == pytest.approx(200.0, rel=1e-9)  # 无裂隙
    assert geom_a.area == pytest.approx(125.0)  # 凸出部分划归 A
    assert geom_b.area == pytest.approx(75.0)


def test_reshape_unmatched_arc_is_rejected_with_contract_code():
    wrong_arc = [[4.0, 0.0], [4.0, 10.0]]  # 不在任何共享位置
    with pytest.raises(gt.GeoTopoError) as err:
        gt.reshape_shared_arc(SQUARE_A, SQUARE_B, wrong_arc,
                              [[4.0, 0.0], [6.0, 5.0], [4.0, 10.0]])
    assert err.value.code == "PWB-GT-201"


def test_reshape_self_intersecting_curve_is_rejected():
    # 曲线自交（8 字形穿越共享边）→ 新环非法。
    bad_curve = [[10.0, 0.0], [14.0, 5.0], [6.0, 5.0], [14.0, 5.0], [10.0, 10.0]]
    with pytest.raises(gt.GeoTopoError) as err:
        gt.reshape_shared_arc(SQUARE_A, SQUARE_B, SHARED_EDGE, bad_curve)
    assert err.value.code in ("PWB-GT-202", "PWB-GT-203")


def test_reshape_crossing_curve_is_rejected_as_overlap():
    # 新曲线越出 B 的外边界再折回 → 与 B 剩余环重叠。
    crossing = [[10.0, 0.0], [30.0, 5.0], [10.0, 10.0]]
    with pytest.raises(gt.GeoTopoError) as err:
        gt.reshape_shared_arc(SQUARE_A, SQUARE_B, SHARED_EDGE, crossing)
    assert err.value.code in ("PWB-GT-202", "PWB-GT-203")


def test_enclave_pair_reports_both_shared_arcs():
    # C 形 A 与补块 B：共享边界是一条连续三边链（底+右+左），非两段。
    c_shape = {"type": "Polygon", "coordinates": [[
        [0.0, 0.0], [20.0, 0.0], [20.0, 10.0], [13.0, 10.0], [13.0, 4.0],
        [7.0, 4.0], [7.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]}
    plug = {"type": "Polygon", "coordinates": [[
        [7.0, 4.0], [13.0, 4.0], [13.0, 10.0], [7.0, 10.0], [7.0, 4.0]]]}
    arcs = gt.find_shared_arcs(c_shape, plug)
    assert len(arcs) == 1
    assert arcs[0].length == pytest.approx(18.0)  # 6 + 6 + 6
    # 重塑可针对极大链的任意子链（这里只重塑底边 y=4）。
    result = gt.reshape_shared_arc(
        c_shape, plug, [[7.0, 4.0], [13.0, 4.0]],
        [[7.0, 4.0], [10.0, 7.0], [13.0, 4.0]])
    total = _area(c_shape) + _area(plug)
    assert _area(result.polygon_a) + _area(result.polygon_b) == pytest.approx(total, rel=1e-9)


def test_smooth_curve_keeps_area_conservation():
    curve = gt.smooth_curve([[10.0, 0.0], [12.0, 4.0], [10.0, 10.0]])
    assert len(curve) > 3  # Catmull-Rom 过采样
    result = gt.reshape_shared_arc(SQUARE_A, SQUARE_B, SHARED_EDGE, curve)
    total = _area(SQUARE_A) + _area(SQUARE_B)
    assert _area(result.polygon_a) + _area(result.polygon_b) == pytest.approx(total, rel=1e-9)


# ---------------------------------------------------------------------------
# 真桥面：geotopo 子模块纯函数 parity + 镜像层联动重塑。


@pytest.mark.qgis
class TestNativeReshape:
    def _bridge(self):
        from paleo_workbench.qgis_runtime import loader

        loader.prepare_bridge_load()
        import qgis_render_bridge as native

        assert hasattr(native, "geotopo")
        return native.geotopo

    def test_bridge_find_shared_arcs_matches_fallback(self):
        geotopo = self._bridge()
        payload = json.loads(geotopo.find_shared_arcs(
            json.dumps(SQUARE_A), json.dumps(SQUARE_B)))
        assert payload["status"] == "ok"
        assert len(payload["arcs"]) == 1
        assert payload["arcs"][0]["length"] == pytest.approx(10.0)

    def test_bridge_reshape_envelope_and_conservation(self):
        geotopo = self._bridge()
        payload = json.loads(geotopo.reshape_shared_arc(
            json.dumps(SQUARE_A), json.dumps(SQUARE_B),
            json.dumps(SHARED_EDGE),
            json.dumps([[10.0, 0.0], [15.0, 5.0], [10.0, 10.0]])))
        assert payload["status"] == "ok", payload
        assert payload["area_before"] == pytest.approx(200.0)
        assert payload["area_after"] == pytest.approx(200.0)
        assert abs(payload["area_residual"]) < 1e-9
        a = _shapely(payload["polygon_a"])
        b = _shapely(payload["polygon_b"])
        assert a.area == pytest.approx(125.0)
        assert b.area == pytest.approx(75.0)
        assert a.intersection(b).area == pytest.approx(0.0, abs=1e-9)

    def test_bridge_unmatched_arc_error_code(self):
        geotopo = self._bridge()
        payload = json.loads(geotopo.reshape_shared_arc(
            json.dumps(SQUARE_A), json.dumps(SQUARE_B),
            json.dumps([[4.0, 0.0], [4.0, 10.0]]),
            json.dumps([[4.0, 0.0], [6.0, 5.0], [4.0, 10.0]])))
        assert payload["status"] == "error"
        assert payload["code"] == "PWB-GT-201"

    def test_mirror_reshape_updates_both_features_and_undo_restores(self, qtbot, qapp):
        from PySide6.QtWidgets import QGraphicsView
        from shiboken6 import wrapInstance

        from qgis_render_bridge.mapstack import QgisMapStack

        stack = QgisMapStack()
        stack.initialize()
        try:
            fc = {"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": SQUARE_A,
                 "properties": {"__pwb_fid": "fa", "facies": "滨岸"}},
                {"type": "Feature",
                 "geometry": SQUARE_B,
                 "properties": {"__pwb_fid": "fb", "facies": "陆棚"}},
            ]}
            fields = json.dumps([{"name": "facies", "type": "QString"}])
            stack.upsert_mirror_layer("doc-poly", "相带", "Polygon", "EPSG:4326",
                                      json.dumps(fc), "", "", "",
                                      True, 1.0,
                                      is_reference=False, is_editable=True,
                                      data_revision=1, fields_json=fields)
            assert stack.start_mirror_layer_editing("doc-poly") == ""
            canvas = stack.create_canvas()
            view = wrapInstance(canvas, QGraphicsView)
            qtbot.addWidget(view)
            view.resize(400, 400)
            view.show()
            events: list[tuple[str, dict]] = []
            stack.set_edit_pick_callback(
                canvas, lambda action, payload: events.append(
                    (action, json.loads(payload))))

            error = stack.reshape_mirror_shared_boundary(
                "doc-poly", "doc-poly", "fa", "fb",
                json.dumps(SHARED_EDGE),
                json.dumps([[10.0, 0.0], [15.0, 5.0], [10.0, 10.0]]))
            assert error == "", error

            payload = json.loads(stack.mirror_features_json("doc-poly", 0))
            rings = {f["id"]: f["geometry"]["coordinates"][0]
                     for f in payload["features"]}
            areas = sorted(
                abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1]
                        - ring[(i + 1) % len(ring)][0] * ring[i][1]
                        for i in range(len(ring))) / 2)
                for ring in rings.values())
            assert areas[0] == pytest.approx(75.0)
            assert areas[1] == pytest.approx(125.0)
            gestures = [p for a, p in events if a == "edit_gesture"]
            assert gestures and gestures[-1]["gesture"] == "boundary_reshape"
            assert "doc-poly" in gestures[-1]["layers"]

            assert stack.undo_mirror_edit("doc-poly") == ""
            payload = json.loads(stack.mirror_features_json("doc-poly", 0))
            rings = {f["id"]: f["geometry"]["coordinates"][0]
                     for f in payload["features"]}
            areas = sorted(
                abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1]
                        - ring[(i + 1) % len(ring)][0] * ring[i][1]
                        for i in range(len(ring))) / 2)
                for ring in rings.values())
            assert areas == [pytest.approx(100.0), pytest.approx(100.0)]
        finally:
            stack.shutdown()

    def test_mirror_reshape_scatters_topological_points(self, qtbot, qapp):
        """3.8：重塑曲线顶点散布到关联线层（addTopologicalPoints 同族）。"""
        from PySide6.QtWidgets import QGraphicsView
        from shiboken6 import wrapInstance

        from qgis_render_bridge.mapstack import QgisMapStack

        stack = QgisMapStack()
        stack.initialize()
        try:
            fc = {"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": SQUARE_A,
                 "properties": {"__pwb_fid": "fa"}},
                {"type": "Feature",
                 "geometry": SQUARE_B,
                 "properties": {"__pwb_fid": "fb"}},
            ]}
            fields = json.dumps([{"name": "facies", "type": "QString"}])
            stack.upsert_mirror_layer("doc-poly", "相带", "Polygon", "EPSG:4326",
                                      json.dumps(fc), "", "", "",
                                      True, 1.0,
                                      is_reference=False, is_editable=True,
                                      data_revision=1, fields_json=fields)
            # 关联线层：一条穿越凸出区域的对角界线（同 CRS、可编辑）——
            # addTopologicalPoints 只把"落在既有线段上"的点插入线层。
            line_fc = {"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": {"type": "LineString",
                              "coordinates": [[10.0, 0.0], [20.0, 10.0]]},
                 "properties": {"__pwb_fid": "edge"}},
            ]}
            stack.upsert_mirror_layer("doc-lines", "界线", "LineString", "EPSG:4326",
                                      json.dumps(line_fc), "", "", "",
                                      True, 1.0,
                                      is_reference=False, is_editable=True,
                                      data_revision=1)
            assert stack.start_mirror_layer_editing("doc-poly") == ""
            assert stack.start_mirror_layer_editing("doc-lines") == ""
            canvas = stack.create_canvas()
            view = wrapInstance(canvas, QGraphicsView)
            qtbot.addWidget(view)
            view.resize(400, 400)
            view.show()

            curve_points = [[10.0, 0.0], [12.5, 2.5], [15.0, 5.0], [12.5, 7.5], [10.0, 10.0]]
            error = stack.reshape_mirror_shared_boundary(
                "doc-poly", "doc-poly", "fa", "fb",
                json.dumps(SHARED_EDGE), json.dumps(curve_points))
            assert error == "", error
            payload = json.loads(stack.mirror_features_json("doc-lines", 0))
            line_coords = payload["features"][0]["geometry"]["coordinates"]
            xs = {round(float(x), 6) for x, _y in line_coords}
            # 曲线中间顶点（12.5/15.0）经拓扑点散布进入关联线层。
            assert 12.5 in xs and 15.0 in xs
        finally:
            stack.shutdown()

