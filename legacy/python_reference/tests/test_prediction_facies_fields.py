"""Prediction facies layer field schema (mock 相面预测分类渲染不可见修复).

WELL/SEISMIC_FACIES_PREDICTION + WELL/SEISMIC_FACIES_CONFIDENCE 的 spec
此前只有 probability：桥侧 memory 层按 schema 落字段时 facies_name 被丢弃，
categorized(attr=facies_name) 渲染匹配不到任何要素，相区完全不可见。
本文件锁定四角色的相字段契约；桥往返断言（qgis marked）无桥诚实跳过。
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.qgis_layer_schema import (
    fields_json_for_spec,
    schema_wire_for_role,
)
from paleo_workbench.mapping_workspace.geological_layer_spec import spec_for_role
from paleo_workbench.mapping_workspace.layer_roles import LayerRole

PREDICTION_ROLES = (
    LayerRole.WELL_FACIES_PREDICTION,
    LayerRole.WELL_FACIES_CONFIDENCE,
    LayerRole.SEISMIC_FACIES_PREDICTION,
    LayerRole.SEISMIC_FACIES_CONFIDENCE,
)


@pytest.mark.parametrize("role", PREDICTION_ROLES)
def test_prediction_roles_carry_facies_identity_fields(role):
    names = [f.name for f in spec_for_role(role).fields]
    assert names == ["facies_name", "facies", "probability"]


@pytest.mark.parametrize("role", PREDICTION_ROLES)
def test_prediction_facies_fields_are_open_text(role):
    by_name = {f.name: f for f in spec_for_role(role).fields}
    for name in ("facies_name", "facies"):
        field = by_name[name]
        assert field.kind == "text"
        assert field.default == ""
        assert field.required is False
        assert field.choices == ()


@pytest.mark.parametrize("role", PREDICTION_ROLES)
def test_prediction_probability_field_kept(role):
    by_name = {f.name: f for f in spec_for_role(role).fields}
    probability = by_name["probability"]
    assert probability.kind == "real"
    assert probability.value_range == (0.0, 1.0)
    assert probability.default == 0.0


@pytest.mark.parametrize("role", PREDICTION_ROLES)
def test_prediction_fields_wire_qgis_types(role):
    by_name = {entry["name"]: entry
               for entry in fields_json_for_spec(spec_for_role(role))}
    assert by_name["facies_name"]["type"] == "QString"
    assert by_name["facies"]["type"] == "QString"
    assert by_name["probability"]["type"] == "double"


def test_prediction_schema_wire_for_seismic_role():
    wire = schema_wire_for_role(LayerRole.SEISMIC_FACIES_PREDICTION)
    assert [entry["name"] for entry in wire["fields"]] == [
        "facies_name", "facies", "probability"]


@pytest.mark.parametrize("role", PREDICTION_ROLES)
def test_prediction_spec_round_trip_preserves_fields(role):
    spec = spec_for_role(role)
    revived = type(spec).from_dict(spec.to_dict())
    assert [f.name for f in revived.fields] == [
        "facies_name", "facies", "probability"]


def _prediction_layer():
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
    from paleo_workbench.ui.workstation.stage_actions import (
        _categorized_facies_style,
    )

    def _feature(x0, facies_name, color):
        geometry = {"type": "Polygon", "coordinates": [
            [[x0, 0.0], [x0 + 9.0, 0.0], [x0 + 9.0, 9.0],
             [x0, 9.0], [x0, 0.0]]]}
        properties = {
            "facies_id": 1,
            "facies_name": facies_name,
            "facies": facies_name,
            "color": color,
            "area": 81.0,
            "area_unit": "m2",
            "area_percent": 50.0,
            "mean_value": 0.5,
        }
        return geometry, properties

    layer_features = [
        _feature(0.0, "delta", "#ffe082"),
        _feature(11.0, "lacustrine", "#81c784"),
    ]
    style = _categorized_facies_style(layer_features)
    assert style and style["field"] == "facies_name"
    return MapLayerSnapshot(
        id="seismic-pred-1",
        name="地震相面预测（mock）",
        layer_type="vector",
        extent=(0.0, 0.0, 20.0, 9.0),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=tuple(
            {"type": "Feature", "geometry": geometry,
             "properties": properties}
            for geometry, properties in layer_features
        ),
        style=style,
        visible=True,
        opacity=1.0,
        metadata={"role": LayerRole.SEISMIC_FACIES_PREDICTION.value},
    )


@pytest.mark.qgis
def test_bridge_keeps_facies_name_for_prediction_role(qapp):
    from tests.qgis_support import require_mapstack

    mapstack = require_mapstack()
    from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot
    from paleo_workbench.mapping.qgis_mirror import (
        mirror_snapshot_to_stack,
        reset_publish_ledger,
    )
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    reset_publish_ledger()
    stack = mapstack.QgisMapStack()
    stack.initialize()
    host = None
    try:
        host = QgisCanvasHost(stack)
        snap = MapRenderSnapshot(
            project_crs="EPSG:4326", layers=(_prediction_layer(),))
        diags: list = []
        _, seen, failures = mirror_snapshot_to_stack(
            stack, host.canvas_address, snap, diags=diags)
        assert failures == [], failures
        assert seen == ["seismic-pred-1"]

        schema = json.loads(
            stack.mirror_layer_schema_json("seismic-pred-1"))
        assert [f["name"] for f in schema["fields"]] == [
            "facies_name", "facies", "probability"]

        stored = json.loads(
            stack.mirror_features_json("seismic-pred-1", 16))["features"]
        assert len(stored) == 2
        assert {props["facies_name"]
                for props in (feat["properties"] for feat in stored)} == {
            "delta", "lacustrine"}

        xml = stack.write_project_xml()
        assert 'attr="facies_name"' in xml
        assert 'value="delta"' in xml
        assert 'value="lacustrine"' in xml
    finally:
        if host is not None:
            try:
                host.close()
            except Exception:
                pass
        stack.shutdown()
        reset_publish_ledger()
