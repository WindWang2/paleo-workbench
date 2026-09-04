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


def test_template_layer_uses_geological_style(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller

    fault = controller.create_layer("", "line", template="fault")
    assert fault.name == "断层线"  # 模板补默认名
    assert fault.style["line_pattern"] == "fault"
    assert fault.style["stroke"] == "#e03131"
    assert controller.layer_template(fault.id) == "fault"

    # 模板自带几何类型：与传入 kind 不一致时以模板为准
    extent = controller.create_layer("", "line", template="extent")
    assert controller.kind_of(extent.id) == "polygon"
    assert extent.name == "成图范围"

    custom = controller.create_layer("手绘", "line")
    assert controller.layer_template(custom.id) == ""


def test_rename_layer(qtbot, tmp_path):
    controller = _document(qtbot, tmp_path).edit_controller
    layer = controller.create_layer("A", "point")
    controller.rename_layer(layer.id, "  井位注记  ")
    assert layer.name == "井位注记"
    controller.rename_layer(layer.id, "")  # 空名忽略
    assert layer.name == "井位注记"


def test_layers_persist_into_project_document(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    layer = controller.create_layer("断层 F1", "line", template="fault")
    controller.start_editing()
    controller.activate_tool("add_line")
    tool = controller.tools.active_tool
    tool.mouse_press((0.0, 0.0))
    tool.mouse_press((10.0, 10.0))
    tool.mouse_press((20.0, 0.0), button="right")  # 右键结束
    controller.save_edits()

    # 人工建数据写回工程文档（纳入数据管理）
    records = document._project.user_vector_layers
    assert len(records) == 1
    record = records[0]
    assert record.name == "断层 F1"
    assert record.template == "fault"
    assert record.geometry_kind == "line"
    assert len(record.features) == 1
    assert record.features[0].geometry["type"] == "LineString"

    # 重新打开文档：图层 / 要素 / 模板全部还原
    fresh = CompositeDocument(document._project)
    qtbot.addWidget(fresh)
    restored = fresh.edit_controller.layer(layer.id)
    assert restored is not None
    assert restored.name == "断层 F1"
    assert len(restored.features()) == 1
    assert fresh.edit_controller.layer_template(layer.id) == "fault"


def test_layers_survive_project_file_roundtrip(qtbot, tmp_path):
    from paleo_workbench.project.manager import ProjectManager

    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    layer = controller.create_layer("", "point", template="well_point")
    controller.start_editing()
    controller.activate_tool("add_point")
    controller.tools.active_tool.mouse_press((3.0, 4.0))
    controller.save_edits()
    document.layer_manager.set_layer_visible(layer.id, False)
    document._sync_composition()

    path = tmp_path / "demo.paleo.json"
    manager = ProjectManager(path)
    assert manager.save(document._project)
    reloaded = manager.load()
    assert len(reloaded.user_vector_layers) == 1
    record = reloaded.user_vector_layers[0]
    assert record.template == "well_point"
    assert len(record.features) == 1
    assert record.visible is False

    # 磁盘加载的工程也能直接恢复为可编辑图层
    fresh = CompositeDocument(reloaded)
    qtbot.addWidget(fresh)
    restored = fresh.edit_controller.layer(layer.id)
    assert restored is not None and len(restored.features()) == 1
    snapshot = fresh.layer_manager.layer_by_id(layer.id)
    assert snapshot.visible is False


def test_explorer_lists_user_vector_layers(qtbot, tmp_path):
    document = _document(qtbot, tmp_path)
    controller = document.edit_controller
    controller.create_layer("物源线 1", "line", template="source")
    project = document._project

    from paleo_workbench.ui.workstation.explorer import (
        OBJECT_ROLE,
        WorkstationExplorer,
    )

    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("data")

    def walk(item):
        for row in range(item.rowCount()):
            child = item.child(row)
            yield child
            yield from walk(child)

    root = explorer.model.invisibleRootItem()
    payloads = [
        (item.text(), item.data(OBJECT_ROLE) or {})
        for item in walk(root)
    ]
    group = next(p for p in payloads if p[1].get("kind") == "group" and "编修数据" in p[0])
    assert group is not None
    leaves = [p for p in payloads if p[1].get("kind") == "user_vector_layer"]
    assert len(leaves) == 1
    assert "物源线 1" in leaves[0][0]


def test_tree_rename_writes_back_to_authority_and_project(qtbot, tmp_path):
    """树内重命名写回编辑权威并持久化；下次重组快照不回滚（M2 终局审查 C1）。"""
    document = _document(qtbot, tmp_path)
    document.show()
    controller = document.edit_controller
    layer = controller.create_layer("井点", "point")
    panel = document.layer_manager
    tree = panel.tree_host.tree_view_address
    stack = document.canvas.stack

    def row_of(name):
        for row in range(stack.tree_view_row_count(tree)):
            if stack.tree_view_layer_name(tree, row) == name:
                return row
        return None

    qtbot.waitUntil(lambda: row_of("井点") is not None, timeout=3000)
    stack.tree_view_rename_row(tree, row_of("井点"), "井点A")
    qtbot.waitUntil(lambda: controller.layer(layer.id).name == "井点A", timeout=2000)
    # 工程文档持久化权威同步
    persisted = next(
        item for item in document._project.user_vector_layers if item.id == layer.id)
    assert persisted.name == "井点A"
    # 重组快照不回滚树名/权威名
    document._sync_composition_now()
    qtbot.waitUntil(lambda: row_of("井点A") is not None, timeout=3000)
    assert controller.layer(layer.id).name == "井点A"
