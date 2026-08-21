"""Screen/export parity: PNG frames and vector exports share one QGIS config.

The screen frame and the exported SVG must interpret the same renderer
payload identically (same category colors, same geometry coverage).  Fonts
and anti-aliasing may differ; color identity at sampled locations may not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)

from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)
from paleo_workbench.mapping.qgis_style import migrate_legacy_style


def _categorized_layer() -> MapLayerSnapshot:
    migrated = migrate_legacy_style(
        {
            "renderer": "categorized",
            "field": "lithology",
            "categories": [["sand", "#cc4444"], ["shale", "#4466cc"]],
        },
        "Polygon",
    )
    assert migrated is not None
    return MapLayerSnapshot(
        id="facies",
        name="Facies",
        layer_type="vector",
        extent=(0.0, 0.0, 20.0, 10.0),
        crs="EPSG:3857",
        data_revision=1,
        style_revision=1,
        features=(
            {
                "id": "sand-1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
                "properties": {"lithology": "sand"},
            },
            {
                "id": "shale-1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]],
                },
                "properties": {"lithology": "shale"},
            },
        ),
        style={"qgis_style": migrated.to_dict()},
    )


def _backend() -> QgisMapRenderBackend:
    backend = QgisMapRenderBackend()
    assert backend.is_available
    backend.initialize()
    backend.set_layer_snapshot(
        MapRenderSnapshot(project_crs="EPSG:3857", layers=(_categorized_layer(),))
    )
    return backend


def test_svg_export_shares_screen_renderer_colors(tmp_path: Path) -> None:
    backend = _backend()
    try:
        backend.set_extent((0.0, 0.0, 20.0, 10.0))
        backend.set_output_size(200, 100)
        frame = backend.render_sync()
        rgba = frame.rgba
        stride = frame.stride

        def pixel(x: int, y: int) -> tuple[int, ...]:
            offset = y * stride + x * 4
            return tuple(rgba[offset : offset + 3])

        # Screen: left half red-dominant, right half blue-dominant.
        assert pixel(50, 50)[0] > 120 and pixel(50, 50)[0] > pixel(50, 50)[2]
        assert pixel(150, 50)[2] > 120 and pixel(150, 50)[2] > pixel(150, 50)[0]

        export_path = tmp_path / "map.svg"
        backend.set_extent((0.0, 0.0, 20.0, 10.0))
        assert backend.export_map_body(str(export_path), "svg", 400, 200, 96.0)
        svg = export_path.read_text(encoding="utf-8")
        # The export is true vector output from the same QGIS renderers.
        assert "path" in svg.lower()
        # Category fills appear with their RGB values in the SVG paint.
        assert "#cc4444" in svg or "204,68,68" in svg
        assert "#4466cc" in svg or "68,102,204" in svg
    finally:
        backend.shutdown()


def test_pdf_export_writes_valid_document(tmp_path: Path) -> None:
    backend = _backend()
    try:
        export_path = tmp_path / "map.pdf"
        backend.set_extent((0.0, 0.0, 20.0, 10.0))
        assert backend.export_map_body(str(export_path), "pdf", 400, 200, 150.0)
        payload = export_path.read_bytes()
        assert payload.startswith(b"%PDF")
        assert len(payload) > 500
    finally:
        backend.shutdown()


def test_export_rejects_unknown_format(tmp_path: Path) -> None:
    backend = _backend()
    backend.set_extent((0.0, 0.0, 20.0, 10.0))
    try:
        # Raster targets are not vector exports; the seam reports unsupported.
        assert backend.export_map_body(str(tmp_path / "x.png"), "png", 64, 64, 96.0) is False
        assert not (tmp_path / "x.png").exists()
    finally:
        backend.shutdown()


def test_export_uses_current_snapshot_not_stale_layers(tmp_path: Path) -> None:
    """A style edit between renders changes the next export identically."""
    backend = _backend()
    backend.set_extent((0.0, 0.0, 20.0, 10.0))
    try:
        layer = _categorized_layer()
        migrated = migrate_legacy_style(
            {
                "renderer": "categorized",
                "field": "lithology",
                "categories": [["sand", "#112233"], ["shale", "#332211"]],
            },
            "Polygon",
        )
        restyled = MapLayerSnapshot(
            **{
                **{field: getattr(layer, field) for field in layer.__dataclass_fields__},
                "style_revision": 2,
                "style": {"qgis_style": migrated.to_dict()},
            }
        )
        backend.set_layer_snapshot(
            MapRenderSnapshot(project_crs="EPSG:3857", layers=(restyled,))
        )
        export_path = tmp_path / "restyled.svg"
        assert backend.export_map_body(str(export_path), "svg", 200, 100, 96.0)
        svg = export_path.read_text(encoding="utf-8")
        assert "#112233" in svg or "17,34,51" in svg
        assert "#cc4444" not in svg
    finally:
        backend.shutdown()
