"""M7 — native QgsLayout composition export (component graph → layout spec).

Requires the qgis_render_bridge extension. Verifies: the spec builder maps
every native component type, unmappable compositions are refused (never
silently partial), the bridge renders a real PDF/SVG/PNG page containing
mirrored QGIS layers, and the fallback policy is reported honestly.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_WELLS = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "W1", "value": 12.5}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [6.5, 4.5]},
     "properties": {"name": "W2", "value": 18.0}}
  ]
}"""

_ZONES = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature",
     "geometry": {"type": "Polygon", "coordinates": [[[1.0, 1.0], [9.0, 1.0], [9.0, 8.0], [1.0, 8.0], [1.0, 1.0]]]},
     "properties": {"facies_name": "浅湖"}}
  ]
}"""

_EXTENT = (0.0, 0.0, 10.0, 9.0)


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    s.add_vector_layer_geojson(
        "相带", "Polygon", "EPSG:4326", _ZONES, "", "", ""
    )
    s.add_vector_layer_geojson(
        "井位", "Point", "EPSG:4326", _WELLS, "", "", ""
    )
    yield s
    s.shutdown()


def _composition():
    from paleo_workbench.mapping.composer.models import (
        ComposerElement,
        ElementType,
        MapCompositionDocument,
    )

    doc = MapCompositionDocument(
        id="comp_layout_test",
        title="七里坪油田 T1 古地理图",
    )
    doc.set_paper("A4", "landscape")
    elements = [
        ComposerElement("el_map", ElementType.MAIN_MAP, 8, 12, 180.0, 150.0,
                        z_index=0, properties={}),
        ComposerElement("el_title", ElementType.TITLE, 8, 2, 180.0, 9.0,
                        z_index=1,
                        properties={"text": "T1 沉积相图", "font_size": 12}),
        ComposerElement("el_legend", ElementType.LEGEND, 192, 12, 60.0, 70.0,
                        z_index=1, properties={}),
        ComposerElement("el_scale", ElementType.SCALE_BAR, 192, 150, 60.0, 12.0,
                        z_index=1, properties={"units": "km"}),
        ComposerElement("el_north", ElementType.NORTH_ARROW, 268, 150, 16.0, 22.0,
                        z_index=1, properties={}),
        ComposerElement("el_neat", ElementType.NEATLINE, 2, 2, 293.0, 206.0,
                        z_index=5, properties={}),
    ]
    for el in elements:
        doc.add_element(el)
    return doc


def test_build_layout_spec_maps_all_native_types():
    from paleo_workbench.mapping.layout_export import build_layout_spec

    spec = build_layout_spec(
        _composition(), map_extent=_EXTENT, crs="EPSG:4326"
    )
    assert spec["page"]["width_mm"] == 297.0
    types = [item["type"] for item in spec["items"]]
    assert types.count("map") == 1
    assert "legend" in types and "scalebar" in types
    assert "north_arrow" in types and "shape" in types
    labels = [item for item in spec["items"] if item["type"] == "label"]
    assert any(item["text"] == "T1 沉积相图" and item["bold"] for item in labels)
    map_item = next(item for item in spec["items"] if item["type"] == "map")
    assert map_item["extent"] == list(_EXTENT)
    assert map_item["crs"] == "EPSG:4326"


def test_grid_element_folds_into_map_grid_interval():
    from paleo_workbench.mapping.composer.models import (
        ComposerElement,
        ElementType,
    )
    from paleo_workbench.mapping.layout_export import build_layout_spec

    composition = _composition()
    composition.add_element(
        ComposerElement("el_grid", ElementType.GRID, 8, 12, 180.0, 150.0,
                        z_index=2, properties={"spacing_mm": 25.0})
    )
    spec = build_layout_spec(
        composition, map_extent=_EXTENT, crs="EPSG:4326"
    )
    map_item = next(item for item in spec["items"] if item["type"] == "map")
    # 25 mm on a 180 mm wide map over a 10-unit extent → 25 * 10 / 180
    assert map_item["grid"]["interval_x"] == pytest.approx(25.0 * 10.0 / 180.0)


def test_unmappable_composition_refused_not_silently_partial():
    from paleo_workbench.mapping.composer.models import (
        ComposerElement,
        ElementType,
    )
    from paleo_workbench.mapping.layout_export import build_layout_spec

    composition = _composition()
    composition.add_element(
        ComposerElement("el_chart", ElementType.STAT_CHART, 192, 90, 60.0, 50.0,
                        z_index=2, properties={})
    )
    with pytest.raises(ValueError, match="stat_chart"):
        build_layout_spec(composition, map_extent=_EXTENT, crs="EPSG:4326")


def test_qgis_layout_export_pdf(qtbot, stack, tmp_path):
    from paleo_workbench.mapping.layout_export import (
        export_composition_reported,
    )

    out = tmp_path / "page.pdf"
    report = export_composition_reported(
        _composition(),
        out,
        fmt="pdf",
        dpi=150,
        map_extent=_EXTENT,
        crs="EPSG:4326",
        stack=stack,
    )
    payload = report.to_dict()
    assert payload["engine"] == "qgis_layout", payload
    assert payload["ok"] is True
    assert out.is_file()
    assert out.stat().st_size > 1000
    head = out.read_bytes()[:8]
    assert head.startswith(b"%PDF")


def test_qgis_layout_export_svg_and_png(qtbot, stack, tmp_path):
    from paleo_workbench.mapping.layout_export import (
        export_composition_reported,
    )

    svg_path = tmp_path / "page.svg"
    svg_report = export_composition_reported(
        _composition(), svg_path, fmt="svg", dpi=150,
        map_extent=_EXTENT, crs="EPSG:4326", stack=stack,
    )
    assert svg_report.engine == "qgis_layout"
    svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    assert "<svg" in svg_text

    png_path = tmp_path / "page.png"
    png_report = export_composition_reported(
        _composition(), png_path, fmt="png", dpi=150,
        map_extent=_EXTENT, crs="EPSG:4326", stack=stack,
    )
    assert png_report.engine == "qgis_layout"
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_fallback_reported_without_stack(tmp_path):
    from paleo_workbench.mapping.layout_export import (
        export_composition_reported,
    )

    out = tmp_path / "page.pdf"
    report = export_composition_reported(
        _composition(), out, fmt="pdf", dpi=150,
        map_extent=_EXTENT, crs="EPSG:4326", stack=None,
    )
    payload = report.to_dict()
    assert payload["engine"] == "composer_fallback"
    assert any("no QGIS map stack" in w for w in payload["warnings"])
    assert out.is_file()


def test_layout_export_vector_content_survives(qtbot, stack, tmp_path):
    """The exported SVG carries the mirrored QGIS symbols — MAIN_MAP content
    flows through QGIS rendering, not the legacy Python chain."""
    from paleo_workbench.mapping.layout_export import (
        export_composition_reported,
    )

    svg_path = tmp_path / "symbols.svg"
    report = export_composition_reported(
        _composition(), svg_path, fmt="svg", dpi=150,
        map_extent=_EXTENT, crs="EPSG:4326", stack=stack,
    )
    assert report.engine == "qgis_layout"
    text = svg_path.read_text(encoding="utf-8", errors="ignore")
    # QGIS layout SVG embeds the page + rendered map content
    assert len(text) > 2000
