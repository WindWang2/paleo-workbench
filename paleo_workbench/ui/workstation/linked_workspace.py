from __future__ import annotations

from paleo_workbench.ui.workstation.dock_title_bar import install_dock_title_bar

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFrame,    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.workstation.common import workstation_icon


class DocumentPane(QFrame):
    maximize_requested = Signal(object)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationDocumentPane")
        self._content: QWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("WorkstationDocumentPaneHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)
        header_layout.setSpacing(4)
        self.title_label = QLabel(title, header)
        self.title_label.setObjectName("WorkstationDocumentPaneTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        self.link_label = QLabel("联动", header)
        self.link_label.setObjectName("WorkstationLinkBadge")
        header_layout.addWidget(self.link_label)
        self.maximize_button = QToolButton(header)
        self.maximize_button.setObjectName("WorkstationChromeButton")
        self.maximize_button.setIcon(workstation_icon("pane-maximize.svg"))
        self.maximize_button.setIconSize(QSize(14, 14))
        self.maximize_button.setToolTip("最大化 / 恢复")
        self.maximize_button.clicked.connect(lambda: self.maximize_requested.emit(self))
        header_layout.addWidget(self.maximize_button)
        outer.addWidget(header)

        self.host = QFrame(self)
        self.host.setObjectName("WorkstationDocumentPaneHost")
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setSpacing(0)
        outer.addWidget(self.host, 1)

    def set_content(self, content: QWidget) -> None:
        if self._content is content:
            return
        if self._content is not None:
            self.host_layout.removeWidget(self._content)
            self._content.setParent(None)
        self._content = content
        content.setParent(self.host)
        self.host_layout.addWidget(content)
        content.show()

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
        # dock 化后标题同时写到 dock 标题栏（拖动柄 / 浮动窗口标题）。
        dock = self.parentWidget()
        if isinstance(dock, QDockWidget):
            dock.setWindowTitle(title)

    def set_maximized(self, maximized: bool) -> None:
        self.maximize_button.setIcon(
            workstation_icon("pane-restore.svg" if maximized else "pane-maximize.svg")
        )
        self.maximize_button.setToolTip("恢复分屏" if maximized else "最大化")


class LinkedInterpretationWorkspace(QWidget):
    """Actual Map/Seismic/Well Qt views in one synchronized document."""

    object_selected = Signal(object)
    status_changed = Signal(str)

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("LinkedInterpretationWorkspace")
        self._project = project
        self._project_path: str | None = None
        self._views_created = False
        self._load_requested = False
        self._coordination = None
        self._maximized_pane: DocumentPane | None = None
        self._active_well_name = "A12"
        self.seismic_panel = None
        self.map_panel = None
        self.well_panel = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.context_bar = QFrame(self)
        self.context_bar.setObjectName("WorkstationContextBar")
        context_layout = QHBoxLayout(self.context_bar)
        context_layout.setContentsMargins(6, 3, 6, 3)
        context_layout.setSpacing(4)

        self.domain_combo = QComboBox(self.context_bar)
        self.domain_combo.addItems(["剖面", "平面", "井轨道"])
        self.domain_combo.setToolTip("活动解释域")
        context_layout.addWidget(self.domain_combo)
        context_layout.addWidget(self._context_separator())
        for label, icon_name, tip in (
            ("选择", "map/select.svg", "选择解释对象"),
            ("平移", "map/pan.svg", "平移活动视图"),
            ("测量", "map/measure_distance.svg", "测量距离或深度差"),
        ):
            button = QToolButton(self.context_bar)
            button.setObjectName("WorkstationContextButton")
            button.setIcon(workstation_icon(icon_name))
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setToolTip(tip)
            context_layout.addWidget(button)

        context_layout.addWidget(self._context_separator())

        self.display_combo = QComboBox(self.context_bar)
        self.display_combo.addItems(["振幅", "相对振幅", "瞬时相位"])
        self.display_combo.setToolTip("地震显示属性")
        context_layout.addWidget(self.display_combo)

        self.link_button = QToolButton(self.context_bar)
        self.link_button.setObjectName("WorkstationLinkButton")
        self.link_button.setIcon(workstation_icon("rb-link.svg"))
        self.link_button.setText("链接")
        self.link_button.setCheckable(True)
        self.link_button.setChecked(True)
        self.link_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.link_button.setToolTip("同步地图、地震和测井选择")
        self.link_button.toggled.connect(self._set_link_state)
        context_layout.addWidget(self.link_button)
        context_layout.addStretch(1)

        self.reset_layout_button = QToolButton(self.context_bar)
        self.reset_layout_button.setObjectName("WorkstationContextButton")
        self.reset_layout_button.setText("重置布局")
        self.reset_layout_button.setIcon(workstation_icon("map/full_extent.svg"))
        self.reset_layout_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.reset_layout_button.clicked.connect(self.restore_split_view)
        context_layout.addWidget(self.reset_layout_button)

        # 窗格菜单：三个视图 dock 的显隐（QGIS 面板管理语义）
        self.panes_button = QToolButton(self.context_bar)
        self.panes_button.setObjectName("WorkstationContextButton")
        self.panes_button.setIcon(workstation_icon("map/panel-manager.svg"))
        self.panes_button.setText("窗格")
        self.panes_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.panes_button.setToolTip("显示 / 隐藏视图窗格")
        self._panes_menu = QMenu(self.panes_button)
        self.panes_button.setMenu(self._panes_menu)
        self.panes_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        context_layout.addWidget(self.panes_button)
        outer.addWidget(self.context_bar)

        # 三个视图窗格 = 嵌套 QMainWindow 的 QDockWidget：可拖出浮动、
        # 叠 tab、重新停靠、关闭后经「窗格」菜单重开（与综合编修面板同一套
        # Qt 原生窗口管理）。无中央部件，dock 填满整个文档区。
        self.dock_area = QMainWindow(self)
        self.dock_area.setObjectName("WorkstationLinkedDockArea")
        # QMainWindow 默认带 Qt::Window 标志：作为子部件嵌入布局时不可见，
        # 必须显式降级为普通 Widget。
        self.dock_area.setWindowFlags(Qt.WindowType.Widget)
        self.dock_area.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
        )
        self.dock_area.setTabPosition(
            Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North
        )
        outer.addWidget(self.dock_area, 1)

        self.seismic_pane = DocumentPane("井震联合剖面: A12 - D63", self.dock_area)
        self.map_pane = DocumentPane("平面图: D63", self.dock_area)
        self.well_pane = DocumentPane("测井轨道: A12", self.dock_area)

        self.seismic_dock = self._add_pane_dock(
            "linked:seismic", self.seismic_pane,
            Qt.DockWidgetArea.LeftDockWidgetArea,
        )
        self.map_dock = self._add_pane_dock(
            "linked:map", self.map_pane,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.well_dock = self._add_pane_dock(
            "linked:well", self.well_pane,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.dock_area.splitDockWidget(self.map_dock, self.well_dock, Qt.Orientation.Vertical)
        for dock in (self.seismic_dock, self.map_dock, self.well_dock):
            self._panes_menu.addAction(dock.toggleViewAction())

        for pane in (self.seismic_pane, self.map_pane, self.well_pane):
            pane.maximize_requested.connect(self._toggle_maximize)
        self._install_empty_states()

        QTimer.singleShot(0, self._apply_default_split_sizes)

    def _add_pane_dock(self, key: str, pane: DocumentPane, area) -> QDockWidget:
        # dock 标题栏承载窗格名（拖动柄 + 浮动/关闭按钮）；窗格内的标题
        # 标签隐藏，避免双标题行浪费高度。
        dock = QDockWidget(pane.title_label.text(), self.dock_area)
        dock.setObjectName(key)  # saveState/restoreState 需要稳定 objectName
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        dock.setWidget(pane)
        pane.title_label.hide()
        install_dock_title_bar(dock)
        self.dock_area.addDockWidget(area, dock)
        return dock

    def _dock_for_pane(self, pane: DocumentPane) -> QDockWidget:
        return {
            self.seismic_pane: self.seismic_dock,
            self.map_pane: self.map_dock,
            self.well_pane: self.well_dock,
        }[pane]

    @staticmethod
    def _context_separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("WorkstationContextSeparator")
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFixedWidth(1)
        return separator

    def _install_empty_states(self) -> None:
        for pane, text in (
            (self.seismic_pane, "打开包含 SEG-Y 的工程后加载地震解释视图"),
            (self.map_pane, "工程井位与层位地图将在此显示"),
            (self.well_pane, "选择井数据后加载测井轨道"),
        ):
            holder = QWidget(pane)
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(10, 10, 10, 10)
            label = QLabel(text, holder)
            label.setObjectName("WorkstationDocumentEmptyState")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            holder_layout.addWidget(label)
            pane.set_content(holder)

    def set_project(self, project, project_path: str | None = None) -> None:
        self._project = project
        self._project_path = str(project_path) if project_path else None
        if self.map_panel is not None:
            self.map_panel.set_project(project)
        self._load_requested = False
        if self.isVisible():
            QTimer.singleShot(0, self.ensure_views)

    def set_project_path(self, project_path: str | None) -> None:
        self._project_path = str(project_path) if project_path else None
        if self.seismic_panel is not None:
            self.seismic_panel.set_project_path(project_path)

    def attach_coordination(self, controller) -> None:
        self._coordination = controller
        if self.seismic_panel is not None:
            self.seismic_panel.attach_coordination(controller)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # resizeDocks 需要 dock_area 已布局完成；show 后再套一次默认比例。
        QTimer.singleShot(0, self._apply_default_split_sizes)
        if not self._load_requested:
            self._load_requested = True
            QTimer.singleShot(0, self.ensure_views)

    def ensure_views(self) -> None:
        if self._views_created or not self._can_create_native_views():
            return
        from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
        from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
        from paleo_workbench.ui.pages.workarea_map_widget import WorkAreaMapWidget

        self.seismic_panel = SeismicViewPanel(self.seismic_pane)
        # 平面图窗格 = 整张 GIS 工区图（与首页同一渲染后端），无额外工具行；
        # 窗格较小，图例关掉避免遮挡井位（首页工区概况仍显示图例）。
        self.map_panel = WorkAreaMapWidget(self.map_pane, show_legend=False)
        self.well_panel = WellLogCanvasPanel(self.well_pane)
        self._configure_compact_panels()
        self.seismic_pane.set_content(self.seismic_panel)
        self.map_pane.set_content(self.map_panel)
        self.well_pane.set_content(self.well_panel)
        self._views_created = True

        self.map_panel.well_selected.connect(self._on_map_well_selected)
        self.map_panel.well_activated.connect(self.open_well)
        self.well_panel.depth_cursor_moved.connect(self._on_depth_cursor)
        if self._coordination is not None:
            self.seismic_panel.attach_coordination(self._coordination)

        self.map_panel.set_project(self._project)
        seismic = self._first_resource("seismic")
        if seismic is not None:
            self.seismic_panel.set_project_path(self._project_path)
            self.seismic_panel.show_resource(seismic, self._project)
        self.open_well(self._preferred_well_name())
        self.status_changed.emit("井震联合工作区已加载")
        self._apply_default_split_sizes()

    def _can_create_native_views(self) -> bool:
        app = QApplication.instance()
        if app is None or app.platformName() in {"offscreen", "minimal"}:
            return False
        resources = list(getattr(self._project, "resources", None) or [])
        return bool(resources)

    def _configure_compact_panels(self) -> None:
        # 地图窗格是 WorkAreaMapWidget（整张工区图），无需裁剪工具行。
        if self.well_panel is not None:
            self.well_panel.title_label.hide()
            self.well_panel.backend_combo.hide()
            self.well_panel.set_backend("legacy")
        if self.seismic_panel is not None:
            for name in (
                "interp_draft_btn",
                "interp_sync_btn",
                "interp_undo_btn",
                "interp_redo_btn",
                "interp_save_btn",
                "interp_reload_btn",
            ):
                widget = getattr(self.seismic_panel, name, None)
                if widget is not None:
                    widget.hide()
            # The joint document is a 2-D interpretation surface. Reuse the
            # engine's real VD profile renderer and keep its 3-D renderer for
            # the dedicated 3-D document, where it has enough space and a
            # valid graphics context. This also gives remote/X11 sessions a
            # stable first frame when OpenGL acceleration is unavailable.
            view = self.seismic_panel.view
            renderer = getattr(view, "_renderer_3d", None)
            main_splitter = renderer.parentWidget() if renderer is not None else None
            if isinstance(main_splitter, QSplitter):
                renderer.setMinimumHeight(0)
                renderer.hide()
                main_splitter.setCollapsible(0, True)
                main_splitter.setHandleWidth(0)
                main_splitter.setSizes([0, 1000])
            for name in ("_profile_xl", "_profile_t", "_profile_arb"):
                profile = getattr(view, name, None)
                panel = profile.parentWidget() if profile is not None else None
                if panel is not None:
                    panel.hide()
            # Inline 剖面板的整行 header 太占高度：隐藏它，把标识收成一个
            # 小徽标插到主工具条（显示/色标/属性/拾取层位/井震标定 那行）开头。
            inline_profile = getattr(view, "_profile_il", None)
            inline_panel = (
                inline_profile.parentWidget() if inline_profile is not None else None
            )
            if inline_panel is not None:
                panel_layout = inline_panel.layout()
                header = (
                    panel_layout.itemAt(0).widget()
                    if panel_layout is not None and panel_layout.count() > 0
                    else None
                )
                if header is not None:
                    header.hide()
                    header.setFixedHeight(0)
            toolbar_row1 = getattr(view, "_toolbar_row1", None)
            if toolbar_row1 is not None and getattr(view, "_inline_badge", None) is None:
                badge = QLabel("Inline 剖面")
                badge.setStyleSheet(
                    "color: #e53e3e; font-weight: bold; font-size: 11px; padding: 0 4px;"
                )
                actions = toolbar_row1.actions()
                if actions:
                    toolbar_row1.insertWidget(actions[0], badge)
                else:
                    toolbar_row1.addWidget(badge)
                view._inline_badge = badge
            for name in (
                "_3d_mode_combo",
                "_horizon_menu_btn",
                "_render_menu_btn",
                "_overlay_menu_btn",
                "_slice_label",
                "_readout_label",
            ):
                widget = getattr(view, name, None)
                if widget is not None:
                    widget.hide()
            toolbar = getattr(view, "_toolbar_row1", None)
            if toolbar is not None:
                hidden_widgets = {
                    widget
                    for widget in (
                        renderer,
                        getattr(view, "_3d_mode_combo", None),
                        getattr(view, "_horizon_menu_btn", None),
                        getattr(view, "_render_menu_btn", None),
                        getattr(view, "_overlay_menu_btn", None),
                        getattr(view, "_slice_label", None),
                        getattr(view, "_readout_label", None),
                    )
                    if widget is not None
                }
                for action in toolbar.actions():
                    widget = toolbar.widgetForAction(action)
                    label = widget.text().strip() if hasattr(widget, "text") else ""
                    if widget in hidden_widgets or label in {"3D模式:", "加载 SEGY", "Demo"}:
                        action.setVisible(False)

    def open_well(self, well_name_or_id: str) -> None:
        if not self._views_created:
            self.ensure_views()
        if not self._views_created:
            return
        well = self._find_well(well_name_or_id)
        if well is None:
            return
        name = str(getattr(well, "name", "") or well_name_or_id)
        resource = self._well_resource(name)
        if resource is not None:
            self.well_panel.show_resource(resource, self._project)
        self.map_panel.select_well(str(getattr(well, "id", "")), zoom=False, emit=False)
        self._active_well_name = name
        self.seismic_pane.set_title(f"井震联合剖面: {name} - {self._target_horizon()}")
        self.well_pane.set_title(f"测井轨道: {name}")
        self.object_selected.emit({"kind": "well", "object": well, "well_name": name})
        self.status_changed.emit(f"已打开井 {name}")

    def show_all_wells(self) -> None:
        if not self._views_created:
            self.ensure_views()
        if self.map_panel is not None:
            self.map_panel.zoom_to_all()
            self.maximize_map()
            self.status_changed.emit("已显示全部工区井位")

    def focus_joint(self) -> None:
        self.restore_split_view()
        self.status_changed.emit("井震联合工作区已聚焦")

    def maximize_map(self) -> None:
        self._set_maximized(self.map_pane)

    def maximize_well(self) -> None:
        self._set_maximized(self.well_pane)

    def maximize_seismic(self) -> None:
        self._set_maximized(self.seismic_pane)

    def restore_split_view(self) -> None:
        self._maximized_pane = None
        # 恢复默认停靠布局：浮动收回、拖乱的 dock 归位（剖面左，平面/测井右上/下）。
        for dock in (self.seismic_dock, self.map_dock, self.well_dock):
            if dock.isFloating():
                dock.setFloating(False)
        self.dock_area.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.seismic_dock)
        self.dock_area.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.map_dock)
        self.dock_area.splitDockWidget(self.map_dock, self.well_dock, Qt.Orientation.Vertical)
        for dock in (self.seismic_dock, self.map_dock, self.well_dock):
            dock.show()
        for pane in (self.seismic_pane, self.map_pane, self.well_pane):
            pane.set_maximized(False)
        self._apply_default_split_sizes()

    def _toggle_maximize(self, pane: DocumentPane) -> None:
        if self._maximized_pane is pane:
            self.restore_split_view()
        else:
            self._set_maximized(pane)

    def _set_maximized(self, pane: DocumentPane) -> None:
        self._maximized_pane = pane
        target = self._dock_for_pane(pane)
        for dock in (self.seismic_dock, self.map_dock, self.well_dock):
            dock.setVisible(dock is target)
        for candidate in (self.seismic_pane, self.map_pane, self.well_pane):
            candidate.set_maximized(candidate is pane)

    def _apply_default_split_sizes(self) -> None:
        if self._maximized_pane is not None:
            return
        width = max(1, self.dock_area.width())
        height = max(1, self.dock_area.height())
        self.dock_area.resizeDocks(
            [self.seismic_dock, self.map_dock],
            [int(width * 0.66), int(width * 0.34)],
            Qt.Orientation.Horizontal,
        )
        self.dock_area.resizeDocks(
            [self.map_dock, self.well_dock],
            [int(height * 0.48), int(height * 0.52)],
            Qt.Orientation.Vertical,
        )

    def save_dock_state(self) -> bytes:
        return bytes(self.dock_area.saveState())

    def restore_dock_state(self, state) -> bool:
        """恢复 dock 布局；浮动窗格保持浮动（saveState 完整记录几何）。"""
        try:
            return bool(self.dock_area.restoreState(state))
        except Exception:  # noqa: BLE001 — 旧版本布局 blob 不兼容时回退默认布局
            return False

    def _set_link_state(self, enabled: bool) -> None:
        for pane in (self.seismic_pane, self.map_pane, self.well_pane):
            pane.link_label.setText("联动" if enabled else "独立")
            pane.link_label.setProperty("linked", bool(enabled))
            pane.link_label.style().unpolish(pane.link_label)
            pane.link_label.style().polish(pane.link_label)

    def _on_map_well_selected(self, well_id: str) -> None:
        well = self._find_well(well_id)
        if well is not None:
            self.object_selected.emit({"kind": "well", "object": well, "well_name": getattr(well, "name", "")})

    def _on_depth_cursor(self, depth: float) -> None:
        if not self.link_button.isChecked():
            return
        self.status_changed.emit(f"联动深度 {depth:,.1f} m")

    def _first_resource(self, resource_type: str):
        for resource in list(getattr(self._project, "resources", None) or []):
            if str(getattr(resource, "type", "")) == resource_type:
                return resource
        return None

    def _well_resource(self, well_name: str):
        target = str(well_name).upper()
        for resource in list(getattr(self._project, "resources", None) or []):
            if str(getattr(resource, "type", "")) != "well_log":
                continue
            resource_name = Path(str(getattr(resource, "name", "") or "")).stem.upper()
            if resource_name == target:
                return resource
        return None

    def _find_well(self, name_or_id: str):
        target = str(name_or_id or "").upper()
        for well in list(getattr(self._project, "wells", None) or []):
            if str(getattr(well, "id", "")).upper() == target:
                return well
            if str(getattr(well, "name", "")).upper() == target:
                return well
        return None

    def _preferred_well_name(self) -> str:
        if self._find_well("A12") is not None and self._well_resource("A12") is not None:
            return "A12"
        for well in list(getattr(self._project, "wells", None) or []):
            name = str(getattr(well, "name", "") or "")
            if name and self._well_resource(name) is not None:
                return name
        return "A12"

    def _target_horizon(self) -> str:
        stratigraphy = getattr(self._project, "stratigraphy", None)
        return str(getattr(stratigraphy, "target_horizon", "") or "D63")

    def shutdown_workers(self, _wait_ms: int = 3_000) -> bool:
        if self.seismic_panel is not None:
            self.seismic_panel.shutdown()
        if self.well_panel is not None:
            self.well_panel.shutdown()
        return True
