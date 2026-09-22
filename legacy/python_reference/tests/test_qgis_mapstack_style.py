"""Style persistence across re-mirror — reproduces图层点击变色."""

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_POLYGON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
            "properties": {},
        }
    ],
}


def _is_red(color):
    return color.red() > 200 and color.green() < 80 and color.blue() < 80


@pytest.fixture()
def shim_stack(qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

    shim = QgisCanvasShim()
    yield shim
    try:
        shim.shutdown()
    except Exception:
        pass


def _snapshot_with_style(style_dict):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot

    layer = MapLayerSnapshot(
        id="l1",
        name="L1",
        layer_type="vector",
        extent=(0, 0, 10, 10),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=(
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}, "properties": {}},
        ),
        style=style_dict,
        visible=True,
        opacity=1.0,
    )
    return MapRenderSnapshot(project_crs="EPSG:4326", layers=(layer,))


def test_legacy_style_persists_across_remirror(qapp, qtbot, shim_stack):
    from PySide6.QtGui import QImage

    shim = shim_stack
    qtbot.addWidget(shim)
    shim.resize(200, 200)
    shim.show()
    qtbot.waitExposed(shim)

    style = {"fill": "#ff0000", "stroke": "#ff0000", "stroke_width": 1.0}
    snap = _snapshot_with_style(style)
    shim.set_layer_snapshot(snap)
    shim.stack.set_canvas_extent(shim.canvas_address, 0, 0, 10, 10)
    shim.stack.refresh_canvas(shim.canvas_address)
    qtbot.wait(150)

    img = shim.canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)
    c = img.pixelColor(100, 100)
    assert _is_red(c), f"first paint not red: {c.red()},{c.green()},{c.blue()}"

    shim.set_layer_snapshot(snap)
    shim.stack.refresh_canvas(shim.canvas_address)
    qtbot.wait(150)
    img2 = shim.canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)
    c2 = img2.pixelColor(100, 100)
    assert _is_red(c2), f"second paint not red (randomized): {c2.red()},{c2.green()},{c2.blue()}"


def test_qgis_style_persists_across_remirror(qapp, qtbot, shim_stack):
    from PySide6.QtGui import QImage

    try:
        import qgis_render_bridge
    except ImportError:
        pytest.skip("qgis_render_bridge not built")

    xml = qgis_render_bridge.legacy_style_to_renderer_xml(
        {"fill": "#ff0000", "stroke": "#ff0000", "stroke_width": 1.0}, "Polygon"
    )
    assert xml, "renderer xml build failed"
    style = {"qgis_style": {"renderer_xml": xml, "labeling_xml": ""}}

    shim = shim_stack
    qtbot.addWidget(shim)
    shim.resize(200, 200)
    shim.show()
    qtbot.waitExposed(shim)

    snap = _snapshot_with_style(style)
    shim.set_layer_snapshot(snap)
    shim.stack.set_canvas_extent(shim.canvas_address, 0, 0, 10, 10)
    shim.stack.refresh_canvas(shim.canvas_address)
    qtbot.wait(150)
    img = shim.canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)
    c = img.pixelColor(100, 100)
    assert _is_red(c), f"first qgis paint not red: {c.red()},{c.green()},{c.blue()}"

    shim.set_layer_snapshot(snap)
    shim.stack.refresh_canvas(shim.canvas_address)
    qtbot.wait(150)
    img2 = shim.canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)
    c2 = img2.pixelColor(100, 100)
    assert _is_red(c2), f"second qgis paint not red: {c2.red()},{c2.green()},{c2.blue()}"


def test_invalid_renderer_xml_surfaces(qapp, qtbot, shim_stack):
    shim = shim_stack
    qtbot.addWidget(shim)
    shim.resize(200, 200)
    shim.show()
    qtbot.waitExposed(shim)

    bad_style = {"qgis_style": {"renderer_xml": "<invalid>not a renderer</invalid>", "labeling_xml": ""}}
    snap = _snapshot_with_style(bad_style)
    with pytest.raises(Exception):
        shim.set_layer_snapshot(snap)


def test_qgis_style_non_style_error_swallowed(qapp, qtbot, shim_stack):
    from unittest import mock

    shim = shim_stack
    qtbot.addWidget(shim)
    shim.resize(200, 200)
    shim.show()
    qtbot.waitExposed(shim)

    try:
        import qgis_render_bridge
    except ImportError:
        pytest.skip("qgis_render_bridge not built")

    xml = qgis_render_bridge.legacy_style_to_renderer_xml(
        {"fill": "#ff0000", "stroke": "#ff0000", "stroke_width": 1.0}, "Polygon"
    )
    assert xml, "renderer xml build failed"
    style = {"qgis_style": {"renderer_xml": xml, "labeling_xml": ""}}
    snap = _snapshot_with_style(style)

    real_stack = shim.stack

    class _FakeStack:
        def __getattr__(self, name):
            return getattr(real_stack, name)

        def add_vector_layer_geojson(self, *a, **kw):
            raise RuntimeError("memory layer creation failed")

    shim.stack = _FakeStack()  # type: ignore[assignment]
    try:
        shim.set_layer_snapshot(snap)
    finally:
        shim.stack = real_stack  # type: ignore[assignment]

    bad_style = {"qgis_style": {"renderer_xml": "<invalid>not a renderer</invalid>", "labeling_xml": ""}}
    snap_bad = _snapshot_with_style(bad_style)
    with pytest.raises(Exception):
        shim.set_layer_snapshot(snap_bad)


def test_mapstack_direct_style_api(qapp, qtbot):
    from qgis_render_bridge.mapstack import QgisMapStack
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost
    from PySide6.QtGui import QImage

    stack = QgisMapStack()
    stack.initialize()
    host = None
    try:
        host = QgisCanvasHost(stack)
        qtbot.addWidget(host)
        host.resize(200, 200)
        host.show()
        qtbot.waitExposed(host)

        # direct add with legacy style
        geojson = json.dumps(_POLYGON)
        layer_id = stack.add_vector_layer_geojson(
            "L1", "Polygon", "EPSG:4326", geojson, "", "", json.dumps({"fill": "#ff0000", "stroke": "#ff0000"})
        )
        assert layer_id
        stack.set_destination_crs(host.canvas_address, "EPSG:4326")
        stack.set_canvas_extent(host.canvas_address, 0, 0, 10, 10)
        stack.refresh_canvas(host.canvas_address)
        qtbot.wait(150)
        img = host.canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)
        assert _is_red(img.pixelColor(100, 100))

        # set_layer_style path
        stack.clear_project_layers()
        layer_id2 = stack.add_vector_layer_geojson("L2", "Polygon", "EPSG:4326", geojson)
        stack.set_layer_style(layer_id2, "", "", {"fill": "#ff0000", "stroke": "#ff0000"})
        stack.refresh_canvas(host.canvas_address)
        qtbot.wait(150)
        img2 = host.canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)
        assert _is_red(img2.pixelColor(100, 100))

        # invalid renderer_xml must throw
        stack.clear_project_layers()
        with pytest.raises(Exception):
            stack.add_vector_layer_geojson("Bad", "Polygon", "EPSG:4326", geojson, "<invalid>", "", "")
    finally:
        if host is not None:
            try:
                host.close()
            except Exception:
                pass
        stack.shutdown()
