from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import navigation
from paleo_workbench.ui.deferred_page_bindings import DeferredPageBindings

# Backward-compatible re-exports: callers used to import the page constants
# from app_shell; the hub indices now live in ui.navigation.
from paleo_workbench.ui.navigation import (  # noqa: F401
    PAGE_INDEX_DATA,
    PAGE_INDEX_MAPPING,
    PAGE_INDEX_SEISMIC,
    PAGE_INDEX_VISUALIZATION,
    PAGE_INDEX_WELL,
)
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.geological_modeling_3d_page import (
    GeologicalModeling3DPage,
)
from paleo_workbench.ui.pages.home_page import HomePage
from paleo_workbench.ui.pages.hub_page import HubPage
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage
from paleo_workbench.ui.pages.stratigraphy_correlation_page import (
    StratigraphyCorrelationPage,
)
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.ui.status_bar import StatusBar
from paleo_workbench.ui.workstation import WorkstationFrame
from paleo_workbench.viz.hosts.well_location_preview import (
    WellLocationPreviewStateStore,
)


class CommandPalette(QFrame):
    """Ctrl+K quick-jump palette: searchable list of hubs and sub-modules.

    A plain child widget of the shell (no window flags, no modality), so it
    is safe under the offscreen CI platform. Filter matches page names;
    Enter or click navigates, Esc dismisses.
    """

    _WIDTH = 360
    _HEIGHT = 320

    def __init__(self, parent, *, navigate):
        super().__init__(parent)
        self.setObjectName("PanelCard")  # themed card chrome from the token sheet
        self._navigate = navigate  # navigate(hub_index, submodule_key)
        self._commands: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        layout.setSpacing(tokens.SPACE_2)

        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText("跳转到页面 / 子模块…")
        self.filter_input.installEventFilter(self)
        layout.addWidget(self.filter_input)

        self.result_list = QListWidget(self)
        self.result_list.itemActivated.connect(self._activate_item)
        self.result_list.itemClicked.connect(self._activate_item)
        self.result_list.installEventFilter(self)
        layout.addWidget(self.result_list, 1)

        self.filter_input.textChanged.connect(self._apply_filter)
        self.hide()

    # --- open / close -------------------------------------------------

    def popup(self) -> None:
        shell = self.parentWidget()
        self._rebuild_commands()
        self._apply_filter(self.filter_input.text())
        self.resize(self._WIDTH, self._HEIGHT)
        if shell is not None:
            self.move(
                max(tokens.SPACE_2, (shell.width() - self.width()) // 2),
                tokens.MENU_BAR_HEIGHT + 92 + tokens.SPACE_2,
            )
        self.show()
        self.raise_()
        self.filter_input.setFocus()

    def dismiss(self) -> None:
        self.hide()
        self.filter_input.clear()

    # --- commands -----------------------------------------------------

    def _rebuild_commands(self) -> None:
        commands: list[dict] = []
        for hub_index, hub_name in enumerate(navigation.HUB_NAMES):
            for key in navigation.submodule_keys(hub_index):
                title = navigation.submodule_title(hub_index, key)
                label = hub_name if title == hub_name else f"{hub_name} / {title}"
                commands.append(
                    {
                        "label": label,
                        "hint": f"{hub_name}页 · {title}",
                        "run": lambda h=hub_index, k=key: self._navigate(h, k),
                    }
                )
        self._commands = commands

    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip()
        self.result_list.clear()
        for command in self._commands:
            if text and text not in command["label"] and text not in command["hint"]:
                continue
            item = QListWidgetItem(f"{command['label']}  —  {command['hint']}")
            item.setData(Qt.ItemDataRole.UserRole, command)
            self.result_list.addItem(item)
        if self.result_list.count():
            self.result_list.setCurrentRow(0)

    def _activate_item(self, item: QListWidgetItem) -> None:
        command = item.data(Qt.ItemDataRole.UserRole)
        self.dismiss()
        if command is not None:
            command["run"]()

    # --- keyboard -----------------------------------------------------

    def eventFilter(self, source, event):
        if event.type() == QEvent.Type.KeyPress:
            # Esc dismisses from both the filter box and the result list;
            # all other keys are only intercepted in the filter box (the
            # list keeps native Up/Down/Enter navigation).
            if event.key() == Qt.Key.Key_Escape:
                self.dismiss()
                return True
            if source is self.filter_input:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    item = self.result_list.currentItem()
                    if item is not None:
                        self._activate_item(item)
                        return True
                if key == Qt.Key.Key_Down:
                    row = self.result_list.currentRow()
                    self.result_list.setCurrentRow(
                        min(row + 1, self.result_list.count() - 1)
                    )
                    return True
                if key == Qt.Key.Key_Up:
                    row = self.result_list.currentRow()
                    self.result_list.setCurrentRow(max(row - 1, 0))
                    return True
        return super().eventFilter(source, event)


class AppShell(QWidget):
    """Application shell (workstation V4).

    全局 UI 是工作站 app bar（工程/视图/任务/Agent/工作区预设）；中央是
    ``WorkstationFrame``（编图常驻 + hub 页栈），页面栈按 hub 模型组织：
    :mod:`paleo_workbench.ui.navigation`。历史 Ribbon 命令面已随死 chrome
    移除，命令入口回归页面内工具条与 app bar。
    """

    #: 工程 / 视图动作转发给窗口（PaleoWorkbenchWindow）。Ribbon 删除后
    #: 由 app bar 与 activity rail 直发，信号名保持旧契约。
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_project_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()
    about_requested = Signal()
    preview_settings_requested = Signal()

    def __init__(
        self,
        project: ProjectDocument | None = None,
        parent=None,
        *,
        defer_nonvisible_bindings: bool = False,
        dock_host=None,
    ):
        super().__init__(parent)
        self.setObjectName("AppShell")
        # One theme system (#1047): the manager renders the token sheet for
        # the active palette; AppShell never bypasses it with a direct
        # tokens.build_qss() call.
        from paleo_workbench.ui.theme import theme_manager

        self.theme_manager = theme_manager
        self.setStyleSheet(self.theme_manager.get_qss())
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        # Multi-view coordination engines (#1029): AppShell is the single
        # owner; pages receive these via attribute injection and the
        # ViewCoordinationController mediates every selection sync.
        from paleo_workbench.ui.view_coordination import ViewCoordinationController
        from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
        from paleo_workbench.viz.selection_context import SelectionContext

        self.selection_context = SelectionContext()
        self.coordinate_hub = CoordinateTransformHub()
        self.view_coordination = ViewCoordinationController(
            self.selection_context, self.coordinate_hub, parent=self
        )
        self.project = project or ProjectDocument.new("Untitled Project")
        self._well_location_state_store = WellLocationPreviewStateStore()
        self._fade_anim: QPropertyAnimation | None = None
        # Opening a large project must not eagerly bind every data-heavy page.
        # Deferred callbacks are keyed by HUB index and operation name so
        # repeated refreshes retain just the latest committed project state.
        self._defer_nonvisible_bindings = defer_nonvisible_bindings
        self._deferred_page_bindings = DeferredPageBindings()
        self._workstation_ready = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- hub pages -------------------------------------------------
        self.page_stack = QStackedWidget(self)

        self.home_page = HomePage(self.page_stack)
        self.data_page = DataPage(
            project=self.project,
            well_state_store=self._well_location_state_store,
            parent=self.page_stack,
        )
        self.hub_data = HubPage(navigation.PAGE_INDEX_DATA, self.page_stack)
        self.hub_data.add_submodule("overview", "项目概述", self.home_page)
        self.hub_data.add_submodule("management", "数据管理", self.data_page)
        self.hub_data.finish()
        self.page_stack.addWidget(self.hub_data)  # hub 0 = 数据（首页）

        self.well_log_page = WellLogPredictionPage(self.page_stack)
        self.sequence_page = SequenceFrameworkPage(self.page_stack)
        self.stratigraphy_page = StratigraphyCorrelationPage(self.page_stack)
        self.hub_well = HubPage(navigation.PAGE_INDEX_WELL, self.page_stack)
        self.hub_well.add_submodule("well_log", "测井预测", self.well_log_page)
        self.hub_well.add_submodule("sequence", "层序格架", self.sequence_page)
        self.hub_well.add_submodule("stratigraphy", "地层对比", self.stratigraphy_page)
        self.hub_well.finish()
        self.page_stack.addWidget(self.hub_well)  # hub 1 = 井

        self.seismic_page = SeismicPredictionPage(self.page_stack)
        self.geomodel_page = GeologicalModeling3DPage(self.page_stack)
        self._run_or_defer_page_update(
            navigation.PAGE_INDEX_SEISMIC,
            "project",
            lambda: self.geomodel_page.set_project(self.project),
        )
        self.hub_seismic = HubPage(navigation.PAGE_INDEX_SEISMIC, self.page_stack)
        self.hub_seismic.add_submodule("seismic", "地震预测", self.seismic_page)
        self.hub_seismic.add_submodule("geomodel", "井震联合 3D", self.geomodel_page)
        self.hub_seismic.finish()
        self.page_stack.addWidget(self.hub_seismic)  # hub 2 = 地震

        self.mapping_page = MappingPage(self.page_stack)
        self.preparation_page = PreparationPage(self.page_stack)
        self.review_page = ReviewExportPage(self.page_stack)
        self.hub_mapping = HubPage(navigation.PAGE_INDEX_MAPPING, self.page_stack)
        self.hub_mapping.add_submodule("canvas", "编图画布", self.mapping_page)
        self.hub_mapping.add_submodule("preparation", "数据制备", self.preparation_page)
        self.hub_mapping.add_submodule("review", "成图审核", self.review_page)
        self.hub_mapping.finish()
        self.page_stack.addWidget(self.hub_mapping)  # hub 3 = 编图

        self.visualization_page = VisualizationPage(
            well_state_store=self._well_location_state_store,
            parent=self.page_stack,
        )
        self.page_stack.addWidget(self.visualization_page)  # hub 4 = 可视化（临时）

        self.workstation = WorkstationFrame(
            self.project, self.page_stack, dock_host=dock_host, parent=self
        )
        # QMainWindow 子部件不会被父布局管理（Qt 设计约束）；dock 宿主由
        # 顶层窗口提供时，工作站自身是普通 QWidget 的文档区域。
        self.workstation.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.workstation.setMinimumSize(0, 0)
        outer.addWidget(self.workstation, 1)

        # 状态栏是整个软件的状态信息：有 dock 宿主（顶层 QMainWindow）时
        # 占宿主的原生状态栏槽位——它位于所有 dock 区域（含底部 Agent/
        # 任务中心）之下、贯穿窗口全宽，dock 浮动/停靠都不影响它。
        # 无宿主（测试/孤立构造）时退回中央内容底部。
        # 属性引用不变（shell.status_bar）以兼容既有接线。
        self.status_bar = StatusBar(self)
        self._status_bar_host: QMainWindow | None = None
        if isinstance(dock_host, QMainWindow):
            host_status = dock_host.statusBar()
            host_status.setSizeGripEnabled(False)
            host_status.setContentsMargins(0, 0, 0, 0)
            host_status.addWidget(self.status_bar, 1)
            self._status_bar_host = dock_host
        else:
            outer.addWidget(self.status_bar)

        # All concrete pages, for broadcast-style operations (shutdown,
        # project-path propagation) that must reach inside the hubs.
        self._all_pages = [
            self.home_page,
            self.data_page,
            self.well_log_page,
            self.sequence_page,
            self.stratigraphy_page,
            self.seismic_page,
            self.geomodel_page,
            self.mapping_page,
            self.preparation_page,
            self.review_page,
            self.visualization_page,
        ]

        # Bridge every page's selection surface onto the shared context (#1029).
        self.view_coordination.attach_app_shell(self)
        # Seismic cursor producer (#1029): the panel publishes (IL, XL, TWT)
        # cursor picks through the coordination controller. Wired HERE so the
        # panel never reaches for a global singleton.
        self._wire_seismic_cursor_producer()
        self.workstation.attach_coordination(self.view_coordination)
        # Register the open project's wells + seismic geometry into the
        # coordinate hub so seismic→well routing has a registry (#1029).
        self.view_coordination.bind_project(self.project)

        # Ctrl+K quick-jump palette (non-modal child; offscreen safe).
        self.command_palette = CommandPalette(self, navigate=self.navigate_to)

        # --- global action wiring (app bar → window handlers) -----------
        self.workstation.navigation_requested.connect(self.navigate_to)
        self.workstation.command_submitted.connect(self._handle_workstation_command)
        self.workstation.status_message.connect(self.status_bar.status_label.setText)
        app_bar = self.workstation.app_bar
        app_bar.new_project_requested.connect(self.new_project_requested.emit)
        app_bar.open_project_requested.connect(self.open_project_requested.emit)
        app_bar.open_sample_requested.connect(
            self.open_sample_project_requested.emit
        )
        app_bar.save_project_requested.connect(self.save_project_requested.emit)
        app_bar.properties_requested.connect(self.properties_requested.emit)
        app_bar.about_requested.connect(self.about_requested.emit)
        # 设置入口（activity rail 齿轮）与 app bar 工程菜单同走窗口层。
        self.workstation.activity_rail.settings_requested.connect(
            self.preview_settings_requested.emit
        )
        for hub in (self.hub_data, self.hub_well, self.hub_seismic, self.hub_mapping):
            hub.page_activated.connect(self._on_hub_page_activated)

        self._setup_shortcuts()

        # Land on 数据 / 项目概述. Deliberately NOT navigate_to(): the fade
        # animation installs a QGraphicsOpacityEffect, and any graphics effect
        # in the window forces QOpenGLWidget children of *hidden* sibling
        # pages to initialize on first show (offscreen CI then dies in
        # pyqtgraph's initializeGL). First landing is instant, no fade.
        self._flush_page_updates(navigation.PAGE_INDEX_DATA)
        self.page_stack.setCurrentIndex(navigation.PAGE_INDEX_DATA)
        hub = self.page_stack.widget(navigation.PAGE_INDEX_DATA)
        if isinstance(hub, HubPage):
            key = navigation.DEFAULT_SUBMODULE[navigation.PAGE_INDEX_DATA]
            hub.switch_to(key)
        self._workstation_ready = True

    # --- navigation -------------------------------------------------------

    def navigate_to(self, hub_index: int, submodule_key: str | None = None) -> None:
        """Switch to a hub page, optionally also selecting a sub-module."""
        if not 0 <= hub_index < self.page_stack.count():
            return
        self._flush_page_updates(hub_index)
        self.page_stack.setCurrentIndex(hub_index)
        hub = self.page_stack.widget(hub_index)
        if isinstance(hub, HubPage):
            if submodule_key is None:
                submodule_key = hub.current_key() or navigation.DEFAULT_SUBMODULE[hub_index]
            hub.switch_to(submodule_key)
        activate = getattr(hub, "activate_page", None)
        if callable(activate):
            activate()
        self.command_palette.dismiss()
        self._animate_page_fade(hub_index)
        title = navigation.HUB_NAMES[hub_index]
        if isinstance(hub, HubPage):
            title = navigation.submodule_title(hub_index, hub.current_key())
        self.workstation.activate_legacy(title)

    def _handle_workstation_command(self, text: str) -> None:
        """Route natural-language work to Agent; keep Ctrl+K page search."""
        command = str(text or "").strip()
        if not command:
            return
        agent_markers = (
            "打开", "显示", "生成", "比较", "把", "绘制", "分析", "计算",
            "open ", "show ", "generate ", "compare ", "plot ", "agent ",
        )
        if any(marker in command.lower() for marker in agent_markers):
            self.workstation.submit_agent_command(command)
            return
        self.command_palette.filter_input.setText(command)
        self.command_palette.popup()

    # Backward-compatible alias: old callers passed a flat page index; the
    # new stack is hub-indexed, so the alias is hub-based navigation.
    def _switch_page(self, index: int) -> None:
        self.navigate_to(index)

    def _on_submodule_changed(self, hub_index: int, key: str) -> None:
        # Hub 内子模块切换：无全局 chrome 需要同步（Ribbon 已删），保留
        # 钩子供页面状态接线。
        _ = hub_index, key

    def _on_hub_page_activated(self, hub_index: int, key: str) -> None:
        if self._workstation_ready:
            self.workstation.activate_legacy(
                navigation.submodule_title(hub_index, key)
            )

    def _setup_shortcuts(self) -> None:
        """Register hub (1-5), sub-module (Alt+1~3), and Ctrl+K shortcuts."""
        for i in range(min(5, len(navigation.HUB_NAMES))):
            QShortcut(QKeySequence(str(i + 1)), self,
                      lambda idx=i: self._shortcut_switch_page(idx))

        for p in range(3):
            QShortcut(QKeySequence(f"Alt+{p + 1}"), self,
                      lambda sub_idx=p: self._shortcut_switch_subpage(sub_idx))

        # Command palette (works from text fields too — standard toggle).
        QShortcut(QKeySequence("Ctrl+K"), self, self._toggle_command_palette)

    def _toggle_command_palette(self) -> None:
        # isHidden (not isVisible): a hidden shell window keeps children
        # isVisible() False even after popup(), which would break toggling
        # under offscreen CI.
        if not self.command_palette.isHidden():
            self.command_palette.dismiss()
        else:
            self.command_palette.popup()

    def _shortcut_switch_subpage(self, sub_idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        hub = self.page_stack.currentWidget()
        if not isinstance(hub, HubPage):
            return
        keys = navigation.submodule_keys(hub.hub_index)
        if 0 <= sub_idx < len(keys):
            self.navigate_to(hub.hub_index, keys[sub_idx])

    def _shortcut_switch_page(self, idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        self.navigate_to(idx)

    def set_theme(self, mode) -> None:
        """Switch the application theme (#1047): palette change, same tokens."""
        self.theme_manager.set_theme(mode)

    def _on_theme_changed(self, theme: str, density: str = "") -> None:
        qss = self.theme_manager.get_qss()
        self.setStyleSheet(qss)
        # top-level windows outside this shell (dialogs) follow the theme too
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)

    def _animate_page_fade(self, index: int) -> None:
        """Fade the newly switched page in from 0.7 to 1.0 opacity (150ms).

        A fresh :class:`QGraphicsOpacityEffect` is installed on each switch so
        rapid back-to-back switches restart cleanly: the previous animation is
        stopped and both the previous and current pages are restored to full
        opacity before the new fade begins.
        """
        page = self.page_stack.widget(index)
        if page is None:
            return
        # Stop any in-flight animation and clear effects on the last faded page.
        if self._fade_anim is not None:
            self._fade_anim.stop()
        fade_timer = getattr(self, "_fade_finalize_timer", None)
        if fade_timer is not None:
            fade_timer.stop()
            fade_timer.deleteLater()
        prev = getattr(self, "_fade_page", None)
        if prev is not None and prev is not page:
            prev.setGraphicsEffect(None)
        existing = page.graphicsEffect()
        if isinstance(existing, QGraphicsOpacityEffect):
            existing.setOpacity(1.0)
            page.setGraphicsEffect(None)
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.7)
        page.setGraphicsEffect(effect)
        self._fade_page = page
        self._fade_anim = QPropertyAnimation(effect, b"opacity", page)
        self._fade_anim.setDuration(150)
        self._fade_anim.setStartValue(0.7)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        def finalize_fade(p=page, e=effect) -> None:
            # A busy offscreen event loop may leave the unified animation
            # timer one frame short of exactly 1.0.  Finalize by identity so
            # stale timers from rapid switches cannot clear a newer effect.
            try:
                if p.graphicsEffect() is e:
                    e.setOpacity(1.0)
                    p.setGraphicsEffect(None)
            except RuntimeError:
                return

        self._fade_anim.finished.connect(finalize_fade)
        self._fade_finalize_timer = QTimer(page)
        self._fade_finalize_timer.setSingleShot(True)
        self._fade_finalize_timer.timeout.connect(finalize_fade)
        self._fade_finalize_timer.start(self._fade_anim.duration())
        self._fade_anim.start()

    def _wire_seismic_cursor_producer(self) -> None:
        """Hand the coordination controller to the seismic view panel."""
        panel = getattr(self.seismic_prediction_page_widget(), "view_panel", None)
        attach = getattr(panel, "attach_coordination", None)
        if callable(attach):
            attach(self.view_coordination)
        # Scenario A/B sinks: well selection elsewhere navigates the seismic
        # profiles; a seismic cursor focuses them (via the same 3D renderer).
        locate = getattr(panel, "locate_position", None)
        if callable(locate):
            self.view_coordination.set_seismic_sink(locate)
            self.view_coordination.set_seismic_focus_sink(locate)
        # Scenario B map marker: the well map shows the picked seismic position.
        map_page = getattr(getattr(self.data_page, "well_map_panel", None), "map_page", None)
        show_cursor = getattr(map_page, "show_spatial_cursor", None)
        if callable(show_cursor):
            self.view_coordination.set_spatial_cursor_sink(show_cursor)
        # Scenario B 3D half: the joint scene's slices follow the cursor too
        # (the IL/XL focus, sample only when the TWT maps onto the volume).
        geo_page = self.geomodel_page
        focus_3d = getattr(geo_page, "focus_seismic_position", None)
        if callable(focus_3d):
            # Both consumers run from the same publish; the seismic panel
            # keeps its own debounce on the producer side.
            existing = self.view_coordination._seismic_focus_sink

            def _focus_both(il, xl, twt=None, _existing=existing, _focus3d=focus_3d):
                if callable(_existing):
                    _existing(il, xl, twt)
                _focus3d(il, xl, twt)

            self.view_coordination.set_seismic_focus_sink(_focus_both)
        # Scenario D: the active horizon identity reaches the 3D workbench.
        highlight_interp = getattr(geo_page, "highlight_interpretation", None)
        if callable(highlight_interp):
            self.view_coordination.set_horizon_sink(highlight_interp)

    # --- page accessors (concrete pages inside the hubs) -----------------

    def data_page_widget(self):
        return self.data_page

    def home_page_widget(self):
        return self.home_page

    def mapping_page_widget(self):
        return self.mapping_page

    def well_log_prediction_page_widget(self):
        return self.well_log_page

    def seismic_prediction_page_widget(self):
        return self.seismic_page

    def sequence_framework_page_widget(self):
        return self.sequence_page

    def stratigraphy_correlation_page_widget(self):
        return self.stratigraphy_page

    def preparation_page_widget(self):
        return self.preparation_page

    def review_export_page_widget(self):
        return self.review_page

    def shutdown_workers(self, wait_ms: int = 400) -> bool:
        """Deterministically release project-scoped jobs before a switch.

        Page ``closeEvent`` handlers remain a last line of defence, but a
        project switch must not wait for Qt deferred deletion before closing a
        catalog or replacing native sessions.

        ``wait_ms`` 是每个 job 在 GUI 线程上的等待预算（#1158：此前默认
        3000ms，最坏把项目切换卡 ~6s）；超时未 join 的线程交给
        detached_job_keeper 后台收尾，调用立即返回。
        """
        all_joined = True
        workstation = getattr(self, "workstation", None)
        shutdown_workstation = getattr(workstation, "shutdown_workers", None)
        if callable(shutdown_workstation) and shutdown_workstation(wait_ms) is False:
            all_joined = False
        for page in self._all_pages:
            shutdown = getattr(page, "shutdown_workers", None)
            if callable(shutdown):
                result = shutdown(wait_ms)
                if result is False:
                    all_joined = False
                continue
            shutdown = getattr(page, "_shutdown_workers", None)
            if callable(shutdown):
                result = shutdown()
                if result is False:
                    all_joined = False
        joint_shutdown = getattr(getattr(self, "geomodel_page", None), "_joint_host", None)
        shutdown = getattr(joint_shutdown, "shutdown", None)
        if callable(shutdown):
            shutdown()
        if self._status_bar_host is not None:
            # 状态栏挂在宿主原生槽位上，不随本壳 deleteLater 销毁；本壳之后
            # 必被拆除/重建（所有调用路径都落到 _refresh_shell 或窗口关闭），
            # 不摘除的话宿主上会堆出多条状态栏。
            self._status_bar_host.statusBar().removeWidget(self.status_bar)
            self.status_bar.setParent(self)
            self._status_bar_host = None
        return all_joined

    # --- deferred page binding (hub-keyed) --------------------------------

    def _run_or_defer_page_update(
        self, index: int, name: str, callback
    ) -> None:
        """Apply a hub binding now, or retain its newest state until visit."""

        if (
            self._defer_nonvisible_bindings
            and index != navigation.PAGE_INDEX_DATA
            and self.page_stack.currentIndex() != index
        ):
            self._deferred_page_bindings.schedule(index, name, callback)
            return
        callback()

    def _update_or_defer_page(
        self, index: int, name: str, callback
    ) -> None:
        """Apply a semantic page state refresh, even after its first visit."""

        if self._defer_nonvisible_bindings and index != self.page_stack.currentIndex():
            self._deferred_page_bindings.schedule(index, name, callback)
            return
        callback()

    def defer_page_project_binding(self, index: int, page) -> None:
        """Let workflow wiring bind a project without defeating lazy open."""

        setter = getattr(page, "set_project", None)
        if callable(setter):
            self._run_or_defer_page_update(
                index,
                "project",
                lambda: setter(self.project),
            )

    def _flush_page_updates(self, index: int) -> None:
        self._deferred_page_bindings.flush(index)

    def has_deferred_page_updates(self, index: int) -> bool:
        """Testing/diagnostic seam for first-usable-project page binding."""

        return self._deferred_page_bindings.has_pending(index)

    def set_project_name(self, name: str) -> None:
        self.status_bar.set_project_name(name)
        self.workstation.app_bar.set_project_name(name)

    def current_content_page(self) -> QWidget | None:
        """The concrete page currently shown (inside the hub, if any)."""
        page = self.page_stack.currentWidget()
        if isinstance(page, HubPage):
            return page.page(page.current_key())
        return page

    # --- page state updates (called by app.py's project binding) ---------

    def update_home_page(self, state: dict, steps: list, project=None) -> None:
        if hasattr(self.home_page, "update_state"):
            # Optional project enables Stage-11 readiness on the contract panel.
            try:
                self.home_page.update_state(state, steps, project=project)
            except TypeError:
                self.home_page.update_state(state, steps)

    def update_data_page(
        self,
        state: dict,
        resources: list,
        artifacts: list | None = None,
        *,
        project_path=None,
    ) -> None:
        current_artifacts = artifacts or []
        page = self.data_page
        if project_path is not None and hasattr(page, "set_project_path"):
            page.set_project_path(project_path)
        if hasattr(page, "update_state"):
            page.update_state(state, resources, current_artifacts)
        # Keep the embedded well-location map in sync with the document (§18).
        refresh_map = getattr(page, "refresh_well_map_panel", None)
        if callable(refresh_map):
            refresh_map()

    def set_data_project_path(self, path) -> None:
        """Propagate the open ``*.paleo.json`` path to every project-bound page.

        DataPage, VisualizationPage, WellLogPredictionPage,
        StratigraphyCorrelationPage and ReviewExportPage derive artifact /
        export locations from the real project file path; without this
        routing they would fabricate ``project.paleo.json`` / ``x.paleo.json``
        names and write into phantom ``.artifacts/`` trees. Pages without a
        ``set_project_path`` hook are skipped.
        """
        for page in self._all_pages:
            if page is None or not hasattr(page, "set_project_path"):
                continue
            try:
                page.set_project_path(path)
            except Exception:
                continue
        self.workstation.set_project_path(str(path) if path is not None else None)

    def update_well_log_prediction_page(self, prediction_tasks: list, project=None) -> None:
        page = self.well_log_page
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(prediction_tasks, project=selected_project)

        self._update_or_defer_page(navigation.PAGE_INDEX_WELL, "state:well_log", update)

    def update_seismic_prediction_page(self, prediction_tasks: list, project=None) -> None:
        page = self.seismic_page
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(prediction_tasks, project=selected_project)

        self._update_or_defer_page(navigation.PAGE_INDEX_SEISMIC, "state:seismic", update)

    def update_sequence_framework_page(self, stratigraphy) -> None:
        page = self.sequence_page

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(stratigraphy)

        self._update_or_defer_page(navigation.PAGE_INDEX_WELL, "state:sequence", update)

    def update_stratigraphy_correlation_page(self, project=None) -> None:
        page = self.stratigraphy_page
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(selected_project)

        self._update_or_defer_page(navigation.PAGE_INDEX_WELL, "state:stratigraphy", update)

    def update_visualization_page(
        self,
        resources: list,
        prediction_tasks: list,
        map_documents: list,
        project=None,
    ) -> None:
        page = self.visualization_page
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "update_state"):
                page.update_state(
                    resources,
                    prediction_tasks,
                    map_documents,
                    project=selected_project,
                )

        self._update_or_defer_page(navigation.PAGE_INDEX_VISUALIZATION, "state:viz", update)

    def update_preparation_page(self, tasks: list) -> None:
        page = self.preparation_page

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(tasks)

        self._update_or_defer_page(navigation.PAGE_INDEX_MAPPING, "state:preparation", update)

    def update_mapping_page(
        self,
        map_documents: list,
        *,
        factor_tasks: list | None = None,
        project_crs: str | None = None,
    ) -> None:
        page = self.mapping_page

        def update() -> None:
            if hasattr(page, "update_state"):
                page.update_state(
                    map_documents,
                    factor_tasks=factor_tasks,
                    project_crs=project_crs,
                )

        self._update_or_defer_page(navigation.PAGE_INDEX_MAPPING, "state:canvas", update)

    def update_review_export_page(self, reports: list, map_documents: list, artifacts: list) -> None:
        page = self.review_page

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(reports, map_documents, artifacts)

        self._update_or_defer_page(navigation.PAGE_INDEX_MAPPING, "state:review", update)
