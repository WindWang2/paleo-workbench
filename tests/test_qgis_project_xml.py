# -*- coding: utf-8 -*-
"""M5: QgsProject XML 写出/按 pwb/doc_id 套用呈现态，不替换要素。"""
import json

import pytest

pytest.importorskip("PySide6")
from tests.qgis_support import QGIS_SKIP_REASON

pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)
pytestmark = pytest.mark.qgis

_GEOJSON_A = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
         "properties": {"name": "A"}}
    ],
})
_GEOJSON_B = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
         "properties": {"name": "B"}}
    ],
})


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack
    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_write_project_xml_contains_qgis_and_doc_id(stack):
    stack.upsert_mirror_layer(
        "doc-a", "LayerA", "Point", "EPSG:4326", _GEOJSON_A,
        visible=True, opacity=1.0,
    )
    xml = stack.write_project_xml()
    assert "<qgis" in xml
    assert "doc-a" in xml


def test_apply_project_xml_restores_visibility_opacity_order(stack):
    stack.upsert_mirror_layer(
        "doc-a", "LayerA", "Point", "EPSG:4326", _GEOJSON_A,
        visible=True, opacity=1.0,
    )
    stack.upsert_mirror_layer(
        "doc-b", "LayerB", "Point", "EPSG:4326", _GEOJSON_B,
        visible=True, opacity=1.0,
    )
    stack.set_mirror_layer_order(["doc-b", "doc-a"])
    stack.set_mirror_layer_visibility("doc-a", False)
    stack.set_mirror_layer_opacity("doc-b", 0.4)
    xml = stack.write_project_xml()

    stack.remove_mirror_layers_except([])
    stack.upsert_mirror_layer(
        "doc-a", "LayerA", "Point", "EPSG:4326", _GEOJSON_A,
        visible=True, opacity=1.0,
    )
    stack.upsert_mirror_layer(
        "doc-b", "LayerB", "Point", "EPSG:4326", _GEOJSON_B,
        visible=True, opacity=1.0,
    )
    applied = stack.apply_project_xml(xml)
    assert applied == 2
    assert stack.mirror_order_top_first()[0] == "doc-b"
    assert stack.mirror_layer_visibility("doc-a") is False


def test_apply_empty_xml_is_noop(stack):
    assert stack.apply_project_xml("") == 0


def test_apply_garbage_xml_raises(stack):
    with pytest.raises(RuntimeError):
        stack.apply_project_xml("not-xml<<<")
