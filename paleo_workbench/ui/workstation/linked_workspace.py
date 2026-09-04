from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class DocumentPane(QFrame):
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


class LinkedInterpretationWorkspace(QWidget):
    """测井轨道 / 地震剖面内容部件的协调器（mapping-centric 壳层）。

    不再是中央文档：两个 :class:`DocumentPane` 由宿主
    ``WorkstationFrame`` 装进宿主级 ``QDockWidget``（默认隐藏，动作打开）。
    嵌套 ``QMainWindow``、平面图窗格与上下文条已删除（编图已含工区井位）。
    """

    object_selected = Signal(object)
    status_changed = Signal(str)
    well_focused = Signal(str)
    show_all_wells_requested = Signal()

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("LinkedInterpretationWorkspace")
        self._project = project
        self._project_path: str | None = None
        self._views_created = False
        self._load_requested = False
        self._coordination = None
        self._linked = True
        self._active_well_name = "A12"
        self.seismic_panel = None
        self.well_panel = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.seismic_pane = DocumentPane("地震剖面", self)
        self.well_pane = DocumentPane("测井轨道", self)
        outer.addWidget(self.seismic_pane, 1)
        outer.addWidget(self.well_pane, 1)
        self._install_empty_states()

    def _install_empty_states(self) -> None:
        for pane, text in (
            (self.seismic_pane, "打开包含 SEG-Y 的工程后加载地震解释视图"),
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
        self._load_requested = False

    def set_project_path(self, project_path: str | None) -> None:
        self._project_path = str(project_path) if project_path else None
        if self.seismic_panel is not None:
            self.seismic_panel.set_project_path(project_path)

    def attach_coordination(self, controller) -> None:
        self._coordination = controller
        if self.seismic_panel is not None:
            self.seismic_panel.attach_coordination(controller)

    def ensure_views(self) -> None:
        if self._views_created or not self._can_create_native_views():
            return
        from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
        from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel

        app = QApplication.instance()
        platform = getattr(app, "platformName", lambda: "")()
        if app is None or platform in {"offscreen", "minimal"}:
            return
        self.seismic_panel = SeismicViewPanel(self.seismic_pane)
        self.well_panel = WellLogCanvasPanel(self.well_pane)
        self._configure_compact_panels()
        self.seismic_pane.set_content(self.seismic_panel)
        self.well_pane.set_content(self.well_panel)
        self._views_created = True

        self.well_panel.depth_cursor_moved.connect(self._on_depth_cursor)
        if self._coordination is not None:
            self.seismic_panel.attach_coordination(self._coordination)

        seismic = self._first_resource("seismic")
        if seismic is not None:
            self.seismic_panel.set_project_path(self._project_path)
            self.seismic_panel.show_resource(seismic, self._project)
        self.open_well(self._preferred_well_name())
        self.status_changed.emit("井震视图已加载")

    def _can_create_native_views(self) -> bool:
        resources = list(getattr(self._project, "resources", None) or [])
        return bool(resources)

    def _configure_compact_panels(self) -> None:
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
            # 联动文档是二维解释面：复用引擎的真实 VD 剖面渲染，
            # 3-D 渲染留给专用三维页。
            view = self.seismic_panel.view
            renderer = getattr(view, "_renderer_3d", None)
            main_splitter = renderer.parentWidget() if renderer is not None else None
            if renderer is not None and isinstance(main_splitter, QSplitter):
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
        well_panel = self.well_panel
        if resource is not None and well_panel is not None:
            well_panel.show_resource(resource, self._project)
        self._active_well_name = name
        self.well_pane.set_title(f"测井轨道 · {name}")
        self.object_selected.emit({"kind": "well", "object": well, "well_name": name})
        self.well_focused.emit(name)
        self.status_changed.emit(f"已打开井 {name}")

    def show_all_wells(self) -> None:
        self.show_all_wells_requested.emit()
        self.status_changed.emit("已显示全部工区井位")

    def focus_joint(self) -> None:
        self.ensure_views()
        self.status_changed.emit("井震视图已聚焦")

    def set_linked(self, enabled: bool) -> None:
        self._linked = bool(enabled)
        for pane in (self.seismic_pane, self.well_pane):
            pane.link_label.setText("联动" if enabled else "独立")
            pane.link_label.setProperty("linked", bool(enabled))
            pane.link_label.style().unpolish(pane.link_label)
            pane.link_label.style().polish(pane.link_label)

    def is_linked(self) -> bool:
        return self._linked

    def _on_depth_cursor(self, depth: float) -> None:
        if not self._linked:
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

    def shutdown_workers(self, _wait_ms: int = 3_000) -> bool:
        if self.seismic_panel is not None:
            self.seismic_panel.shutdown()
        if self.well_panel is not None:
            self.well_panel.shutdown()
        return True
