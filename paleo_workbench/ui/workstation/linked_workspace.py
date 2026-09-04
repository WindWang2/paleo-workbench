from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.viz import welllog_engine_adapter as engine_adapter


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
        # B9: honest degradation note when the docked well panel is not on the
        # native engine (None while the engine backend is active).
        self._well_backend_note: str | None = None

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
        note = self.well_backend_note()
        self.status_changed.emit(
            "井震视图已加载"
            if note is None
            else f"井震视图已加载 · 测井轨道 {note}"
        )

    def _can_create_native_views(self) -> bool:
        resources = list(getattr(self._project, "resources", None) or [])
        return bool(resources)

    def _configure_compact_panels(self) -> None:
        if self.well_panel is not None:
            self.well_panel.title_label.hide()
            self.well_panel.backend_combo.hide()
            # B9: the dock no longer hardcodes the legacy backend; the panel's
            # own engine detection decides (see apply_default_well_backend).
            self.apply_default_well_backend()
        if self.seismic_panel is not None:
            # 联动文档是二维解释面：把地震面板降为 inline 剖面解释形态，
            # 3-D 渲染留给专用三维页。引擎视图改造全部走面板的公开 API
            # （SeismicViewPanel.enter_profile_mode），不再探测引擎私有属性。
            self.seismic_panel.set_interpretation_bar_visible(False)
            self.seismic_panel.enter_profile_mode()

    def apply_default_well_backend(self) -> None:
        """Resolve the docked well backend from real binding availability.

        B9: this dock used to hardcode ``set_backend("legacy")``, which kept
        the native WellLogEngine unreachable in the workstation main flow.
        The adapter's honest detection now decides: ``engine`` when the env
        default is on and the binding imports, otherwise ``legacy`` with the
        fallback reason recorded for the status bar instead of being
        disguised.
        """
        if self.well_panel is None:
            return
        backend, reason = engine_adapter.resolve_default_backend()
        self.set_well_backend(backend, reason=reason)
        note = self.well_backend_note()
        if note is not None:
            self.status_changed.emit(f"测井轨道使用 Legacy 渲染: {note}")

    def set_well_backend(self, name: str, *, reason: str | None = None) -> None:
        """Manual Legacy ↔ WellLogEngine switch for the docked well panel.

        ``reason`` documents why the resolved backend is not the engine; it
        is kept verbatim so the degradation stays traceable (honest, not
        cosmetic). A manual switch without a reason gets a plain description.
        """
        panel = self.well_panel
        if panel is None:
            return
        panel.set_backend(name)
        if panel.backend() == "engine":
            self._well_backend_note = None
            return
        self._well_backend_note = reason or "已切换到 Legacy (QPainter)"

    def well_backend(self) -> str:
        """Effective docked well backend ("" before the views exist)."""
        return self.well_panel.backend() if self.well_panel is not None else ""

    def well_backend_note(self) -> str | None:
        """Why the dock is not on the native engine (``None`` when it is)."""
        return self._well_backend_note

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
