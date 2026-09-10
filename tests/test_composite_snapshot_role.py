"""快照 metadata["role"]：编辑侧角色进桥 schema 路径的钉住测试。

断链背景：snapshot_layers 曾只写 editable/geometry_kind/template/editing
四键，桥侧 `_fields_json_for_metadata` 读不到 role → legacy 无 schema 路径
→ 属性全丢 → 分类渲染零匹配 → 画布不可见。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.mapping import qgis_mirror
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.models import UserVectorLayer
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


def _controller() -> CompositeEditController:
    return CompositeEditController(project_crs="EPSG:32650")


def test_role_layer_snapshot_carries_role_and_schema() -> None:
    controller = _controller()
    layer = controller.create_layer(
        "地震预测相", "polygon", role=LayerRole.SEISMIC_FACIES_PREDICTION)
    assert controller.layer_role(layer.id) == "seismic_facies_prediction"
    snapshot = controller.snapshot_layers()[0]
    assert snapshot.metadata.get("role") == "seismic_facies_prediction"
    names = [entry.get("name") for entry in
             json.loads(qgis_mirror._fields_json_for_metadata(dict(snapshot.metadata)))]
    assert "facies_name" in names


def test_unroled_and_generic_layers_stay_schemaless() -> None:
    controller = _controller()
    plain = controller.create_layer("手绘", "line")
    generic = controller.create_layer("通用", "polygon", role=LayerRole.USER_GENERAL)
    legacy = controller.create_layer("旧层", "point", role="legacy_unclassified")
    snapshots = {snap.id: snap for snap in controller.snapshot_layers()}
    for layer in (plain, generic, legacy):
        assert "role" not in snapshots[layer.id].metadata, layer.id
        assert qgis_mirror._fields_json_for_metadata(
            dict(snapshots[layer.id].metadata)) == ""


def test_preexisting_layer_metadata_role_not_overwritten() -> None:
    controller = _controller()
    layer = controller.create_layer("草稿", "polygon")
    layer.metadata = {"role": LayerRole.INITIAL_FACIES_DRAFT.value}  # type: ignore[attr-defined]
    controller.set_layer_role(layer.id, LayerRole.SEISMIC_FACIES_PREDICTION)
    snapshot = controller.snapshot_layers()[0]
    assert snapshot.metadata.get("role") == LayerRole.INITIAL_FACIES_DRAFT.value


def test_set_clear_duplicate_remove_role() -> None:
    controller = _controller()
    layer = controller.create_layer("手绘", "line")
    controller.set_layer_role(layer.id, LayerRole.FACIES_BOUNDARY)
    assert controller.layer_role(layer.id) == "facies_boundary"
    controller.set_layer_role(layer.id, "")
    assert controller.layer_role(layer.id) == ""
    assert "role" not in controller.snapshot_layers()[0].metadata

    controller.set_layer_role(layer.id, LayerRole.FACIES_BOUNDARY)
    copy = controller.duplicate_layer(layer.id)
    assert copy is not None
    assert controller.layer_role(copy.id) == "facies_boundary"
    snapshots = {snap.id: snap for snap in controller.snapshot_layers()}
    assert snapshots[copy.id].metadata.get("role") == "facies_boundary"

    controller.remove_layer(copy.id)
    assert controller.layer_role(copy.id) == ""
    assert copy.id not in {snap.id for snap in controller.snapshot_layers()}


def test_load_from_project_restores_roles() -> None:
    controller = _controller()
    layer = controller.create_layer("地震预测相", "polygon",
                                    role=LayerRole.SEISMIC_FACIES_PREDICTION)
    record = UserVectorLayer(id=layer.id, name=layer.name, geometry_kind="polygon")

    class _Project:
        user_vector_layers = [record]
        mapping_workspace = {"memberships": {
            layer.id: {"role": LayerRole.SEISMIC_FACIES_PREDICTION.value}}}

    fresh = _controller()
    assert fresh.load_from_project(_Project()) is not False
    assert fresh.layer_role(layer.id) == "seismic_facies_prediction"
    snapshot = fresh.snapshot_layers()[0]
    assert snapshot.metadata.get("role") == "seismic_facies_prediction"


def test_create_role_layer_funnel_registers_edit_role() -> None:
    from paleo_workbench.mapping_workspace.controller import MappingStageController
    from paleo_workbench.ui.workstation.stage_actions import StageActionDispatcher

    controller = _controller()
    stage = MappingStageController()

    class _Composite:
        edit_controller = controller
        stage_controller = stage
        synced = 0

        def _sync_composition_now(self) -> None:
            self.synced += 1

        class status_message:
            messages: list[str] = []

            @classmethod
            def emit(cls, text: str) -> None:
                cls.messages.append(text)

    dispatcher = StageActionDispatcher(_Composite())
    layer_id = dispatcher._create_role_layer(
        "地震预测相", "polygon", LayerRole.SEISMIC_FACIES_PREDICTION)
    assert layer_id
    assert controller.layer_role(layer_id) == "seismic_facies_prediction"
    assert stage.state.membership(layer_id).role == LayerRole.SEISMIC_FACIES_PREDICTION
    snapshot = next(snap for snap in controller.snapshot_layers() if snap.id == layer_id)
    assert snapshot.metadata.get("role") == "seismic_facies_prediction"
