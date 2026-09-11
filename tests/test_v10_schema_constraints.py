"""V10 M-I — schema 去重后的唯一约束与控件推断单一权威验证。

覆盖：

* **控件推断单一权威**：``attribute_schema`` 的描述符不再自带一份推断
  规则——对注册表全部角色，spec 派生列的 ``editor_widget`` 必须与
  ``qgis_layer_schema._editor_widget_for``（镜像 ``fields_json`` 同源）
  逐字段一致；词表钉住（choices→ValueMap、bool→CheckBox、
  real+value_range→Range、纯文本→TextEdit——此前纯文本为空串，V10 起
  与 QGIS wire 对齐）；
* **SpecField.unique → AttributeFieldMeta.unique 流转**；
* **属性表 unique 约束写入路径**：同层其他要素已持有该值时拒绝（与
  必填/Range 同一拒绝 UX）、自身当前值不冲突、空值不占用唯一域、数值
  按 float 归一比较、未置 unique 标志的字段不做扫描。

表达式约束（expression）不实现——provider 侧职责，会话保持 schema
无关（见 ``composite_attribute_table._write_attribute`` docstring）。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.qgis_layer_schema import (
    _editor_widget_for,
    fields_json_for_spec,
)
from paleo_workbench.mapping_workspace.geological_layer_spec import (
    GeologicalLayerSpec,
    SpecField,
    spec_for_role,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.ui.workstation.attribute_schema import (
    AttributeFieldMeta,
    field_descriptors_for_layer,
)


class _FakeController:
    """descriptors 的控制器假体（不依赖 Qt，同 test_v9_schema_and_attribute）。"""

    def __init__(self, role_value: str = "") -> None:
        self._role = role_value

    def layer_schema(self, layer_id):
        return {}

    def role_of_layer(self, layer_id):
        return self._role

    def layer(self, layer_id):
        return None


def _spec_descriptors_for(role: LayerRole) -> dict[str, AttributeFieldMeta]:
    descriptors = field_descriptors_for_layer(
        _FakeController(role_value=role.value), "L1")
    return {d.key: d for d in descriptors if d.origin == "spec"}


# --------------------------------------------------------------------------- #
# 控件推断单一权威（Part 1）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("role", list(LayerRole), ids=lambda r: r.value)
def test_descriptor_widgets_match_single_inference_authority(role):
    """全部角色：描述符控件 == _editor_widget_for == 镜像 fields_json wire。"""
    try:
        spec = spec_for_role(role)
    except KeyError:
        pytest.skip("角色不在注册表")
    if not spec.fields:
        pytest.skip("spec 无字段（栅格/自由图层）")
    descriptors = _spec_descriptors_for(role)
    assert descriptors, f"{role.value} spec 无字段"
    wire = {entry["name"]: entry for entry in fields_json_for_spec(spec)}
    for field in spec.fields:
        expected = _editor_widget_for(field)
        assert descriptors[field.name].editor_widget == expected
        assert wire[field.name]["editor_widget"] == expected


def test_widget_vocabulary_pins():
    """词表钉住：ValueMap / CheckBox / Range / 纯文本 TextEdit。"""
    fault = _spec_descriptors_for(LayerRole.FAULT_CONSTRAINT)
    assert fault["fault_type"].editor_widget == "ValueMap"
    assert fault["active"].editor_widget == "CheckBox"
    direction = _spec_descriptors_for(LayerRole.PROVENANCE_DIRECTION)
    assert direction["azimuth_deg"].editor_widget == "Range"
    # 纯文本字段此前推断为空串；V10 起与 QGIS wire 一致为 TextEdit
    # （本测试即该收敛的钉子）。
    annotation = _spec_descriptors_for(LayerRole.INTERPRETATION_ANNOTATION)
    assert annotation["text"].editor_widget == "TextEdit"


def test_spec_unique_flag_flows_into_meta(monkeypatch):
    """SpecField.unique 必须流入 AttributeFieldMeta.unique（写入路径依据）。"""
    import paleo_workbench.mapping_workspace.geological_layer_spec as spec_module

    custom = GeologicalLayerSpec(
        spec_id="test-unique-v1",
        role=LayerRole.INTERPRETATION_ANNOTATION,
        geometry_kind="point",
        title="测试唯一字段",
        fields=(
            SpecField(name="station", label="测站", kind="text", unique=True),
            SpecField(name="note", label="备注", kind="text"),
        ),
    )
    monkeypatch.setattr(spec_module, "spec_for_role", lambda _role: custom)
    descriptors = field_descriptors_for_layer(
        _FakeController(role_value=LayerRole.INTERPRETATION_ANNOTATION.value), "L1")
    by_key = {d.key: d for d in descriptors}
    assert by_key["station"].unique is True
    assert by_key["note"].unique is False


# --------------------------------------------------------------------------- #
# 属性表 unique 约束写入路径（Part 2，需 Qt）
# --------------------------------------------------------------------------- #

@pytest.fixture()
def controller(qtbot):
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    return CompositeEditController(project_crs="EPSG:4326")


def _dialog_with_unique_column(qtbot, controller, *, key="station", kind="text"):
    """两个要素 + 注入 unique 列的属性表（词表暂无 unique 字段，经缓存注入）。"""
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    layer = controller.create_layer("测站层", "point")
    controller.import_layer_features(layer.id, [
        VectorFeature("f1", {"type": "Point", "coordinates": [0.0, 0.0]},
                      {key: "A"}),
        VectorFeature("f2", {"type": "Point", "coordinates": [1.0, 1.0]},
                      {key: "B"}),
    ])
    layer.start_editing()
    dialog = CompositeAttributeTableDialog(controller, layer.id)
    qtbot.addWidget(dialog)
    dialog._columns_cache = (
        AttributeFieldMeta(key=key, label="测站", kind=kind, unique=True),
    )
    return layer, dialog


def test_unique_conflict_rejected(qtbot, controller):
    layer, dialog = _dialog_with_unique_column(qtbot, controller)

    written = dialog._write_attribute("f2", "station", "text", "A")

    assert written is False
    assert "unique" in dialog._info.text()
    # 权威会话未写入
    assert layer.edit_session.feature("f2").attributes["station"] == "B"


def test_unique_allows_distinct_value(qtbot, controller):
    layer, dialog = _dialog_with_unique_column(qtbot, controller)

    written = dialog._write_attribute("f2", "station", "text", "C")

    assert written is None
    assert layer.edit_session.feature("f2").attributes["station"] == "C"


def test_unique_allows_rewriting_own_current_value(qtbot, controller):
    layer, dialog = _dialog_with_unique_column(qtbot, controller)

    # f1 自身当前值 "A" 不构成冲突（原地重写合法）
    written = dialog._write_attribute("f1", "station", "text", "A")

    assert written is None
    assert layer.edit_session.feature("f1").attributes["station"] == "A"


def test_unique_ignores_empty_values(qtbot, controller):
    layer, dialog = _dialog_with_unique_column(qtbot, controller)

    # 空值不占用唯一域（NULL 语义：与另一要素的 "A" 不撞车）
    written = dialog._write_attribute("f2", "station", "text", "")

    assert written is None
    assert layer.edit_session.feature("f2").attributes["station"] == ""


def test_unique_compares_numerics_by_value(qtbot, controller):
    layer, dialog = _dialog_with_unique_column(
        qtbot, controller, key="elevation", kind="real")
    session = layer.edit_session
    session.change_attribute("f1", "elevation", 100.0)

    # "100.0" 与 100.0 同值 → 拒绝
    assert dialog._write_attribute("f2", "elevation", "real", "100.0") is False
    # 数值不同 → 放行
    assert dialog._write_attribute("f2", "elevation", "real", "200.5") is None
    assert session.feature("f2").attributes["elevation"] == 200.5


def test_non_unique_field_allows_duplicate(qtbot, controller):
    """未置 unique 标志的字段不扫描、不拒绝（O(n) 只发生在标志置位时）。"""
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.ui.workstation.composite_attribute_table import (
        CompositeAttributeTableDialog,
    )

    layer = controller.create_layer("普通层", "point")
    controller.import_layer_features(layer.id, [
        VectorFeature("f1", {"type": "Point", "coordinates": [0.0, 0.0]},
                      {"station": "A"}),
        VectorFeature("f2", {"type": "Point", "coordinates": [1.0, 1.0]},
                      {"station": "B"}),
    ])
    layer.start_editing()
    dialog = CompositeAttributeTableDialog(controller, layer.id)
    qtbot.addWidget(dialog)
    dialog._columns_cache = (
        AttributeFieldMeta(key="station", label="测站", kind="text"),
    )

    assert dialog._write_attribute("f2", "station", "text", "A") is None
    assert layer.edit_session.feature("f2").attributes["station"] == "A"
