"""mock 预测层与真实层一视同仁地持久化（用户显式要求）。

sync_to_project 写全部 _layers（无角色过滤），load_from_project 按
user_vector_layers + mapping_workspace 成员资格恢复。mock 只是来源，
不是二等图层：删 mock 的唯一正规途径是删除图层动作，而非保存时丢弃。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


def _controller() -> CompositeEditController:
    return CompositeEditController(project_crs="EPSG:32650")


class _Project:
    def __init__(self) -> None:
        self.user_vector_layers: list = []
        self.mapping_workspace: dict = {}


def _polygon(x0: float) -> dict:
    return {"type": "Polygon", "coordinates": [
        [[x0, 0.0], [x0 + 1.0, 0.0], [x0 + 1.0, 1.0],
         [x0, 1.0], [x0, 0.0]]]}


def test_mock_and_real_layers_persist_identically() -> None:
    from paleo_workbench.mapping_workspace.controller import MappingStageController

    controller = _controller()
    stage = MappingStageController()
    mock = controller.create_layer(
        "测井相预测（mock）", "polygon", role=LayerRole.WELL_FACIES_PREDICTION)
    stage.group_controller.register_layer(
        mock.id, LayerRole.WELL_FACIES_PREDICTION)
    controller.import_layer_features(mock.id, [
        VectorFeature("m1", _polygon(0.0), {"facies_name": "delta"}),
        VectorFeature("m2", _polygon(2.0), {"facies_name": "shore"}),
    ])
    real = controller.create_layer("手绘解释", "polygon")
    controller.import_layer_features(real.id, [
        VectorFeature("r1", _polygon(5.0), {"note": "x"}),
    ])

    project = _Project()
    controller.sync_to_project(project)
    project.mapping_workspace = stage.save_state()

    assert {record.id for record in project.user_vector_layers} == {
        mock.id, real.id}
    assert stage.state.membership(mock.id) is not None

    fresh = _controller()
    assert fresh.load_from_project(project) is not False
    assert {layer.id for layer in fresh._layers.values()} == {mock.id, real.id}
    assert len(list(fresh.layer(mock.id).features())) == 2
    assert len(list(fresh.layer(real.id).features())) == 1
    # 角色随成员资格恢复：mock 重开仍是预测相（分类渲染不断链）。
    assert fresh.layer_role(mock.id) == "well_facies_prediction"
