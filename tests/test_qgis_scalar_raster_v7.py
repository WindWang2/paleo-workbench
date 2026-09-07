"""v7 §5/§9 bridge tests — scalar raster mirrors, renderer XML codec,
canvas feature-delta channel.  QGIS-marked: skip without the bridge
(built locally via PALEO_WITH_QGIS_RENDERER; see tests/qgis_support.py).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from tests.qgis_support import require_qgis  # noqa: E402

native = require_qgis()

_GRID = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)


def _gdal() -> bool:
    try:
        from osgeo import gdal  # noqa: F401

        return True
    except ImportError:
        return False


def _write_tif(path, grid=_GRID, extent=(0.0, 0.0, 2.0, 2.0)):
    from osgeo import gdal, osr

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(path, grid.shape[1], grid.shape[0], 1,
                            gdal.GDT_Float32)
    xmin, ymin, xmax, ymax = extent
    dataset.SetGeoTransform(
        (xmin, (xmax - xmin) / grid.shape[1], 0.0,
         ymax, 0.0, -(ymax - ymin) / grid.shape[0]))
    reference = osr.SpatialReference()
    reference.ImportFromEPSG(32650)
    dataset.SetProjection(reference.ExportToWkt())
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(float("nan"))
    band.WriteArray(grid)
    dataset.FlushCache()
    dataset = None
    return path


@pytest.fixture()
def stack(qapp, tmp_path):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s, tmp_path
    s.shutdown()


# ---------------------------------------------------------------------------
# Renderer XML codec


def test_build_scalar_renderer_xml_roundtrip():
    payload = {
        "ramp_name": "viridis",
        "mode": "continuous",
        "min": 0.0,
        "max": 10.0,
        "items": [
            {"value": 0.0, "color": "#440154", "label": "0.0"},
            {"value": 5.0, "color": "#21918c", "label": "5.0"},
            {"value": 10.0, "color": "#fde725", "label": "10.0"},
        ],
        "opacity": 1.0,
        "nodata_transparent": True,
    }
    xml = native.build_scalar_renderer_xml(json.dumps(payload))
    assert "rasterrenderer" in xml
    info = native.raster_renderer_info(xml)
    assert info is not None
    assert info["type"] == "singlebandpseudocolor"
    assert int(info["item_count"]) == 3


def test_build_scalar_renderer_xml_rejects_bad_payload():
    with pytest.raises(Exception):
        native.build_scalar_renderer_xml("{not json")
    with pytest.raises(Exception):
        native.build_scalar_renderer_xml(json.dumps({"mode": "continuous"}))


# ---------------------------------------------------------------------------
# Raster mirror upsert (mapstack)


@pytest.mark.skipif(not _gdal(), reason="requires osgeo.gdal")
def test_upsert_raster_mirror_layer_lifecycle(stack):
    s, tmp_path = stack
    tif = _write_tif(str(tmp_path / "factor.tif"))
    payload = {
        "ramp_name": "viridis", "mode": "continuous", "min": 0.0, "max": 3.0,
        "items": [
            {"value": 0.0, "color": "#440154", "label": "0"},
            {"value": 1.5, "color": "#21918c", "label": "1.5"},
            {"value": 3.0, "color": "#fde725", "label": "3"},
        ],
        "opacity": 1.0, "nodata_transparent": True,
    }
    renderer_xml = native.build_scalar_renderer_xml(json.dumps(payload))
    qid = s.upsert_raster_mirror_layer(
        "factor-1", "砂地比", tif, "EPSG:32650", renderer_xml, True, 1.0)
    assert qid
    assert s.project_layer_count() == 1
    # style-only change: same layer object, renderer reapplied
    payload2 = dict(payload, min=0.0, max=6.0)
    renderer_xml2 = native.build_scalar_renderer_xml(json.dumps(payload2))
    qid2 = s.upsert_raster_mirror_layer(
        "factor-1", "砂度比(改)", tif, "EPSG:32650", renderer_xml2, True, 0.8)
    assert qid2 == qid
    # visibility + order participate like vector mirrors
    s.set_mirror_layer_visibility("factor-1", False)
    assert s.mirror_layer_visibility("factor-1") is False
    s.set_mirror_layer_opacity("factor-1", 0.5)
    # project XML envelope round-trips the raster renderer
    xml = s.write_project_xml()
    s.set_mirror_layer_visibility("factor-1", True)
    applied = s.apply_project_xml(xml)
    assert applied >= 1
    assert s.mirror_layer_visibility("factor-1") is False


@pytest.mark.skipif(not _gdal(), reason="requires osgeo.gdal")
def test_upsert_raster_mirror_rejects_bad_renderer(stack):
    s, tmp_path = stack
    tif = _write_tif(str(tmp_path / "factor.tif"))
    with pytest.raises(Exception):
        s.upsert_raster_mirror_layer(
            "factor-bad", "x", tif, "", "<not-raster-xml/>", True, 1.0)


# ---------------------------------------------------------------------------
# Canvas feature-delta channel (§9)


_FC3 = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
         "properties": {"__pwb_fid": "a", "name": "a"}},
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
         "properties": {"__pwb_fid": "b", "name": "b"}},
    ],
}


def _fc(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def test_mirror_delta_applies_in_place(stack):
    s, _ = stack
    s.upsert_mirror_layer("doc", "层", "Point", "EPSG:4326", _fc(*_FC3["features"]),
                          "", "", "", True, 1.0, data_revision=1)
    delta = json.dumps({
        "base_revision": 1,
        "changed": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [9.0, 9.0]},
             "properties": {"__pwb_fid": "b", "name": "b-moved"}},
        ],
        "removed_ids": ["a"],
    })
    # delta rides the call; the full collection stays the fallback payload
    s.upsert_mirror_layer("doc", "层", "Point", "EPSG:4326",
                          _fc(*_FC3["features"][1:], _FC3["features"][:1]),
                          "", "", "", True, 1.0,
                          data_revision=2, delta=delta)
    snapshot = json.loads(s.tree_snapshot_json())
    # layer count unchanged (one mirror) — delta did not rebuild the tree
    assert s.project_layer_count() == 1


def test_mirror_delta_stale_base_falls_back(stack):
    s, _ = stack
    s.upsert_mirror_layer("doc", "层", "Point", "EPSG:4326", _fc(*_FC3["features"]),
                          "", "", "", True, 1.0, data_revision=1)
    delta = json.dumps({"base_revision": 99, "changed": [], "removed_ids": ["a"]})
    # mismatched base: full collection applies (no error, layer intact)
    s.upsert_mirror_layer("doc", "层", "Point", "EPSG:4326", _fc(*_FC3["features"]),
                          "", "", "", True, 1.0, data_revision=2, delta=delta)
    assert s.project_layer_count() == 1


# ---------------------------------------------------------------------------
# Offscreen scalar DATA path (render actual pixels through the new renderer)


@pytest.mark.skipif(not _gdal(), reason="requires osgeo.gdal")
def test_offscreen_scalar_data_render(qapp, tmp_path):
    from qgis_render_bridge import QgisRenderBridge

    tif = _write_tif(str(tmp_path / "scalar.tif"))
    payload = {
        "ramp_name": "viridis", "mode": "continuous", "min": 0.0, "max": 3.0,
        "items": [
            {"value": 0.0, "color": "#440154", "label": "0"},
            {"value": 3.0, "color": "#fde725", "label": "3"},
        ],
        "opacity": 1.0, "nodata_transparent": True,
    }
    bridge = QgisRenderBridge()
    bridge.initialize()
    try:
        bridge.set_layer_snapshot(
            [{
                "id": "scalar-1", "name": "factor", "crs": "EPSG:32650",
                "kind": "raster", "source_path": tif,
                "raster_renderer_xml": native.build_scalar_renderer_xml(
                    json.dumps(payload)),
                "data_revision": 1, "style_revision": 1,
                "visible": True, "opacity": 1.0, "features": [],
            }],
            "EPSG:32650",
        )
        frame = bridge.render_sync((0.0, 0.0, 2.0, 2.0), 64, 64, 96.0)
        assert frame and frame.get("width") == 64
        rgba = frame["rgba"]
        # ramp end colours must appear (bottom-left cool purple family,
        # top-right warm yellow family) — not an all-grey broken render
        assert len(set(rgba[::97])) > 8
    finally:
        bridge.shutdown()


@pytest.mark.skipif(not _gdal(), reason="requires osgeo.gdal")
def test_offscreen_scalar_style_change_reuses_mirror(qapp, tmp_path):
    from qgis_render_bridge import QgisRenderBridge

    tif = _write_tif(str(tmp_path / "scalar.tif"))
    payload = {
        "ramp_name": "viridis", "mode": "continuous", "min": 0.0, "max": 3.0,
        "items": [
            {"value": 0.0, "color": "#000000", "label": "0"},
            {"value": 3.0, "color": "#ffffff", "label": "3"},
        ],
        "opacity": 1.0, "nodata_transparent": True,
    }
    bridge = QgisRenderBridge()
    bridge.initialize()
    try:
        base = {
            "id": "scalar-1", "name": "factor", "crs": "EPSG:32650",
            "kind": "raster", "source_path": tif,
            "data_revision": 1, "style_revision": 1,
            "visible": True, "opacity": 1.0, "features": [],
        }
        bridge.set_layer_snapshot(
            [dict(base, raster_renderer_xml=native.build_scalar_renderer_xml(
                json.dumps(payload)))], "EPSG:32650")
        before = bridge.diagnostics()
        bridge.set_layer_snapshot(
            [dict(base, style_revision=2,
                  raster_renderer_xml=native.build_scalar_renderer_xml(
                      json.dumps(dict(payload, max=6.0))))],
            "EPSG:32650")
        after = bridge.diagnostics()
        assert after["mirror_reuses"] == before["mirror_reuses"] + 1
        assert after["mirror_builds"] == before["mirror_builds"]
        assert after["style_reapplies"] >= before["style_reapplies"] + 1
    finally:
        bridge.shutdown()
