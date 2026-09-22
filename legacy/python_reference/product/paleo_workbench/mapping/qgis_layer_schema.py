"""GeologicalLayerSpec → QGIS layer schema wire adapter (v7 §3).

Converts the pure-domain spec (:mod:`paleo_workbench.mapping_workspace.
geological_layer_spec`) into the ``fields_json`` payload accepted by the
qgis_render_bridge mirror upsert, so QgsFields / field constraints / value
domains / defaults / editor widgets on the QGIS side are generated from the
SAME spec Python validates — never a second, divergent field set.

Pure functions; no bridge import required to *compute* the wire (the bridge
only consumes it), so these tests run everywhere.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.mapping_workspace.geological_layer_spec import (
    GeologicalLayerSpec,
    SpecField,
    spec_for_role,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole

__all__ = [
    "fields_json_for_spec",
    "qgis_geometry_type_name",
    "qgs_field_type_for_kind",
    "schema_wire_for_role",
]

#: spec ``kind`` → (QMetaType name used by QgsField, QVariant type name).
_KIND_TO_QGS_TYPE: dict[str, str] = {
    "text": "QString",
    "int": "qlonglong",
    "real": "double",
    "bool": "bool",
    "datetime": "QDateTime",
}

#: geometry_kind (spec vocabulary) → QGIS provider geometry type names
#: (memory-provider / QgsWkbType string forms).  Polygon layers mirror as
#: MultiPolygon so single/multi features share one WKB type.
_GEOMETRY_TYPE_NAMES: dict[str, str] = {
    "point": "Point",
    "line": "LineString",
    "polygon": "MultiPolygon",
    "raster": "raster",  # raster layers have no WKB type
    "vector": "NoGeometry",  # geometry decided per-layer by features
}


def qgis_geometry_type_name(geometry_kind: str) -> str:
    try:
        return _GEOMETRY_TYPE_NAMES[geometry_kind]
    except KeyError:
        raise ValueError(
            f"unknown geometry kind {geometry_kind!r}; expected one of "
            f"{sorted(_GEOMETRY_TYPE_NAMES)}") from None


def qgs_field_type_for_kind(kind: str) -> str:
    try:
        return _KIND_TO_QGS_TYPE[kind]
    except KeyError:
        raise ValueError(
            f"unknown spec field kind {kind!r}; expected one of "
            f"{sorted(_KIND_TO_QGS_TYPE)}") from None


def _editor_widget_for(spec_field: SpecField) -> str:
    if spec_field.editor_widget is not None:
        return spec_field.editor_widget
    if spec_field.choices:
        return "ValueMap"
    if spec_field.kind == "bool":
        return "CheckBox"
    if spec_field.kind == "datetime":
        return "DateTime"
    if spec_field.kind in {"int", "real"} and spec_field.value_range is not None:
        return "Range"
    return "TextEdit"


def fields_json_for_spec(spec: GeologicalLayerSpec) -> list[dict[str, Any]]:
    """Wire form of the spec's field schema for the bridge mirror upsert.

    Each entry: name/type/length/precision + optional constraint/domain/
    default/editor widget — exactly what QgsField + QgsFieldConstraints +
    QgsEditorWidgetSetup need on the C++ side.
    """
    wire: list[dict[str, Any]] = []
    for spec_field in spec.fields:
        entry: dict[str, Any] = {
            "name": spec_field.name,
            "type": qgs_field_type_for_kind(spec_field.kind),
            "alias": spec_field.label or spec_field.name,
            "editor_widget": _editor_widget_for(spec_field),
        }
        if spec_field.length is not None:
            entry["length"] = spec_field.length
        if spec_field.precision is not None:
            entry["precision"] = spec_field.precision
        constraints: dict[str, Any] = {}
        if spec_field.required:
            constraints["not_null"] = True
        if spec_field.unique:
            constraints["unique"] = True
        if spec_field.expression:
            constraints["expression"] = spec_field.expression
        if constraints:
            entry["constraints"] = constraints
        if spec_field.choices:
            entry["domain"] = {"map": {c: c for c in spec_field.choices}}
        elif spec_field.value_range is not None:
            lo, hi = spec_field.value_range
            entry["domain"] = {"range": [lo, hi]}
        if spec_field.default not in (None, ""):
            entry["default"] = spec_field.default
        wire.append(entry)
    return wire


def schema_wire_for_role(role: LayerRole | str) -> dict[str, Any]:
    """Full mirror-creation wire fragment for a role: geometry type name +
    fields_json + (raster marker for the bridge's raster mirror path)."""
    spec = spec_for_role(role)
    wire: dict[str, Any] = {
        "role": spec.role.value,
        "geometry_kind": spec.geometry_kind,
        "qgis_geometry_type": qgis_geometry_type_name(spec.geometry_kind),
        "fields": fields_json_for_spec(spec),
    }
    if spec.geometry_kind == "raster":
        wire["raster"] = True
    if spec.renderer_binding is not None:
        wire["renderer_binding"] = {
            "style_id": spec.renderer_binding.style_id,
            "renderer_kind": spec.renderer_binding.renderer_kind,
            "field": spec.renderer_binding.field,
        }
    return wire
