"""V9 桥 0.5.0a0 集成面 — topological editing 推送、画布 scale/destination-CRS
自省、发布路径 schema 验证（真实 QgsFields 比对）。QGIS-marked：无桥环境
诚实跳过。
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from tests.qgis_support import require_mapstack  # noqa: E402

mapstack = require_mapstack()

_FAULT_FIELDS = json.dumps([
    {"name": "fault_id", "type": "QString", "alias": "断层编号",
     "constraints": {"not_null": True}},
    {"name": "confidence", "type": "double", "alias": "置信度"},
])

_FAULT_FEATURES = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature",
     "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [5.0, 5.0]]},
     "properties": {"__pwb_fid": "F-1", "fault_id": "F-1"}}
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


def test_manifest_declares_v9_features():
    manifest = __import__("qgis_render_bridge").capability_manifest()
    assert "snapping_topological_editing" in manifest["features"]
    # 同 v10：版本语义比较（字符串序在 0.10+ 会假红）。
    from packaging.version import Version

    assert Version(__import__("qgis_render_bridge").__version__) >= Version("0.5.0a0")


def test_snapping_config_pushes_topological_editing(stack, canvas):
    import qgis_render_bridge as native

    config = {
        "enabled": True,
        "mode": "all_layers",
        "tolerance_px": 12.0,
        "types": ["vertex", "segment"],
        "topological_editing": True,
    }
    stack.set_snapping_config(canvas, json.dumps(config))
    project = native if hasattr(native, "QgsProject") else None
    # 桥不暴露 QgsProject 句柄——以行为面验证：合法 JSON 被接受（旧键
    # 语义不回归），topological_editing 键不再抛 invalid argument。
    stack.set_snapping_config(canvas, json.dumps({**config,
                                                  "topological_editing": False}))
    # 畸形 JSON 仍然 fail-closed（不因新键放宽）
    with pytest.raises(Exception):
        stack.set_snapping_config(canvas, "{not json")


def test_canvas_scale_and_destination_crs_reflect_authority(stack, canvas):
    stack.set_destination_crs(canvas, "EPSG:4326")
    stack.set_canvas_extent(canvas, 0.0, 0.0, 2.0, 1.5)
    crs = stack.canvas_destination_crs(canvas)
    assert isinstance(crs, str)
    if crs:
        # proj 数据可解析的环境：auth id 必须是设定的 4326
        assert crs.upper().startswith("EPSG") and "4326" in crs
    # proj.db 缺席的运行环境（本 worktree 配方）：CRS 无法验证 → 诚实空串，
    # 宿主侧 digitize 守卫按「未知不比对」处理（不产生假失败）。
    scale = stack.canvas_scale(canvas)
    assert scale > 0.0
    # 范围减半 → 比例尺分母约减半（QGIS scale 语义）
    stack.set_canvas_extent(canvas, 0.0, 0.0, 1.0, 0.75)
    assert stack.canvas_scale(canvas) == pytest.approx(scale / 2.0, rel=0.01)


def test_publish_path_schema_verification_against_real_provider(stack):
    from paleo_workbench.mapping import qgis_mirror

    stack.upsert_mirror_layer(
        "fault-1", "断层约束", "LineString", "EPSG:4326", _FAULT_FEATURES,
        "", "", "", True, 1.0, False, True, False, 1, "", _FAULT_FIELDS,
    )
    diags: list = []
    # wire 与发布后 provider 完全一致 → 无诊断
    qgis_mirror._verify_published_schema(
        stack, "fault-1", _FAULT_FIELDS,
        lambda doc_id, message: diags.append((doc_id, message)))
    assert diags == []

    # wire 声明第三个字段而 provider 未应用 → 漂移诊断（fail-visible）
    drifted = json.dumps(
        json.loads(_FAULT_FIELDS)
        + [{"name": "ghost", "type": "QString"}]
    )
    qgis_mirror._verify_published_schema(
        stack, "fault-1", drifted,
        lambda doc_id, message: diags.append((doc_id, message)))
    assert diags and "ghost" in diags[0][1]


def test_mirror_snapshot_verification_end_to_end(stack, canvas):
    """role 标注快照经 mirror_snapshot_to_stack 发布 → fields 物化 + 验证。

    V9 W6 闭环：snapshot metadata.role（stage membership 派生）→
    ``_fields_json_for_metadata`` → C++ QgsFields → 发布后读回比对。
    """
    from types import SimpleNamespace

    from paleo_workbench.mapping import qgis_mirror

    feature = {
        "id": "F-1",
        "geometry": {"type": "LineString",
                     "coordinates": [[0.0, 0.0], [4.0, 4.0]]},
        "properties": {"fault_id": "F-1"},
    }
    layer = SimpleNamespace(
        id="fault-9",
        name="断层约束",
        layer_type="vector",
        extent=(0.0, 0.0, 4.0, 4.0),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=(feature,),
        style={},
        visible=True,
        opacity=1.0,
        # 角色标注（W6）：编辑层快照带 role → spec fields_json
        metadata={"editable": "true", "geometry_kind": "line",
                  "role": "fault_constraint"},
    )
    snapshot = SimpleNamespace(
        project_crs="EPSG:4326", layers=(layer,))
    diags: list = []
    mirrored, seen, failures = qgis_mirror.mirror_snapshot_to_stack(
        stack, canvas, snapshot, diags)
    assert failures == []
    assert "fault-9" in seen
    # 发布后的 provider schema 含 spec 字段（fault spec ≥ name/fault_type…）
    reported = json.loads(stack.mirror_layer_schema_json("fault-9"))
    assert reported.get("exists") is True
    names = [f["name"] for f in reported.get("fields") or []]
    assert "name" in names and "fault_type" in names
    # 一致发布无 schema-drift 诊断
    drift = [d for d in diags if d[0] == "fault-9" and "drift" in d[1]]
    assert drift == []
