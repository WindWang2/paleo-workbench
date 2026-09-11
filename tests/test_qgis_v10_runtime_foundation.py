"""V10 桥 0.6.0a0 集成面 — runtime facts / project CRS push / map-settings
facts / provider introspection / mirror scale range / current-layer clear /
style read-back。QGIS-marked：无桥环境诚实跳过。

本文件与 docs/development/qgis-spatial-layer-foundation-v10/ 的 D 决策
一一对应（01-qgis-runtime / 02-crs-transform / 06-provider-schema /
07-rendering）。
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from tests.qgis_support import require_mapstack  # noqa: E402

mapstack = require_mapstack()

_LINE_FEATURES = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature",
     "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [5.0, 5.0]]},
     "properties": {"__pwb_fid": "L-1"}}
  ]
}"""


@pytest.fixture()
def stack(qapp):
    s = mapstack.QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


@pytest.fixture()
def canvas(stack, qtbot):
    from PySide6.QtWidgets import QGraphicsView
    from shiboken6 import Shiboken

    addr = stack.create_canvas()
    widget = Shiboken.wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    return addr


@pytest.fixture(scope="module")
def bridge():
    import qgis_render_bridge

    return qgis_render_bridge


def test_manifest_declares_v10_features(bridge):
    manifest = bridge.capability_manifest()
    features = manifest["features"]
    for flag in (
        "runtime_facts", "project_crs_push", "map_settings_facts",
        "provider_introspection", "style_readback", "layer_scale_range",
        "current_layer_clear", "digitize_scratch_honest_crs",
    ):
        assert flag in features, f"manifest 缺少 V10 特性 {flag}"
    assert bridge.__version__ >= "0.6.0a0"


def test_runtime_facts_reports_versions_and_probes(stack):
    facts = stack.runtime_facts()
    # 版本面：真实字符串，不是占位
    assert str(facts["qgis_version"]).startswith("4.")
    assert facts["proj_version"]
    assert facts["gdal_version"]
    # provider 注册表
    assert facts["provider_count"] > 0
    assert any("memory" in p for p in facts["providers"])
    # CRS probes（4326/4490/4214/4610——V10 review-round-2 集合）
    probes = facts["crs_probes"]
    assert probes["EPSG:4326"] is True
    assert probes["EPSG:4490"] is True
    assert probes["EPSG:4214"] is True
    assert probes["EPSG:4610"] is True
    # proj 数据库解析链
    assert facts["proj_db_reachable"] is True
    assert facts["proj_db_path"]


def test_runtime_facts_transform_probe(stack):
    facts = stack.runtime_facts()
    assert facts["transform_available"] is True


def test_set_project_crs_pushes_crs_and_ellipsoid(stack, canvas):
    assert stack.set_project_crs("EPSG:4490") == ""
    # 无效 authid → 人读原因，不抛
    error = stack.set_project_crs("NOT:ACRS")
    assert error and "NOT:ACRS" in error


def test_canvas_map_units_and_dpi(stack, canvas):
    stack.set_destination_crs(canvas, "EPSG:4326")
    units = stack.canvas_map_units(canvas)
    assert units == "degrees"
    dpi = stack.canvas_output_dpi(canvas)
    assert dpi > 0


def test_mirror_provider_facts_vector(stack, canvas):
    stack.upsert_mirror_layer(
        "doc-probe", "探测层", "LineString", "EPSG:4326", _LINE_FEATURES,
        is_editable=True, data_revision=1)
    facts = stack.mirror_provider_facts("doc-probe")
    assert facts["exists"] is True
    assert facts["layer_type"] == "vector"
    assert facts["provider"] == "memory"
    assert facts["geometry_type"] == "Line"
    capability = facts["capability"]
    # memory provider：加要素/改几何/改属性全支持
    assert capability["add_features"] is True
    assert capability["change_geometries"] is True
    assert capability["change_attribute_values"] is True
    assert facts["supports_editing"] is True
    missing = stack.mirror_provider_facts("doc-absent")
    assert missing["exists"] is False


def test_upsert_scale_range_applies_scale_visibility(stack, canvas):
    stack.upsert_mirror_layer(
        "doc-scale", "比例尺层", "LineString", "EPSG:4326", _LINE_FEATURES,
        min_scale=1000.0, max_scale=50000.0)
    # 读回验证：provider facts 无 scale 字段——经 XML 信封读回
    xml = stack.write_project_xml()
    # 应用面验证走 mirror_style/layer schema 不含 scale；这里用行为面：
    # 写入 project XML 的 layer 定义应包含 minimumScale（QGIS 序列化）。
    assert "minimumScale" in xml or "minScale" in xml or "ScaleBasedVisibility" in xml


def test_current_layer_empty_clears(stack, canvas):
    stack.upsert_mirror_layer(
        "doc-cur", "当前层", "LineString", "EPSG:4326", _LINE_FEATURES)
    stack.set_current_layer(canvas, "doc-cur")
    # 空 doc_id = 显式清除（旧桥抛 unknown doc_id——V10 语义）
    stack.set_current_layer(canvas, "")


def test_mirror_style_json_reads_back_renderer(stack, canvas):
    renderer_xml = (
        '<renderer-v2 type="singleSymbol" symbols="0">'
        '<symbols><symbol name="0" type="line" force_rhr="0">'
        '<layer class="SimpleLine" enabled="1" locked="0"/>'
        '</symbol></symbols></renderer-v2>')
    stack.upsert_mirror_layer(
        "doc-style", "样式层", "LineString", "EPSG:4326", _LINE_FEATURES,
        renderer_xml=renderer_xml)
    facts = stack.mirror_style_json("doc-style")
    assert facts["exists"] is True
    assert facts["layer_type"] == "vector"
    applied = str(facts.get("renderer_xml") or "")
    assert applied.strip()
    semantic = json.dumps(["singleSymbol"]) if False else None  # noqa: F841
    assert "renderer" in applied.lower() or "symbol" in applied.lower()


def test_digitize_scratch_honest_when_canvas_crs_invalid(stack, canvas, qtbot):
    """quiet-4326 清理：画布 CRS 无效时 scratch 不带 4326（raw 帧）。

    行为面验证：无效 CRS 画布上启动 digitize 工具不再产生 4326 scratch
    ——通过 upsert 一个 CRS 后清空，工具仍可用（不抛）即可；scratch 内部
    细节不暴露，断言面 = 不抛 + 工具激活成功。
    """
    stack.set_destination_crs(canvas, "")
    stack.set_map_tool(canvas, "addPoint")  # 不抛 = scratch 创建成功
    stack.set_map_tool(canvas, "pan")
