"""M11 — professional output: engine parity, GeoPDF, metadata honesty.

Screen/export parity contract: an export whose live canvas ran the QGIS
renderer uses the QGIS renderer, and every fallback is reported in the
export result metadata (decision D2) — never silent. GeoPDF capability is
exercised against the vendored QGIS (decision D10 evidence).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from paleo_workbench.ui.map_export_worker import (
    MapExportSpec,
    render_and_save_map_export,
)


def _spec(path: Path, *, prefer: bool) -> MapExportSpec:
    from paleo_workbench.mapping.map_render_backend import (
        FallbackMapRenderBackend,
    )
    from paleo_workbench.mapping.layers import MapDocument, VectorMapLayer

    layer = VectorMapLayer(
        id="lyr_parity",
        name="井位",
        layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0),
        crs="EPSG:4326",
        features=(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
                "properties": {"name": "W1"},
            },
        ),
    )
    doc = MapDocument(crs="EPSG:4326", extent=(0.0, 0.0, 10.0, 10.0))
    doc.add_layer(layer)
    snapshot = doc.to_snapshot()
    backend = FallbackMapRenderBackend()
    return MapExportSpec(
        snapshot=snapshot,
        extent=(0.0, 0.0, 10.0, 10.0),
        width=400,
        height=300,
        dpi=96.0,
        decorations={},
        path=str(path),
        prefer_native_renderer=prefer,
    )


def test_fallback_export_reports_itself(qapp, tmp_path):
    out = tmp_path / "fallback.png"
    report = render_and_save_map_export(_spec(out, prefer=False))
    assert out.is_file()
    assert report["engine"] == "fallback"
    assert report["degraded"] is True
    assert report["degraded_reason"]
    assert "not requested" in report["degraded_reason"]


def test_qgis_export_reports_qgis_engine(qapp, tmp_path):
    """With the bridge available a preferred-QGIS export runs the QGIS
    renderer and reports the qgis engine (no degradation)."""
    pytest.importorskip("qgis_render_bridge")
    from paleo_workbench.mapping.map_render_backend import qgis_backend_probe

    if not qgis_backend_probe():
        pytest.skip("QGIS backend probe failed in this environment")
    out = tmp_path / "qgis.png"
    report = render_and_save_map_export(_spec(out, prefer=True))
    assert out.is_file()
    assert report["engine"] == "qgis"
    assert report["degraded"] is False


def test_provider_prefers_probe_and_records_renderer(tmp_path):
    """The headless production provider must follow the probe (D2) — the
    hard-coded prefer_native_renderer=False fallback-as-production is gone."""
    import inspect

    from paleo_workbench.providers.builtin import map_export as provider_mod

    source = inspect.getsource(provider_mod)
    assert "prefer_native_renderer=False" not in source
    assert "qgis_backend_probe" in source


_WELLS = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "W1"}}
  ]
}"""


def test_geopdf_capability_is_explicit_never_fake(qtbot, tmp_path):
    """D10 evidence: the vendored QGIS 4.2 exposes writeGeoPdf and the bridge
    wires it, but GeoPDF export FAILS in this offscreen environment
    (PrintError=4) while plain PDF succeeds. The contract under test: the
    attempt is opt-in, a failure is LOUD (exception, no partial file), and a
    success would be a real PDF — a fake GeoPDF can never be written."""
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    stack.initialize()
    try:
        stack.add_vector_layer_geojson(
            "井位", "Point", "EPSG:4326", _WELLS, "", "", ""
        )
        plain_spec = {
            "page": {"width_mm": 297.0, "height_mm": 210.0},
            "items": [
                {
                    "type": "map",
                    "key": "map",
                    "x": 10.0,
                    "y": 10.0,
                    "w": 200.0,
                    "h": 150.0,
                    "crs": "EPSG:4326",
                    "extent": [0.0, 0.0, 10.0, 9.0],
                },
                {"type": "legend", "map_item": "map", "x": 216.0, "y": 10.0,
                 "w": 60.0, "h": 60.0},
            ],
        }
        plain = tmp_path / "plain.pdf"
        payload = json.loads(
            stack.layout_export(json.dumps(plain_spec), str(plain), "pdf", 150.0)
        )
        assert payload["ok"] is True and plain.read_bytes()[:5] == b"%PDF-"

        geo_spec = dict(plain_spec, geo_pdf=True)
        geo = tmp_path / "geo.pdf"
        try:
            result = json.loads(
                stack.layout_export(json.dumps(geo_spec), str(geo), "pdf", 150.0)
            )
            # If GeoPDF ever works here it must be a real PDF page.
            assert result["ok"] is True
            assert geo.read_bytes()[:5] == b"%PDF-"
        except RuntimeError:
            # Environment cannot produce GeoPDF: the failure must be loud and
            # leave no fake artifact behind.
            assert not geo.exists() or geo.read_bytes()[:5] != b"%PDF-"
            pytest.mark.deselect  # documentation marker; test still passes
    finally:
        stack.shutdown()

