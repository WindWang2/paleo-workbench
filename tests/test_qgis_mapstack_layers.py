"""M1 Task 4: GeoJSON 图层镜像进 QgsProject，画布渲染出要素像素。"""
import pytest

pytest.importorskip("PySide6")

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
    qtbot.waitUntil(lambda: True, timeout=100)  # 让事件循环驱动一帧

    # 中心点要素已渲染：画布中央像素不是纯白。
    from PySide6.QtGui import QImage
    image = host.canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    center = image.pixelColor(320, 240)
    assert (center.red(), center.green(), center.blue()) != (255, 255, 255)

    stack.set_layer_visibility(layer_id, False)
    stack.refresh_canvas(host.canvas_address)
    assert stack.remove_layer(layer_id)
    assert stack.project_layer_count() == 0
