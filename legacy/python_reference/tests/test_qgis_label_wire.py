"""QGIS label wire parity tests (#1052 / #1102).

The Python host must actually SHIP the new label keys on the native wire
(labels.buffer_color and the per-feature data-defined field names) in the
exact format the pybind11 decoder reads — string colour values and string
attribute field names inside the ``style.labels`` mapping.
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    _flatten_qgis_style,
    _qgis_snapshot,
)
from paleo_workbench.mapping.map_styles import TextStyle, VectorStyle


def _labelled_layer(labels: dict, layer_id: str = "wells") -> MapLayerSnapshot:
    style = dict(VectorStyle(fill="#22b8a7", stroke="#182431").to_dict())
    style["labels"] = dict(labels)
    return MapLayerSnapshot(
        id=layer_id,
        name="Wells",
        layer_type="vector",
        extent=(100.0, 30.0, 120.0, 45.0),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=(
            {
                "id": "w1",
                "geometry": {"type": "Point", "coordinates": [116.0, 40.0]},
                # The data-defined field names must exist as feature
                # attributes — the bridge builds layer fields from them.
                "properties": {
                    "name": "BJ-1",
                    "dip": "32.5",
                    "mag": "14.0",
                    "zone": "#ff5500",
                },
            },
            {
                "id": "w2",
                "geometry": {"type": "Point", "coordinates": [117.0, 41.0]},
                "properties": {
                    "name": "BJ-2",
                    "dip": "-12.0",
                    "mag": "9.0",
                    "zone": "#339af0",
                },
            },
        ),
        style=style,
    )


def _wire_layer(layer: MapLayerSnapshot) -> dict:
    snapshot = MapRenderSnapshot(project_crs="EPSG:4326", layers=(layer,))
    layers = _qgis_snapshot(snapshot)
    assert len(layers) == 1, "vector layer with features must ship on the wire"
    return layers[0]


# ---------------------------------------------------------------------------
# TextStyle schema (#1052 / #1102)
# ---------------------------------------------------------------------------


def test_text_style_data_defined_fields_roundtrip() -> None:
    style = TextStyle(
        field="name",
        rotation_field="dip",
        size_field="mag",
        color_field="zone",
        buffer_color="#101820",
    )
    payload = style.to_dict()
    assert payload["rotation_field"] == "dip"
    assert payload["size_field"] == "mag"
    assert payload["color_field"] == "zone"
    assert payload["buffer_color"] == "#101820"
    assert TextStyle.from_dict(payload) == style


def test_text_style_defaults_keep_new_fields_disabled() -> None:
    style = TextStyle()
    assert style.rotation_field == ""
    assert style.size_field == ""
    assert style.color_field == ""
    assert style.buffer_color == ""
    # from_dict ignores the new keys when absent (legacy persisted styles).
    legacy = TextStyle.from_dict({"field": "name", "size": 9.0, "halo_color": "#111111"})
    assert legacy.field == "name"
    assert legacy.rotation_field == ""
    assert legacy.buffer_color == ""


# ---------------------------------------------------------------------------
# Wire assembly (#1052 / #1102)
# ---------------------------------------------------------------------------


def test_wire_carries_data_defined_label_fields() -> None:
    labels = TextStyle(
        field="name",
        size=12.0,
        rotation_field="dip",
        size_field="mag",
        color_field="zone",
        buffer_color="#101820",
    ).to_dict()
    wire = _wire_layer(_labelled_layer(labels))
    wire_labels = wire["style"]["labels"]
    # Optional field overrides travel as attribute FIELD NAME strings.
    assert wire_labels["rotation_field"] == "dip"
    assert wire_labels["size_field"] == "mag"
    assert wire_labels["color_field"] == "zone"
    assert isinstance(wire_labels["rotation_field"], str)
    assert isinstance(wire_labels["size_field"], str)
    assert isinstance(wire_labels["color_field"], str)
    # Buffer colour uses the SAME wire format as the label colour: a string.
    assert wire_labels["buffer_color"] == "#101820"
    assert isinstance(wire_labels["buffer_color"], str)
    # Fixed values keep their #1025 point/millimetre conversions.
    assert wire_labels["size"] == 12.0 * (72.0 / 96.0)
    # The field-driven attributes must ride along so the bridge can create
    # the layer fields the data-defined properties reference.
    attributes = [feature["attributes"] for feature in wire["features"]]
    assert all(entry.get("dip") is not None for entry in attributes)
    assert all(entry.get("mag") is not None for entry in attributes)
    assert all(entry.get("zone") is not None for entry in attributes)


def test_wire_buffer_color_falls_back_to_halo_color() -> None:
    """A TextStyle without an explicit buffer colour keeps the historical
    halo-colour behaviour (halos are NOT silently white on the wire)."""
    labels = TextStyle(field="name", halo_color="#182431", halo_width=1.5).to_dict()
    wire = _wire_layer(_labelled_layer(labels))
    wire_labels = wire["style"]["labels"]
    assert wire_labels["buffer_color"] == "#182431"
    assert wire_labels["buffer"] == pytest.approx(1.5 * (25.4 / 96.0))


def test_wire_omits_buffer_color_only_when_fully_unset() -> None:
    """A legacy labels dict without halo/buffer colour keys ships no
    buffer_color — the C++ side then keeps its white default."""
    labels = {"field": "name", "size": 9.0}
    wire = _wire_layer(_labelled_layer(labels))
    wire_labels = wire["style"]["labels"]
    assert "buffer_color" not in wire_labels
    assert "rotation_field" not in wire_labels
    assert "size_field" not in wire_labels
    assert "color_field" not in wire_labels


def test_flatten_qgis_style_promotes_nested_label_payload() -> None:
    """qgis_style payloads (persisted authoring styles) also surface the new
    label keys after flattening."""
    flat = _flatten_qgis_style(
        {
            "fill": "#22b8a7",
            "qgis_style": {
                "renderer_xml": "<renderer/>",
                "labeling_xml": "<labeling/>",
            },
            "labels": TextStyle(
                field="name",
                rotation_field="dip",
                buffer_color="#0b7285",
                visible=True,
            ).to_dict(),
        }
    )
    assert flat["renderer_xml"] == "<renderer/>"
    assert flat["labeling_xml"] == "<labeling/>"
    assert flat["labels"]["rotation_field"] == "dip"
    assert flat["labels"]["buffer_color"] == "#0b7285"


def test_annotation_default_style_binds_per_feature_fields() -> None:
    """#1052: AnnotationMapLayer features carry rotation/font_size/color
    properties; the annotation default style must opt into the QGIS
    data-defined label bindings so per-feature angle/size/colour survive
    the native backend instead of flattening to the fixed format."""
    from paleo_workbench.mapping.layers import AnnotationMapLayer
    from paleo_workbench.mapping.map_styles import default_style_for

    style = default_style_for("annotation")
    assert style.labels.rotation_field == "rotation"
    assert style.labels.size_field == "font_size"
    assert style.labels.color_field == "color"

    layer = AnnotationMapLayer(id="ann", name="ann")
    layer.add_annotation("断层F1", 110.0, 35.0, font_size=14.0, color="#ffaa00", rotation=30.0)

    snapshot_layer = MapLayerSnapshot(
        id=layer.id,
        name=layer.name,
        layer_type=layer.layer_type,
        extent=layer.extent,
        crs="EPSG:4326",
        data_revision=layer.data_revision,
        style_revision=1,
        features=tuple(layer.features),
        style=layer.style,
    )
    wire = _wire_layer(snapshot_layer)
    labels = wire["style"]["labels"]
    assert labels["rotation_field"] == "rotation"
    assert labels["size_field"] == "font_size"
    assert labels["color_field"] == "color"
    # The per-feature values ride the feature attributes the bridge turns
    # into QgsFields (QgsProperty::fromField evaluates against them).
    first_attrs = wire["features"][0]["attributes"]
    assert first_attrs["rotation"] == "30.0" or first_attrs["rotation"] == 30.0
