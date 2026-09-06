"""V6 RAW 门禁闭合（baseline B-P0-1）。

两个历史旁路：

1. 属性表 ``_edit_session`` 直接 ``layer.start_editing()``，未经角色
   门禁——RAW 图层的单元格编辑可以开启会话；
2. ``flush_edit_sessions``（工程保存/阶段切换路径）提交**所有**打开的
   会话，不复查角色——RAW 会话被静默写进工程。

V6 修复：门禁以 ``CompositeEditController.set_edit_gate`` 注入（单点 =
``CompositeDocument._role_allows_editing``），所有会话起点与 flush 提交
全部经过门禁；被拒会话保持打开（可回滚），原因可读。
"""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_attribute_table import (
    CompositeAttributeTableDialog,
)
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


def _document(qtbot, tmp_path) -> CompositeDocument:
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


def _raw_layer(document: CompositeDocument):
    """注册为 RAW 保护角色的用户图层（初始沉积相图源）。"""
    layer = document.edit_controller.create_layer("初始相图源", "polygon")
    document.stage_controller.group_controller.register_layer(
        layer.id, LayerRole.INITIAL_FACIES_SOURCE
    )
    return layer


# --- 门禁注入 ---------------------------------------------------------------


def test_edit_controller_gate_blocks_session_start(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    layer = _raw_layer(document)
    document.edit_controller.set_active_layer(layer.id)
    assert document.edit_controller.active_layer_id == layer.id
    document.edit_controller.start_editing()
    assert layer.edit_session is None  # 门禁拒绝：会话未开启


def test_ensure_layer_session_returns_reason_for_raw(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    layer = _raw_layer(document)
    session, reason = document.edit_controller.ensure_layer_session(layer.id)
    assert session is None
    assert reason  # 必须给出原因


def test_ensure_layer_session_returns_session_for_editable(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    layer = document.edit_controller.create_layer("用户草稿", "polygon")
    session, reason = document.edit_controller.ensure_layer_session(layer.id)
    assert session is not None
    assert reason == ""


# --- 属性表旁路闭合 -----------------------------------------------------------


def test_attribute_table_cannot_open_raw_session(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    layer = _raw_layer(document)
    dialog = CompositeAttributeTableDialog(document.edit_controller, layer.id)
    qtbot.addWidget(dialog)
    dialog._write_attribute("f1", "name", "text", "x")
    assert layer.edit_session is None  # 写入被门禁吞下，绝不产生会话


def test_attribute_table_shows_readonly_reason_for_raw(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    layer = _raw_layer(document)
    dialog = CompositeAttributeTableDialog(document.edit_controller, layer.id)
    qtbot.addWidget(dialog)
    dialog.refresh()
    info = dialog._info.text()
    assert "不可编辑" in info or "RAW" in info


# --- flush 旁路闭合 -----------------------------------------------------------


def test_flush_refuses_to_commit_raw_session(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    layer = _raw_layer(document)
    # 模拟历史旁路遗留的 RAW 会话（直接 layer.start_editing）。
    layer.start_editing()
    assert layer.edit_session is not None
    layer.edit_session.add_feature(
        VectorFeature(
            feature_id="f1",
            geometry={"type": "Point", "coordinates": [1.0, 2.0]},
            attributes={"name": "x"},
        )
    )
    committed, blocked = document.edit_controller.flush_edit_sessions()
    assert committed == 0
    assert blocked, "RAW 会话必须出现在 blocked 列表（不静默）"
    assert layer.edit_session is not None  # 会话保持打开（可回滚），绝不提交


def test_flush_commits_editable_session_normally(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    layer = document.edit_controller.create_layer("用户草稿", "polygon")
    layer.start_editing()
    layer.edit_session.add_feature(
        VectorFeature(
            feature_id="f1",
            geometry={"type": "Point", "coordinates": [1.0, 2.0]},
            attributes={"name": "x"},
        )
    )
    committed, blocked = document.edit_controller.flush_edit_sessions()
    assert committed == 1
    assert blocked == []
    assert layer.edit_session is None
