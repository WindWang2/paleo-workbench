"""复制图层回归（V12 duplicate 契约）。

- 逐字节一致：深拷贝 + 实时视图（会话所见），不做任何修复/归一——
  有效性是「修复无效几何」工具的职责，复制不得静默改数据。
- 老工程成员资格缺失时回落控制器角色，预测源副本落解释草稿。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.mapping.geometry_operations import validate
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController

BOWTIE = {
    "type": "Polygon",
    "coordinates": [
        [[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]]
    ],
}
SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    ],
}


def _controller() -> CompositeEditController:
    return CompositeEditController(project_crs="EPSG:32650")


def _layer_with(controller: CompositeEditController, geometry: dict, **kwargs):
    layer = controller.create_layer("相带", "polygon", **kwargs)
    controller.import_layer_features(
        layer.id, [VectorFeature("bad", dict(geometry))])
    return layer


def _as_lists(value):
    if isinstance(value, dict):
        return {key: _as_lists(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_lists(item) for item in value]
    return value


def test_duplicate_preserves_geometry_byte_identical() -> None:
    """逐字节契约：无效几何原样保留（不静默修复），由修复工具显式处理。"""
    controller = _controller()
    assert not validate(BOWTIE).valid
    layer = _layer_with(controller, BOWTIE)
    copy = controller.duplicate_layer(layer.id)
    assert copy is not None
    copied = list(copy.features())
    assert len(copied) == 1
    assert _as_lists(copied[0].geometry) == BOWTIE
    assert not validate(dict(copied[0].geometry)).valid
    # 修复工具仍能修副本（职责分离不断链）。
    assert controller.repair_layer_geometries(copy.id) >= 1
    assert validate(
        dict(list(copy.edit_session.features())[0].geometry)).valid


def test_duplicate_valid_geometry_byte_identical() -> None:
    controller = _controller()
    layer = _layer_with(controller, SQUARE)
    copy = controller.duplicate_layer(layer.id)
    assert copy is not None
    copied = list(copy.features())
    assert _as_lists(copied[0].geometry) == SQUARE


def test_duplicate_deepcopy_independent() -> None:
    controller = _controller()
    layer = _layer_with(controller, SQUARE)
    copy = controller.duplicate_layer(layer.id)
    assert copy is not None
    copied = list(copy.features())[0]
    source = list(layer.features())[0]
    # 嵌套坐标/属性/样式对象互不共享（冻结元组比较用 ==，身份用 is）。
    assert copied.geometry is not source.geometry
    assert copied.geometry["coordinates"] is not source.geometry["coordinates"]
    assert copied.attributes is not source.attributes
    assert copy.style is not layer.style
    assert _as_lists(copied.geometry) == _as_lists(source.geometry)


def test_duplicate_copies_live_session_view() -> None:
    """会话打开时复制所见即所得：快照显示会话视图，副本必须一致。

    此前副本只读已提交基线——源有未提交编辑时副本缺要素，基线为空
    时副本就是空白层（树上可见、画布空白，修复显示“未发现”）。
    """
    controller = _controller()
    layer = _layer_with(controller, SQUARE)
    controller.set_active_layer(layer.id)
    controller.start_editing()
    layer.edit_session.add_feature(VectorFeature(
        "live",
        {"type": "Polygon", "coordinates": [
            [[5.0, 5.0], [6.0, 5.0], [6.0, 6.0], [5.0, 6.0], [5.0, 5.0]]] }))
    copy = controller.duplicate_layer(layer.id)
    assert copy is not None
    assert copy.edit_session is None  # 副本自带完整内容，不继承会话
    snapshots = {snap.id: snap for snap in controller.snapshot_layers()}
    assert len(snapshots[copy.id].features) == len(snapshots[layer.id].features) == 2


def test_duplicate_raw_protected_via_controller_role_fallback() -> None:
    """成员资格缺失的老工程：控制器角色仍是 RAW 保护 → 副本落解释草稿。"""
    from paleo_workbench.mapping_workspace.controller import MappingStageController
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    controller = _controller()
    stage = MappingStageController()

    class _Composite:
        edit_controller = controller
        stage_controller = stage
        _project = object()

        class status_message:
            @classmethod
            def emit(cls, text: str) -> None:
                pass

    host = _Composite()
    layer = controller.create_layer(
        "测井预测相", "polygon", role=LayerRole.WELL_FACIES_PREDICTION)
    assert stage.state.membership(layer.id) is None  # 老工程：无成员资格
    assert controller.layer_role(layer.id) == "well_facies_prediction"
    CompositeDocument._duplicate_vector_layer(host, layer.id)

    copies = [l for l in controller._layers.values() if l.name.endswith(" 副本")]
    assert len(copies) == 1
    record = stage.state.membership(copies[0].id)
    assert record is not None
    assert record.role == LayerRole.INITIAL_FACIES_DRAFT
    assert controller.layer_role(copies[0].id) == "initial_facies_draft"


def _staged():
    from paleo_workbench.mapping_workspace.controller import MappingStageController

    controller = _controller()
    stage = MappingStageController()
    return controller, stage


def test_place_copy_adjacent_same_group() -> None:
    """同组：副本登记覆盖并插到源之后一位。"""
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord

    controller, stage = _staged()
    src = controller.create_layer("源", "polygon")
    controller.set_layer_role(src.id, LayerRole.FACIES_BOUNDARY)
    stage.state.set_membership(LayerMembershipRecord(
        layer_id=src.id, role=LayerRole.FACIES_BOUNDARY))
    group = stage.group_controller
    group._group_orders["phase2.constraints"] = [src.id, "other-id"]
    copy = controller.duplicate_layer(src.id)
    assert copy is not None
    stage.state.set_membership(LayerMembershipRecord(
        layer_id=copy.id, role=LayerRole.FACIES_BOUNDARY))
    assert group.place_copy_adjacent(src.id, copy.id) == "phase2.constraints"
    assert group._placements[copy.id] == "phase2.constraints"
    assert group._group_orders["phase2.constraints"] == [
        src.id, copy.id, "other-id"]


def test_place_copy_adjacent_incompatible_goes_home() -> None:
    """语义不相容（草稿进预测组）：不硬塞、不登记覆盖，回家。"""
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord

    controller, stage = _staged()
    src = controller.create_layer(
        "地震预测相", "polygon", role=LayerRole.SEISMIC_FACIES_PREDICTION)
    stage.state.set_membership(LayerMembershipRecord(
        layer_id=src.id, role=LayerRole.SEISMIC_FACIES_PREDICTION))
    group = stage.group_controller
    group._group_orders["phase1.seismic_predictions"] = [src.id]
    copy = controller.duplicate_layer(src.id)
    assert copy is not None
    stage.state.set_membership(LayerMembershipRecord(
        layer_id=copy.id, role=LayerRole.INITIAL_FACIES_DRAFT))
    assert group.place_copy_adjacent(src.id, copy.id) == ""
    assert copy.id not in group._placements
    assert copy.id not in group._group_orders["phase1.seismic_predictions"]


def test_draft_spec_covers_prediction_fields() -> None:
    """草稿字段是预测字段的超集：预测→草稿复制不丢属性。"""
    from paleo_workbench.mapping_workspace.geological_layer_spec import spec_for_role

    draft = {f.name for f in spec_for_role(LayerRole.INITIAL_FACIES_DRAFT).fields}
    for role in (LayerRole.WELL_FACIES_PREDICTION,
                 LayerRole.SEISMIC_FACIES_PREDICTION):
        missing = [f.name for f in spec_for_role(role).fields
                   if f.name not in draft]
        assert missing == [], (role, missing)


def test_duplicate_roundtrip_through_project() -> None:
    """复制到本地：副本随工程保存落盘，重开仍在（内容一致）。"""

    class _Project:
        def __init__(self) -> None:
            self.user_vector_layers: list = []
            self.mapping_workspace: dict = {}

    controller = _controller()
    layer = _layer_with(controller, SQUARE)
    copy = controller.duplicate_layer(layer.id)
    assert copy is not None
    project = _Project()
    controller.sync_to_project(project)
    assert {record.id for record in project.user_vector_layers} == {
        layer.id, copy.id}
    fresh = _controller()
    assert fresh.load_from_project(project) is not False
    assert len(list(fresh.layer(copy.id).features())) == 1
    assert _as_lists(
        list(fresh.layer(copy.id).features())[0].geometry) == SQUARE
