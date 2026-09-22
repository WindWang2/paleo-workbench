"""Authoritative QGIS style payload model (bridge not required)."""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    _flatten_qgis_style,
)
from paleo_workbench.mapping.qgis_style import (
    QGIS_STYLE_SCHEMA_VERSION,
    QgisStylePayload,
)

RENDERER_XML = "<renderer-v2 type=\"singleSymbol\"><symbols/></renderer-v2>"


class TestQgisStylePayload:
    def test_payload_roundtrips_through_dict(self) -> None:
        payload = QgisStylePayload(
            renderer_xml=RENDERER_XML,
            labeling_xml="<labeling/>",
            name="Facies",
            tags=("lithology", "sandstone"),
            revision=4,
        )
        restored = QgisStylePayload.from_dict(payload.to_dict())
        assert restored == payload

    def test_missing_renderer_xml_is_rejected(self) -> None:
        assert QgisStylePayload.from_dict({"schema_version": 1}) is None
        assert QgisStylePayload.from_dict({"renderer_xml": "   "}) is None
        with pytest.raises(ValueError):
            QgisStylePayload(renderer_xml="")

    def test_unknown_schema_version_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            QgisStylePayload(renderer_xml=RENDERER_XML, schema_version=99)

    def test_from_dict_is_tolerant_of_legacy_garbage(self) -> None:
        assert QgisStylePayload.from_dict(None) is None
        assert QgisStylePayload.from_dict("not-a-dict") is None
        payload = QgisStylePayload.from_dict({"renderer_xml": RENDERER_XML, "revision": "x"})
        assert payload is not None
        assert payload.revision == 1

    def test_bumped_increments_revision(self) -> None:
        payload = QgisStylePayload(renderer_xml=RENDERER_XML, revision=2)
        assert payload.bumped().revision == 3
        assert payload.revision == 2
        assert payload.bumped().renderer_xml == RENDERER_XML

    def test_schema_version_default(self) -> None:
        assert QGIS_STYLE_SCHEMA_VERSION == 1


class TestFlattenQgisStyle:
    def test_promotes_nested_payload_to_wire_keys(self) -> None:
        style = {
            "fill": "#6c8ebf",
            "qgis_style": {
                "schema_version": 1,
                "renderer_xml": RENDERER_XML,
                "labeling_xml": "<labeling/>",
                "revision": 7,
            },
        }
        flat = _flatten_qgis_style(style)
        assert flat["renderer_xml"] == RENDERER_XML
        assert flat["labeling_xml"] == "<labeling/>"
        assert "qgis_style" not in flat
        # The legacy vocabulary survives untouched.
        assert flat["fill"] == "#6c8ebf"

    def test_style_without_payload_is_unchanged(self) -> None:
        style = {"fill": "#fff", "stroke": "#000", "stroke_width": 2.0}
        assert _flatten_qgis_style(style) == style

    def test_invalid_payload_entries_are_ignored(self) -> None:
        style = {"qgis_style": {"renderer_xml": "  ", "labeling_xml": ""}, "fill": "#111"}
        assert _flatten_qgis_style(style) == {"fill": "#111"}

    def test_snapshot_style_flows_to_wire_format(self) -> None:
        """MapLayerSnapshot styles flatten inside the native snapshot payload."""
        from paleo_workbench.mapping.map_render_backend import _qgis_snapshot

        layer = MapLayerSnapshot(
            id="facies",
            name="Facies",
            layer_type="vector",
            extent=(0.0, 0.0, 10.0, 10.0),
            crs="EPSG:3857",
            data_revision=3,
            style_revision=5,
            features=(
                {
                    "id": "f1",
                    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 0]]]},
                    "properties": {},
                },
            ),
            style={"qgis_style": {"renderer_xml": RENDERER_XML}},
        )
        encoded = _qgis_snapshot(MapRenderSnapshot(project_crs="EPSG:3857", layers=(layer,)))
        assert len(encoded) == 1
        assert encoded[0]["style"]["renderer_xml"] == RENDERER_XML
        assert "qgis_style" not in encoded[0]["style"]
