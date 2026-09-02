from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.workstation.activity_rail import ActivityRail
from paleo_workbench.ui.workstation.app_bar import WorkstationAppBar
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.explorer import WorkstationExplorer
from paleo_workbench.ui.workstation.inspector import WorkstationInspector
from paleo_workbench.ui.workstation.linked_workspace import (
    LinkedInterpretationWorkspace,
)
from paleo_workbench.ui.workstation.process_hub import ProcessHub


class WorkstationFrame(QWidget):
    """Native Qt workstation shell.

    图件显示区域（文档区）是窗口中央内容，永不浮动；其余一切面板 —
    资源管理器、检查器、任务/Agent、图层管理、输入与结果、联动视图 —
    全部是 ``QDockWidget``，享有 Qt 完整窗口管理：四边停靠、拖出浮动、
    面板叠 tab、关闭重开（「面板」菜单）、布局持久化。

    ``QMainWindow`` 设计上必须是顶层窗口，因此 dock 宿主由
    ``PaleoWorkbenchWindow`` 提供（``dock_host``）；本部件是宿主的中央
    文档区域。未提供宿主时（测试/孤立构造）使用一个隐藏的 detached
    宿主，结构完整但不显示 dock。
    """

    navigation_requested = Signal(int, str)
    command_submitted = Signal(str)
    status_message = Signal(str)

    TAB_JOINT = 0
    TAB_MAP = 1
    TAB_WELL = 2
    TAB_LEGACY = 3
    TAB_COMPOSITE = 4

    _WINDOW_STATE_KEY = "layout/windowState"

    def __init__(self, project, page_stack: QWidget, dock_host=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationFrame")
        self._project = project
        self._project_path: str | None = None
        self._settings = QSettings("PaleoWorkbench", "WorkstationV3")
        self._user_hid_inspector = False
        self._responsive_hid_inspector = False
        self._post_show_restored = False
        self._composite_docks_visible: dict[str, bool] | None = None
        self._owns_dock_host = dock_host is None
        self._dock_host: QMainWindow = dock_host if dock_host is not None else QMainWindow()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save_layout)

        self._dock_host.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
        )
        self._dock_host.setTabPosition(
            Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North
        )
        self._dock_host.setCorner(
            Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea
        )

        # --- 中央：App bar + 文档区（图件主体所在） ----------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.app_bar = WorkstationAppBar(self)
        # QMainWindowLayout 会把子件 minimumSizeHint 计入中央区最小尺寸；
        # App bar 与文档栈的内容提示之和必须被忽略，否则 dock 化窗口的
        # 最小宽度会撑爆外层壳（2041px 实测）。
        self.app_bar.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.app_bar.setMinimumSize(0, 0)
        layout.addWidget(self.app_bar)

        self.document_tabs = QTabBar(self)
        self.document_tabs.setObjectName("WorkstationDocumentTabs")
        self.document_tabs.setDocumentMode(True)
        self.document_tabs.setExpanding(False)
        self.document_tabs.addTab("井震联合剖面: A12 - D63")
        self.document_tabs.addTab("平面图: D63")
        self.document_tabs.addTab("井轨道: A12")
        self.document_tabs.addTab("项目工作流")
        self.document_tabs.addTab("综合编修")
        self.document_tabs.currentChanged.connect(self._on_document_tab_changed)
        self.document_tabs.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.document_tabs)

        self.document_stack = QStackedWidget(self)
        self.document_stack.setObjectName("WorkstationDocumentStack")
        self.document_stack.setMinimumSize(0, 0)
        self.document_stack.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.linked_workspace = LinkedInterpretationWorkspace(
            project, self.document_stack
        )
        self.document_stack.addWidget(self.linked_workspace)
        self.composite = CompositeDocument(project, self.document_stack)
        self.document_stack.addWidget(self.composite)
        self.page_stack = page_stack
        self.page_stack.setMinimumSize(0, 0)
        self.document_stack.addWidget(page_stack)
        layout.addWidget(self.document_stack, 1)

        # --- 面板：全部为宿主窗口上的可浮动 dock -------------------------
        self.navigation_region = QFrame(self._dock_host)
        self.navigation_region.setObjectName("WorkstationNavigationRegion")
        nav_layout = QHBoxLayout(self.navigation_region)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        self.activity_rail = ActivityRail(self.navigation_region)
        self.explorer = WorkstationExplorer(project, self.navigation_region)
        nav_layout.addWidget(self.activity_rail)
        nav_layout.addWidget(self.explorer, 1)

        self.inspector = WorkstationInspector(self._dock_host)
        self.process_hub = ProcessHub(project, self._dock_host)

        self.nav_dock = self._add_dock(
            "资源管理器", self.navigation_region,
            Qt.DockWidgetArea.LeftDockWidgetArea,
        )
        self.inspector_dock = self._add_dock(
            "检查器", self.inspector, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.process_dock = self._add_dock(
            "任务 / Agent", self.process_hub, Qt.DockWidgetArea.BottomDockWidgetArea
        )

        # 综合编修面板（随文档显隐；由宿主 QMainWindow 持有 dock）
        self.composite_layer_dock = self._add_dock(
            "图层管理", self.composite.layer_manager,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.composite_input_dock = self._add_dock(
            "输入与结果", self.composite.input_tree,
            Qt.DockWidgetArea.LeftDockWidgetArea,
        )
        self.composite_linked_dock = self._add_dock(
            "联动视图", self.composite.linked_views,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )
        # 默认视图：图件最大化（variant C），仅图层管理随综合编修打开。
        self.composite_input_dock.hide()
        self.composite_linked_dock.hide()
        self.composite.register_panel_actions(
            [
                self.composite_input_dock.toggleViewAction(),
                self.composite_layer_dock.toggleViewAction(),
                self.composite_linked_dock.toggleViewAction(),
            ],
            self._reset_composite_layout,
        )
        # 图层管理与检查器在右侧叠 tab，任务/联动视图在底部叠 tab。
        self._dock_host.tabifyDockWidget(self.inspector_dock, self.composite_layer_dock)
        self._dock_host.tabifyDockWidget(self.process_dock, self.composite_linked_dock)

        self._wire()
        self.set_project(project)
        # 进入工作站默认落在综合编修环境（全幅图件 + 浮动面板）。
        self.document_tabs.setCurrentIndex(self.TAB_COMPOSITE)
        QTimer.singleShot(0, self._restore_layout)

    def _add_dock(self, title: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self._dock_host)
        dock.setObjectName(f"WorkstationDock_{title}")
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._dock_host.addDockWidget(area, dock)
        return dock

    def _wire(self) -> None:
        self.activity_rail.mode_requested.connect(self._on_activity_mode)
        self.activity_rail.collapse_requested.connect(self.toggle_explorer)
        self.explorer.object_selected.connect(self.inspector.show_payload)
        self.explorer.object_activated.connect(self._activate_explorer_object)
        self.explorer.navigation_requested.connect(self.navigation_requested)
        self.explorer.joint_workspace_requested.connect(self.activate_joint)
        self.linked_workspace.object_selected.connect(self.inspector.show_payload)
        self.linked_workspace.status_changed.connect(self.status_message)
        self.composite.object_selected.connect(self.inspector.show_payload)
        self.process_hub.agent.open_well_requested.connect(self._open_well_from_agent)
        self.process_hub.agent.show_wells_requested.connect(self._show_wells_from_agent)
        self.process_hub.agent.focus_joint_requested.connect(self.activate_joint)
        self.process_hub.agent.undo_requested.connect(self._undo_agent_gui)
        self.process_hub.task_count_changed.connect(self.app_bar.set_task_count)
        self.app_bar.agent_requested.connect(self.show_agent)
        self.app_bar.task_center_requested.connect(self.show_tasks)
        self.app_bar.command_submitted.connect(self.command_submitted)
        self.inspector.style_changed.connect(
            lambda _style: self.status_message.emit("当前解释样式已更新")
        )
        for dock in (
            self.nav_dock,
            self.inspector_dock,
            self.process_dock,
            self.composite_layer_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
        ):
            dock.topLevelChanged.connect(lambda *_: self._schedule_state_save())
            dock.dockLocationChanged.connect(lambda *_: self._schedule_state_save())
            dock.visibilityChanged.connect(lambda *_: self._schedule_state_save())
        for dock in (
            self.linked_workspace.seismic_dock,
            self.linked_workspace.map_dock,
            self.linked_workspace.well_dock,
        ):
            dock.topLevelChanged.connect(lambda *_: self._schedule_state_save())
            dock.dockLocationChanged.connect(lambda *_: self._schedule_state_save())
            dock.visibilityChanged.connect(lambda *_: self._schedule_state_save())
        self.process_hub.agent_splitter.splitterMoved.connect(
            lambda *_args: self._schedule_state_save()
        )

    def set_project(self, project, project_path: str | None = None) -> None:
        self._project = project
        if project_path is not None:
            self._project_path = str(project_path)
        meta = getattr(project, "meta", None)
        name = str(getattr(meta, "name", "") or "未命名工程")
        region = str(getattr(meta, "region", "") or "")
        if not region:
            region = str(getattr(getattr(project, "workarea", None), "name", "") or "")
        self.app_bar.set_project(name, region)
        self.explorer.set_project(project)
        self.inspector.set_project(project)
        self.linked_workspace.set_project(project, self._project_path)
        self.process_hub.set_project(project, self._project_path)
        self.composite.set_project(project)

    def set_project_path(self, path: str | None) -> None:
        self._project_path = str(path) if path else None
        self.linked_workspace.set_project_path(self._project_path)
        self.process_hub.set_project(self._project, self._project_path)

    def attach_coordination(self, controller) -> None:
        self.linked_workspace.attach_coordination(controller)

    def activate_joint(self) -> None:
        self.document_tabs.setCurrentIndex(self.TAB_JOINT)
        self.document_stack.setCurrentWidget(self.linked_workspace)
        self.linked_workspace.focus_joint()

    def activate_legacy(self, title: str = "项目工作流") -> None:
        self.document_tabs.setTabText(self.TAB_LEGACY, str(title or "项目工作流"))
        self.document_tabs.setCurrentIndex(self.TAB_LEGACY)
        self.document_stack.setCurrentWidget(self.page_stack)

    def is_joint_active(self) -> bool:
        return self.document_stack.currentWidget() is self.linked_workspace

    def show_agent(self) -> None:
        self.process_dock.show()
        self.process_hub.show_agent()
        self._expand_process_dock()

    def show_tasks(self) -> None:
        self.process_dock.show()
        self.process_hub.show_tasks()
        self._expand_process_dock()

    def submit_agent_command(self, text: str) -> None:
        self.process_dock.show()
        self.process_hub.submit_agent_command(text)
        self._expand_process_dock()

    def toggle_explorer(self) -> None:
        # dock 内部件用显式隐藏标志：孤立构造（宿主未显示）时
        # isVisible() 恒为 False，不能作为折叠状态真值。
        hidden = self.explorer.isHidden()
        self.explorer.setVisible(hidden)
        self.activity_rail.set_explorer_expanded(hidden)
        self._save_timer.start()

    def toggle_inspector(self) -> None:
        show = self.inspector_dock.isHidden()
        self._user_hid_inspector = not show
        self._responsive_hid_inspector = False
        self.inspector_dock.setVisible(show)
        self._save_timer.start()

    def panel_entries(self) -> list[dict]:
        return [
            {"key": "workstation:explorer", "title": "资源管理器", "widget": self.explorer},
            {"key": "workstation:inspector", "title": "检查器", "widget": self.inspector},
            {"key": "workstation:process", "title": "任务 / Agent", "widget": self.process_hub},
        ]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_panels()

    def _apply_responsive_panels(self) -> None:
        if self.width() < 1280 and not self.inspector_dock.isHidden():
            self._responsive_hid_inspector = True
            self.inspector_dock.hide()
            return
        if (
            self.inspector_dock.isHidden()
            and self._responsive_hid_inspector
            and not self._user_hid_inspector
        ):
            # 恢复条件必须保证「显示后」宽度仍不低于隐藏阈值，否则
            # 隐藏↔显示在临界宽度上往复，形成 resize 风暴（画布渲染被饿死）。
            inspector_width = self.inspector_dock.sizeHint().width()
            if inspector_width <= 0:
                inspector_width = 286
            if self.width() - inspector_width >= 1280:
                self._responsive_hid_inspector = False
                self.inspector_dock.show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_responsive_panels()
        if not self._post_show_restored:
            self._post_show_restored = True
            # 构造发生在顶层窗口拿到最终几何之前；show 之后再恢复一次，
            # 避免 dock 布局被首帧的默认几何覆盖。
            QTimer.singleShot(50, self._restore_layout)

    def _on_document_tab_changed(self, index: int) -> None:
        if index == self.TAB_LEGACY:
            self._set_composite_docks_visible(False)
            self.document_stack.setCurrentWidget(self.page_stack)
            return
        if index == self.TAB_COMPOSITE:
            self.document_stack.setCurrentWidget(self.composite)
            self._set_composite_docks_visible(True)
            return
        self._set_composite_docks_visible(False)
        self.document_stack.setCurrentWidget(self.linked_workspace)
        if index == self.TAB_MAP:
            self.linked_workspace.maximize_map()
        elif index == self.TAB_WELL:
            self.linked_workspace.maximize_well()
        else:
            self.linked_workspace.restore_split_view()

    def _set_composite_docks_visible(self, visible: bool) -> None:
        docks = (
            self.composite_layer_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
        )
        if visible:
            state = self._composite_docks_visible or {
                "layer": True, "input": False, "linked": False,
            }
            for dock, key in zip(docks, ("layer", "input", "linked"), strict=True):
                dock.setVisible(state[key])
        else:
            self._composite_docks_visible = {
                "layer": not self.composite_layer_dock.isHidden(),
                "input": not self.composite_input_dock.isHidden(),
                "linked": not self.composite_linked_dock.isHidden(),
            }
            for dock in docks:
                if not dock.isHidden():
                    dock.hide()

    def _reset_composite_layout(self) -> None:
        """恢复综合编修面板的默认停靠布局（不改可见性）。"""
        host = self._dock_host
        for dock, area in (
            (self.composite_input_dock, Qt.DockWidgetArea.LeftDockWidgetArea),
            (self.composite_layer_dock, Qt.DockWidgetArea.RightDockWidgetArea),
            (self.composite_linked_dock, Qt.DockWidgetArea.BottomDockWidgetArea),
        ):
            if dock.isFloating():
                dock.setFloating(False)
            host.addDockWidget(area, dock)
        host.tabifyDockWidget(self.inspector_dock, self.composite_layer_dock)
        host.tabifyDockWidget(self.process_dock, self.composite_linked_dock)
        self._save_timer.start()

    def _on_activity_mode(self, mode: str) -> None:
        self.explorer.set_mode(mode)
        if mode == "search":
            self.explorer.focus_search()
        elif mode == "history":
            self.process_hub.tabs.setCurrentIndex(2)
            self._expand_process_dock()
        elif mode == "workspaces":
            self.document_tabs.setFocus(Qt.FocusReason.OtherFocusReason)

    def _activate_explorer_object(self, payload) -> None:
        payload = payload or {}
        kind = payload.get("kind") if isinstance(payload, dict) else ""
        if kind == "well":
            self._open_well_from_agent(str(payload.get("well_name") or "A12"))
            return
        if kind == "resource":
            resource = payload.get("object")
            resource_type = str(getattr(resource, "type", "") or "")
            if resource_type == "well_log":
                self._open_well_from_agent(
                    str(getattr(resource, "name", "A12")).rsplit(".", 1)[0]
                )
            elif resource_type == "seismic":
                self.activate_joint()
                self.linked_workspace.ensure_views()
                if self.linked_workspace.seismic_panel is not None:
                    self.linked_workspace.seismic_panel.show_resource(resource, self._project)
            return
        if kind in {"horizon", "interpretation", "layer"}:
            self.activate_joint()

    def _open_well_from_agent(self, well_name: str) -> None:
        self.document_tabs.setCurrentIndex(self.TAB_JOINT)
        self.document_stack.setCurrentWidget(self.linked_workspace)
        self.linked_workspace.restore_split_view()
        self.linked_workspace.open_well(well_name)

    def _show_wells_from_agent(self) -> None:
        self.document_tabs.setCurrentIndex(self.TAB_MAP)
        self.document_stack.setCurrentWidget(self.linked_workspace)
        self.linked_workspace.show_all_wells()

    def _undo_agent_gui(self) -> None:
        self.document_tabs.setCurrentIndex(self.TAB_JOINT)
        self.linked_workspace.restore_split_view()
        self.linked_workspace.open_well("A12")

    def _expand_process_dock(self) -> None:
        self.process_dock.show()
        self._dock_host.resizeDocks(
            [self.process_dock], [245], Qt.Orientation.Vertical
        )

    def _schedule_state_save(self) -> None:
        """部件已关闭时不再保存布局——退出/销毁阶段的全部隐藏态不是布局。"""
        if not self.isVisible():
            return
        self._save_timer.start()

    def _restore_layout(self) -> None:
        data = self._settings.value(self._WINDOW_STATE_KEY)
        if isinstance(data, QByteArray) and not data.isNull():
            self._dock_host.restoreState(data)
        linked_state = self._settings.value("layout/linked_docks")
        if isinstance(linked_state, QByteArray) and not linked_state.isNull():
            self.linked_workspace.restore_dock_state(linked_state)
        self.process_hub.agent_splitter.setSizes(
            self._read_sizes("agent", [560, 560])
        )

    def _read_sizes(self, key: str, fallback: list[int]) -> list[int]:
        value = self._settings.value(f"layout/{key}")
        if not isinstance(value, (list, tuple)) or len(value) != len(fallback):
            return fallback
        try:
            sizes = [max(0, int(part)) for part in value]
        except (TypeError, ValueError):
            return fallback
        return sizes if sum(sizes) > 0 else fallback

    def _save_layout(self) -> None:
        if not self.isVisible():
            return  # 关闭后保存的全隐藏布局会污染下次启动
        self._settings.setValue(self._WINDOW_STATE_KEY, self._dock_host.saveState())
        self._settings.setValue(
            "layout/linked_docks", self.linked_workspace.dock_area.saveState()
        )
        self._settings.setValue("layout/agent", self.process_hub.agent_splitter.sizes())

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        self._save_timer.stop()
        self._save_layout()
        self.process_hub.shutdown()
        self.composite.shutdown()
        self._teardown_docks()
        return self.linked_workspace.shutdown_workers(wait_ms)

    def _teardown_docks(self) -> None:
        """工程切换 / 退出时把 dock 从宿主上摘除（宿主可被重建复用）。"""
        docks = (
            self.nav_dock,
            self.inspector_dock,
            self.process_dock,
            self.composite_layer_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
        )
        for dock in docks:
            host = dock.parentWidget()
            if isinstance(host, QMainWindow):
                host.removeDockWidget(dock)
            dock.deleteLater()
        if self._owns_dock_host:
            self._dock_host.deleteLater()
