from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
from paleo_workbench.ui.ribbon import RibbonBar
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
    """Application shell (UI v2, Ribbon variant A).

    A :class:`RibbonBar` on top (page tabs = the 4+1 hubs, command groups
    per hub/sub-module context, global search), a ``QStackedWidget`` of the
    five hub pages, and a StatusBar. Hub model:
    :mod:`paleo_workbench.ui.navigation`.
    """

    def __init__(
        self,
        project: ProjectDocument | None = None,
        parent=None,
        *,
        defer_nonvisible_bindings: bool = False,
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

        self.ribbon = RibbonBar(navigation.HUB_NAMES, self)
        # Ribbon 右键菜单管理当前页面的内容面板（显隐/浮动）。
        self.ribbon.set_panel_provider(self._current_panel_entries)
        outer.addWidget(self.ribbon)
        # The ribbon remains a compatibility command surface while workflow
        # pages migrate.  The workstation app bar is the visible global UI.
        self.ribbon.setFixedHeight(0)
        self.ribbon.setMinimumWidth(0)
        self.ribbon.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )

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

        self.workstation = WorkstationFrame(self.project, self.page_stack, self)
        outer.addWidget(self.workstation, 1)

        self.status_bar = StatusBar(self)
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

        # --- ribbon contexts & wiring -----------------------------------
        self._density_pairs: list = []
        self._build_ribbon_contexts()
        self.ribbon.tab_changed.connect(self.navigate_to)
        self.workstation.navigation_requested.connect(self.navigate_to)
        self.workstation.command_submitted.connect(self._handle_workstation_command)
        self.workstation.status_message.connect(self.status_bar.status_label.setText)
        app_bar = self.workstation.app_bar
        app_bar.new_project_requested.connect(self.ribbon.new_project_requested.emit)
        app_bar.open_project_requested.connect(self.ribbon.open_project_requested.emit)
        app_bar.open_sample_requested.connect(
            self.ribbon.open_sample_project_requested.emit
        )
        app_bar.save_project_requested.connect(self.ribbon.save_project_requested.emit)
        app_bar.properties_requested.connect(self.ribbon.properties_requested.emit)
        self.workstation.activity_rail.settings_requested.connect(
            self.ribbon.preview_settings_requested.emit
        )
        for hub in (self.hub_data, self.hub_well, self.hub_seismic, self.hub_mapping):
            hub.submodule_changed.connect(self._on_submodule_changed)
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
            self.ribbon.set_context(
                self._context_key(navigation.PAGE_INDEX_DATA, key)
            )
        self.ribbon.set_active_tab(navigation.PAGE_INDEX_DATA)
        self._workstation_ready = True

    # --- ribbon ---------------------------------------------------------

    def _context_key(self, hub_index: int, submodule_key: str) -> str:
        names = {
            navigation.PAGE_INDEX_DATA: "data",
            navigation.PAGE_INDEX_WELL: "well",
            navigation.PAGE_INDEX_SEISMIC: "seismic",
            navigation.PAGE_INDEX_MAPPING: "mapping",
            navigation.PAGE_INDEX_VISUALIZATION: "viz",
        }
        return f"{names[hub_index]}:{submodule_key}"

    def _build_ribbon_contexts(self) -> None:
        """Register every (hub, sub-module) command body and wire commands."""
        # 数据 / 项目概述: 工程 + 视图
        body = self.ribbon.add_context("data:overview")
        self.ribbon.populate_project_group(body)
        self._populate_view_group(body)
        body.finish()

        # 数据 / 数据管理: 导入 + 资产 + 视图
        body = self.ribbon.add_context("data:management")
        toolbar = self.data_page.data_toolbar
        group = body.add_group("导入")
        group.add_button("导入文件", icon="map/btn-import.svg", tooltip="导入文件并创建项目受管的不可变 RAW 副本",
                         on_click=toolbar.import_btn.click)
        group.add_button("导入目录", icon="map/btn-import-folder.svg", tooltip="导入整个目录",
                         on_click=toolbar.import_folder_btn.click)
        group.add_button("重新扫描", icon="map/btn-rescan.svg", tooltip="重新扫描选中项",
                         on_click=toolbar.rescan_btn.click)
        group.add_button("完整性校验", icon="map/btn-verify.svg", tooltip="后台校验数据资产完整性与 SHA-256",
                         on_click=toolbar.verify_btn.click)
        group.add_button("健康检查", icon="map/btn-health.svg", tooltip="数据目录健康体检",
                         on_click=toolbar.health_btn.click)
        group = body.add_group("资产")
        group.add_button("标签筛选", icon="map/btn-tag-filter.svg", tooltip="按标签筛选资产表",
                         on_click=toolbar.tag_filter_btn.click)
        group.add_button("标签管理", icon="map/btn-tag-manager.svg", tooltip="管理项目标签词表",
                         on_click=toolbar.tag_manager_btn.click)
        group.add_button("移出项目", icon="map/btn-remove.svg", tooltip="移出项目（不删源文件）",
                         on_click=toolbar.remove_btn.click)
        group.add_button("打开目录", icon="map/btn-open-folder.svg", tooltip="在文件管理器中打开",
                         on_click=toolbar.open_folder_btn.click)
        group.add_button("可视化", icon="map/btn-visualize.svg", tooltip="在可视化页面打开",
                         on_click=toolbar.visualize_btn.click)
        self._populate_view_group(body)
        body.finish()

        # 井 / 测井预测: 数据 + 预测 + 成果 + 视图
        body = self.ribbon.add_context("well:well_log")
        page = self.well_log_page
        group = body.add_group("数据")
        group.add_button("导入 LAS/XML", icon="map/btn-import.svg", tooltip="导入 LAS / XML 测井数据",
                         on_click=page.import_well_btn.click)
        evidence = page.evidence_panel
        group = body.add_group("预测")
        group.add_button("运行预测", icon="rb-run.svg", tooltip="运行线上测井预测",
                         on_click=evidence.run_btn.click)
        group.add_button("演示预测", icon="rb-demo.svg", tooltip="运行演示预测",
                         on_click=evidence.demo_btn.click)
        group.add_button("复制日志", icon="rb-copy.svg", tooltip="复制运行日志",
                         on_click=evidence.copy_diagnostic_btn.click)
        group = body.add_group("成果")
        group.add_button("导出剖面", icon="rb-export.svg", tooltip="导出单井剖面",
                         on_click=evidence.export_btn.click)
        group.add_button("发送制备", icon="rb-send.svg", tooltip="发送预测成果到数据制备",
                         on_click=evidence.send_btn.click)
        self._populate_view_group(body)
        body.finish()

        # 井 / 层序格架: 选择型页面，无页级命令 — 视图
        body = self.ribbon.add_context("well:sequence")
        self._populate_view_group(body)
        body.finish()

        # 井 / 地层对比: 数据 + 编辑 + 解释版本 + 导出 + 视图
        body = self.ribbon.add_context("well:stratigraphy")
        page = self.stratigraphy_page
        group = body.add_group("数据")
        group.add_button("加载剖面", icon="rb-load.svg", tooltip="加载连井剖面",
                         on_click=page.load_btn.click)
        group.add_button("绑定井", icon="rb-link.svg", tooltip="选用预测绑定井",
                         on_click=page.select_bound_btn.click)
        group = body.add_group("编辑")
        group.add_button("撤销", icon="map/undo.svg", tooltip="撤销", on_click=page.undo_btn.click)
        group.add_button("重做", icon="map/redo.svg", tooltip="重做", on_click=page.redo_btn.click)
        group.add_button("自动连线", icon="rb-auto-link.svg", tooltip="自动连线",
                         on_click=page.auto_link_btn.click)
        group.add_button("DTW 传播", icon="rb-dtw.svg", tooltip="DTW 传播",
                         on_click=page.dtw_btn.click)
        group.add_button("清空剖面", icon="rb-clear.svg", tooltip="清空剖面",
                         on_click=page.clear_btn.click)
        group = body.add_group("解释版本")
        group.add_button("保存版本", icon="menu-save.svg", tooltip="保存解释版本",
                         on_click=page.save_interp_btn.click)
        group.add_button("打开版本", icon="menu-open.svg", tooltip="打开已保存解释",
                         on_click=page.open_interp_btn.click)
        group.add_button("恢复版本", icon="map/rollback.svg", tooltip="恢复已保存版本",
                         on_click=page.restore_interp_btn.click)
        group = body.add_group("导出")
        group.add_button("导出剖面", icon="rb-export.svg", tooltip="导出连井剖面",
                         on_click=page.export_btn.click)
        group.add_button("导出分层", icon="rb-export.svg", tooltip="导出分层顶 CSV",
                         on_click=page.export_tops_btn.click)
        self._populate_view_group(body)
        body.finish()

        # 地震 / 地震预测: 预测 + 视图
        body = self.ribbon.add_context("seismic:seismic")
        toolbar = self.seismic_page.context_toolbar
        group = body.add_group("预测")
        group.add_button("运行预测", icon="rb-run.svg", tooltip="运行地震预测",
                         on_click=toolbar.run_btn.click)
        group.add_button("演示预测", icon="rb-demo.svg", tooltip="运行演示预测",
                         on_click=toolbar.demo_btn.click)
        group.add_button("设置详情", icon="rb-settings.svg", tooltip="设置与详情",
                         on_click=toolbar.settings_btn.click)
        self._populate_view_group(body)
        body.finish()

        # 地震 / 井震联合 3D: 数据 + 分析 + 视图
        body = self.ribbon.add_context("seismic:geomodel")
        page = self.geomodel_page
        group = body.add_group("数据")
        group.add_button("刷新数据", icon="map/refresh.svg", tooltip="从工程/数据刷新",
                         on_click=page._joint_add_btn.click)
        group = body.add_group("分析")
        group.add_button("分析", icon="rb-analysis.svg", tooltip="分析",
                         on_click=page._joint_analysis_btn.click)
        group.add_button("切片位置", icon="rb-slice.svg", tooltip="切片位置",
                         on_click=page._joint_slice_card_btn.click)
        group.add_button("色标", icon="rb-colorbar.svg", tooltip="色标",
                         on_click=page._joint_color_card_btn.click)
        group.add_button("井间剖面", icon="rb-fence.svg", tooltip="井间剖面",
                         on_click=page._joint_fence_btn.click)
        group.add_button("删 active", icon="map/delete_selected.svg", tooltip="删除 active 井间剖面",
                         on_click=page._joint_del_fence_btn.click)
        self._populate_view_group(body)
        body.finish()

        # 编图 / 编图画布: 编辑 + 视图
        # (导航/选择/要素工具在页面内的图标工具条中 — 全量搬进 Ribbon 会超宽;
        # Ribbon 承载的是状态性强的编辑动作。)
        body = self.ribbon.add_context("mapping:canvas")
        group = body.add_group("编辑")
        for action_id in (
            "toggle_editing", "save_edits", "rollback", "undo", "redo",
            "delete_selected",
        ):
            self._add_map_action(group, action_id)
        group = body.add_group("画布")
        for action_id in ("full_extent", "refresh", "snapping", "topology"):
            self._add_map_action(group, action_id)
        self._populate_view_group(body)
        body.finish()

        # 编图 / 数据制备: 生成 + 质检 + 边界 + 视图
        body = self.ribbon.add_context("mapping:preparation")
        page = self.preparation_page
        group = body.add_group("生成")
        group.add_button("批量生成", icon="rb-generate.svg", tooltip="批量生成单因素图",
                         on_click=page.task_panel.generate_btn.click)
        group.add_button("等值线初稿", icon="map/btn-contour-draft.svg", tooltip="生成等值线初稿",
                         on_click=page.task_panel.contour_draft_btn.click)
        group = body.add_group("质检")
        group.add_button("井数据质检", icon="rb-qc.svg", tooltip="运行井数据质检",
                         on_click=page.well_table_panel.run_qc_btn.click)
        group = body.add_group("边界")
        group.add_button("生成边界", icon="rb-boundary.svg", tooltip="生成初始边界并送入编图",
                         on_click=page.boundary_panel.generate_btn.click)
        self._populate_view_group(body)
        body.finish()

        # 编图 / 成图审核: 质检 + 定稿 + 视图
        body = self.ribbon.add_context("mapping:review")
        header = self.review_page.action_header
        group = body.add_group("质检")
        group.add_button("运行检查", icon="rb-qc.svg", tooltip="运行自动质检规则",
                         on_click=header.run_btn.click)
        group.add_button("规则配置", icon="rb-settings.svg", tooltip="规则配置",
                         on_click=header.config_btn.click)
        group.add_button("导出报告", icon="rb-export.svg", tooltip="导出检查报告",
                         on_click=header.export_btn.click)
        group = body.add_group("定稿")
        group.add_button("专家定稿", icon="rb-finalize.svg", tooltip="写入 VersionSet 快照并标记为 final",
                         on_click=header.finalize_btn.click)
        self._populate_view_group(body)
        body.finish()

        # 可视化 (临时页): 显示 + 视图
        body = self.ribbon.add_context("viz:viz")
        group = body.add_group("显示")
        btn = group.add_button(
            "网格(IL/XL)", icon="rb-grid.svg", tooltip="显示 IL/XL 网格坐标", checkable=True,
            on_click=self.visualization_page.btn_coord.click,
        )
        self.visualization_page.btn_coord.toggled.connect(btn.setChecked)
        self._populate_view_group(body)
        body.finish()

    def _add_map_action(self, group, action_id: str):
        """Mirror one MapActionController QAction as a ribbon button."""
        action = self.mapping_page.action_controller.actions[action_id]
        btn = group.add_button(
            action.text(), icon=f"map/{action_id}.svg", tooltip=action.toolTip(),
            checkable=action.isCheckable(), on_click=action.trigger,
        )
        btn.setChecked(action.isChecked())
        btn.setEnabled(action.isEnabled())
        action.toggled.connect(btn.setChecked)
        action.changed.connect(lambda a=action, b=btn: b.setEnabled(a.isEnabled()))
        return btn

    def _populate_view_group(self, body) -> None:
        """Shared 视图 group: density pair + preview settings."""
        group = body.add_group("视图")
        comfortable = group.add_button(
            "舒适", icon="rb-density-comfortable.svg", tooltip="界面密度：舒适", checkable=True,
            on_click=lambda: self.ribbon.density_changed.emit("comfortable"),
        )
        compact = group.add_button(
            "紧凑", icon="rb-density-compact.svg", tooltip="界面密度：紧凑", checkable=True,
            on_click=lambda: self.ribbon.density_changed.emit("compact"),
        )
        comfortable.setChecked(True)
        self._density_pairs.append((comfortable, compact))
        group.add_button(
            "预览设置", icon="menu-preview-settings.svg", tooltip="预览设置…",
            on_click=self.ribbon.preview_settings_requested.emit,
        )

    def set_density_checked(self, density: str) -> None:
        """Sync every context's density pair with the active density."""
        for comfortable, compact in self._density_pairs:
            comfortable.setChecked(density == "comfortable")
            compact.setChecked(density == "compact")

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
            self.ribbon.set_context(self._context_key(hub_index, submodule_key))
        else:
            self.ribbon.set_context(self._context_key(hub_index, "viz"))
        activate = getattr(hub, "activate_page", None)
        if callable(activate):
            activate()
        self.command_palette.dismiss()
        self.ribbon.set_active_tab(hub_index)
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
        self.ribbon.set_context(self._context_key(hub_index, key))

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

        # Collapse/expand the ribbon command body (Office Ctrl+F1).
        QShortcut(QKeySequence("Ctrl+F1"), self, self.ribbon.toggle_collapsed)

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

    def _on_theme_changed(self, theme: str) -> None:
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

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Deterministically release project-scoped jobs before a switch.

        Page ``closeEvent`` handlers remain a last line of defence, but a
        project switch must not wait for Qt deferred deletion before closing a
        catalog or replacing native sessions.
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

    def _current_panel_entries(self) -> list[dict]:
        """Ribbon 右键菜单的数据源：当前页面的可管理面板。"""
        if self.workstation.is_joint_active():
            return self.workstation.panel_entries()
        page = self.current_content_page()
        getter = getattr(page, "ribbon_panel_entries", None)
        if not callable(getter):
            return []
        return getter()

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
