# -*- coding: utf-8 -*-
"""换相的编辑会话路由（V12 续）：原生镜像缓冲写入 + 原生脏态。

背景（用户报障 + 新需求）：

* 原生编辑会话期间 ``ensure_layer_session`` 直接拒绝 → 编辑中换不了相
  （本次要支持的正是「编辑支持弹窗更换相」）；
* ``dirty`` 只看 Python 会话 → 原生会话有未提交修改时「保存编辑」恒灰
  （用户报的「保存是灰色的」）。

本文件用 fake stack（无桥）钉住宿主侧路由与判词；真桥面在
``-m qgis`` 用例（``tests/test_qgis_mirror_attributes_v12.py``）。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping.edit_session_set import reset_session_set
from paleo_workbench.mapping.qgis_mirror import reset_publish_ledger

QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _clean_session_state():
    reset_publish_ledger()
    reset_session_set()
    yield
    reset_publish_ledger()
    reset_session_set()


class FakeNativeStack:
    """原生编辑面（能力可裁剪：``with_attribute_write=False`` = 旧桥）。"""

    def __init__(self, *, with_attribute_write: bool = True,
                 with_dirty_query: bool = True) -> None:
        self.editing: set[str] = set()
        self.calls: list[tuple] = []
        self.attribute_calls: list[tuple] = []
        self.dirty_flags: dict[str, bool] = {}
        self.mirror: dict[str, list[dict]] = {}
        self._with_attribute_write = with_attribute_write
        self._with_dirty_query = with_dirty_query

    # -- 会话面 -----------------------------------------------------------
    def start_mirror_layer_editing(self, doc_id: str) -> str:
        self.calls.append(("start", doc_id))
        self.editing.add(doc_id)
        return ""

    def commit_mirror_layer(self, doc_id: str) -> str:
        self.editing.discard(doc_id)
        return ""

    def roll_back_mirror_layer(self, doc_id: str) -> str:
        self.editing.discard(doc_id)
        return ""

    def mirror_features_json(self, doc_id: str, *_args) -> str:
        return json.dumps({
            "exists": True,
            "features": self.mirror.get(doc_id, []),
        })

    def set_committed_callback(self, *_args) -> None:
        return None


def _install_attribute_ops(stack: FakeNativeStack) -> None:
    """把可选面挂到实例上（缺省即旧桥形态：属性都不存在）。"""
    if stack._with_attribute_write:
        def _set(doc_id, ids_json, attrs_json) -> str:
            ids = json.loads(ids_json)
            attrs = json.loads(attrs_json)
            stack.attribute_calls.append((doc_id, tuple(ids), dict(attrs)))
            for record in stack.mirror.get(doc_id, []):
                if str(record.get("id")) in set(ids):
                    record.setdefault("properties", {}).update(attrs)
                    record["properties"]["__pwb_fid"] = str(record.get("id"))
            stack.dirty_flags[doc_id] = True
            return ""

        stack.set_mirror_feature_attributes = _set  # type: ignore[attr-defined]
    if stack._with_dirty_query:
        stack.mirror_layer_dirty = (  # type: ignore[attr-defined]
            lambda doc_id: bool(stack.dirty_flags.get(doc_id, False)))


@pytest.fixture
def native_doc(qtbot, tmp_path):
    """相带草稿图层 + 已开启的原生编辑会话（fake stack）。"""
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    project = ProjectDocument.new("换相路由", region="T1")
    project.meta.project_root = str(tmp_path)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    layer = doc.edit_controller.create_layer("相带草稿", "polygon", template="facies")
    doc.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer.id), role=LayerRole.INITIAL_FACIES_DRAFT))
    doc.edit_controller.set_active_layer(str(layer.id))
    doc.edit_controller.import_layer_features(str(layer.id), [
        VectorFeature(
            feature_id="f1",
            geometry={"type": "Polygon", "coordinates": [[
                [0, 0], [2, 0], [2, 2], [0, 0]]]},
            attributes={"facies": "三角洲前缘"},
        ),
    ])
    stack = FakeNativeStack()
    _install_attribute_ops(stack)
    stack.mirror[str(layer.id)] = [{
        "id": "f1",
        "geometry": {"type": "Polygon", "coordinates": [[
            [0, 0], [2, 0], [2, 2], [0, 0]]]},
        "properties": {"__pwb_fid": "f1", "facies": "三角洲前缘"},
    }]
    ok, reason = doc.edit_controller.native_editing.open(
        stack, layer, gate=None, canvas_address=0)
    assert ok, reason
    doc._sync_action_state()
    return doc, str(layer.id), stack


# --------------------------------------------------------------------------- #
# 路由：原生会话内换相走镜像缓冲
# --------------------------------------------------------------------------- #

def test_apply_facies_selection_writes_through_native_buffer(native_doc):
    doc, layer_id, stack = native_doc
    controller = doc.edit_controller
    ok, reason = controller.apply_facies_selection(
        layer_id, ["f1"], {"facies": "滨浅湖", "sub_facies": "", "micro_facies": ""})
    assert ok, reason
    assert stack.attribute_calls == [
        (layer_id, ("f1",), {"facies": "滨浅湖", "sub_facies": "",
                             "micro_facies": "", "level": "facies"})]
    # 编辑权威仍在原生缓冲：不得因这次写入开第二个 Python 会话。
    assert controller.layer(layer_id).edit_session is None


def test_apply_facies_selection_single_id_matches_legacy_signature(native_doc):
    doc, layer_id, stack = native_doc
    ok, reason = doc.edit_controller.apply_facies_selection(
        layer_id, "f1", {"facies": "滨浅湖"})
    assert ok, reason
    assert stack.attribute_calls[0][1] == ("f1",)


def test_apply_facies_selection_bulk_writes_every_feature(native_doc):
    doc, layer_id, stack = native_doc
    stack.mirror[layer_id].append({
        "id": "f2",
        "geometry": {"type": "Polygon", "coordinates": [[
            [3, 3], [4, 3], [4, 4], [3, 3]]]},
        "properties": {"__pwb_fid": "f2", "facies": "三角洲前缘"},
    })
    ok, reason = doc.edit_controller.apply_facies_selection(
        layer_id, ["f1", "f2"], {"facies": "滨浅湖"})
    assert ok, reason
    assert stack.attribute_calls[0][1] == ("f1", "f2")


def test_apply_facies_selection_without_bridge_op_refuses_honestly(
        qtbot, tmp_path, monkeypatch):
    """旧桥（无属性写 op）：拒绝且原因自曝重建桥扩展，不静默丢失。"""
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    project = ProjectDocument.new("旧桥", region="T1")
    project.meta.project_root = str(tmp_path)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    layer = doc.edit_controller.create_layer("相带草稿", "polygon", template="facies")
    doc.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer.id), role=LayerRole.INITIAL_FACIES_DRAFT))
    doc.edit_controller.set_active_layer(str(layer.id))
    doc.edit_controller.import_layer_features(str(layer.id), [VectorFeature(
        feature_id="f1",
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        attributes={"facies": "三角洲前缘"})])
    stack = FakeNativeStack(with_attribute_write=False, with_dirty_query=False)
    _install_attribute_ops(stack)
    ok, reason = doc.edit_controller.native_editing.open(stack, layer, gate=None)
    assert ok, reason
    ok, reason = doc.edit_controller.apply_facies_selection(
        layer_id=str(layer.id), feature_ids=["f1"], selection={"facies": "滨浅湖"})
    assert ok is False
    assert "qgis_render_bridge" in reason


# --------------------------------------------------------------------------- #
# 原生脏态：保存/回滚不再恒灰
# --------------------------------------------------------------------------- #

def test_native_pending_changes_feed_dirty_fact(native_doc):
    doc, layer_id, stack = native_doc
    assert doc.tool_context().dirty is False
    assert doc.tool_availability()["save_edits"].enabled is False
    ok, reason = doc.edit_controller.apply_facies_selection(
        layer_id, ["f1"], {"facies": "滨浅湖"})
    assert ok, reason
    ctx = doc.tool_context()
    assert ctx.editing is True and ctx.dirty is True, "原生缓冲的修改必须进脏态"
    doc._sync_action_state()
    availability = doc.tool_availability()
    assert availability["save_edits"].enabled is True
    assert availability["rollback"].enabled is True


def test_unknown_dirty_query_does_not_fabricate_dirty(native_doc):
    """旧桥无 dirty 查询 → None（未知）不得被当成 True/False 造假。"""
    doc, layer_id, stack = native_doc
    del stack.mirror_layer_dirty  # type: ignore[attr-defined]
    assert doc.edit_controller.native_editing.pending_changes(layer_id) is None
    assert doc.tool_context().dirty is False
