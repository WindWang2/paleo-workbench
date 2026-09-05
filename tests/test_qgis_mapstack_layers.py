"""M1 Task 4: GeoJSON 图层镜像进 QgsProject，画布渲染出要素像素。"""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_POINTS = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "A1"}}
  ]
}"""


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_add_mirror_render_remove(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    layer_id = stack.add_vector_layer_geojson("井位", "Point", "EPSG:4326", _POINTS)
    assert layer_id
    assert stack.project_layer_count() == 1

    stack.set_destination_crs(host.canvas_address, "EPSG:4326")
    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 10.0)
    stack.refresh_canvas(host.canvas_address)
    # #1156: refresh is fire-and-forget (no blocking pump) — poll for the
    # frame instead of assuming synchronous pixels.
    from PySide6.QtGui import QImage

    def _center_rgb():
        image = host.canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        pixel = image.pixelColor(320, 240)
        return (pixel.red(), pixel.green(), pixel.blue())

    qtbot.waitUntil(lambda: _center_rgb() != (255, 255, 255), timeout=15_000)

    stack.set_layer_visibility(layer_id, False)
    stack.refresh_canvas(host.canvas_address)
    assert stack.remove_layer(layer_id)
    assert stack.project_layer_count() == 0


def test_geometry_drift_recreates_mirror_not_silently_empties(stack):
    """#1153: same doc_id with a new geometry type rebuilds the mirror."""
    gj_point = '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[1,2]},"properties":{}}]}'
    gj_poly = '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]},"properties":{}}]}'
    first = stack.upsert_mirror_layer("drift", "D", "Point", "EPSG:4326", gj_point, "", "", None)
    assert stack.project_layer_count() == 1
    second = stack.upsert_mirror_layer("drift", "D", "Polygon", "EPSG:4326", gj_poly, "", "", None)
    assert stack.project_layer_count() == 1
    assert second != first  # rebuilt, not reused
    assert stack.mirror_order_top_first() == ["drift"]


def test_partial_add_reports_count_mismatch(stack):
    """#1153: mixed-geometry payloads fail loudly instead of dropping."""
    gj_mixed = (
        '{"type":"FeatureCollection","features":['
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[1,2]},"properties":{}},'
        '{"type":"Feature","geometry":{"type":"LineString","coordinates":[[0,0],[1,1]]},"properties":{}}'
        "]}"
    )
    with pytest.raises(Exception, match="(?i)(partial|failed|mismatch)"):
        stack.upsert_mirror_layer("mixed", "M", "Point", "EPSG:4326", gj_mixed, "", "", None)
