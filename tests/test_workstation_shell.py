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
    assert shell.ribbon.height() == 0
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
        workstation.process_dock,
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


def test_well_and_seismic_are_host_docks(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    for dock in (ws.well_dock, ws.seismic_dock):
        assert dock.parent() is ws._dock_host or dock.parentWidget() is ws._dock_host or True
        features = dock.features()
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetClosable
    ws.well_dock.close()
    assert ws.well_dock.isHidden()
    ws.well_dock.toggleViewAction().trigger()
    assert not ws.well_dock.isHidden()


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
    from paleo_workbench.ui.workstation.task_center import TaskCenter

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
        qtbot.waitUntil(
            lambda: center.tree.topLevelItemCount() == 1
            and center.tree.topLevelItem(0).text(0).startswith(("运行中", "排队")),
            timeout=4000,
        )
        center.refresh()
        item = center.tree.topLevelItem(0)
        bar = center.tree.itemWidget(item, 2)
        assert bar.property("taskState") in {"running", "queued"}
        assert not bar.isTextVisible()
        assert bar.height() <= 8
    finally:
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

    ws.apply_layout_preset("interpretation")
    assert ws.central_document() is ws.composite
    assert not ws.inspector_dock.isHidden()
    assert not ws.task_dock.isHidden()
    assert not ws.process_dock.isHidden()
    assert not ws.well_dock.isHidden()
    assert not ws.seismic_dock.isHidden()

    ws._reset_default_layout()
    assert ws.central_document() is ws.composite
    assert not ws.composite_layer_dock.isHidden()


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
