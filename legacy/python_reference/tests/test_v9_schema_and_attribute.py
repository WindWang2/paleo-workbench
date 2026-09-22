"""V9 W5/W6 — provider schema 生产验证与属性表 schema 消费。

覆盖：

* ``_verify_published_schema``：spec wire 与发布后 ``mirror_layer_schema_json``
  比对——一致无诊断、字段名漂移/类型漂移进诊断、自省失败进诊断、
  旧桥（无自省面）跳过；
* ``_fields_json_for_metadata``：未知角色诊断（不再静默 legacy）；
* ``field_descriptors_for_layer``：角色 spec 优先（与镜像 fields_json 同
  权威）→ 模板回落 → 额外键；控件词表（ValueMap/CheckBox/Range）推导；
* ``qgis_schema_parity``：synced/drift/unavailable 三态；
* 属性表对话框：必填空值拒绝、Range 越界拒绝（QGIS provider 约束同源）。
"""
from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping import qgis_mirror
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.ui.workstation.attribute_schema import (
    field_descriptors_for_layer,
    qgis_schema_parity,
)
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


# --------------------------------------------------------------------------- #
# fake stacks
# --------------------------------------------------------------------------- #

_FAULT_FIELDS = json.dumps({
    "fields": [
        {"name": "name", "type": "QString", "alias": "断层名称",
         "constraints": {"not_null": True}},
        {"name": "fault_type", "type": "QString", "alias": "断层性质"},
        {"name": "throw_m", "type": "double"},
    ]
})


class _FakeStack:
    """最小桥 stack 假体：可编程的 schema 自省面。"""

    def __init__(self, reported_fields=None, *, exists=True) -> None:
        self.reported_fields = reported_fields
        self.exists = exists

    def mirror_layer_schema_json(self, doc_id: str) -> str:
        return json.dumps({
            "exists": self.exists,
            "fields": self.reported_fields or [],
        })


def _sink_into(sink: list):
    def _sink(doc_id: str, message: str) -> None:
        sink.append((doc_id, message))
    return _sink


def _spec_fields_wire():
    return _FAULT_FIELDS


def _verify(stack, fields_json=_FAULT_FIELDS):
    diags: list = []
    qgis_mirror._verify_published_schema(
        stack, "fault-1", fields_json, _sink_into(diags))
    return diags


# --------------------------------------------------------------------------- #
# W6 — publish-path schema verification
# --------------------------------------------------------------------------- #

def test_verify_passes_on_matching_schema():
    reported = [
        {"name": "name", "type": "QString"},
        {"name": "fault_type", "type": "QString"},
        {"name": "throw_m", "type": "double"},
    ]
    assert _verify(_FakeStack(reported)) == []


def test_verify_reports_field_name_drift():
    reported = [
        {"name": "name", "type": "QString"},
        {"name": "fault_type", "type": "QString"},
    ]
    diags = _verify(_FakeStack(reported))
    assert diags and "schema drift" in diags[0][1]
    assert diags[0][0] == "fault-1"


def test_verify_reports_type_drift():
    reported = [
        {"name": "name", "type": "QString"},
        {"name": "fault_type", "type": "QString"},
        {"name": "throw_m", "type": "QString"},  # spec 说 double
    ]
    diags = _verify(_FakeStack(reported))
    assert diags and "throw_m" in diags[0][1] and "type" in diags[0][1]


def test_verify_reports_missing_layer():
    diags = _verify(_FakeStack(exists=False))
    assert diags and "missing" in diags[0][1]


def test_verify_skipped_without_introspection_face():
    class _OldStack:
        pass

    assert _verify(_OldStack()) == []


def test_fields_json_unknown_role_records_diagnostic():
    diags: list = []
    result = qgis_mirror._fields_json_for_metadata(
        {"role": "bogus_role"}, on_skip=_sink_into(diags))
    assert result == ""
    assert diags and "bogus_role" in diags[0][1]


def test_fields_json_known_role_silent():
    diags: list = []
    result = qgis_mirror._fields_json_for_metadata(
        {"role": "fault_constraint"}, on_skip=_sink_into(diags))
    assert result  # fault spec 有字段
    assert diags == []


# --------------------------------------------------------------------------- #
# W5 — attribute field descriptors
# --------------------------------------------------------------------------- #

class _FakeController:
    """descriptors 的控制器假体（不依赖 Qt）。"""

    def __init__(self, schema=None, role_value="", features_per_layer=None):
        self._schema = schema or {}
        self._role = role_value
        self.layer = lambda layer_id: None
        self.features_per_layer = features_per_layer or {}
        from types import SimpleNamespace

        _features = tuple(
            type("F", (), {"attributes": dict(attrs)})()
            for attrs in self.features_per_layer.get("L1", ())
        )
        self._ns = SimpleNamespace(
            edit_session=None,
            features=lambda: _features,
        )
        self.layer = lambda layer_id: self._ns

    def layer_schema(self, layer_id):
        return self._schema

    def role_of_layer(self, layer_id):
        return self._role


def test_descriptors_prefer_role_spec_over_template():
    controller = _FakeController(role_value="fault_constraint")
    descriptors = field_descriptors_for_layer(controller, "L1")
    spec_keys = [d.key for d in descriptors]
    assert "name" in spec_keys and "fault_type" in spec_keys
    by_key = {d.key: d for d in descriptors}
    assert by_key["name"].origin == "spec"
    assert by_key["fault_type"].origin == "spec"
    # 控件词表：choices → ValueMap
    assert by_key["fault_type"].editor_widget == "ValueMap"
    assert by_key["fault_type"].choices  # 闭合值域随描述符走


def test_descriptors_fall_back_to_template_without_role():
    controller = _FakeController(
        schema={"fields": [{"name": "name", "label": "名称", "kind": "text"}]})
    descriptors = field_descriptors_for_layer(controller, "L1")
    assert descriptors and descriptors[0].origin == "template"
    assert descriptors[0].key == "name"


def test_descriptors_append_extra_feature_keys():
    controller = _FakeController(
        features_per_layer={"L1": ({"custom_key": "v"},)})
    descriptors = field_descriptors_for_layer(controller, "L1")
    extras = [d for d in descriptors if d.origin == "extra"]
    assert any(d.key == "custom_key" for d in extras)


def test_parity_synced_drift_unavailable():
    descriptors = field_descriptors_for_layer(
        _FakeController(role_value="fault_constraint"), "L1")
    want = [d.key for d in descriptors if d.origin != "extra"]

    class _Canvas:
        def __init__(self, stack):
            self.stack = stack

    reported = [{"name": k, "type": "QString"} for k in want]
    state, detail = qgis_schema_parity(_Canvas(_FakeStack(reported)), "L1", descriptors)
    assert state == "synced"

    state, detail = qgis_schema_parity(
        _Canvas(_FakeStack(reported[:1])), "L1", descriptors)
    assert state == "drift"

    state, detail = qgis_schema_parity(_Canvas(None), "L1", descriptors)
    assert state == "unavailable"


# --------------------------------------------------------------------------- #
# W5 — dialog constraint feedback（需 Qt）
# --------------------------------------------------------------------------- #

@pytest.fixture()
def controller(qtbot):
    return CompositeEditController(project_crs="EPSG:4326")


def _open_session_with_feature(controller, *, kind="line", role=None):
    layer = controller.create_layer("L", kind)
    if role is not None:
        controller.set_role_lookup(
            lambda lid, _r=role: _r if lid == layer.id else None)
    session = controller.ensure_layer_session(layer.id)[0]
    from paleo_workbench.mapping.vector_layer import VectorFeature

    session.add_feature(
        VectorFeature("f1", {"type": "LineString",
                             "coordinates": [[0, 0], [1, 1]]}, {}))
    return layer


def test_dialog_rejects_empty_required_field(qtbot, controller):
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    layer = _open_session_with_feature(
        controller, role=LayerRole.FAULT_CONSTRAINT)
    dialog = CompositeAttributeTableDialog(controller, layer.id)
    qtbot.addWidget(dialog)
    required = next(
        (c for c in dialog._columns() if c.required and c.origin == "spec"), None)
    if required is None:
        pytest.skip("fault spec 无必填字段——词表变化时更新本测试")
    written = dialog._write_attribute("f1", required.key, required.kind, "")
    assert written is False
    assert "必填" in dialog._info.text()


def test_dialog_rejects_out_of_range_value(qtbot, controller):
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    layer = _open_session_with_feature(
        controller, role=LayerRole.FAULT_CONSTRAINT)
    dialog = CompositeAttributeTableDialog(controller, layer.id)
    qtbot.addWidget(dialog)
    ranged = next(
        (c for c in dialog._columns()
         if c.value_range is not None), None)
    if ranged is None:
        pytest.skip("fault spec 无 Range 字段——词表变化时更新本测试")
    low, high = ranged.value_range
    written = dialog._write_attribute(
        "f1", ranged.key, ranged.kind, str(float(high) + 1000.0))
    assert written is False
    assert "超出范围" in dialog._info.text()


def test_dialog_numeric_sorting_payload(qtbot, controller):
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    layer = _open_session_with_feature(controller, kind="polygon")
    dialog = CompositeAttributeTableDialog(controller, layer.id)
    qtbot.addWidget(dialog)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableWidgetItem

    field = type(
        "F", (), {"key": "depth", "label": "深度", "kind": "real",
                  "numeric": True})()
    item = QTableWidgetItem()
    dialog._apply_display(item, field, 300.0)
    assert item.data(Qt.ItemDataRole.DisplayRole) == 300.0  # 数值排序键
    dialog._apply_display(item, field, "abc")
    assert item.data(Qt.ItemDataRole.DisplayRole) == "abc"  # 不可解析保持文本
