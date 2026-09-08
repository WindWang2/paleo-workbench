"""QGIS layer-schema wire adapter (v7 §3): GeologicalLayerSpec → fields_json.

Pure-python wire tests (always run).  The bridge consumption of this wire is
covered by qgis-marked tests once qgis_render_bridge is built.
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.qgis_layer_schema import (
    fields_json_for_spec,
    qgis_geometry_type_name,
    qgs_field_type_for_kind,
    schema_wire_for_role,
)
from paleo_workbench.mapping_workspace.geological_layer_spec import spec_for_role
from paleo_workbench.mapping_workspace.layer_roles import LayerRole


def test_qgs_field_types():
    assert qgs_field_type_for_kind("text") == "QString"
    assert qgs_field_type_for_kind("int") == "qlonglong"
    assert qgs_field_type_for_kind("real") == "double"
    assert qgs_field_type_for_kind("bool") == "bool"
    with pytest.raises(ValueError):
        qgs_field_type_for_kind("blob")


def test_fault_fields_wire():
    wire = fields_json_for_spec(spec_for_role(LayerRole.FAULT_CONSTRAINT))
    by_name = {f["name"]: f for f in wire}
    fault_type = by_name["fault_type"]
    assert fault_type["type"] == "QString"
    assert fault_type["constraints"] == {"not_null": True}
    assert fault_type["domain"] == {"map": {c: c for c in fault_type["domain"]["map"]}}
    assert len(fault_type["domain"]["map"]) == 5
    assert fault_type["editor_widget"] == "ValueMap"
    # boolean field → CheckBox + not_null carries over
    assert by_name["active"]["editor_widget"] == "CheckBox"
    assert by_name["active"]["default"] is True


def test_direction_fields_wire_range_widget():
    wire = fields_json_for_spec(spec_for_role(LayerRole.PROVENANCE_DIRECTION))
    by_name = {f["name"]: f for f in wire}
    azimuth = by_name["azimuth_deg"]
    assert azimuth["type"] == "double"
    assert azimuth["domain"] == {"range": [0.0, 360.0]}
    assert azimuth["editor_widget"] == "Range"


def test_schema_wire_for_role_raster():
    wire = schema_wire_for_role(LayerRole.FACTOR_GRID)
    assert wire["raster"] is True
    assert wire["qgis_geometry_type"] == "raster"
    assert wire["renderer_binding"]["renderer_kind"] == "pseudocolor"


def test_geometry_names():
    assert qgis_geometry_type_name("polygon") == "MultiPolygon"
    assert qgis_geometry_type_name("vector") == "NoGeometry"


def test_wire_field_names_unique_per_role():
    for role in LayerRole:
        try:
            spec = spec_for_role(role)
        except KeyError:
            continue
        names = [f["name"] for f in fields_json_for_spec(spec)]
        assert len(names) == len(set(names)), role
