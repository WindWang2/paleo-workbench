"""V8 M1/W1 — GeologicalLayerSpec 的 fields_json 真正落到 QGIS memory
provider（QgsFields/约束/别名/编辑器控件/默认值 + GeoJSON properties 的
typed 属性往返）。QGIS-marked：无桥环境诚实跳过。

自省面：``mirror_layer_schema_json``（桥 ≥ 0.4.0）——测的是 provider 上
真实应用的结果，不是 wire 形状。
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from tests.qgis_support import require_mapstack  # noqa: E402

mapstack = require_mapstack()


_FAULT_FEATURES = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature",
     "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [5.0, 5.0]]},
     "properties": {"__pwb_fid": "F-1", "fault_id": "F-1", "fault_type": "normal",
                    "confidence": 0.8, "active": true, "depth_m": 2500}}
  ]
}"""

#FAULT_CONSTRAINT 角色的 wire（qgis_layer_schema 产出形状；含约束/域/默认值）
_FAULT_FIELDS = json.dumps([
    {"name": "fault_id", "type": "QString", "alias": "断层编号",
     "editor_widget": "TextEdit",
     "constraints": {"not_null": True, "unique": True},
     "default": "F-0"},
    {"name": "fault_type", "type": "QString", "alias": "断层性质",
     "editor_widget": "ValueMap",
     "constraints": {"not_null": True},
     "domain": {"map": {"normal": "normal", "reverse": "reverse", "strike-slip": "strike-slip"}}},
    {"name": "confidence", "type": "double", "alias": "置信度",
     "editor_widget": "Range", "domain": {"range": [0.0, 1.0]}},
    {"name": "active", "type": "bool", "alias": "现今活动",
     "editor_widget": "CheckBox", "default": False},
    {"name": "depth_m", "type": "qlonglong", "alias": "深度(m)",
     "editor_widget": "Range", "domain": {"range": [0.0, 12000.0]}},
])


@pytest.fixture()
def stack(qapp):
    s = mapstack.QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _upsert(stack, *, fields=_FAULT_FIELDS, features=_FAULT_FEATURES, revision=1, delta=""):
    return stack.upsert_mirror_layer(
        "fault-1", "断层约束", "LineString", "EPSG:4326", features,
        "", "", "", True, 1.0, False, True, False, revision, delta, fields,
    )


def _schema(stack, doc_id="fault-1") -> dict:
    return json.loads(stack.mirror_layer_schema_json(doc_id))


def test_manifest_declares_provider_fields_feature():
    manifest = __import__("qgis_render_bridge").capability_manifest()
    assert "provider_fields" in manifest["features"]
    assert "row_indicators" in manifest["features"]
    assert "legend_filter" in manifest["features"]


def test_provider_fields_applied_with_types_aliases_and_constraints(stack):
    _upsert(stack)
    schema = _schema(stack)
    assert schema["exists"] is True
    by_name = {field["name"]: field for field in schema["fields"]}
    assert set(by_name) == {
        "fault_id", "fault_type", "confidence", "active", "depth_m"}
    # typed provider fields (QMetaType names as QGIS reports them)
    assert by_name["fault_id"]["type"] == "QString"
    assert by_name["depth_m"]["type"] == "qlonglong"
    assert by_name["confidence"]["type"] == "double"
    assert by_name["active"]["type"] == "bool"
    # aliases
    assert by_name["fault_id"]["alias"] == "断层编号"
    # constraints ride WITH the provider fields (attribute-form enforcement)
    assert by_name["fault_id"]["constraints"]["not_null"] is True
    assert by_name["fault_id"]["constraints"]["unique"] is True
    assert by_name["fault_type"]["constraints"]["not_null"] is True


def test_editor_widgets_and_value_domains(stack):
    _upsert(stack)
    by_name = {f["name"]: f for f in _schema(stack)["fields"]}
    assert by_name["fault_type"]["editor_widget"] == "ValueMap"
    value_map = by_name["fault_type"]["editor_config"]["map"]
    assert value_map == {"normal": "normal", "reverse": "reverse",
                         "strike-slip": "strike-slip"}
    assert by_name["confidence"]["editor_widget"] == "Range"
    assert by_name["confidence"]["editor_config"]["Min"] == 0.0
    assert by_name["confidence"]["editor_config"]["Max"] == 1.0
    assert by_name["active"]["editor_widget"] == "CheckBox"


def test_defaults_recorded_as_qgis_expressions(stack):
    _upsert(stack)
    by_name = {f["name"]: f for f in _schema(stack)["fields"]}
    assert by_name["fault_id"]["default"] == "'F-0'"
    assert by_name["active"]["default"] == "false"


def _stored_feature(stack, doc_id="fault-1") -> dict:
    payload = json.loads(stack.mirror_features_json(doc_id))
    assert payload["exists"] is True
    return payload["features"][0]


def test_geojson_properties_land_as_typed_attributes(stack):
    """端到端：properties 不再在解析时被丢弃——镜像层真实存下 typed 属性。"""
    _upsert(stack)
    props = _stored_feature(stack)["properties"]
    assert props["fault_id"] == "F-1"
    assert props["fault_type"] == "normal"
    assert props["depth_m"] == 2500
    assert props["confidence"] == pytest.approx(0.8)
    assert bool(props["active"]) is True
    # 几何仍在（schema 化不丢几何路径）
    assert _stored_feature(stack)["geometry"]["type"] == "LineString"


def test_legacy_untyped_mirror_stays_geometry_only(stack):
    """无 schema 的 legacy 路径：属性仍被丢弃（V7 行为），几何不受影响。"""
    wells = """{"type": "FeatureCollection", "features": [
      {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
       "properties": {"name": "W1"}}]}"""
    stack.upsert_mirror_layer(
        "well-legacy", "井位", "Point", "EPSG:4326", wells,
        "", "", "", True, 1.0, False, False, False, 1, "", "",
    )
    payload = json.loads(stack.mirror_features_json("well-legacy"))
    assert payload["exists"] is True
    feature = payload["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"] == {}


def test_delta_channel_reapplies_typed_attributes(stack):
    _upsert(stack)
    changed = json.dumps({
        "base_revision": 1,
        "changed": [
            {"type": "Feature",
             "geometry": {"type": "LineString",
                          "coordinates": [[0.0, 0.0], [6.0, 6.0]]},
             "properties": {"__pwb_fid": "F-1", "fault_id": "F-1",
                            "fault_type": "reverse", "confidence": 0.4,
                            "active": False, "depth_m": 900}},
        ],
    })
    _upsert(stack, revision=2, delta=changed)
    # delete+re-add：仍是单要素，且值为 delta 的新值
    payload = json.loads(stack.mirror_features_json("fault-1"))
    assert len(payload["features"]) == 1
    props = payload["features"][0]["properties"]
    assert props["fault_type"] == "reverse"
    assert props["depth_m"] == 900
    assert props["fault_id"] == "F-1"


def test_schema_drift_rebuilds_provider_fields(stack):
    _upsert(stack)
    narrower = json.dumps([
        {"name": "fault_id", "type": "QString", "alias": "断层编号",
         "editor_widget": "TextEdit"},
    ])
    _upsert(stack, fields=narrower, revision=2)
    by_name = {f["name"]: f for f in _schema(stack)["fields"]}
    assert set(by_name) == {"fault_id"}


def test_legacy_payload_clears_stale_schema(stack):
    _upsert(stack)
    assert _schema(stack)["fields"]
    # 空 fields_json（角色回退到 legacy 路径）：陈旧 schema 声明必须清掉。
    _upsert(stack, fields="", revision=2)
    schema = _schema(stack)
    assert schema["exists"] is True
    assert schema["fields"] == []


def test_malformed_fields_json_fails_closed(stack):
    with pytest.raises(Exception):
        stack.upsert_mirror_layer(
            "bad-1", "坏schema", "LineString", "EPSG:4326", _FAULT_FEATURES,
            "", "", "", True, 1.0, False, True, False, 1, "", "{not json",
        )


def test_row_indicators_replaces_and_clears(stack, qapp):
    """V8 M5：通用行指示器（编辑铅笔之外的呈现态词汇）。"""
    _upsert(stack)
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 9.0)
    tree = stack.create_layer_tree_view(host.canvas_address)
    stack.set_row_indicators(tree, "fault-1", json.dumps(["dirty", "published"]))
    assert stack.row_indicator_count(tree, "fault-1") == 2
    assert stack.row_indicator_count(tree, "fault-1", "dirty") == 1
    assert stack.row_indicator_count(tree, "fault-1", "published") == 1
    # 未知 kind 静默跳过（host"未知=无装饰"同语义）
    stack.set_row_indicators(tree, "fault-1", json.dumps(["stale", "nonsense"]))
    assert stack.row_indicator_count(tree, "fault-1") == 1
    assert stack.row_indicator_count(tree, "fault-1", "stale") == 1
    # 整组清除
    stack.set_row_indicators(tree, "fault-1", "[]")
    assert stack.row_indicator_count(tree, "fault-1") == 0


def test_legend_filter_layers_keeps_project_tree_intact(stack, qapp, tmp_path):
    """V8 M8：legend filter（include 表）——导出后工程本树不被剪枝。"""
    wells = """{"type": "FeatureCollection", "features": [
      {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
       "properties": {"name": "W1"}}]}"""
    stack.upsert_mirror_layer(
        "well-1", "井位", "Point", "EPSG:4326", wells,
        "", "", "", True, 1.0, False, False, False, 1, "", "",
    )
    _upsert(stack)
    before = json.loads(stack.tree_snapshot_json())
    spec = {
        "page": {"width_mm": 297.0, "height_mm": 210.0},
        "items": [
            {"type": "map", "key": "map", "x": 10.0, "y": 10.0, "w": 180.0,
             "h": 150.0, "crs": "EPSG:4326", "extent": [0.0, 0.0, 10.0, 9.0],
             "frame": True},
            {"type": "legend", "map_item": "map", "title": "井位图例",
             "x": 200.0, "y": 10.0, "resize_to_contents": False,
             "filter_layers": ["well-1"]},
        ],
    }
    out = tmp_path / "legend_filter.pdf"
    result = json.loads(
        stack.layout_export(json.dumps(spec), str(out), "pdf", 96.0)
    )
    assert result.get("ok") is True
    assert out.exists() and out.stat().st_size > 0
    # 工程本树不受 legend 剪枝影响（两层的可见性/存在不变）
    after = json.loads(stack.tree_snapshot_json())
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
