from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QDockWidget

from paleo_workbench.harness.actions.well import _well_resource_path
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui import navigation
from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    project.resources.extend(
        [
            ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las"),
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
            ResourceItem(name="meta.json", path=".preview_cache/meta.json", type="tabular", format="json"),
        ]
    )
    project.stratigraphy.target_horizon = "D63"
    return project


def test_app_shell_starts_in_native_workstation(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    assert ws.objectName() == "WorkstationFrame"
    # Ribbon 已随死 chrome 移除（B2）：壳上不得再残留 ribbon 属性。
    assert not hasattr(shell, "ribbon")
    assert getattr(ws, "document_tabs", None) is None
    assert ws.central_document() is ws.composite
    assert ws.well_dock.isHidden()
    assert ws.seismic_dock.isHidden()
    titles = " ".join(d.windowTitle() for d in (ws.well_dock, ws.seismic_dock, ws.nav_dock))
    assert "A12 - D63" not in titles
    assert ws.linked_workspace._views_created is False


def test_composite_document_is_default_with_dock_panels(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    workstation = shell.workstation
    composite = workstation.composite

    # 图件显示区域 = 主窗口中央内容（永不浮动）；面板全部是宿主 dock。
    # QMainWindow 宿主由顶层窗口提供；孤立构造（无宿主）时工作站自身是
    # 普通文档区部件。
    assert workstation._dock_host is not None
    assert composite.canvas.parentWidget() is composite
    for dock in (
        workstation.nav_dock,
        workstation.inspector_dock,
        workstation.agent_dock,
        workstation.composite_layer_dock,
        workstation.composite_input_dock,
        workstation.composite_linked_dock,
    ):
        assert isinstance(dock, QDockWidget)
        features = dock.features()
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetMovable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetClosable

    # 默认视图：图件最大化（variant C），仅图层管理随编图打开
    assert not workstation.composite_layer_dock.isHidden()
    assert workstation.composite_input_dock.isHidden()
    assert workstation.composite_linked_dock.isHidden()
    assert workstation.well_dock.isHidden()
    assert workstation.seismic_dock.isHidden()

    # 面板菜单语义：toggleViewAction 重开 / 关闭面板
    workstation.composite_input_dock.toggleViewAction().trigger()
    assert not workstation.composite_input_dock.isHidden()
    workstation.composite_input_dock.toggleViewAction().trigger()
    assert workstation.composite_input_dock.isHidden()

    # 完整窗口管理：拖出浮动 → 停靠恢复
    workstation.composite_layer_dock.setFloating(True)
    assert workstation.composite_layer_dock.isFloating()
    workstation._reset_composite_layout()
    assert not workstation.composite_layer_dock.isFloating()

    # 编图常驻中央：无文档切换，综合编修面板显隐只走布局预设
    assert workstation.central_document() is composite

    # 图层管理是真实渲染控制
    assert composite.layer_manager.tree_row_count() > 0
    layer_id = composite.layer_manager._layers[0].id
    visible_before = composite.layer_manager.layer_by_id(layer_id).visible
    composite.layer_manager.set_layer_visible(layer_id, not visible_before)
    assert composite.layer_manager.layer_by_id(layer_id).visible is not visible_before

    # 布局持久化：saveState/restoreState 往返（经 dock 宿主）
    state = workstation._dock_host.saveState()
    assert isinstance(state, QByteArray)
    assert workstation._dock_host.restoreState(state)


def test_composite_input_tree_lists_project_data(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    tree = shell.workstation.composite.input_tree.tree

    labels = []
    for row in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(row)
        labels.append(group.text(0))
        for child in range(group.childCount()):
            labels.append(group.child(child).text(0))
    assert any("井数据" in label for label in labels)
    assert "A12" in labels
    assert any("图件成果" in label for label in labels)


def test_hub_navigation_does_not_replace_bian_tu(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    shell.navigate_to(navigation.PAGE_INDEX_MAPPING, "review")
    assert ws.central_document() is ws.composite
    assert not ws.hub_dock.isHidden()
    assert "成图审核" in ws.hub_dock.windowTitle()


def test_hub_dock_close_keeps_bian_tu(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    shell.navigate_to(navigation.PAGE_INDEX_DATA, "overview")
    assert ws.central_document() is ws.composite
    assert ws.hub_dock.isFloating()
    ws.hub_dock.close()
    assert ws.hub_dock.isHidden()
    assert ws.central_document() is ws.composite


def test_well_and_seismic_are_host_docks(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    for dock in (ws.well_dock, ws.seismic_dock):
        assert dock.parentWidget() is ws._dock_host
        features = dock.features()
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetClosable
    ws.well_dock.close()
    assert ws.well_dock.isHidden()
    ws.well_dock.toggleViewAction().trigger()
    assert not ws.well_dock.isHidden()


def test_linked_workspace_has_no_nested_map_document(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    lw = shell.workstation.linked_workspace
    assert getattr(lw, "map_dock", None) is None
    assert getattr(lw, "dock_area", None) is None
    assert getattr(lw, "context_bar", None) is None


def test_bian_tu_toolbar_toggles_view_docks(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    well_btn = ws.composite.well_track_button
    seis_btn = ws.composite.seismic_section_button
    link_btn = ws.composite.link_button
    assert well_btn.isCheckable()
    assert seis_btn.isCheckable()
    assert link_btn.isCheckable()
    well_btn.setChecked(True)
    assert not ws.well_dock.isHidden()
    well_btn.setChecked(False)
    assert ws.well_dock.isHidden()
    seis_btn.setChecked(True)
    assert not ws.seismic_dock.isHidden()
    seis_btn.setChecked(False)
    assert ws.seismic_dock.isHidden()
    link_btn.setChecked(False)
    assert ws.linked_workspace.is_linked() is False
    link_btn.setChecked(True)
    assert ws.linked_workspace.is_linked() is True


def test_explorer_separates_data_from_storage_cache(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    explorer = shell.workstation.explorer
    explorer.set_mode("data")

    labels = []
    root = explorer.model.invisibleRootItem()
    pending = [root.child(row) for row in range(root.rowCount())]
    while pending:
        item = pending.pop()
        labels.append(item.text())
        pending.extend(item.child(row) for row in range(item.rowCount()))

    assert "A12.Las" in labels
    assert "D63.dat" in labels
    assert "meta.json" not in labels
    assert "存储缓存默认隐藏" in explorer.footer_label.text()


def test_agent_plans_map_scientific_commands_to_typed_actions():
    show = AgentWorkspace._plan("显示所有井的平面位置")
    assert show.action_id == "well.list"
    assert show.gui_action == "show_wells"

    log = AgentWorkspace._plan("打开井 A12，把 GR 曲线放到第一道")
    assert log.action_id == "well.open"
    assert log.parameters == {"well": "A12"}
    assert log.followup_action == ("well.create_display", {"well": "A12", "curves": ["GR"]})

    joint = AgentWorkspace._plan("生成井震联合剖面")
    assert joint.action_id == "workflow.status"
    assert joint.gui_action == "focus_joint"


def test_agent_resolves_project_relative_well_resources(tmp_path):
    project = _project(tmp_path)
    context = ActionContext(
        project=project,
        project_path=str(tmp_path / "demo.paleo.json"),
    )

    assert _well_resource_path(context, project.wells[0]) == str(
        (tmp_path / "wells" / "A12.Las").resolve()
    )


def test_rail_collapse_affordance_tracks_explorer_state(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    rail = shell.workstation.activity_rail

    # explorer 挂在 dock 里；显式隐藏标志（isHidden）是折叠语义的真值——
    # 孤立构造（无顶层 dock 宿主）时 isVisible 恒为 False。
    rail.set_explorer_expanded(False)
    assert rail.collapse_button.toolTip() == "展开资源管理器"
    rail.set_explorer_expanded(True)
    assert rail.collapse_button.toolTip() == "折叠资源管理器"

    shell.workstation.toggle_explorer()
    assert shell.workstation.explorer.isHidden()
    assert rail.collapse_button.toolTip() == "展开资源管理器"
    shell.workstation.toggle_explorer()
    assert not shell.workstation.explorer.isHidden()


def test_task_center_renders_state_colored_progress(qtbot):
    import time as _time

    from paleo_workbench.runtime.task_scheduler import TaskSpec, get_scheduler
    from paleo_workbench.ui.workstation.task_center import TaskCenter, _TaskRowDelegate

    center = TaskCenter()
    qtbot.addWidget(center)

    handle = get_scheduler().submit(
        TaskSpec(
            callable=lambda ctx: (_time.sleep(30), "late")[1],
            kind="background.io",
            title="QA · 状态渲染探针",
        )
    )
    try:
        qtbot.waitUntil(lambda: center.model.rowCount() == 1, timeout=4000)
        row_handle = center.model.handle_at(0)
        assert row_handle.task_id == handle.task_id
        # 状态文本由 delegate 绘制（模型 DisplayRole 只承载任务名/用时）。
        assert _TaskRowDelegate._state_text(row_handle).startswith(("运行中", "排队"))
        assert 0.0 <= row_handle.progress <= 1.0
        # 增量刷新不重建行：集合不变时行身份保持，选中不丢（#1157）。
        center.tree.selectRow(0)
        center.refresh()
        assert center.model.handle_at(0).task_id == row_handle.task_id
        assert center.tree.selectionModel().selectedRows(0)
    finally:
        get_scheduler().cancel(handle.task_id)
        center.shutdown()


def test_task_center_incremental_update_keeps_rows_stable(qtbot):
    """#1157：相同任务集合的刷新必须原位更新，不产生整树重建。"""
    import time as _time

    from paleo_workbench.runtime.task_scheduler import TaskSpec, get_scheduler
    from paleo_workbench.ui.workstation.task_center import TaskCenter

    center = TaskCenter()
    qtbot.addWidget(center)
    handles = [
        get_scheduler().submit(
            TaskSpec(
                callable=lambda ctx, n=n: (_time.sleep(30), n)[1],
                kind="background.io",
                title=f"QA · 增量探针 {n}",
            )
        )
        for n in range(3)
    ]
    try:
        my_ids = {h.task_id for h in handles}
        # 其它测试残留的已取消任务可能仍在表中（取消是协作式的），
        # 因此按「本组任务全部出现」而非总行数判断。
        qtbot.waitUntil(
            lambda: my_ids.issubset(
                {
                    center.model.handle_at(r).task_id
                    for r in range(center.model.rowCount())
                }
            ),
            timeout=8000,
        )
        rows = center.model.rowCount()
        ids_before = [center.model.handle_at(r).task_id for r in range(rows)]
        center.refresh()
        ids_after = [center.model.handle_at(r).task_id for r in range(rows)]
        assert ids_before == ids_after, "相同任务集合的刷新必须保持行集合与顺序"
        # 行内零常驻 widget：进度/取消由 delegate 绘制。
        viewport_children_before = len(center.tree.viewport().findChildren(object))
        center.refresh()
        assert len(center.tree.viewport().findChildren(object)) == viewport_children_before
    finally:
        for handle in handles:
            get_scheduler().cancel(handle.task_id)
        center.shutdown()


def test_inspector_marks_missing_values(qtbot, tmp_path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.ui.workstation.inspector import WorkstationInspector

    project = _project(tmp_path)
    inspector = WorkstationInspector(project)
    qtbot.addWidget(inspector)

    bare_well = WellEntity(name="B7")
    inspector.show_well(bare_well)
    fields = inspector.properties_form
    values = [
        fields.itemAt(row, fields.ItemRole.FieldRole).widget()
        for row in range(fields.rowCount())
    ]
    missing = [edit for edit in values if edit.property("missing")]
    assert missing, "至少 KB/总深度 等缺失字段应带 missing 标记"
    assert all(edit.text() == "—" for edit in missing)

    inspector.show_well(WellEntity(name="C9", kb=12.5, td=2100))
    present = [
        fields.itemAt(row, fields.ItemRole.FieldRole).widget()
        for row in range(fields.rowCount())
    ]
    texts = [edit.text() for edit in present]
    assert "12.5 m" in texts
    assert "2100 m" in texts


def test_layout_presets_apply_visibility_matrix(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation

    ws.apply_layout_preset("composite_default")
    assert ws.central_document() is ws.composite
    assert not ws.composite_layer_dock.isHidden()
    assert ws.composite_input_dock.isHidden()
    assert ws.composite_linked_dock.isHidden()
    assert ws.layout_preset_visibility("composite_default")["composite_layer"] is True

    ws.apply_layout_preset("integrated")
    assert ws.central_document() is ws.composite
    assert not ws.inspector_dock.isHidden()
    assert not ws.task_dock.isHidden()
    assert not ws.agent_dock.isHidden()
    assert not ws.well_dock.isHidden()
    assert not ws.seismic_dock.isHidden()

    ws._reset_default_layout()
    assert ws.central_document() is ws.composite
    assert not ws.composite_layer_dock.isHidden()


def test_show_tasks_does_not_expand_agent_dock(qtbot, tmp_path):
    """打开任务中心只 raise 任务 dock，不得强制展开 Agent 面板（B2）。"""
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    ws.apply_layout_preset("composite_default")
    assert ws.agent_dock.isHidden()
    assert ws.task_dock.isHidden()

    ws.show_tasks()

    assert not ws.task_dock.isHidden()
    assert ws.agent_dock.isHidden(), "打开任务中心不得连带显示 Agent 面板"


def test_agent_tasks_logs_console_are_independent_docks(qtbot, tmp_path):
    """B18 去重：Agent / 任务中心 / 日志 / 控制台各自是宿主级 dock，
    不再存在面板内层 tab（旧 ProcessHub QTabWidget 已拆除）。"""
    from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace

    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation

    for attr, title in (
        ("agent_dock", "Agent"),
        ("task_dock", "任务中心"),
        ("logs_dock", "日志"),
        ("console_dock", "控制台"),
    ):
        dock = getattr(ws, attr)
        assert dock.windowTitle() == title
        feats = dock.features()
        assert feats & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert feats & QDockWidget.DockWidgetFeature.DockWidgetMovable
        assert feats & QDockWidget.DockWidgetFeature.DockWidgetClosable
    # dock 内容直接就是各部件：Agent 面板下不再嵌 tab 容器。
    assert isinstance(ws.agent_dock.widget(), AgentWorkspace)
    assert not hasattr(ws.agent_panel, "tabs")
    assert ws.logs_dock.isHidden() and ws.console_dock.isHidden()

    # 各自独立显隐 + 浮动。
    ws.logs_dock.show()
    ws.console_dock.show()
    assert not ws.logs_dock.isHidden() and not ws.console_dock.isHidden()
    ws.logs_dock.setFloating(True)
    assert ws.logs_dock.isFloating()
    assert not ws.console_dock.isFloating()
    assert not ws.agent_dock.isFloating()
    ws.logs_dock.setFloating(False)


def test_log_viewer_streams_and_caps(qtbot):
    """「日志」dock 是真实日志查看器：流式追加 + 2000 行上限（B2）。"""
    import logging

    from paleo_workbench.ui.workstation.process_hub import ConsolePane, LogViewer

    viewer = LogViewer()
    qtbot.addWidget(viewer)
    try:
        logging.getLogger("paleo_workbench.b2_probe").warning("B2 日志探针")
        assert "B2 日志探针" in viewer.logs.toPlainText()
        assert viewer.logs.isReadOnly()

        probe = logging.getLogger("paleo_workbench.b2_probe")
        for i in range(2300):
            probe.warning("cap line %d", i)
        assert viewer.logs.blockCount() <= 2000, "超出上限必须丢弃最旧"
        assert "cap line 2299" in viewer.logs.toPlainText()
    finally:
        viewer.shutdown()
    root = logging.getLogger("paleo_workbench")
    assert viewer._log_handler not in root.handlers, "shutdown 必须摘除全局 handler"

    console = ConsolePane()
    qtbot.addWidget(console)
    assert "预留：嵌入式控制台" in console.console.toPlainText()
    assert console.console.isReadOnly()


def test_float_all_and_dock_all_panels(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    ws.apply_layout_preset("composite_default")

    ws.float_all_panels()
    floated = [d for d in ws._shell_docks() if not d.isHidden()]
    assert floated
    assert all(d.isFloating() for d in floated)

    ws.dock_all_panels()
    assert all(not d.isFloating() for d in ws._shell_docks())


def test_panel_menu_exposes_presets_and_batch_float(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    menu = shell.workstation.composite._panels_menu
    labels = [a.text() for a in menu.actions() if a.text()]
    # Submenus + batch actions + restore
    assert "显示面板" in labels
    assert "布局预设" in labels
    assert "全部浮动" in labels
    assert "全部停靠" in labels
    assert "恢复默认布局" in labels
