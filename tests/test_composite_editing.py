"""综合编修矢量编辑：图层新建 / 编辑会话 / 工具条集成。"""

from pathlib import Path

from PySide6.QtWidgets import QStackedWidget

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    return project


def _document(qtbot, tmp_path) -> CompositeDocument:
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


def test_create_layer_appends_editable_snapshot(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    base_count = len(document._base_layers)
    assert base_count > 0

    layer = document.edit_controller.create_layer("相带边界", "polygon")

    layers = document.layer_manager._layers
    assert len(layers) == base_count + 1
    snapshot = document.layer_manager.layer_by_id(layer.id)
    assert snapshot.name == "相带边界"
    assert snapshot.metadata["editable"] == "true"
    assert snapshot.metadata["geometry_kind"] == "polygon"
    # 用户图层绘制在基础工区图层之上（快照自下而上）。
    assert layers[-1].id == layer.id
    # 新建图层即成为活动图层
    assert document.edit_controller.active_layer_id == layer.id


def test_editing_session_add_undo_redo_save(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    layer = controller.create_layer("井点", "point")
    controller.start_editing()
    assert controller.editing

    # 数字化工具真实写入编辑会话工作副本
    controller.activate_tool("add_point")
    tool = controller.tools.active_tool
    assert tool is not None and tool.tool_id == "add_point"
    assert tool.mouse_press((100.0, 200.0))
    session = layer.edit_session
    assert len(session.features()) == 1

    # 撤销 / 重做
    assert controller.edit_command("undo")
    assert len(session.features()) == 0
    assert controller.edit_command("redo")
    assert len(session.features()) == 1

    # 保存编辑：提交到图层，会话关闭
    controller.save_edits()
    assert not controller.editing
    assert len(layer.features()) == 1


def test_rollback_discards_working_copy(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    layer = controller.create_layer("断层线", "line")
    controller.start_editing()
    controller.activate_tool("add_line")
    tool = controller.tools.active_tool
    tool.mouse_press((0.0, 0.0))
    tool.mouse_press((10.0, 10.0))
    tool.mouse_press((20.0, 0.0), button="right")  # 右键结束
    assert len(layer.edit_session.features()) == 1

    controller.rollback_edits()
    assert not controller.editing
    assert len(layer.features()) == 0


def test_kind_mismatch_does_not_hijack_tool(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    controller.create_layer("相带", "polygon")
    controller.start_editing()
    controller.activate_tool("add_line")  # 面图层不接受加线工具
    assert controller.tools.active_tool is None or (
        controller.tools.active_tool.tool_id != "add_line"
    )
    controller.activate_tool("add_polygon")
    assert controller.tools.active_tool.tool_id == "add_polygon"


def test_select_and_delete_selected(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    layer = controller.create_layer("井点", "point")
    controller.start_editing()
    controller.activate_tool("add_point")
    controller.tools.active_tool.mouse_press((5.0, 5.0))

    # 选择（命中测试经 FeatureSpatialIndex，容差取像素级）
    controller.activate_tool("select")
    tool = controller.tools.active_tool
    controller._canvas = None  # 容差退回像素常数
    assert tool.mouse_press((5.0, 5.0))
    assert len(layer.selection) == 1

    assert controller.edit_command("delete_selected")
    assert len(layer.edit_session.features()) == 0
    assert not layer.selection


def test_remove_layer_rebinds_active(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    first = controller.create_layer("A", "point")
    second = controller.create_layer("B", "line")
    assert controller.active_layer_id == second.id

    controller.remove_layer(second.id)
    assert controller.active_layer_id == first.id
    controller.remove_layer(first.id)
    assert controller.active_layer_id is None
    assert controller.layer_ids() == ()


def test_toolbar_actions_track_editing_state(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    actions = document.action_controller.actions

    # 无矢量图层：编辑与数字化命令不可用
    document._sync_action_state()
    assert not actions["toggle_editing"].isEnabled()
    assert not actions["add_point"].isEnabled()
    assert not actions["delete_selected"].isEnabled()
    # 导航 / 画布命令始终可用
    assert actions["pan"].isEnabled()
    assert actions["full_extent"].isEnabled()

    controller = document.edit_controller
    controller.create_layer("井点", "point")
    document._sync_action_state()
    assert actions["toggle_editing"].isEnabled()
    assert not actions["toggle_editing"].isChecked()
    assert not actions["save_edits"].isEnabled()

    # 经命令面开启编辑（QGIS 语义：toggle_editing 即开始 / 保存）
    document._on_command_requested("toggle_editing")
    assert controller.editing
    assert actions["toggle_editing"].isChecked()
    assert actions["save_edits"].isEnabled()
    assert actions["add_point"].isEnabled()

    document._on_command_requested("toggle_editing")  # 再次 = 保存并退出
    assert not controller.editing
    assert not actions["toggle_editing"].isChecked()


def test_layer_manager_survives_content_resync(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    layer = controller.create_layer("井点", "point")
    controller.start_editing()
    controller.activate_tool("add_point")
    controller.tools.active_tool.mouse_press((1.0, 1.0))

    # 内容变更 → 面板重载后活动图层与可见性状态不丢
    document._sync_composition()
    document.layer_manager.set_layer_visible(layer.id, False)
    controller.tools.active_tool.mouse_press((2.0, 2.0))
    document._sync_composition()

    snapshot = document.layer_manager.layer_by_id(layer.id)
    assert snapshot.visible is False
    assert len(snapshot.features) == 2
    assert controller.active_layer_id == layer.id


def test_shell_exposes_digitizing_toolbar(qtbot, tmp_path):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    composite = shell.workstation.composite

    for action_id in (
        "toggle_editing", "save_edits", "rollback",
        "add_point", "add_line", "add_polygon", "move_feature", "vertex",
        "undo", "redo", "delete_selected",
    ):
        assert action_id in composite.action_controller.actions
