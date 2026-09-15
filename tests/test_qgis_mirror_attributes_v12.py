# -*- coding: utf-8 -*-
"""真桥面：编辑期属性写入 + 原生脏态（V12 换相弹窗的功能底座）。

宿主侧路由在 ``tests/test_facies_change_native_v12.py``（fake stack，无桥）；
本文件在真实 QGIS 桥上验三件事：

1. ``set_mirror_feature_attributes`` 写进**镜像编辑缓冲**（读回即新值，
   宿主 id 映射不变），且 undo 可撤销（一宏 = 一次 Ctrl+Z）；
2. ``mirror_layer_dirty`` 反映未提交修改（写前 False → 写后 True →
   回滚/提交后会话关闭即 False）——用户报的「保存编辑恒灰」的事实来源；
3. ``capability_manifest`` 自曝两个新能力 flag（旧桥据此诚实降级）。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FIELDS = json.dumps([{"name": "facies", "type": "QString"},
                      {"name": "sub_facies", "type": "QString"}])

_SQUARES = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             [0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]]},
         "properties": {"__pwb_fid": "fa", "facies": "三角洲前缘"}},
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             [3.0, 3.0], [5.0, 3.0], [5.0, 5.0], [3.0, 3.0]]]},
         "properties": {"__pwb_fid": "fb", "facies": "滨浅湖"}},
    ],
}


@pytest.fixture()
def editing_stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    stack.initialize()
    stack.upsert_mirror_layer(
        "doc-facies", "相带草稿", "Polygon", "EPSG:4326",
        json.dumps(_SQUARES), "", "", "", True, 1.0,
        is_reference=False, is_editable=True, data_revision=1,
        fields_json=_FIELDS)
    assert stack.start_mirror_layer_editing("doc-facies") == ""
    yield stack
    stack.shutdown()


def _attrs_of(stack, host_id):
    payload = json.loads(stack.mirror_features_json("doc-facies", 0))
    assert payload["exists"]
    for feature in payload["features"]:
        if str(feature.get("id")) == host_id:
            return dict(feature.get("properties") or {})
    raise AssertionError(f"{host_id} not in readback")


def test_capability_manifest_declares_attribute_write_and_dirty(monkeypatch):
    import qgis_render_bridge

    features = set(qgis_render_bridge.capability_manifest()["features"])
    assert {"mirror_attribute_write", "mirror_dirty_query"} <= features


def test_set_attributes_writes_into_edit_buffer(editing_stack):
    stack = editing_stack
    assert stack.mirror_layer_dirty("doc-facies") is False
    error = stack.set_mirror_feature_attributes(
        "doc-facies", json.dumps(["fa"]),
        json.dumps({"facies": "滨浅湖", "sub_facies": ""}))
    assert error == ""
    assert _attrs_of(stack, "fa")["facies"] == "滨浅湖"
    assert _attrs_of(stack, "fb")["facies"] == "滨浅湖"
    # 编辑缓冲被改动 → 宿主 dirty 事实成立（保存/回滚不再恒灰）。
    assert stack.mirror_layer_dirty("doc-facies") is True


def test_set_attributes_bulk_batch_and_host_ids_stable(editing_stack):
    stack = editing_stack
    assert stack.set_mirror_feature_attributes(
        "doc-facies", json.dumps(["fb", "fa"]),
        json.dumps({"facies": "深水盆地"})) == ""
    assert _attrs_of(stack, "fa")["facies"] == "深水盆地"
    assert _attrs_of(stack, "fb")["facies"] == "深水盆地"


def test_set_attributes_is_one_undoable_macro(editing_stack):
    stack = editing_stack
    assert stack.set_mirror_feature_attributes(
        "doc-facies", json.dumps(["fa", "fb"]),
        json.dumps({"facies": "深水盆地"})) == ""
    assert stack.undo_mirror_edit("doc-facies") == ""
    # 一次撤销即回到两个要素的原值（一宏语义）。
    assert _attrs_of(stack, "fa")["facies"] == "三角洲前缘"
    assert _attrs_of(stack, "fb")["facies"] == "滨浅湖"


def test_set_attributes_rejects_unknown_field_and_unknown_feature(editing_stack):
    stack = editing_stack
    error = stack.set_mirror_feature_attributes(
        "doc-facies", json.dumps(["fa"]), json.dumps({"nope": "x"}))
    assert "no matching field" in error
    error = stack.set_mirror_feature_attributes(
        "doc-facies", json.dumps(["missing"]), json.dumps({"facies": "x"}))
    assert "unknown feature id" in error
    # 拒绝路径不留半改缓冲。
    assert stack.mirror_layer_dirty("doc-facies") is False


def test_set_attributes_requires_open_edit_session(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    stack.initialize()
    try:
        stack.upsert_mirror_layer(
            "doc-idle", "相带草稿", "Polygon", "EPSG:4326",
            json.dumps(_SQUARES), "", "", "", True, 1.0,
            is_reference=False, is_editable=True, data_revision=1,
            fields_json=_FIELDS)
        error = stack.set_mirror_feature_attributes(
            "doc-idle", json.dumps(["fa"]), json.dumps({"facies": "x"}))
        assert "not in an edit session" in error
        assert stack.mirror_layer_dirty("doc-idle") is False
    finally:
        stack.shutdown()


def test_host_change_facies_inside_native_session_end_to_end(
        qtbot, tmp_path, monkeypatch):
    """用户故事全链：开始编辑（原生）→ 弹窗换相 → 确定 → 保存。

    「保存编辑」在原生会话有未提交修改时必须是可用的，且换相写的是镜像
    缓冲（Python 真源在提交后对齐）。
    """
    from PySide6.QtWidgets import QDialog

    from paleo_workbench.mapping.facies_taxonomy import FaciesTaxonomy
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation import facies_selector
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    project = ProjectDocument.new("换相 e2e", region="T1")
    project.meta.project_root = str(tmp_path)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    # role= 是镜像字段 schema 的来源（无 role 的 legacy 层桥侧丢属性留几何
    # ——换相要的是 facies 字段本身）。
    layer = controller.create_layer(
        "相带草稿", "polygon", template="facies",
        role=LayerRole.INITIAL_FACIES_DRAFT)
    doc.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer.id), role=LayerRole.INITIAL_FACIES_DRAFT))
    controller.set_active_layer(str(layer.id))
    controller.import_layer_features(str(layer.id), [VectorFeature(
        feature_id="f1",
        geometry={"type": "Polygon", "coordinates": [[
            [0, 0], [2, 0], [2, 2], [0, 0]]]},
        attributes={"facies": "三角洲前缘"})])
    controller.layer(str(layer.id)).set_selection(("f1",))
    doc._sync_action_state()

    assert controller.start_editing() is None or controller.editing
    native_open = controller.native_editing.is_open(str(layer.id))

    target = FaciesTaxonomy.builtin().names("facies")[-1]
    real_dialog = facies_selector.FaciesChangeDialog

    class _Probe(real_dialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.select_facies(target)

        def exec(self):  # noqa: A003 — Qt 契约
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(facies_selector, "FaciesChangeDialog", _Probe)
    doc.assign_facies_to_selection(str(layer.id))

    # 落盘字段名按图层实际 schema 解析（角色 spec 图层是 facies_name，
    # 模板图层是 facies）——断言与写入同源，不假设其一。
    from paleo_workbench.mapping.facies_taxonomy import resolve_facies_field

    stack = controller.native_editing.stack_for(str(layer.id))
    schema = json.loads(stack.mirror_layer_schema_json(str(layer.id))) if native_open else {}
    available = {str(f.get("name")) for f in (schema.get("fields") or [])}
    field = resolve_facies_field("facies", available) if available else "facies"
    assert field, "镜像 schema 里应当有相字段"

    if native_open:
        # 编辑权威在镜像缓冲：读回即新相（Python 真源仍是提交前旧态）。
        payload = json.loads(stack.mirror_features_json(str(layer.id), 0))
        values = {str(f["id"]): str((f.get("properties") or {}).get(field))
                  for f in payload["features"]}
        assert values.get("f1") == target, (values, field)
        ctx = doc.tool_context()
        assert ctx.editing is True and ctx.dirty is True
        doc._sync_action_state()
        assert doc.tool_availability()["save_edits"].enabled is True

    assert controller.save_edits() is None
    features = {f.feature_id: f.attributes.get(field)
                for f in controller.layer(str(layer.id)).features()}
    assert features.get("f1") == target, "保存后 Python 真源对齐镜像"


def test_rollback_clears_dirty_fact(editing_stack):
    stack = editing_stack
    assert stack.set_mirror_feature_attributes(
        "doc-facies", json.dumps(["fa"]), json.dumps({"facies": "滨浅湖"})) == ""
    assert stack.mirror_layer_dirty("doc-facies") is True
    assert stack.roll_back_mirror_layer("doc-facies") == ""
    assert stack.mirror_layer_dirty("doc-facies") is False
    assert _attrs_of(stack, "fa")["facies"] == "三角洲前缘"
