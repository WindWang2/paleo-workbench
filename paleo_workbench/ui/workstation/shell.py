from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.dock_manager import WorkspacePreset, dock_manager
from paleo_workbench.ui.layout_persistence import (
    LAYOUT_STATE_VERSION,
    SETTINGS_APP,
    SETTINGS_ORG,
    migrate_legacy_layout_settings,
)
from paleo_workbench.ui.workstation.activity_rail import ActivityRail
from paleo_workbench.ui.workstation.app_bar import WorkstationAppBar
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.explorer import WorkstationExplorer
from paleo_workbench.ui.workstation.inspector import WorkstationInspector
from paleo_workbench.ui.layout_presets import (
    RESET_LAYOUT_PRESET_ID,
    get_preset,
    list_presets,
    visibility_dict,
)
from paleo_workbench.ui.workstation.linked_workspace import (
    LinkedInterpretationWorkspace,
)
from paleo_workbench.ui.workstation.process_hub import ProcessHub
from paleo_workbench.ui.workstation.task_center import TaskCenter
from paleo_workbench.ui.workstation.dock_title_bar import install_dock_title_bar

_log = logging.getLogger(__name__)


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

    _WINDOW_STATE_KEY = "layout/window_state"
    _STATE_VERSION_KEY = "layout/state_version"

    def __init__(self, project, page_stack: QWidget, dock_host=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationFrame")
        # 壳本身可持焦：作为初始键盘焦点落点（见 showEvent 注释）。
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._project = project
        self._project_path: str | None = None
        # 统一 QSettings 身份（B2）：与主题同一 (PaleoWorkbench, Workstation)
        # 存储；旧 WorkstationV3 身份的数据在读任何键之前一次性迁移。
        migrate_legacy_layout_settings()
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._settings.sync()
        self._user_hid_inspector = bool(
            self._settings.value("layout/inspector_user_hidden", False, type=bool)
        )
        self._responsive_hid_inspector = False
        self._post_show_restored = False
        # 工作区预设追踪：apply_layout_preset 记录 id；用户手调任一预设
        # dock 可见性后置 None（app bar 下拉回「自定义」）。
        self._current_preset_id: str | None = None
        self._preset_tracking_paused = False
        # teardown 阶段冻结布局保存：拆除 dock 触发的 visibilityChanged
        # 不得把「已拆除」状态写进 QSettings（#1124）。
        self._layout_frozen = False
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

        # --- 中央：编图（唯一文档，永不替换） ------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.app_bar = WorkstationAppBar(self)
        # 首行顶置：App bar 挂在宿主的顶部工具栏区（dock 区域之上），
        # 占满窗口全宽，左/右 dock 不再推移这一行。固定不可移动/浮动；
        # objectName 供 saveState/restoreState 识别；右键菜单屏蔽，
        # 防止通过 toggleViewAction 把全局栏藏起来。
        self.app_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.app_bar.setMinimumSize(0, 0)
        self.app_bar_toolbar = QToolBar("工作站全局栏", self._dock_host)
        self.app_bar_toolbar.setObjectName("WorkstationAppBarToolbar")
        self.app_bar_toolbar.setMovable(False)
        self.app_bar_toolbar.setFloatable(False)
        self.app_bar_toolbar.setContextMenuPolicy(
            Qt.ContextMenuPolicy.PreventContextMenu
        )
        # 平台主题为 QToolBar 预留的内边距会让全宽首行缩进几像素，清零。
        self.app_bar_toolbar.layout().setContentsMargins(0, 0, 0, 0)
        self.app_bar_toolbar.addWidget(self.app_bar)
        self._dock_host.addToolBar(
            Qt.ToolBarArea.TopToolBarArea, self.app_bar_toolbar
        )

        self.linked_workspace = LinkedInterpretationWorkspace(project, self)
        # 联动区不再是中央文档：内容部件已由宿主 dock 接管，本体保持隐藏。
        self.linked_workspace.hide()
        self.composite = CompositeDocument(project, self)
        self.page_stack = page_stack
        self.page_stack.setMinimumSize(0, 0)
        layout.addWidget(self.composite, 1)

        # --- 面板：全部为宿主窗口上的可浮动 dock -------------------------
        # 中央编图最小宽度：再糟糕的持久化布局（或极端拖拽）也不能把
        # 地图挤没了——dock 布局由 QMainWindow 在中央 minimum 之上分配。
        self.composite.setMinimumWidth(420)
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
        self._agent_undo_stack: list[dict] = []
        self._current_well_name = ""
        self.process_hub = ProcessHub(project, self._dock_host)
        # 任务中心是独立面板：与 Agent 各自浮动 / 显隐，不再焊在同一 dock 里。
        self.task_center = TaskCenter(self._dock_host)

        self.nav_dock = self._add_dock(
            "资源管理器", self.navigation_region,
            Qt.DockWidgetArea.LeftDockWidgetArea,
        )
        self.inspector_dock = self._add_dock(
            "检查器", self.inspector, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.process_dock = self._add_dock(
            "Agent", self.process_hub, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.task_dock = self._add_dock(
            "任务中心", self.task_center, Qt.DockWidgetArea.BottomDockWidgetArea
        )

        # 编图面板（由宿主 QMainWindow 持有 dock）
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
        # 测井轨道 / 地震剖面 / 功能页：宿主级 dock，动作打开，默认隐藏。
        self.well_dock = self._add_dock(
            "测井轨道", self.linked_workspace.well_pane,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )
        self.seismic_dock = self._add_dock(
            "地震剖面", self.linked_workspace.seismic_pane,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )
        self.hub_dock = self._add_dock(
            "功能页", self.page_stack,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.well_dock.hide()
        self.seismic_dock.hide()
        self.hub_dock.hide()
        # 默认视图：图件最大化（variant C），仅图层管理随编图打开。
        self.composite_input_dock.hide()
        self.composite_linked_dock.hide()
        self._wire_composite_panel_menu()
        # 图层管理与检查器在右侧叠 tab，任务/联动视图在底部叠 tab。
        self._dock_host.tabifyDockWidget(self.inspector_dock, self.composite_layer_dock)
        self._dock_host.tabifyDockWidget(self.process_dock, self.composite_linked_dock)
        self._dock_host.tabifyDockWidget(self.process_dock, self.task_dock)
        self._dock_host.tabifyDockWidget(self.process_dock, self.well_dock)
        self._dock_host.tabifyDockWidget(self.well_dock, self.seismic_dock)

        self._wire()
        self.set_project(project)
        # 中央永远是编图，无需切换。
        self._schedule_restore(0)

    # 浮动时避免邮票窗；停靠时交还内容 hint（否则 220px 最小宽在多面板
    # 停靠时撑爆布局，#1123）。
    _FLOAT_MIN_SIZE = (220, 160)

    def _add_dock(self, title: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self._dock_host)
        dock.setObjectName(f"WorkstationDock_{title}")
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setMinimumSize(0, 0)
        dock.topLevelChanged.connect(
            lambda floating, d=dock: self._sync_float_min_size(d, floating)
        )
        if dock.isFloating():
            dock.setMinimumSize(*self._FLOAT_MIN_SIZE)
        install_dock_title_bar(dock, title)
        self._dock_host.addDockWidget(area, dock)
        return dock

    @classmethod
    def _sync_float_min_size(cls, dock: QDockWidget, floating: bool) -> None:
        if floating:
            dock.setMinimumSize(*cls._FLOAT_MIN_SIZE)
        else:
            dock.setMinimumSize(0, 0)

    def _wire(self) -> None:
        self.activity_rail.mode_requested.connect(self._on_activity_mode)
        self.activity_rail.collapse_requested.connect(self.toggle_explorer)
        self.explorer.object_selected.connect(self.inspector.show_payload)
        self.explorer.object_activated.connect(self._activate_explorer_object)
        self.explorer.navigation_requested.connect(self.navigation_requested)
        self.explorer.joint_workspace_requested.connect(self.activate_joint)
        self.linked_workspace.object_selected.connect(self.inspector.show_payload)
        self.linked_workspace.status_changed.connect(self.status_message)
        self.linked_workspace.well_focused.connect(self._on_well_focused)
        self.linked_workspace.show_all_wells_requested.connect(
            lambda: self._show_wells_from_agent()
        )
        self.composite.well_track_toggled.connect(self._on_well_track_toggled)
        self.composite.seismic_section_toggled.connect(self._on_seismic_section_toggled)
        self.composite.link_toggled.connect(self._on_link_toggled)
        # 菜单/关闭按钮关 dock 后，工具条勾选态回写（避免状态撒谎）。
        # 工具条勾选回写只在 dock 真正关闭时发生：底部 dock 全部 tab 化，
        # 被兄弟 tab 遮挡时 Qt 仍报 visible——若照写会视觉谎报为已关闭，
        # 用户再点按钮反而把 dock 真正关掉。
        self.well_dock.visibilityChanged.connect(
            lambda visible: self._sync_dock_toggle(
                self.well_dock, self.composite.well_track_button, visible
            )
        )
        self.seismic_dock.visibilityChanged.connect(
            lambda visible: self._sync_dock_toggle(
                self.seismic_dock, self.composite.seismic_section_button, visible
            )
        )
        self.composite.object_selected.connect(self.inspector.show_payload)
        self.process_hub.agent.open_well_requested.connect(self._open_well_from_agent)
        self.process_hub.agent.show_wells_requested.connect(self._show_wells_from_agent)
        self.process_hub.agent.focus_joint_requested.connect(self._focus_joint_from_agent)
        self.process_hub.agent.undo_requested.connect(self._undo_agent_gui)
        self.task_center.active_count_changed.connect(self.app_bar.set_task_count)
        # 首个信号可能早于本接线发出（TaskCenter 构造即首刷，当时 app_bar
        # 还不存在，400ms 周期内若无状态变化不再补发）——接线后显式拉平。
        self.app_bar.set_task_count(self.task_center._last_active)
        self.app_bar.agent_requested.connect(self.show_agent)
        self.app_bar.task_center_requested.connect(self.show_tasks)
        self.app_bar.command_submitted.connect(self.command_submitted)
        self.app_bar.workspace_preset_requested.connect(self.apply_layout_preset)
        # 样式编辑走真实符号系统：检查器只提供入口，编辑发生在图层属性。
        self.inspector.edit_style_requested.connect(self._open_style_editor)
        for dock in (
            self.nav_dock,
            self.inspector_dock,
            self.process_dock,
            self.task_dock,
            self.composite_layer_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
            self.well_dock,
            self.seismic_dock,
            self.hub_dock,
        ):
            dock.topLevelChanged.connect(lambda *_: self._schedule_state_save())
            dock.dockLocationChanged.connect(lambda *_: self._schedule_state_save())
            dock.visibilityChanged.connect(lambda *_: self._schedule_state_save())
        # 预设追踪走同一条 visibilityChanged 路径（不新增机制）：预设矩阵
        # 覆盖的 dock 被手动显隐后，当前预设失效（hub_dock 除外——功能页
        # 浮窗由导航管理，不属于工作区布局）。
        for dock in self._preset_tracked_docks():
            dock.visibilityChanged.connect(lambda *_: self._mark_layout_customized())

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
        """接入全局选择总线（B11）：资源树选择即工作区上下文。"""
        self._coordination = controller
        self.linked_workspace.attach_coordination(controller)
        self.explorer.object_selected.connect(self._publish_explorer_selection)

    def _publish_explorer_selection(self, payload) -> None:
        """把资源树选择发布为 SelectionContext 事实（井/层位/图层）。"""
        controller = getattr(self, "_coordination", None)
        if controller is None or not isinstance(payload, dict):
            return
        kind = str(payload.get("kind") or "")
        if kind == "well":
            well_id = str(payload.get("well_name") or payload.get("id") or "")
            if well_id:
                controller.publish_well_selection(
                    well_id, source=type(controller).SOURCE_WORKSTATION
                )
        elif kind in ("horizon", "interpretation"):
            horizon_id = str(payload.get("id") or payload.get("name") or "")
            if horizon_id:
                controller.publish_horizon_selection(
                    horizon_id, source=type(controller).SOURCE_WORKSTATION
                )
        elif kind in ("layer", "user_vector_layer"):
            layer_id = str(payload.get("layer_id") or payload.get("id") or "")
            if layer_id and hasattr(controller, "publish_layer_selection"):
                controller.publish_layer_selection(
                    layer_id, source=type(controller).SOURCE_WORKSTATION
                )

    def _open_style_editor(self, layer_id: str) -> None:
        layer_id = str(layer_id or "")
        if not layer_id:
            return
        self.composite.open_layer_properties(layer_id, focus="symbology")
        self.status_message.emit(f"图层 {layer_id} 样式编辑已打开")

    def central_document(self):
        """中央唯一文档：编图（永不替换）。"""
        return self.composite

    def show_well(self, well_name: str = "") -> None:
        self.well_dock.show()
        self.well_dock.raise_()
        if well_name:
            self._current_well_name = str(well_name)
            self.process_hub.agent.set_active_well(str(well_name))
            self.linked_workspace.open_well(well_name)

    def show_seismic(self, resource=None) -> None:
        self.seismic_dock.show()
        self.seismic_dock.raise_()
        self.linked_workspace.ensure_views()
        if resource is not None and self.linked_workspace.seismic_panel is not None:
            self.linked_workspace.seismic_panel.show_resource(resource, self._project)
            name = str(getattr(resource, "name", "") or "")
            self.linked_workspace.seismic_pane.set_title(
                f"地震剖面 · {name}" if name else "地震剖面"
            )

    def show_hub_page(self, title: str) -> None:
        self.hub_dock.setWindowTitle(str(title or "功能页"))
        self.hub_dock.show()
        self.hub_dock.setFloating(True)
        self.hub_dock.raise_()

    def activate_joint(self) -> None:
        self.show_seismic()

    def activate_composite(self, layer_id: str = "") -> None:
        """编图常驻中央；携带 layer_id 时选中该编修图层。"""
        if layer_id:
            self.composite.layer_manager.select_layer(layer_id)

    def activate_legacy(self, title: str = "功能页") -> None:
        self.show_hub_page(title)

    def show_agent(self) -> None:
        self.process_dock.show()
        self.process_dock.raise_()  # 与 task_dock 同 tabify 链：必须前置
        self.process_hub.show_agent()
        self._expand_process_dock()

    def show_tasks(self) -> None:
        # 任务中心独立于 Agent 面板：只 raise 自己所在的 tab 链，绝不
        # 强制展开 process_dock（旧副作用：打开任务中心连带显示 Agent）。
        self.task_dock.show()
        self.task_dock.raise_()
        self.task_center.tree.setFocus(Qt.FocusReason.ShortcutFocusReason)

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
        # Expanding the tree should also surface the nav dock if the user
        # closed it; collapsing never auto-hides the rail+dock chrome.
        if hidden and self.nav_dock.isHidden():
            self.nav_dock.show()
        self._save_timer.start()

    def toggle_inspector(self) -> None:
        show = self.inspector_dock.isHidden()
        self._user_hid_inspector = not show
        self._responsive_hid_inspector = False
        self.inspector_dock.setVisible(show)
        self._settings.setValue("layout/inspector_user_hidden", self._user_hid_inspector)
        self._save_timer.start()

    # --- 工作区预设 -------------------------------------------------------

    @classmethod
    def preset_ids(cls) -> list[str]:
        """预设 id 列表（注册表顺序 = app bar 下拉顺序，稳定）。"""
        return [preset.id for preset in list_presets()]

    @property
    def current_preset_id(self) -> str | None:
        """当前预设 id；用户手调 dock 可见性后为 None（自定义）。"""
        return self._current_preset_id

    def _preset_tracked_docks(self) -> tuple[QDockWidget, ...]:
        """预设可见性矩阵覆盖的 dock（hub 浮窗除外）。"""
        return tuple(dock for dock in self._shell_docks() if dock is not self.hub_dock)

    def _mark_layout_customized(self) -> None:
        if self._preset_tracking_paused or self._layout_frozen:
            return
        if self._current_preset_id is not None:
            self._current_preset_id = None
            self.app_bar.set_current_workspace(None)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_panels()

    def _apply_responsive_panels(self) -> None:
        if self._layout_frozen:
            return  # 拆除阶段不再调整布局
        # 响应式显隐是 viewport 策略而非用户定制：不使当前预设失效。
        self._preset_tracking_paused = True
        try:
            self._apply_responsive_panels_unlocked()
        finally:
            self._preset_tracking_paused = False

    def _apply_responsive_panels_unlocked(self) -> None:
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
            self._schedule_restore(50)

    def _schedule_restore(self, delay_ms: int) -> None:
        # 定时器必须挂在本部件上：壳被拆除（deleteLater）后，迟到的
        # restore 不得再触碰已删除的 dock（游离 singleShot 会越界）。
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(delay_ms)
        timer.timeout.connect(self._restore_layout)
        timer.start()

    def _wire_composite_panel_menu(self) -> None:
        """面板菜单：显隐、布局预设、全部浮动/停靠、恢复默认。"""
        toggle_actions = []
        for dock, label in (
            (self.composite_input_dock, "显示输入与结果"),
            (self.composite_layer_dock, "显示图层管理"),
            (self.composite_linked_dock, "显示联动视图"),
        ):
            action = dock.toggleViewAction()
            action.setText(label)
            toggle_actions.append(action)
        preset_actions = [
            (preset.id, preset.label) for preset in list_presets()
        ]
        self.composite.register_panel_actions(
            toggle_actions,
            reset_callable=self._reset_default_layout,
            float_all_callable=self.float_all_panels,
            dock_all_callable=self.dock_all_panels,
            layout_presets=preset_actions,
            apply_preset_callable=self.apply_layout_preset,
        )

    def _shell_docks(self) -> tuple[QDockWidget, ...]:
        return (
            self.nav_dock,
            self.inspector_dock,
            self.process_dock,
            self.task_dock,
            self.composite_layer_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
            self.well_dock,
            self.seismic_dock,
            self.hub_dock,
        )

    def float_all_panels(self) -> None:
        """Float every currently visible shell dock (map stays central)."""
        for dock in self._shell_docks():
            if not dock.isHidden() and not dock.isFloating():
                dock.setFloating(True)
                dock.raise_()
        self._save_timer.start()

    def dock_all_panels(self) -> None:
        """Dock back every floating shell dock to its default area."""
        self._reset_composite_layout()
        for dock in (
            self.nav_dock,
            self.inspector_dock,
            self.process_dock,
            self.task_dock,
            self.well_dock,
            self.seismic_dock,
            self.hub_dock,
        ):
            if dock.isFloating():
                dock.setFloating(False)
        self._dock_host.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.nav_dock
        )
        self._dock_host.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock
        )
        self._dock_host.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.process_dock
        )
        self._dock_host.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.task_dock
        )
        self._dock_host.tabifyDockWidget(self.inspector_dock, self.composite_layer_dock)
        self._dock_host.tabifyDockWidget(self.process_dock, self.composite_linked_dock)
        self._dock_host.tabifyDockWidget(self.process_dock, self.task_dock)
        self._save_timer.start()

    def apply_layout_preset(self, preset_id: str) -> None:
        """Apply a named workstation layout preset (visibility only; no document tab)."""
        preset = get_preset(preset_id)
        if preset is None:
            return
        vis = preset.visibility

        # 应用期间的 visibilityChanged 是预设自身造成的，不算用户定制。
        self._preset_tracking_paused = True
        try:
            self.nav_dock.setVisible(vis.nav)
            self.inspector_dock.setVisible(vis.inspector)
            self._user_hid_inspector = not vis.inspector
            self._responsive_hid_inspector = False
            self._settings.setValue(
                "layout/inspector_user_hidden", self._user_hid_inspector
            )
            self.process_dock.setVisible(vis.process)
            self.task_dock.setVisible(vis.tasks)
            self.composite_layer_dock.setVisible(vis.composite_layer)
            self.composite_input_dock.setVisible(vis.composite_input)
            self.composite_linked_dock.setVisible(vis.composite_linked)
            for dock_name, flag in (
                ("well_dock", vis.well),
                ("seismic_dock", vis.seismic),
                ("hub_dock", vis.hub),
            ):
                dock = getattr(self, dock_name, None)
                if dock is not None:
                    dock.setVisible(flag)

            self.explorer.setVisible(vis.explorer_expanded)
            self.activity_rail.set_explorer_expanded(vis.explorer_expanded)

            # Dock everything for a deterministic preset geometry.
            self.dock_all_panels()
        finally:
            self._preset_tracking_paused = False
        self._current_preset_id = preset.id
        self.app_bar.set_current_workspace(preset.id)

        if preset_id == RESET_LAYOUT_PRESET_ID:
            dock_manager.set_active_preset(WorkspacePreset.WORKSTATION_COMPOSITE)
        elif preset_id == "integrated":
            dock_manager.set_active_preset(WorkspacePreset.WORKSTATION_INTERPRETATION)
            if vis.process:
                self._expand_process_dock()
            if vis.tasks:
                self.task_dock.raise_()

        self.status_message.emit(f"已应用布局：{preset.label}")
        QTimer.singleShot(0, self._apply_default_pane_sizes)
        self._save_timer.start()

    def _reset_default_layout(self) -> None:
        """面板菜单「恢复默认布局」→ 默认编图 + 停靠几何。"""
        self.apply_layout_preset(RESET_LAYOUT_PRESET_ID)

    def _reset_composite_layout(self) -> None:
        """恢复编图面板的默认停靠布局（不改可见性）。"""
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

    def layout_preset_visibility(self, preset_id: str) -> dict[str, bool] | None:
        """Test/diagnostic seam: flat visibility matrix for a preset id."""
        preset = get_preset(preset_id)
        if preset is None:
            return None
        return visibility_dict(preset.visibility)

    def _on_activity_mode(self, mode: str) -> None:
        self.explorer.set_mode(mode)
        if mode == "search":
            self.explorer.focus_search()
        elif mode == "history":
            # 历史聚焦资源树的历史视图；不再误开 Agent「日志」tab（#1128）。
            if self.nav_dock.isHidden():
                self.nav_dock.show()
        elif mode == "workspaces":
            self.composite.setFocus(Qt.FocusReason.OtherFocusReason)

    def _activate_explorer_object(self, payload) -> None:
        payload = payload or {}
        kind = payload.get("kind") if isinstance(payload, dict) else ""
        if kind == "well":
            well_name = str(payload.get("well_name") or "").strip()
            if well_name:
                self.show_well(well_name)
            return
        if kind == "resource":
            resource = payload.get("object")
            resource_type = str(getattr(resource, "type", "") or "")
            if resource_type == "well_log":
                resource_name = str(getattr(resource, "name", "") or "").strip()
                if resource_name:
                    self.show_well(resource_name.rsplit(".", 1)[0])
            elif resource_type == "seismic":
                self.show_seismic(resource)
            return
        if kind in {"horizon", "interpretation", "layer"}:
            self.show_seismic()
            return
        if kind == "user_vector_layer":
            self.activate_composite(str(payload.get("layer_id") or ""))

    def _open_well_from_agent(self, well_name: str) -> None:
        self._push_agent_snapshot("open_well")
        self.show_well(well_name)

    def _focus_joint_from_agent(self) -> None:
        self._push_agent_snapshot("focus_joint")
        self.activate_joint()

    def _sync_dock_toggle(self, dock, button, visible: bool) -> None:
        if visible or not hasattr(self._dock_host, "tabifiedDockWidgets"):
            button.setChecked(bool(visible))
            return
        try:
            tabified = bool(self._dock_host.tabifiedDockWidgets(dock))
        except RuntimeError:
            return
        if not tabified:
            button.setChecked(False)

    def _push_agent_snapshot(self, action: str) -> None:
        """撤销用：记录 Agent 动作前的工作区 GUI 状态（B12：真撤销）。"""
        self._agent_undo_stack.append(
            {
                "action": action,
                "well_dock_visible": not self.well_dock.isHidden(),
                "seismic_dock_visible": not self.seismic_dock.isHidden(),
                "well": self._current_well_name,
            }
        )

    def _on_well_focused(self, well_name: str) -> None:
        if well_name:
            self.status_message.emit(f"编图已聚焦井 {well_name}")

    def _on_well_track_toggled(self, on: bool) -> None:
        self.well_dock.setVisible(on)
        if on:
            self.well_dock.raise_()
            self.linked_workspace.ensure_views()

    def _on_seismic_section_toggled(self, on: bool) -> None:
        self.seismic_dock.setVisible(on)
        if on:
            self.seismic_dock.raise_()
            self.linked_workspace.ensure_views()

    def _on_link_toggled(self, on: bool) -> None:
        self.linked_workspace.set_linked(on)

    def _show_wells_from_agent(self) -> None:
        self._push_agent_snapshot("show_wells")
        # 与工具条全幅按钮同一路径：回到 home extent（全部工区井位）。
        self.composite.zoom_to_full_extent()

    def _undo_agent_gui(self, entry=None) -> None:
        """真撤销：弹出动作前快照并恢复；无快照时诚实说明（B12）。"""
        snapshot = self._agent_undo_stack.pop() if self._agent_undo_stack else None
        if snapshot is None:
            self.status_message.emit("没有可撤销的 Agent 工作区变更")
            return
        action = str(snapshot.get("action") or "")
        if action == "open_well":
            prev_well = str(snapshot.get("well") or "")
            if snapshot.get("well_dock_visible") and prev_well:
                self.show_well(prev_well)
            else:
                if not snapshot.get("well_dock_visible"):
                    self.well_dock.hide()
                if prev_well:
                    self.show_well(prev_well)
            self.status_message.emit(f"已撤销：恢复井 {prev_well or '（无）'} 的显示状态")
        elif action == "show_wells":
            self.status_message.emit("已撤销记录：视图范围请用编图画布的范围历史回退")
        elif action == "focus_joint":
            if not snapshot.get("seismic_dock_visible"):
                self.seismic_dock.hide()
            self.status_message.emit("已撤销：地震剖面 dock 已恢复原状")
        else:
            self.status_message.emit("该 Agent 动作没有已记录的撤销状态")

    def _expand_process_dock(self) -> None:
        self.process_dock.show()
        self._dock_host.resizeDocks(
            [self.process_dock], [245], Qt.Orientation.Vertical
        )

    def _schedule_state_save(self) -> None:
        """部件已关闭时不再保存布局——退出/销毁阶段的全部隐藏态不是布局。"""
        if self._layout_frozen or not self.isVisible():
            return
        self._save_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt 契约
        super().showEvent(event)
        if getattr(self, "_pending_default_sizes", False) and self.isVisible():
            self._pending_default_sizes = False
            QTimer.singleShot(0, self._apply_default_pane_sizes)

    def _apply_default_pane_sizes(self) -> None:
        """给中央编图主导的空间分配（首运行/预设重置共用，B15/B17）。

        QMainWindow 对新 dock 默认近似均分窗口宽度：无持久化布局时中央
        画布会被挤到接近零宽——专业工作站必须让地图拿到绝大部分空间。
        resizeDocks 是尽力而为：不可见 dock 由 Qt 忽略，属预期。
        """
        host = self._dock_host
        horizontal = Qt.Orientation.Horizontal
        vertical = Qt.Orientation.Vertical
        host.resizeDocks([self.nav_dock], [264], horizontal)
        host.resizeDocks(
            [self.inspector_dock, self.composite_layer_dock], [312, 312], horizontal
        )
        host.resizeDocks(
            [self.process_dock, self.task_dock, self.composite_linked_dock],
            [224, 224, 200],
            vertical,
        )

    def _restore_layout(self) -> None:
        if self._layout_frozen:
            # teardown 已拆除 dock：迟到的 restore 定时器不得再触碰。
            return
        data = self._settings.value(self._WINDOW_STATE_KEY)
        if data is None:
            # 首运行：没有可恢复的布局，显式给中央编图主导的空间分配，
            # 不靠 QMainWindow 的均分默认值。singleShot 若在 dock 首次布局
            # 前触发会被 Qt 静默忽略（视觉 QA 实测 nav/右列各吃 717px），
            # 改为标记 + showEvent 后补投（见下）。
            self._pending_default_sizes = True
        if data is not None:
            version = self._settings.value(self._STATE_VERSION_KEY, 0, type=int)
            if version != LAYOUT_STATE_VERSION:
                # 版本未知（更旧/无版本）或来自更新的应用：恢复语义无法
                # 保证，丢弃并走默认布局（B2 版本栅栏）。
                _log.warning(
                    "忽略持久化布局：状态版本 %s 与支持的版本 %s 不一致，使用默认布局",
                    version,
                    LAYOUT_STATE_VERSION,
                )
                self._pending_default_sizes = True
            elif isinstance(data, QByteArray) and not data.isNull():
                self._dock_host.restoreState(data)
        # restore 之后必须重新执行响应式策略：restoreState 可能把检查器
        # 在窄屏下重新显示（保存时按「可见」写入），不能让 restore 反杀
        # 响应式隐藏（#1121）。
        self._apply_responsive_panels()

    def _save_layout(self, *, force: bool = False) -> None:
        if self._layout_frozen:
            return  # teardown 后的二次 shutdown 不得写入已拆除的布局（review #8）
        if not self.isVisible() and not force:
            return  # 关闭后保存的全隐藏布局会污染下次启动
        self._settings.setValue(
            "layout/inspector_user_hidden", self._user_hid_inspector
        )
        # 响应式隐藏是临时 viewport 策略，不得写进持久布局（#1121）：
        # 保存时把检查器按「可见」记录，冷启动宽屏即恢复，窄屏由
        # restore 后的 _apply_responsive_panels 再次隐藏。
        suppress_visibility_signals = (
            self._responsive_hid_inspector and not self._user_hid_inspector
        )
        if suppress_visibility_signals:
            self.inspector_dock.blockSignals(True)
            self.inspector_dock.show()
        try:
            self._settings.setValue(
                self._STATE_VERSION_KEY, LAYOUT_STATE_VERSION
            )
            self._settings.setValue(self._WINDOW_STATE_KEY, self._dock_host.saveState())
        finally:
            if suppress_visibility_signals:
                self.inspector_dock.hide()
                self.inspector_dock.blockSignals(False)

    def flush_layout(self) -> None:
        """立即落盘当前布局（忽略可见性守卫）。

        供 ``_refresh_shell`` 在 hide 之前调用：工程切换路径上，
        hide-before-flush 会丢掉 350ms debounce 内的最后一次调整（#1124）。
        """
        if self._layout_frozen:
            return
        self._save_timer.stop()
        self._save_layout(force=True)

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        if self._layout_frozen:
            # 幂等：工程切换路径上 _end_current_session 与 _refresh_shell 会
            # 对同一个 shell 连续调用两次（review #8）。
            return True
        self._save_timer.stop()
        # teardown 前最后一次强制落盘（close 路径不先 hide，force 兜底）。
        self._save_layout(force=True)
        self._layout_frozen = True
        self.process_hub.shutdown()
        self.task_center.shutdown()
        self.composite.shutdown()
        self._teardown_docks()
        return self.linked_workspace.shutdown_workers(wait_ms)

    def _teardown_docks(self) -> None:
        """工程切换 / 退出时把 dock 从宿主上摘除（宿主可被重建复用）。"""
        docks = (
            self.nav_dock,
            self.inspector_dock,
            self.process_dock,
            self.task_dock,
            self.composite_layer_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
            self.well_dock,
            self.seismic_dock,
            self.hub_dock,
        )
        # 先断开布局信号再拆除：removeDockWidget/hide 触发的
        # visibilityChanged 不得重新调度 350ms 后的保存（#1124）。
        for dock in docks:
            dock.blockSignals(True)
        for dock in docks:
            host = dock.parentWidget()
            if isinstance(host, QMainWindow):
                host.removeDockWidget(dock)
            dock.deleteLater()
        # App bar 的容器 toolbar 同样注册在宿主上：不摘除的话，壳重建
        # 一次就多挂一条全局栏。
        toolbar_host = self.app_bar_toolbar.parentWidget()
        if isinstance(toolbar_host, QMainWindow):
            toolbar_host.removeToolBar(self.app_bar_toolbar)
        self.app_bar_toolbar.deleteLater()
        if self._owns_dock_host:
            self._dock_host.deleteLater()
