# -*- coding: utf-8 -*-
import json
import pytest
pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_GEO_POINTS = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "P1"}}]}
_GEO_POLY = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[
        [4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0], [4.0, 4.0]]]},
     "properties": {"name": "P1"}}]}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack
    s = QgisMapStack(); s.initialize(); yield s; s.shutdown()


def _show(qtbot, canvas):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    w = wrapInstance(canvas, QWidget)
    qtbot.addWidget(w); w.resize(400, 400); w.show()


@pytest.mark.parametrize("geom,geojson", [("point", _GEO_POINTS), ("polygon", _GEO_POLY)])
def test_snap_matches(qtbot, stack, geom, geojson):
    canvas = stack.create_canvas()
    _show(qtbot, canvas)
    stack.upsert_mirror_layer("doc", "d", geom, "EPSG:4326",
                              json.dumps(geojson), "", "", "", True, 1.0)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    stack.set_snapping_config(canvas, json.dumps({
        "enabled": True, "mode": "all_layers",
        "tolerance_px": 20.0, "types": ["vertex"]}))
    result = stack.snap_to_map(canvas, 4.9, 5.1)
    print("\ngeom:", geom, "matched:", result["matched"])
    assert result["matched"] is True
