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
    """树内重命名写回编辑权威并持久化；下次重组快照不回滚（M2 终局审查 C1）。

    双路径：QGIS 桥可用时走真 QgsLayerTreeView 内联改名；无桥（本机/CI
    fallback）走回退面板的重命名请求信号 + QInputDialog（mock 输入）。
    两条路径最终断言同一权威：edit_controller + 工程文档 + 重组不回滚。
    """
    document = _document(qtbot, tmp_path)
    document.show()
    controller = document.edit_controller
    layer = controller.create_layer("井点", "point")
    panel = document.layer_manager

    if getattr(panel, "tree_host", None) is not None:
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
    else:
        from PySide6.QtWidgets import QInputDialog

        qtbot.waitUntil(
            lambda: any(
                "井点" in panel.tree.topLevelItem(r).text(0)
                for r in range(panel.tree_row_count())
            ),
            timeout=3000,
        )
        # 回退路径：树面板右键菜单发出的改名请求（对话框 mock 为「井点A」）。
        qtbot.addWidget(panel)
        original_get_text = QInputDialog.getText

        def _fake_get_text(*_args, **_kwargs):
            return "井点A", True

        QInputDialog.getText = staticmethod(_fake_get_text)
        try:
            panel.rename_layer_requested.emit(str(layer.id))
        finally:
            QInputDialog.getText = original_get_text
        qtbot.waitUntil(lambda: controller.layer(layer.id).name == "井点A", timeout=2000)
        assert any(
            "井点A" in panel.tree.topLevelItem(r).text(0)
            for r in range(panel.tree_row_count())
        )

    # 工程文档持久化权威同步
    persisted = next(
        item for item in document._project.user_vector_layers if item.id == layer.id)
    assert persisted.name == "井点A"
    # 重组快照不回滚树名/权威名
    document._sync_composition_now()
    assert controller.layer(layer.id).name == "井点A"
    if getattr(panel, "tree_host", None) is not None:
        stack = document.canvas.stack
        tree = panel.tree_host.tree_view_address
        qtbot.waitUntil(lambda: any(
            stack.tree_view_layer_name(tree, row) == "井点A"
            for row in range(stack.tree_view_row_count(tree))
        ), timeout=3000)
    else:
        qtbot.waitUntil(lambda: any(
            "井点A" in panel.tree.topLevelItem(r).text(0)
            for r in range(panel.tree_row_count())
        ), timeout=3000)


def test_layer_checkbox_toggle_keeps_tree_items_alive(qtbot, tmp_path):
    """图层可见性复选框：不得同步重建树（鼠标释放栈内 clear() 会 UAF 崩溃）。

    回归（2026-09-06 core dump）：勾选「井位信息」复选框 → itemChanged →
    set_layer_visible → _reload() → tree.clear() 销毁 delegate 仍持有的
    item，mouseReleaseEvent 返回后在 QStyledItemDelegate::editorEvent 内
    SIGSEGV。修复后复选框路径只重发渲染快照，树 item 对象保持存活。

    双路径：该 UAF 只存在于 fallback QTreeWidget 面板（QGIS 桥面板用原生
    QgsLayerTreeView，无 Python 树重建）；桥环境下改断言等效契约——可见性
    写回权威并直达镜像，且 tree_host 不被重建。
    """
    from PySide6.QtCore import Qt

    document = _document(qtbot, tmp_path)
    panel = document.layer_manager
    assert panel.tree_row_count() > 0

    if not hasattr(panel, "tree"):
        # QGIS 桥路径：QgsLayerTreeView 原生树。可见性直达镜像、宿主存活。
        layer_id = next(
            iter(
                sorted(
                    (layer.id for layer in panel._layers),
                )
            )
        )
        host_before = panel.tree_host
        panel.set_layer_visible(layer_id, False)
        assert panel.layer_by_id(layer_id).visible is False
        assert panel.tree_host is host_before
        return

    items = [panel.tree.topLevelItem(i) for i in range(panel.tree_row_count())]
    target = next(
        (
            item
            for item in items
            if "井位" in item.text(0) or panel.layer_by_id(item.data(0, Qt.ItemDataRole.UserRole)) is not None
        ),
        items[0],
    )
    layer_id = target.data(0, Qt.ItemDataRole.UserRole)
    assert panel.layer_by_id(layer_id).visible is True

    # 模拟用户勾选：触发 itemChanged → _on_item_changed。
    target.setCheckState(0, Qt.CheckState.Unchecked)

    # 树未重建：同一批 item 对象仍挂在树上（clear() 会换新对象）。
    assert [panel.tree.topLevelItem(i) for i in range(panel.tree_row_count())] == items
    # 可见性确实写回了渲染快照权威。
    assert panel.layer_by_id(layer_id).visible is False


def test_native_properties_apply_to_base_workarea_layers(qtbot, tmp_path):
    """基础工区图层（井位 / 地震工区）的原生属性写回快照与源头。

    回归：_apply_native_layer_properties 原先对非编辑控制器图层直接
    return——井位 / 地震工区打开属性对话框后确定也全被丢弃。现在名称 /
    不透明度写回面板快照与 _base_layers 源（重组不回滚），引用描述符
    同步；符号 / 标注经镜像层与呈现态信封生效。
    """
    document = _document(qtbot, tmp_path)
    assert document._base_layers, "工区基础图层应已随 set_project 组装"
    base = document._base_layers[0]
    original_name = base.name
    snapshot = document.layer_manager.layer_by_id(base.id)
    assert snapshot is not None

    document._apply_native_layer_properties(
        base.id,
        {"ok": True, "name": f"{original_name}改", "opacity": 0.55,
         "renderer_xml": "", "labeling_xml": ""},
    )

    # 快照源是 frozen dataclass：写回以 replace 换列表条目，按 id 复查。
    def _source_layer():
        return next(layer for layer in document._base_layers if layer.id == base.id)

    assert _source_layer().name == f"{original_name}改"
    assert abs(_source_layer().opacity - 0.55) < 1e-9
    refreshed = document.layer_manager.layer_by_id(base.id)
    assert refreshed.name == f"{original_name}改"
    assert abs(refreshed.opacity - 0.55) < 1e-9
