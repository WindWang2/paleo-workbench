from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.dock_manager import WorkspacePreset, dock_manager
from paleo_workbench.ui.dock_framework import (
    INSPECTOR_HIDE_BELOW,
    INSPECTOR_RESTORE_ABOVE,
    ensure_dock_usable,
    apply_first_run_sizes,
    classify_viewport,
    workstation_dock_registry,
)
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
from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace
from paleo_workbench.ui.workstation.process_hub import ConsolePane, LogViewer
from paleo_workbench.ui.workstation.task_center import TaskCenter

_log = logging.getLogger(__name__)


class HubScrollArea(QScrollArea):
    """功能页自适应滚动宿主（V9 审计 B-1 结构性修复）。

    hub dock 的最小宽度此前等于「当前功能页」的布局最小值（侧板
    fixed width + 不可折叠 splitter），页面一换 dock 就锁死。现在页面
    栈由本滚动区承载：dock 宽于页面最小宽度时按自然布局铺满；被压到
    页面最小宽度以下时出现滚动条（诚实降级），dock 本身永远可以自由
    调整宽度。中央画布不受影响（编图不在页面栈里）。
    """

    def __init__(self, page_stack: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationHubScroll")
        self.setWidget(page_stack)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMinimumSize(0, 0)
        # R2 P1-2：滚动区自身不作 Tab 停靠点/不偷点击焦点（QScrollArea
        # 默认 StrongFocus）；键盘焦点落在子控件时滚动到其可见（QScrollArea
        # 原生不保证）。
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 — Qt 契约
        from PySide6.QtCore import QEvent

        if (
            watched is self.widget()
            and event.type() == QEvent.Type.FocusIn
        ):
            focused = self.widget().focusWidget()
            if focused is not None:
                self.ensureWidgetVisible(focused)
        return super().eventFilter(watched, event)


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
    _WINDOW_GEOMETRY_KEY = "layout/window_geometry"
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
        # 顶栏行归位：restoreState 按 objectName 认条，旧持久化布局
        # （阶段条独占一行、无地图条）恢复后必须重排；_restore_layout 在
        # 每次成功 restore 后都归位（构造 + show 后补投，后者会覆盖前者）。
        self._owns_dock_host = dock_host is None
        # 自有宿主挂为本部件的子窗口：QMainWindow 仍是顶层窗口（不随父
        # 显示），但 QObject 父子链保证壳拆除（deleteLater→C++ 析构）时
        # 宿主连同其 dock/toolbar 子树一并销毁。此前宿主无父，测试路径
        # （不经过 shutdown_workers/_teardown_docks）每壳泄漏一个
        # QMainWindow 子树（约 15 个 dock/toolbar）。
        self._dock_host: QMainWindow = (
            dock_host if dock_host is not None else QMainWindow(self)
        )
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save_layout)
        # R3 P1-1：dock 吸收窗口缩量时本帧宽度不变（resizeEvent 不发），
        # 策略只挂在帧上会失明——恰是紧凑策略该起效的场景。宿主窗口的
        # Resize 事件同样（经同一 180ms 去抖）触发评估。
        self._dock_host.installEventFilter(self)
        # V9：viewport 策略评估定时器（180ms 去抖，restart-on-resize）。
        self._viewport_timer = QTimer(self)
        self._viewport_timer.setSingleShot(True)
        self._viewport_timer.setInterval(180)
        self._viewport_timer.timeout.connect(self._apply_responsive_panels)

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
        # V9：页面栈保留自然 minimumSizeHint——HubScrollArea 会在 dock
        # 过窄时以滚动条降级（见 HubScrollArea），不再需要清零式豁免。
        layout.addWidget(self.composite, 1)

        # --- 面板：全部为宿主窗口上的可浮动 dock -------------------------
        # 中央编图最小宽度：再糟糕的持久化布局（或极端拖拽）也不能把
        # 地图挤没了——dock 布局由 QMainWindow 在中央 minimum 之上分配。
        # V9：420 → 320（B-2 约束栈收敛；配合窗口最小 960x600，紧凑
        # 屏下左导航 + 检查器 + 画布仍各有可用空间）。
        self.composite.setMinimumWidth(320)
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
        # V6 §6：图层检查的域上下文 seam（角色/成熟度/可编辑/新鲜度）。
        # 检查器不解析 mapping 权威——由本壳从 CompositeDocument 取数。
        def _layer_context_seam(payload: dict):
            layer_id = None
            if isinstance(payload, dict):
                layer_id = payload.get("layer_id")
                if not layer_id:
                    obj = payload.get("object")
                    layer_id = getattr(obj, "id", None)
            if not layer_id:
                return None
            return self.composite.layer_domain_status(str(layer_id))

        self.inspector.set_context_seam(_layer_context_seam)
        self._agent_undo_stack: list[dict] = []
        self._current_well_name = ""
        # B18 去重：Agent 面板直接作为 dock 内容（旧 ProcessHub 内层
        # 「任务/日志/控制台」tab 与 dock 层概念重复，已拆除——任务中心 /
        # 日志 / 控制台各自是宿主级 dock，显隐 / 浮动 / 停靠独立）。
        self.agent_panel = AgentWorkspace(project, self._dock_host)
        self.log_viewer = LogViewer(self._dock_host)
        self.console_pane = ConsolePane(self._dock_host)
        # 任务中心是独立面板：与 Agent 各自浮动 / 显隐，不再焊在同一 dock 里。
        self.task_center = TaskCenter(self._dock_host)

        # Dock 身份/几何偏好统一来自 Dock Framework V2 描述符（V9）：
        # 本壳不再散落标题/区域/浮动性字面量；描述符是唯一词表。
        self.nav_dock = self._add_dock("nav", self.navigation_region)
        self.inspector_dock = self._add_dock("inspector", self.inspector)
        self.agent_dock = self._add_dock("agent", self.agent_panel)
        self.task_dock = self._add_dock("tasks", self.task_center)
        self.logs_dock = self._add_dock("logs", self.log_viewer)
        self.console_dock = self._add_dock("console", self.console_pane)

        # 编图面板（由宿主 QMainWindow 持有 dock）
        self.composite_layer_dock = self._add_dock(
            "composite_layer", self.composite.layer_manager
        )
        self.composite_input_dock = self._add_dock(
            "composite_input", self.composite.input_tree
        )
        self.composite_linked_dock = self._add_dock(
            "composite_linked", self.composite.linked_views
        )
        # 测井轨道 / 地震剖面 / 功能页：宿主级 dock，动作打开，默认隐藏。
        self.well_dock = self._add_dock("well", self.linked_workspace.well_pane)
        self.seismic_dock = self._add_dock(
            "seismic", self.linked_workspace.seismic_pane
        )
        # 功能页经 HubScrollArea 承载（B-1）：dock 可自由调整宽度，
        # 窄 dock 下页面滚动降级而不是锁死手柄。
        self.hub_scroll = HubScrollArea(self.page_stack, self._dock_host)
        self.hub_dock = self._add_dock("hub", self.hub_scroll)
        from paleo_workbench.ui.workstation.tool_page_dialog import ToolPageDialog

        self.tool_page_dialog = ToolPageDialog(self._dock_host)
        # V5 编图阶段面板（QStackedWidget 三阶段；中央地图永不切换）。
        from paleo_workbench.ui.workstation.mapping_stage_panel import MappingStagePanel

        self.mapping_stage_panel = MappingStagePanel(self._dock_host)
        self.mapping_stage_dock = self._add_dock(
            "mapping_stage", self.mapping_stage_panel
        )
        self._wire_composite_panel_menu()
        self._apply_canonical_dock_layout()
        self._hide_default_closed_docks()

        # 第 1 行：全局栏 + 阶段条同行（阶段条进 AppBar 空白区；两者共享顶行，
        # 不再独占一整行）。同行多工具条按 sizeHint 共处：全局栏内搜索框可压
        # 缩（最小 180），阶段条固定内容，两者在 ≥1440px 下完整可见。
        from paleo_workbench.ui.workstation.mapping_stage_bar import MappingStageBar

        self.stage_bar = MappingStageBar(self._dock_host)
        self.stage_toolbar = QToolBar("编图阶段切换", self._dock_host)
        self.stage_toolbar.setObjectName("MappingStageToolbar")
        self.stage_toolbar.setMovable(False)
        self.stage_toolbar.setFloatable(False)
        self.stage_toolbar.setContextMenuPolicy(
            Qt.ContextMenuPolicy.PreventContextMenu
        )
        self.stage_toolbar.layout().setContentsMargins(0, 0, 0, 0)
        self.stage_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.stage_toolbar.addWidget(self.stage_bar)
        self._dock_host.addToolBar(
            Qt.ToolBarArea.TopToolBarArea, self.stage_toolbar)

        # 第 2 行：地图工具条（composite 建条、宿主托管；画布上不再悬浮）。
        # Qt 原生允许多工具条并排同行，窄窗时自动换行/原生 » 溢出。
        self._dock_host.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        for _map_bar in self.composite.host_map_toolbars():
            self._dock_host.addToolBar(
                Qt.ToolBarArea.TopToolBarArea, _map_bar)

        self._wire()
        self.set_project(project)
        # 中央永远是编图，无需切换。
        self._schedule_restore(0)

    _AREA_BY_NAME = {
        "left": Qt.DockWidgetArea.LeftDockWidgetArea,
        "right": Qt.DockWidgetArea.RightDockWidgetArea,
        "top": Qt.DockWidgetArea.TopDockWidgetArea,
        "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
    }

    def _add_dock(self, dock_id: str, widget: QWidget) -> QDockWidget:
        # 纯原生 QDockWidget（B18）：原生标题栏负责拖拽停靠 / 浮动 / 叠
        # tab / 浮动关闭按钮，不再安装自绘标题栏（ setTitleBarWidget 会
        # 架空 Qt 原生拖拽——「窗口拖不动 / 不响应停靠」的根因）。壳层
        # 只负责 dock 的创建位置与显隐时机；中央固定为绘图区。
        # V9：标题 / 初始区域 / 浮动性 / 浮动最小尺寸全部来自描述符
        # （dock_framework.workstation_dock_registry），单一词表。
        descriptor = workstation_dock_registry.require(dock_id)
        dock = QDockWidget(descriptor.title, self._dock_host)
        dock.setObjectName(descriptor.object_name)
        # dock_id 属性：批量动作（全部浮动等）据此查阅描述符约束；
        # setTitleBarWidget 之外 Qt 不承载自定义元数据，属性名带 V9
        # 前缀避免与 Qt 动态属性冲突。
        dock.setProperty("pwbDockId", dock_id)
        dock.setWidget(widget)
        features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        if descriptor.can_float:
            features |= QDockWidget.DockWidgetFeature.DockWidgetFloatable
        dock.setFeatures(features)
        dock.setMinimumSize(0, 0)
        float_min = descriptor.min_floating_size
        dock.topLevelChanged.connect(
            lambda floating, d=dock, m=float_min: self._sync_float_min_size(d, floating, m)
        )
        if dock.isFloating():
            dock.setMinimumSize(*float_min)
        self._dock_host.addDockWidget(
            self._AREA_BY_NAME[descriptor.preferred_area], dock
        )
        return dock

    @staticmethod
    def _sync_float_min_size(dock: QDockWidget, floating: bool, min_size) -> None:
        if floating:
            dock.setMinimumSize(*min_size)
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
        # V7 §8：图层树选择驱动类型化 Inspector（layer / factor 分节）。
        composite_layer_panel = getattr(self.composite, "layer_manager", None)
        if composite_layer_panel is not None:
            composite_layer_panel.active_layer_changed.connect(
                self._inspect_layer_selection
            )
        self.agent_panel.open_well_requested.connect(self._open_well_from_agent)
        self.agent_panel.show_wells_requested.connect(self._show_wells_from_agent)
        self.agent_panel.focus_joint_requested.connect(self._focus_joint_from_agent)
        self.agent_panel.undo_requested.connect(self._undo_agent_gui)
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
        # V9：布局保存信号覆盖全部 shell dock（旧实现漏接 logs/console/
        # mapping_stage——单独切换这三个 dock 时布局不会落盘，C-4）。
        for dock in self._shell_docks():
            dock.topLevelChanged.connect(lambda *_: self._schedule_state_save())
            dock.dockLocationChanged.connect(lambda *_: self._schedule_state_save())
            dock.visibilityChanged.connect(lambda *_: self._schedule_state_save())
        # R2 P1-1：检查器显隐归因。visibilityChanged 无法区分来源且异步
        # 发射（策略标志已复位），不能作归因依据；用户显隐全部经过
        # toggleViewAction（标题栏 X / 面板菜单 / palette），而
        # action.triggered 只在用户交互时发射——程序化 setVisible 与
        # restoreState 均不触发。据此归因：显式重开清两类隐藏，显式
        # 关闭独占用户隐藏语义。否则：紧凑下自动折叠 → 用户重开 → 再
        # 关 → 宽屏时策略把面板弹回，跨会话还会复活。
        self.inspector_dock.toggleViewAction().triggered.connect(
            self._attribute_inspector_user_toggle
        )
        # 预设追踪走同一条 visibilityChanged 路径（不新增机制）：预设矩阵
        # 覆盖的 dock 被手动显隐后，当前预设失效（hub_dock 除外——功能页
        # 浮窗由导航管理，不属于工作区布局）。
        for dock in self._preset_tracked_docks():
            dock.visibilityChanged.connect(lambda *_: self._mark_layout_customized())
        self._wire_mapping_stage()
        self._wire_screen_changes()

    def _wire_screen_changes(self) -> None:
        """运行时屏幕集变化（C-7）：显示器拔插/主屏切换 → 重新钳位。

        旧实现只在启动 restore 和面板浮动时 clamp：拔掉显示器后主窗口
        与浮动 dock 可能在不可见桌面上滞留直到重启。连接以本壳为
        receiver，壳销毁时自动断开。
        """
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is None:
            return
        app.screenAdded.connect(self._on_screen_set_changed)
        app.screenRemoved.connect(self._on_screen_set_changed)
        app.primaryScreenChanged.connect(self._on_screen_set_changed)

    def _on_screen_set_changed(self, *_args) -> None:
        if self._layout_frozen:
            return
        # 函数内导入：panel_float_controller 经 floating_panel 依赖本包
        # __init__，模块级导入会闭合成环。
        from paleo_workbench.ui.panel_float_controller import clamp_geometry_to_screens

        host = self._dock_host
        try:
            if host.isVisible() and not (
                host.isMaximized() or host.isFullScreen()
            ):
                current = host.geometry()
                clamped = clamp_geometry_to_screens(current)
                if clamped != current:
                    host.setGeometry(clamped)
        except RuntimeError:
            return  # teardown 竞态：宿主 C++ 已析构（与下方 dock 同类）
        for dock in self._shell_docks():
            try:
                if dock.isFloating() and dock.isVisible():
                    current = dock.geometry()
                    clamped = clamp_geometry_to_screens(current)
                    if clamped != current:
                        dock.setGeometry(clamped)
            except RuntimeError:
                # teardown 竞态：dock 已 C++ 析构而本壳尚存（与 D-3 同类
                # 迟到信号面，_layout_frozen 之外的残余窗口）。
                continue

    def _wire_mapping_stage(self) -> None:
        """V5 阶段工作区接线：阶段条/阶段面板 ↔ MappingStageController。

        阶段切换是瞬时上下文切换（组可见性增量 + 编辑目标重指派 + dock
        建议），绝不重开工程/画布、绝不触发科学重计算；切换前 flush 未
        提交编辑（不静默丢弃，V5 §60）。
        """
        controller = self.composite.stage_controller

        def _request_stage(stage_value: str) -> None:
            if stage_value == controller.current_stage.value:
                return
            self.composite.flush_edit_sessions()
            controller.set_stage(stage_value)

        self.stage_bar.stage_requested.connect(_request_stage)
        self.mapping_stage_panel.stage_switch_requested.connect(_request_stage)
        self.stage_bar.horizon_requested.connect(self._on_mapping_horizon)

        def _on_stage_changed(stage_value: str) -> None:
            self.stage_bar.set_current_stage(stage_value)
            self.mapping_stage_panel.set_stage(stage_value)
            # V6 §4：阶段驱动工具条命令面（数字化/编辑动作按 profile 过滤）。
            self.composite.apply_stage_tool_profile(stage_value)
            # V7 R1-P1：阶段也改变组可见性/白名单/求值器输出——统一可用性
            # 必须随阶段刷新（此前仅 profile 过滤，factor/qa/layout_export
            # 组与阶段禁用项停留在旧阶段状态）。
            self.composite._sync_action_state()
            # 「我画进哪个图层」必须可见：阶段切换消息携带当前编辑目标
            #（无目标时明说，绝不静默）。
            target_id = controller.active_target_layer_id
            if target_id:
                layer = self.composite.edit_controller.layer(str(target_id))
                target_name = layer.name if layer is not None else str(target_id)
                message = (
                    f"编图阶段：{controller.current_stage.label}"
                    f" — 当前编辑目标：{target_name}")
            else:
                message = (
                    f"编图阶段：{controller.current_stage.label}"
                    " — 本阶段尚无编辑对象（用阶段动作创建）")
            self.status_message.emit(message)
            self._refresh_stage_badges()

        controller.current_stage_changed.connect(_on_stage_changed)
        # 构造即应用当前阶段的工具面（恢复的持久化阶段同样生效）。
        self.composite.apply_stage_tool_profile(controller.current_stage.value)

        def _on_readiness(readiness) -> None:
            from paleo_workbench.mapping_workspace.stages import stage_from_value

            stage = stage_from_value(controller.current_stage.value)
            if stage is not None:
                self.mapping_stage_panel.show_readiness(stage, readiness)

        controller.readiness_changed.connect(_on_readiness)

        def _on_stale(summary) -> None:
            self._refresh_stage_badges()

        def _refresh_stage_badges() -> None:
            """阶段条徽标：就绪度（! 未就绪 / ~ 提醒）+ 本阶段过期计数。

            徽标含义经动态 tooltip 解释（✓ 就绪 / ~ 有提醒 / ! 未就绪 /
            N↑ 本阶段过期输入数）——不再让 NOT_READY 显示成空白。
            """
            from paleo_workbench.mapping_workspace.readiness import (
                StageReadinessStatus,
            )
            from paleo_workbench.mapping_workspace.stages import STAGE_ORDER

            stale = controller.stale_summary
            badges: dict[str, str] = {}
            for stage in STAGE_ORDER:
                parts = []
                # 就绪度按各阶段 profile 独立评估（当前阶段的缓存之外，
                # 用轻量重估——只读工程引用，无 IO）。
                if stage == controller.current_stage:
                    status = controller.readiness.status
                else:
                    from paleo_workbench.mapping_workspace.readiness import (
                        evaluate_stage_readiness,
                    )
                    status = evaluate_stage_readiness(
                        stage, document=self._project,
                        workspace_state=controller.state
                        if self._project is not None else None).status
                if status == StageReadinessStatus.NOT_READY:
                    parts.append("!")
                elif status == StageReadinessStatus.READY_WITH_WARNINGS:
                    parts.append("~")
                count = stale.stage_stale_count(stage)
                if count:
                    parts.append(f"{count}↑")
                badges[stage.value] = "".join(parts) or "✓"
            self.stage_bar.refresh_badges(badges)
            # 动态 tooltip：徽标含义 + 本阶段过期输入提示。
            for stage in STAGE_ORDER:
                button = self.stage_bar._buttons.get(stage)
                if button is None:
                    continue
                badge = badges.get(stage.value, "")
                hints = {
                    "!": "未就绪（缺关键输入）",
                    "~": "就绪（有提醒）",
                    "✓": "就绪",
                }
                hint = next((text for glyph, text in hints.items()
                             if glyph in badge), "")
                count = stale.stage_stale_count(stage)
                stale_hint = f"；{count} 项输入成果已过期" if count else ""
                button.setToolTip(
                    f"{stage.label} — {hint}{stale_hint}\n{stage.description}")

        controller.stale_summary_changed.connect(_on_stale)
        self._refresh_stage_badges = _refresh_stage_badges

        # V6 §7：新鲜度进入图层组聚合（group_summary 真实统计）。
        controller.stale_summary_changed.connect(
            controller.group_controller.apply_freshness
        )

        controller.stage_notification.connect(self.status_message.emit)

        # P1-4：就绪度清单「可点击定位」——选中目标组/图层并提升图层管理 dock。
        def _on_locate(stage_value: str, target: str) -> None:
            if not target:
                return
            from paleo_workbench.mapping_workspace.layer_groups import (
                home_group_for_role,
            )

            layer_id = ""
            for lid in controller.state.memberships:
                record = controller.state.membership(lid)
                home = home_group_for_role(
                    record.role, factor_task_id=record.factor_task_id)
                if target in (home, record.factor_task_id or ""):
                    if self.composite.edit_controller.layer(lid) is not None:
                        layer_id = str(lid)
                        break
            if layer_id:
                self.composite.layer_manager.select_layer(layer_id)
            self.composite_layer_dock.show()
            self.composite_layer_dock.raise_()

        self.mapping_stage_panel.locate_requested.connect(_on_locate)

        def _on_dock_recommendation(recommended: dict) -> None:
            self._apply_stage_dock_recommendation(recommended)

        controller.dock_recommendation.connect(_on_dock_recommendation)

        # 阶段动作的 hub 导航请求（单因素制备等既有页面）。
        # V7 修复：此前只 show 浮动 hub dock、不切换子模块（「单因素工作台」
        # 实际停在编图画布）。改为经 navigation_requested 走 AppShell 真导航
        # （切 hub + 子模块 + 激活页面）。
        self._HUB_ROUTES = {
            "mapping": (3, "canvas"),
            "preparation": (3, "preparation"),
            "review": (3, "review"),
            "data": (0, "management"),
        }
        self.composite.hub_page_requested.connect(self._on_hub_page_requested)
        # 阶段面板上下文动作（执行体在 composite 的阶段动作层）。
        self.mapping_stage_panel.action_requested.connect(
            self._dispatch_stage_action)
        self.mapping_stage_panel.constraint_requested.connect(
            self._dispatch_stage_constraint)
        # V6 §4：阶段动作进入命令面板（阶段限定白名单；错误阶段禁用但
        # 保留可发现性 + 原因——palette 据此渲染禁用条目）。
        self._register_stage_palette_commands()

    def _register_stage_palette_commands(self) -> None:
        """阶段面板动作注册为 palette 命令（``stage:<阶段>:<动作>``）。

        阶段面板按钮与 palette 条目共用同一分派路径（``_dispatch_stage_action``），
        动作语义只有一份。``stages`` 白名单使跨阶段调用在 palette 侧被
        禁用并显示原因（命令注册表 evaluate），执行侧不再重复判定。

        V7 §5：有工具面映射的阶段动作追加 ``applicability``——与工具条
        共用 ``tool_surface.evaluate_tool``（经 UIContext 快照适配），
        palette 禁用原因与 tooltip 同一字符串源。
        """
        from paleo_workbench.mapping_workspace.stages import MappingStage
        from paleo_workbench.ui.command_registry import CommandSpec, command_registry
        from paleo_workbench.ui.workstation.mapping_stage_panel import (
            MappingStagePanel,
        )
        from paleo_workbench.ui.workstation.tool_surface import (
            evaluate_tool,
            tool_context_from_ui_snapshot,
        )

        # 阶段动作 id → 工具面 id：单一词表（stage_actions.STAGE_ACTION_TOOLS，
        # 执行侧 re-gate 共用；无映射的动作不受工具门禁，仅阶段白名单）。
        from paleo_workbench.ui.workstation.stage_actions import STAGE_ACTION_TOOLS

        stage_action_tools = STAGE_ACTION_TOOLS

        for stage, actions in (
            (MappingStage.FACIES_CALIBRATION, MappingStagePanel._PHASE1_ACTIONS),
            (MappingStage.CONSTRAINT_FACTOR, MappingStagePanel._PHASE2_ACTIONS),
            (MappingStage.INTEGRATED_COMPILATION, MappingStagePanel._PHASE3_ACTIONS),
        ):
            for action_id, title in actions:
                tool_id = stage_action_tools.get(action_id)

                def _applicability(ctx, _tool=tool_id):
                    if _tool is None:
                        return None
                    avail = evaluate_tool(
                        _tool, tool_context_from_ui_snapshot(ctx)
                    )
                    return avail.disabled_reason or None

                command_registry.register(
                    CommandSpec(
                        id=f"stage:{stage.value}:{action_id}",
                        # 「阶段动作 · 」前缀是刻意的：palette 子序列打分取
                        # 首字符位置，带前缀后导航命令（如「井 / 测井预测」）
                        # 对同名查询仍然先行——阶段动作不抢导航焦点。
                        label=f"阶段动作 · {title}",
                        hint=stage.label,
                        keywords="阶段 stage 编图",
                        group="编图阶段",
                        stages=(stage.value,),
                        applicability=_applicability,
                        callback=lambda s=stage.value, a=action_id: (
                            self._dispatch_stage_action(s, a)
                        ),
                    )
                )
        self._register_surface_palette_commands()

    def _register_surface_palette_commands(self) -> None:
        """V7 §3 / V8 M6：工具面动作注册为 palette 命令（同一求值器）。

        palette 与工具条对同一动作给同一禁用原因（goal §5 四表面一致）；
        回调经 composite 的命令分派（同一执行路径 + execution re-gate）。
        V8：核心编辑/会话/检查命令进 palette（此前只有 surface 组）——
        split/merge/reshape 依赖会话几何细节（palette 快照不可精确判定），
        留在工具条/右键菜单，不进 palette（诚实优先于覆盖）。
        """
        from paleo_workbench.ui.command_registry import CommandSpec, command_registry
        from paleo_workbench.ui.map_action_controller import MapActionController
        from paleo_workbench.ui.workstation.tool_surface import (
            evaluate_tool,
            tool_context_from_ui_snapshot,
        )

        surface_tools = (
            "layer_new", "reference_import", "layer_properties",
            "attribute_table", "layer_zoom", "layer_export", "symbology",
            "style_manager", "factor_workbench", "factor_overlay",
            "qa_run", "map_product_assemble", "map_export",
            # V8 M6：核心编辑/会话/检查命令（快照字段足够精确判定的集合）
            "toggle_editing", "save_edits", "rollback", "undo", "redo",
            "delete_selected", "snapping", "topology",
            "identify", "measure_distance", "select_rectangle",
        )
        labels = MapActionController._LABELS
        from paleo_workbench.ui.workstation.action_help import TOOL_HELP

        for tool_id in surface_tools:

            def _applicability(ctx, _tool=tool_id):
                avail = evaluate_tool(_tool, tool_context_from_ui_snapshot(ctx))
                return avail.disabled_reason or None

            spec = TOOL_HELP.get(tool_id)
            command_registry.register(
                CommandSpec(
                    id=f"map:{tool_id}",
                    label=f"编图 · {labels.get(tool_id, tool_id)}",
                    # M4：palette details 显示执行影响（静态登记处单一来源）。
                    hint=spec.impact if spec else "",
                    keywords="map 编图 图层 符号 因子 导出",
                    group="编图工具",
                    applicability=_applicability,
                    callback=lambda t=tool_id: (
                        self.composite._on_command_requested(t)
                    ),
                )
            )

    def _apply_stage_dock_recommendation(self, recommended: dict) -> None:
        """阶段 dock 建议（仅首次进入阶段时应用；建议而非强制，V5 §6/§7）。

        与 WorkstationLayoutPreset 解耦：这里只调整 dock 显隐（不触碰停靠
        几何/tab 结构），用户后续布局完全自由。
        """
        mapping = {
            "composite_input": self.composite_input_dock,
            "composite_layer": self.composite_layer_dock,
            "inspector": self.inspector_dock,
            "well": self.well_dock,
            "seismic": self.seismic_dock,
            "composite_linked": self.composite_linked_dock,
        }
        for key, visible in (recommended or {}).items():
            dock = mapping.get(str(key))
            if dock is None:
                continue
            dock.setVisible(bool(visible))

    def _sync_mapping_horizon(self) -> None:
        from paleo_workbench.workflow.stratigraphy import (
            active_target_horizon,
            ensure_horizon_catalog,
        )

        project = self._project
        if project is None:
            self.stage_bar.set_horizon_state("", [])
            return
        self.stage_bar.set_horizon_state(
            active_target_horizon(project), ensure_horizon_catalog(project))

    def _on_mapping_horizon(self, horizon: str) -> None:
        from paleo_workbench.workflow.stratigraphy import (
            active_target_horizon,
            set_target_from_boundary,
        )

        project = self._project
        text = str(horizon or "").strip()
        if project is None:
            return
        if not text:
            self._sync_mapping_horizon()
            self.status_message.emit("请先设定编图层位（相图按层位进行）")
            return
        if text == active_target_horizon(project):
            return
        set_target_from_boundary(project, text)
        self._sync_mapping_horizon()
        self.composite.stage_controller.refresh_evaluation()
        self.status_message.emit(f"编图层位：{text}（相图在此层位下进行）")

    def _dispatch_stage_action(self, stage_value: str, action_id: str) -> None:
        """阶段面板上下文动作分派（composite 实现具体工作流）。"""
        handler = getattr(self.composite, "stage_action", None)
        if callable(handler):
            handler(stage_value, action_id)

    def _on_hub_page_requested(self, key: str) -> None:
        """composite 的 hub 导航请求 → 真导航（切 hub + 子模块）。

        未知 key 落到编图 hub 的画布页（与旧行为「显示综合编图」等价，
        但现在真的切换页面而不是只弹 dock）。
        """
        hub_index, subkey = self._HUB_ROUTES.get(
            str(key or "mapping"), (3, "canvas")
        )
        self.navigation_requested.emit(hub_index, subkey)

    def _inspect_layer_selection(self, layer_id) -> None:
        """图层树选择 → 类型化 Inspector payload（V7 §8）。

        factor 系角色（带 factor_task_id）→ 单因素分节（任务 + live 网格
        摘要）；其余 → layer 分节（域行经 context seam）。
        """
        if not layer_id:
            return
        try:
            composite = self.composite
            state = composite.stage_controller.state
            record = state.membership(str(layer_id))
            if record is not None and record.factor_task_id:
                task = None
                for candidate in getattr(self._project, "factor_map_tasks", None) or []:
                    if str(candidate.id) == str(record.factor_task_id):
                        task = candidate
                        break
                if task is not None:
                    # V9（goal §25）：优先提供 FactorSummary 契约行（诚实
                    # 状态），Inspector 无契约时回退 legacy 直读。
                    summary_rows = None
                    try:
                        from paleo_workbench.workflow.interpretation.summaries import (
                            factor_summary_for_task,
                        )

                        summary_rows = factor_summary_for_task(
                            self._project, str(task.id),
                            workspace_state=state,
                        ).to_display_dict()["rows"]
                    except Exception:  # noqa: BLE001 — 契约失败回退直读
                        summary_rows = None
                    self.inspector.show_payload({
                        "kind": "factor",
                        "task": task,
                        "grid": self._factor_grid_summary(record.factor_task_id),
                        "layer_id": str(layer_id),
                        "name": getattr(task, "name", None),
                        "summary_rows": summary_rows,
                    })
                    return
            role = state.role_of(str(layer_id))
            self.inspector.show_payload({
                "kind": "layer",
                "layer_id": str(layer_id),
                "layer_type": role.label,
                "object": composite.edit_controller.layer(str(layer_id)),
                "name": getattr(
                    composite.edit_controller.layer(str(layer_id)), "name", None),
            })
        except RuntimeError:
            pass  # 拆壳期迟到信号
        except Exception:
            logger.exception("inspector layer selection failed")

    @staticmethod
    def _factor_grid_summary(task_id: str) -> dict:
        """live 因子网格摘要（min/max/不确定性；缓存缺失 → 空 dict）。"""
        try:
            from paleo_workbench.project.factor_grid_artifacts import (
                peek_live_factor_grid,
            )

            grid = peek_live_factor_grid(str(task_id))
        except Exception:
            return {}
        if grid is None:
            return {}
        summary: dict = {}
        try:
            values = getattr(grid, "values", None)
            if values is not None:
                import numpy as np

                finite = np.asarray(values, dtype=float)
                finite = finite[np.isfinite(finite)]
                if finite.size:
                    summary["min"] = float(finite.min())
                    summary["max"] = float(finite.max())
            uncertainty = getattr(grid, "uncertainty", None)
            if uncertainty is not None:
                import numpy as np

                array = np.asarray(uncertainty, dtype=float)
                finite = array[np.isfinite(array)]
                if finite.size:
                    summary["uncertainty"] = (float(finite.min()), float(finite.max()))
        except Exception:
            logger.exception("factor grid summary failed")
        return summary

    def _dispatch_stage_constraint(self, kind_value: str) -> None:
        handler = getattr(self.composite, "create_stage_constraint", None)
        if callable(handler):
            handler(kind_value)

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
        self.agent_panel.set_project(project, self._project_path)
        self.composite.set_project(project)
        # V5：工程装载后同步阶段条/面板（composite.set_project 已恢复状态）。
        stage_value = self.composite.stage_controller.current_stage.value
        self.stage_bar.set_current_stage(stage_value)
        self._sync_mapping_horizon()
        self.mapping_stage_panel.set_stage(stage_value)
        self.mapping_stage_panel.show_readiness(
            self.composite.stage_controller.current_stage,
            self.composite.stage_controller.readiness)
        if self.composite.stage_controller.group_controller.degraded:
            self.status_message.emit(
                "当前环境缺少 QGIS 分组能力——图层分组功能不可用（平铺模式）")

    def set_project_path(self, path: str | None) -> None:
        self._project_path = str(path) if path else None
        self.linked_workspace.set_project_path(self._project_path)
        self.agent_panel.set_project(self._project, self._project_path)

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
            self.agent_panel.set_active_well(str(well_name))
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

    #: 编图旁边的工具页：弹出对话框，不进「功能页」dock。
    _TOOL_DIALOG_KEYS = frozenset({"preparation", "review"})

    def show_hub_page(self, title: str) -> None:
        """功能页 dock 显示（V7 D12：不再强制浮动）。

        旧实现每次导航 ``setFloating(True)`` 弹独立窗口——双架构接缝的
        主要来源（预设定制被排除、多屏几何噪声）。现在 hub_dock 是普通
        停靠 dock，导航 = show + raise；用户可自由拖出/叠 tab/关闭，
        与其余 dock 行为一致（重开路径：面板菜单/palette 不变）。
        """
        self.tool_page_dialog.hide()
        self.hub_dock.setWindowTitle(str(title or "功能页"))
        self.hub_dock.show()
        self.hub_dock.raise_()

    def activate_joint(self) -> None:
        self.show_seismic()

    def activate_composite(self, layer_id: str = "") -> None:
        """编图常驻中央；携带 layer_id 时选中该编修图层。"""
        if layer_id:
            self.composite.layer_manager.select_layer(layer_id)

    def activate_legacy(
        self,
        title: str = "功能页",
        *,
        hub_index: int | None = None,
        subkey: str = "",
    ) -> None:
        if subkey in self._TOOL_DIALOG_KEYS and hub_index is not None:
            self._open_tool_page_dialog(title, hub_index, subkey)
            return
        if subkey == "canvas":
            self.hub_dock.hide()
            self.tool_page_dialog.hide()
            return
        self.show_hub_page(title)

    def _open_tool_page_dialog(self, title: str, hub_index: int, subkey: str) -> None:
        hub = self.page_stack.widget(hub_index)
        page = hub.page(subkey) if hasattr(hub, "page") else None
        if page is None:
            self.show_hub_page(title)
            return
        home = getattr(hub, "_stack", None)
        self.hub_dock.hide()
        self.tool_page_dialog.present(page, title, home)

    def show_agent(self) -> None:
        self.agent_dock.show()
        self.agent_dock.raise_()  # 与 task_dock 同 tabify 链：必须前置
        self.agent_panel.command_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._expand_agent_dock()

    def show_tasks(self) -> None:
        # 任务中心独立于 Agent 面板：只 raise 自己所在的 tab 链，绝不
        # 强制展开 agent_dock（旧副作用：打开任务中心连带显示 Agent）。
        self.task_dock.show()
        self.task_dock.raise_()
        self.task_center.tree.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def submit_agent_command(self, text: str) -> None:
        self.agent_dock.show()
        self.agent_dock.raise_()
        self.agent_panel.submit(text)
        self._expand_agent_dock()

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
        """预设可见性矩阵覆盖的 dock（V7 D12：hub 不再强制浮动，纳入追踪）。"""
        return tuple(self._shell_docks())

    def _mark_layout_customized(self) -> None:
        if self._preset_tracking_paused or self._layout_frozen:
            return
        if self._current_preset_id is not None:
            self._current_preset_id = None
            try:
                self.app_bar.set_current_workspace(None)
            except RuntimeError:
                return  # 死壳迟到的可见性信号：C++ 已销毁，忽略

    def eventFilter(self, watched, event) -> None:  # noqa: N802 — Qt 契约
        from PySide6.QtCore import QEvent

        if watched is self._dock_host and event.type() == QEvent.Type.Resize:
            self._request_viewport_evaluation()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # V9（B-4 修复）：viewport 策略评估去抖化——绝不在 resizeEvent
        # 热路径里改布局（旧实现拖 dock 时中央帧宽度跨过 1280 阈值会
        # 立即隐藏检查器，整个 dock 布局在光标下重排）。拖拽/连续缩放
        # 只重启 180ms 定时器，静止后才评估一次。窗口级 resize 由
        # eventFilter（宿主）补充触发（R3 P1-1）。
        self._request_viewport_evaluation()

    def _attribute_inspector_user_toggle(self, visible: bool) -> None:
        """用户经 toggleViewAction 显隐检查器 → 归因为用户意图（R2 P1-1）。

        仅用户交互触发（triggered）；策略 hide/show、程序 dock.show()、
        restoreState 均不进本路径。
        """
        if getattr(self, "_layout_frozen", False):
            return
        if visible:
            # 用户重开：清两类隐藏归属（此后策略不再自作主张收回）。
            self._responsive_hid_inspector = False
            self._user_hid_inspector = False
            self._settings.setValue("layout/inspector_user_hidden", False)
        else:
            # 用户显式关闭（X / 面板菜单）：独占用户隐藏语义。
            self._responsive_hid_inspector = False
            self._user_hid_inspector = True
            self._settings.setValue("layout/inspector_user_hidden", True)

    def _request_viewport_evaluation(self) -> None:
        if self._layout_frozen:
            return
        self._viewport_timer.start()

    def _window_width(self) -> int:
        """工作站顶层窗口逻辑宽度（策略判定输入）。

        生产中 frame.window() 即 dock 宿主（PaleoWorkbenchWindow）；
        孤立构造时是 AppShell（普通顶层部件，可 resize 驱动测试）。
        不用本帧宽度：帧宽已被 dock 占用扣减，在其上判定「窗口窄」会
        对正常宽度二次惩罚（V9 审计 B-4）。
        """
        for source in (self.window(), self._dock_host, self):
            try:
                width = source.width()
            except RuntimeError:
                continue
            if width > 0:
                return width
        return 0

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
        """窄窗检查器折叠策略（V9 阈值：宿主窗口逻辑宽度）。

        V9 尺寸地板收敛后（nav≈230 + inspector 220 + 中央 320），1280
        级窗口已能完整容纳核心 dock；只有真正紧凑（<1100，如
        1366@125% ≈ 1093 逻辑像素）才折叠检查器。恢复阈值 1200 构成
        滞回带，杜绝临界宽度上的隐藏↔显示风暴。
        """
        window_width = self._window_width()
        if window_width <= 0:
            return
        # viewport 分类策略（非偏好性布局约束）：紧凑视口收缩顶栏命令
        # 输入下限、隐藏阶段条前缀标签。密度（字号/控件高度）是用户
        # 显式设置，viewport 策略绝不触碰。
        viewport = classify_viewport(window_width)
        try:
            self.app_bar.set_viewport_class(viewport)
            self.stage_bar.set_viewport_class(viewport)
        except RuntimeError:
            return  # 死壳迟到信号（与 D-3 同类）
        # 折叠前提：面板未被用户显式隐藏过。user=True 且可见只在
        # 「构造读入跨会话偏好 + 首运行默认显示」的边界态出现——策略
        # 此时不接管标记（否则宽屏恢复被 user 阻断，面板卡死在折叠）。
        if (
            window_width < INSPECTOR_HIDE_BELOW
            and not self.inspector_dock.isHidden()
            and not self._user_hid_inspector
        ):
            self._responsive_hid_inspector = True
            self.inspector_dock.hide()
            # R2 P1-1：折叠不是静默的——用户必须能解释面板去哪了。
            self.status_message.emit(
                "窗口较窄：检查器已自动折叠，加宽窗口后自动恢复")
            return
        if (
            self.inspector_dock.isHidden()
            and self._responsive_hid_inspector
            and not self._user_hid_inspector
        ):
            if window_width >= INSPECTOR_RESTORE_ABOVE:
                self._responsive_hid_inspector = False
                self.inspector_dock.show()
                self.status_message.emit("窗口已加宽：检查器已恢复")

    def _schedule_restore(self, delay_ms: int) -> None:
        # 定时器必须挂在本部件上：壳被拆除（deleteLater）后，迟到的
        # restore 不得再触碰已删除的 dock（游离 singleShot 会越界）。
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(delay_ms)
        timer.timeout.connect(self._restore_layout)
        timer.start()

    #: 可切换面板的 (dock, 菜单/palette 标签)——两个消费方共用一张表。
    #: V6：必须覆盖全部 shell dock——任何被关掉的 dock 都要有菜单/palette
    #: 重开入口（否则用户只能重启会话找回面板）。
    _PANEL_TOGGLE_TABLE = (
        ("nav_dock", "显示资源管理器"),
        ("inspector_dock", "显示检查器"),
        ("composite_input_dock", "显示输入与结果"),
        ("composite_layer_dock", "显示图层管理"),
        ("composite_linked_dock", "显示联动视图"),
        ("mapping_stage_dock", "显示编图阶段"),
        ("well_dock", "显示测井轨道"),
        ("seismic_dock", "显示地震剖面"),
        ("hub_dock", "显示枢纽页"),
        ("agent_dock", "显示 Agent"),
        ("task_dock", "显示任务中心"),
        ("logs_dock", "显示日志"),
        ("console_dock", "显示控制台"),
    )

    def panel_commands(self) -> list[tuple[str, QAction]]:
        """可切换面板的 (标签, toggleViewAction) 列表（palette / 菜单共用）。"""
        actions = []
        for attr, label in self._PANEL_TOGGLE_TABLE:
            dock = getattr(self, attr)
            action = dock.toggleViewAction()
            action.setText(label)
            actions.append((label, action))
        return actions

    def _wire_composite_panel_menu(self) -> None:
        """面板菜单：显隐、布局预设、全部浮动/停靠、恢复默认。"""
        toggle_actions = []
        for attr, label in self._PANEL_TOGGLE_TABLE:
            action = getattr(self, attr).toggleViewAction()
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
            self.agent_dock,
            self.task_dock,
            self.logs_dock,
            self.console_dock,
            self.composite_layer_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
            self.well_dock,
            self.seismic_dock,
            self.hub_dock,
            self.mapping_stage_dock,
        )

    def float_all_panels(self) -> None:
        """Float every currently visible shell dock (map stays central).

        R2 P0-1：DockWidgetFloatable 特性位只拦「用户」浮动；程序化
        setFloating(True) 不受其约束。GL 承载 dock（well/seismic/hub）
        绝不能走浮动路径——重父级化 GL 上下文是已记录的 EGL segfault
        类（qt_platform.py）。按描述符 can_float 过滤。
        """
        floated = False
        for dock in self._shell_docks():
            dock_id = str(dock.property("pwbDockId") or "")
            descriptor = workstation_dock_registry.get(dock_id)
            if descriptor is not None and not descriptor.can_float:
                continue
            if not dock.isHidden() and not dock.isFloating():
                dock.setFloating(True)
                dock.raise_()
                floated = True
        if floated:
            self.status_message.emit(
                "已浮动可停靠面板（测井轨道 / 地震剖面 / 功能页含 3D 视图，"
                "不支持浮动以避免 GL 上下文跨窗口重定位崩溃）")
        self._save_timer.start()

    def dock_all_panels(self) -> None:
        """Dock back every floating shell dock to its default area."""
        self._apply_canonical_dock_layout()
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
            self.agent_dock.setVisible(vis.agent)
            self.task_dock.setVisible(vis.tasks)
            self.logs_dock.setVisible(vis.logs)
            self.console_dock.setVisible(vis.console)
            self.composite_layer_dock.setVisible(vis.composite_layer)
            self.composite_input_dock.setVisible(vis.composite_input)
            self.composite_linked_dock.setVisible(vis.composite_linked)
            self.mapping_stage_dock.setVisible(vis.mapping_stage)
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
            # V6：具名预设只切可见性，绝不重排 dock 几何——用户浮动/分屏
            # 布局是显式偏好（audit A-P0-3）。停靠化重置只在
            # 「恢复默认布局」（_reset_default_layout）发生。
        finally:
            self._preset_tracking_paused = False
        self._current_preset_id = preset.id
        self.app_bar.set_current_workspace(preset.id)

        if preset_id == RESET_LAYOUT_PRESET_ID:
            dock_manager.set_active_preset(WorkspacePreset.WORKSTATION_COMPOSITE)
        elif preset_id == "integrated":
            dock_manager.set_active_preset(WorkspacePreset.WORKSTATION_INTERPRETATION)
            # R3 P2-1：预设路径不再触达任何 resizeDocks（B-3 规则的字面
            # 兑现；grow-only 展开只属于显式打开 Agent 的动作路径）。
            if vis.tasks:
                self.task_dock.raise_()

        self.status_message.emit(f"已应用布局：{preset.label}")
        # V9（B-3 修复）：具名预设只切可见性，绝不触碰 dock 几何——
        # 旧实现在此追加 _apply_default_pane_sizes，用户手工尺寸被
        # 280/300/200 系列硬编码值整体回卷。默认尺寸只在首运行/
        # 显式「恢复默认布局」时应用。
        self._save_timer.start()

    def _reset_default_layout(self) -> None:
        """面板菜单「恢复默认布局」→ 停靠几何重置 + 默认尺寸 + 默认可见性。

        R3 P1-2：旧实现只重排停靠结构与可见性，不重应用首运行空间
        分配——被用户拖垮的 dock 几何（如检查器 700px）在「恢复默认」
        后原样保留，唯一恢复途径是抹 QSettings。显式重置是
        ``apply_first_run_sizes`` 的合法调用点（与首运行同一份描述符
        尺寸）。
        """
        self.dock_all_panels()
        self.apply_layout_preset(RESET_LAYOUT_PRESET_ID)
        if not self._layout_frozen and self.isVisible():
            # 50ms：重排后的 QMainWindow 布局需要一轮事件循环安定，
            # 同帧/0ms 的 resizeDocks 会被布局计算覆盖（实测重置无效
            # 的根因）；与首运行 restore 的补投节奏一致。
            QTimer.singleShot(50, self, self._apply_default_pane_sizes)

    def _reset_composite_layout(self) -> None:
        """恢复编图面板的默认停靠布局（不改可见性）。"""
        self._apply_canonical_dock_layout()
        self._save_timer.start()

    def _apply_canonical_dock_layout(self) -> None:
        """固定默认停靠几何：左资源+编图阶段，右图层/检查器，底辅助面板叠 tab。"""
        host = self._dock_host
        for dock in self._shell_docks():
            if dock.isFloating():
                dock.setFloating(False)
        left = Qt.DockWidgetArea.LeftDockWidgetArea
        right = Qt.DockWidgetArea.RightDockWidgetArea
        bottom = Qt.DockWidgetArea.BottomDockWidgetArea
        host.addDockWidget(left, self.nav_dock)
        host.addDockWidget(left, self.mapping_stage_dock)
        host.splitDockWidget(
            self.nav_dock, self.mapping_stage_dock, Qt.Orientation.Vertical)
        host.tabifyDockWidget(self.mapping_stage_dock, self.composite_input_dock)
        host.addDockWidget(right, self.inspector_dock)
        host.addDockWidget(right, self.composite_layer_dock)
        host.tabifyDockWidget(self.inspector_dock, self.composite_layer_dock)
        self.composite_layer_dock.raise_()
        host.addDockWidget(right, self.hub_dock)
        host.addDockWidget(bottom, self.agent_dock)
        host.addDockWidget(bottom, self.task_dock)
        host.tabifyDockWidget(self.agent_dock, self.task_dock)
        host.tabifyDockWidget(self.agent_dock, self.logs_dock)
        host.tabifyDockWidget(self.agent_dock, self.console_dock)
        host.tabifyDockWidget(self.agent_dock, self.composite_linked_dock)
        host.tabifyDockWidget(self.agent_dock, self.well_dock)
        host.tabifyDockWidget(self.well_dock, self.seismic_dock)

    def _hide_default_closed_docks(self) -> None:
        """编图默认：地图为主，只留资源管理器、编图阶段、图层管理、检查器。"""
        for dock in (
            self.well_dock,
            self.seismic_dock,
            self.hub_dock,
            self.logs_dock,
            self.console_dock,
            self.composite_input_dock,
            self.composite_linked_dock,
            self.agent_dock,
            self.task_dock,
        ):
            dock.hide()
        self.nav_dock.show()
        self.mapping_stage_dock.show()
        self.composite_layer_dock.show()
        # 检查器尊重跨会话的用户偏好（user 标志在构造时同步读入）：
        # 用户上会话显式关闭过，首运行/无持久化布局时不强行弹出。
        if self._user_hid_inspector:
            self.inspector_dock.hide()
        else:
            self.inspector_dock.show()

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

    def _expand_agent_dock(self) -> None:
        """打开 Agent 面板时保证底行可用高度（grow-only，V9 B-3）。

        旧实现无条件 resizeDocks([agent_dock],[245])——每次打开 Agent 都
        把用户调好的底行高度压回 245px。现在只在当前高度低于可用下限时
        增长，绝不缩小、绝不钉住。
        """
        self.agent_dock.show()
        descriptor = workstation_dock_registry.get("agent")
        floor = descriptor.preferred_height if descriptor else 245
        ensure_dock_usable(
            self._dock_host, self.agent_dock, minimum=floor, vertical=True
        )

    def _schedule_state_save(self) -> None:
        """部件已关闭时不再保存布局——退出/销毁阶段的全部隐藏态不是布局。"""
        if self._layout_frozen:
            return
        try:
            # 死壳（deleteLater 后包装器仍被 _all_pages / dock 信号引用）
            # 的迟到可见性信号：C++ 已销毁，静默忽略而非刷屏 RuntimeError。
            if self.isVisible():
                self._save_timer.start()
        except RuntimeError:
            pass

    def showEvent(self, event) -> None:  # noqa: N802 — Qt 契约
        super().showEvent(event)
        # V6：合并历史双定义（第一份曾为死代码，post-show 布局恢复从未执行）。
        self._apply_responsive_panels()
        if not self._post_show_restored:
            self._post_show_restored = True
            # 构造发生在顶层窗口拿到最终几何之前；show 之后再恢复一次，
            # 避免 dock 布局被首帧的默认几何覆盖。
            self._schedule_restore(50)
        if getattr(self, "_pending_default_sizes", False) and self.isVisible():
            self._pending_default_sizes = False
            QTimer.singleShot(0, self, self._apply_default_pane_sizes)

    def _apply_default_pane_sizes(self) -> None:
        """首运行/显式重置的空间分配（V9：尺寸来自 dock 描述符）。

        QMainWindow 对新 dock 默认近似均分窗口宽度：无持久化布局时中央
        画布会被挤到接近零宽——专业工作站必须让地图拿到绝大部分空间。
        resizeDocks 是尽力而为：不可见 dock 由 Qt 忽略，属预期。
        调用点仅两处：首运行（无持久化状态）与「恢复默认布局」；
        具名预设应用不再触达（B-3）。
        """
        if getattr(self, "_layout_frozen", False):
            return  # teardown 已拆 dock：迟到的 singleShot 不得触碰
        apply_first_run_sizes(
            self._dock_host,
            {
                "nav": self.nav_dock,
                "mapping_stage": self.mapping_stage_dock,
                "composite_input": self.composite_input_dock,
                "inspector": self.inspector_dock,
                "composite_layer": self.composite_layer_dock,
                "agent": self.agent_dock,
                "tasks": self.task_dock,
                "composite_linked": self.composite_linked_dock,
            },
        )

    def _restore_layout(self) -> None:
        if self._layout_frozen:
            # teardown 已拆除 dock：迟到的 restore 定时器不得再触碰。
            return
        data = self._settings.value(self._WINDOW_STATE_KEY)
        if data is None:
            # 首运行：没有可恢复的布局，显式给中央编图主导的空间分配，
            # 不靠 QMainWindow 的均分默认值。生产构造顺序是同步
            # show()（showEvent 先于本定时器执行），标记必须在此立即消费；
            # showEvent 补投路径保留给「restore 早于首帧显示」的测试序。
            self._pending_default_sizes = True
            if self.isVisible():
                self._pending_default_sizes = False
                QTimer.singleShot(0, self, self._apply_default_pane_sizes)
        restored = False
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
                if self.isVisible():
                    self._pending_default_sizes = False
                    QTimer.singleShot(0, self, self._apply_default_pane_sizes)
            else:
                if isinstance(data, QByteArray) and not data.isNull():
                    self._dock_host.restoreState(data)
                    restored = True
                # 主窗口几何与 dock 状态同栅栏恢复（V6 audit G-P0-2）。
                self._restore_host_window_geometry()
        # restore 之后强制工具条行归位（第 1 行全局栏+阶段条 / 第 2 行地图
        # 工具条）：旧版本 QSettings 存的是「阶段独占第 2 行、无地图工具条」
        # 布局，不校正会出现工具条消失或错位；各条均不可移动，用户无自定义
        # 可丢。每次成功 restore 都重排：本方法每壳最多触发两次（构造 +
        # show 后补投），后一次 restoreState 会覆盖前一次归位结果，只在
        # 首轮重排会被迟到的补投反杀（真机：四条被压回同一行）。重排次数
        # 有界（≤2/壳），break 不会无界堆积；无 restore 时只做残留清扫。
        if restored:
            self._enforce_toolbar_rows()
        else:
            self._sweep_stray_toolbars()
        # restore 之后必须重新执行响应式策略：restoreState 可能把检查器
        # 在窄屏下重新显示（保存时按「可见」写入），不能让 restore 反杀
        # 响应式隐藏（#1121）。
        self._apply_responsive_panels()
        # 归一化「隐藏但无归属」状态：restoreState 恢复出隐藏检查器而两个
        # 显隐标志均为 False。_save_layout 的 suppress hack（#1121）保证
        # 响应式隐藏从不以「隐藏」落盘——因此恢复出的隐藏只可能是用户
        # 手动关闭（原生标题栏 X / 面板菜单均不写 user 标志）。归入
        # 用户隐藏并持久化，宽屏绝不违背用户意愿弹回；toggle 重开即恢复。
        if (
            self.inspector_dock.isHidden()
            and not self._user_hid_inspector
            and not self._responsive_hid_inspector
        ):
            self._user_hid_inspector = True
            self._settings.setValue(
                "layout/inspector_user_hidden", self._user_hid_inspector
            )

    #: 宿主顶栏四条工具条的 objectName（saveState/restoreState 身份 + 清扫依据）。
    _HOST_TOOLBAR_NAMES = (
        "WorkstationAppBarToolbar",
        "MappingStageToolbar",
        "WorkstationMapToolsToolbarTop",
        "WorkstationMapToolsToolbarBottom",
    )

    def _own_toolbar_rows(self) -> tuple:
        """本壳四条顶栏（第 1 行全局栏/阶段条，第 2 行两条地图条）。"""
        return (
            self.app_bar_toolbar,
            self.stage_toolbar,
            *self.composite.host_map_toolbars(),
        )

    @staticmethod
    def _retire_toolbar(bar) -> None:
        """宿主行工具条退役：摘除 + 改名 + 延后销毁。

        改名是关键：``saveState/restoreState`` 按 objectName 认条；旧条
        C++ 对象在 ``deleteLater`` 落定前仍存活，若保留原名会被后建壳的
        ``restoreState`` 按名复活（``findChild`` 取最老匹配），造成同名
        双条挤占顶栏。改名后复活按名查找必然落空。
        """
        try:
            host = bar.parentWidget()
        except RuntimeError:
            return
        if isinstance(host, QMainWindow):
            try:
                host.removeToolBar(bar)
            except RuntimeError:
                pass
        try:
            bar.hide()
            name = str(bar.objectName() or "")
            if not name.endswith("_retired"):
                bar.setObjectName(f"{name}_retired")
            bar.deleteLater()
        except RuntimeError:
            pass

    def _sweep_stray_toolbars(self) -> None:
        """清除宿主上同名但非本壳的顶栏条（前壳拆除不完全的残留）。

        正常 teardown 已退役旧条；本清扫只处理跳过 teardown 的极端路径
        （如已销毁壳的重建）。命中即退役（改名防复活），不动本壳四条。
        """
        if self._layout_frozen:
            return
        try:
            own = set(self._own_toolbar_rows())
            wanted = set(self._HOST_TOOLBAR_NAMES)
            strays = [
                bar for bar in self._dock_host.findChildren(QToolBar)
                if str(bar.objectName() or "") in wanted and bar not in own
            ]
        except RuntimeError:
            return  # 拆壳期迟到调用：C++ 已销毁，忽略
        for bar in strays:
            self._retire_toolbar(bar)

    def _enforce_toolbar_rows(self) -> None:
        """把四条顶栏工具条放回正确行/顺序（第 1 行两条，第 2 行两条）。

        ``saveState/restoreState`` 只认 objectName：旧持久化布局没有地图
        工具条、且阶段条自成一行——恢复后必须重排，否则错位。幂等，可在
        任何时刻调用（迟到的 restore 定时器同样收敛到同一布局）。
        """
        if self._layout_frozen:
            return
        host = self._dock_host
        bars = self._own_toolbar_rows()
        try:
            # 先清扫前壳残留：同名旧条不除，restoreState 会按名复活它们。
            self._sweep_stray_toolbars()
            for bar in bars:
                # removeToolBar 会把条显式隐藏（Qt 语义），重加后必须 show。
                host.removeToolBar(bar)
            host.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.app_bar_toolbar)
            host.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.stage_toolbar)
            host.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
            for bar in self.composite.host_map_toolbars():
                host.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
            for bar in bars:
                bar.show()
        except RuntimeError:
            pass  # 拆壳期迟到调用：C++ 已销毁，忽略

    def _restore_host_window_geometry(self) -> None:
        """恢复主窗口（dock 宿主）几何并 clamp 到可见桌面（V6 G-P0-2）。

        此前窗口本身从不持久化：dock 布局恢复了，窗口却每次回到默认
        1440x900——多显示器用户丢的是同一次「布局」的另一半。恢复走
        同一版本栅栏；restoreGeometry 之后由
        :func:`clamp_geometry_to_screens` 兜底（保存时的显示器已断开时
        窗口必须回到可见桌面，与浮动面板同一条多显示器契约）。
        """
        data = self._settings.value(self._WINDOW_GEOMETRY_KEY)
        if not isinstance(data, QByteArray) or data.isNull():
            return
        # 函数内导入：panel_float_controller 经 floating_panel 依赖本包
        # __init__，模块级导入会闭合成环（review round 1/2 P0）。
        from paleo_workbench.ui.panel_float_controller import clamp_geometry_to_screens

        host = self._dock_host
        host.restoreGeometry(data)
        if host.isMaximized() or host.isFullScreen():
            return  # 最大化/全屏几何由窗口管理器接管
        current = host.geometry()
        clamped = clamp_geometry_to_screens(current)
        if clamped != current:
            host.setGeometry(clamped)

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
            # 主窗口几何随同一版本栅栏落盘（V6 audit G-P0-2）。孤立构造
            # （宿主从未显示）不写：隐藏窗的默认几何会污染真实会话。
            if self._dock_host.isVisible():
                self._settings.setValue(
                    self._WINDOW_GEOMETRY_KEY, self._dock_host.saveGeometry()
                )
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
        self.log_viewer.shutdown()
        self.task_center.shutdown()
        self.composite.shutdown()
        self._teardown_docks()
        return self.linked_workspace.shutdown_workers(wait_ms)

    def _teardown_docks(self) -> None:
        """工程切换 / 退出时把 dock 从宿主上摘除（宿主可被重建复用）。

        dock 清单单一来源 ``_shell_docks()``：本地复制一份 13 元组曾在
        save 接线修复（C-4）中漏掉三个 dock——同类隐患不再留门。
        """
        docks = self._shell_docks()
        # 先断开布局信号再拆除：removeDockWidget/hide 触发的
        # visibilityChanged 不得重新调度 350ms 后的保存（#1124）。
        for dock in docks:
            dock.blockSignals(True)
        for dock in docks:
            host = dock.parentWidget()
            if isinstance(host, QMainWindow):
                host.removeDockWidget(dock)
            dock.deleteLater()
        # App bar 的容器 toolbar 同样退役：只 remove 不改名的话，C++ 对象
        # 在 deleteLater 落定前仍以原名存活，下个壳 restoreState 按名复活。
        self._retire_toolbar(self.app_bar_toolbar)
        # V5 阶段切换条容器 toolbar 同样摘除（防重建叠条）。
        self._retire_toolbar(self.stage_toolbar)
        # 地图工具条（两条，第 2 行）同样退役：条本体挂在宿主名下，不摘除
        # 会残留成下个壳的同名旧条（restoreState 按名复活）。
        try:
            map_bars = self.composite.host_map_toolbars()
        except (AttributeError, RuntimeError):
            map_bars = ()
        for bar in map_bars:
            self._retire_toolbar(bar)
        if self._owns_dock_host:
            self._dock_host.deleteLater()
