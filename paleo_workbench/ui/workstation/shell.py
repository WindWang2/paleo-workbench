from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.workstation.activity_rail import ActivityRail
from paleo_workbench.ui.workstation.app_bar import WorkstationAppBar
from paleo_workbench.ui.workstation.explorer import WorkstationExplorer
from paleo_workbench.ui.workstation.inspector import WorkstationInspector
from paleo_workbench.ui.workstation.linked_workspace import (
    LinkedInterpretationWorkspace,
)
from paleo_workbench.ui.workstation.process_hub import ProcessHub


class WorkstationFrame(QWidget):
    """Native Qt shell around linked documents and compatible legacy pages."""

    navigation_requested = Signal(int, str)
    command_submitted = Signal(str)
    status_message = Signal(str)

    TAB_JOINT = 0
    TAB_MAP = 1
    TAB_WELL = 2
    TAB_LEGACY = 3

    def __init__(self, project, page_stack: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationFrame")
        self._project = project
        self._project_path: str | None = None
        self._settings = QSettings("PaleoWorkbench", "WorkstationV3")
        self._user_hid_inspector = False
        self._post_show_restored = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save_layout)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.app_bar = WorkstationAppBar(self)
        outer.addWidget(self.app_bar)

        self.body_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.body_splitter.setObjectName("WorkstationBodySplitter")
        self.body_splitter.setChildrenCollapsible(False)
        outer.addWidget(self.body_splitter, 1)

        self.navigation_region = QFrame(self.body_splitter)
        self.navigation_region.setObjectName("WorkstationNavigationRegion")
        nav_layout = QHBoxLayout(self.navigation_region)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        self.activity_rail = ActivityRail(self.navigation_region)
        self.explorer = WorkstationExplorer(project, self.navigation_region)
        nav_layout.addWidget(self.activity_rail)
        nav_layout.addWidget(self.explorer, 1)
        self.navigation_region.setMinimumWidth(54)
        self.navigation_region.setMaximumWidth(470)
        self.body_splitter.addWidget(self.navigation_region)

        self.content_splitter = QSplitter(Qt.Orientation.Vertical, self.body_splitter)
        self.content_splitter.setObjectName("WorkstationContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        # Complex document/task children have generous minimum-size hints.
        # The shell owns responsive sizing, so cap the propagated horizontal
        # minimum and leave room for the object explorer at 1180px windows.
        self.content_splitter.setMinimumWidth(640)
        self.content_splitter.setMinimumHeight(500)
        self.body_splitter.addWidget(self.content_splitter)
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)

        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal, self.content_splitter)
        self.editor_splitter.setObjectName("WorkstationShellEditorSplitter")
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.setMinimumHeight(300)

        self.document_region = QFrame(self.editor_splitter)
        self.document_region.setObjectName("WorkstationDocumentRegion")
        document_layout = QVBoxLayout(self.document_region)
        document_layout.setContentsMargins(0, 0, 0, 0)
        document_layout.setSpacing(0)

        self.document_tabs = QTabBar(self.document_region)
        self.document_tabs.setObjectName("WorkstationDocumentTabs")
        self.document_tabs.setDocumentMode(True)
        self.document_tabs.setExpanding(False)
        self.document_tabs.addTab("井震联合剖面: A12 - D63")
        self.document_tabs.addTab("平面图: D63")
        self.document_tabs.addTab("井轨道: A12")
        self.document_tabs.addTab("项目工作流")
        self.document_tabs.currentChanged.connect(self._on_document_tab_changed)
        document_layout.addWidget(self.document_tabs)

        self.document_stack = QStackedWidget(self.document_region)
        self.document_stack.setObjectName("WorkstationDocumentStack")
        self.document_stack.setMinimumSize(0, 0)
        self.document_stack.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.linked_workspace = LinkedInterpretationWorkspace(project, self.document_stack)
        self.document_stack.addWidget(self.linked_workspace)
        self.page_stack = page_stack
        self.page_stack.setMinimumSize(0, 0)
        self.page_stack.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.document_stack.addWidget(page_stack)
        document_layout.addWidget(self.document_stack, 1)

        self.inspector = WorkstationInspector(project, self.editor_splitter)
        self.editor_splitter.addWidget(self.document_region)
        self.editor_splitter.addWidget(self.inspector)
        self.editor_splitter.setStretchFactor(0, 1)
        self.editor_splitter.setStretchFactor(1, 0)
        self.content_splitter.addWidget(self.editor_splitter)

        self.process_hub = ProcessHub(project, self.content_splitter)
        self.process_hub.setMinimumHeight(150)
        self.content_splitter.addWidget(self.process_hub)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)

        self._wire()
        self.set_project(project)
        QTimer.singleShot(0, self._restore_layout)

    def _wire(self) -> None:
        self.activity_rail.mode_requested.connect(self._on_activity_mode)
        self.activity_rail.collapse_requested.connect(self.toggle_explorer)
        self.explorer.object_selected.connect(self.inspector.show_payload)
        self.explorer.object_activated.connect(self._activate_explorer_object)
        self.explorer.navigation_requested.connect(self.navigation_requested)
        self.explorer.joint_workspace_requested.connect(self.activate_joint)
        self.linked_workspace.object_selected.connect(self.inspector.show_payload)
        self.linked_workspace.status_changed.connect(self.status_message)
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
        for splitter in (
            self.body_splitter,
            self.content_splitter,
            self.editor_splitter,
            self.linked_workspace.horizontal_splitter,
            self.linked_workspace.right_splitter,
            self.process_hub.agent_splitter,
        ):
            splitter.splitterMoved.connect(lambda *_args: self._save_timer.start())

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
        self.process_hub.show_agent()
        self._expand_process_hub()

    def show_tasks(self) -> None:
        self.process_hub.show_tasks()
        self._expand_process_hub()

    def submit_agent_command(self, text: str) -> None:
        self.process_hub.submit_agent_command(text)
        self._expand_process_hub()

    def toggle_explorer(self) -> None:
        visible = self.explorer.isVisible()
        self.explorer.setVisible(not visible)
        if visible:
            self.navigation_region.setMaximumWidth(54)
            self.navigation_region.setMinimumWidth(54)
        else:
            self.navigation_region.setMaximumWidth(470)
            self.navigation_region.setMinimumWidth(250)
            self.body_splitter.setSizes([300, max(600, self.body_splitter.width() - 300)])
        self._save_timer.start()

    def toggle_inspector(self) -> None:
        show = not self.inspector.isVisible()
        self._user_hid_inspector = not show
        self.inspector.setVisible(show)
        if show:
            self.editor_splitter.setSizes(
                [max(520, self.editor_splitter.width() - 300), 300]
            )
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
        if self.width() < 1280 and not self.inspector.isHidden():
            self.inspector.hide()
        elif self.width() >= 1320 and not self._user_hid_inspector and self.inspector.isHidden():
            self.inspector.show()
            self.editor_splitter.setSizes(
                [max(520, self.editor_splitter.width() - 300), 300]
            )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_responsive_panels()
        if not self._post_show_restored:
            self._post_show_restored = True
            # Construction happens before the top-level window has its final
            # geometry. Restore once more after layout so the explorer is not
            # normalized down to the activity-rail minimum on first launch.
            QTimer.singleShot(50, self._restore_layout)

    def _on_document_tab_changed(self, index: int) -> None:
        if index == self.TAB_LEGACY:
            self.document_stack.setCurrentWidget(self.page_stack)
            return
        self.document_stack.setCurrentWidget(self.linked_workspace)
        if index == self.TAB_MAP:
            self.linked_workspace.maximize_map()
        elif index == self.TAB_WELL:
            self.linked_workspace.maximize_well()
        else:
            self.linked_workspace.restore_split_view()

    def _on_activity_mode(self, mode: str) -> None:
        self.explorer.set_mode(mode)
        if mode == "search":
            self.explorer.focus_search()
        elif mode == "history":
            self.process_hub.tabs.setCurrentIndex(2)
            self._expand_process_hub()
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

    def _expand_process_hub(self) -> None:
        total = max(320, self.content_splitter.height())
        self.content_splitter.setSizes([max(320, total - 245), 245])

    def _restore_layout(self) -> None:
        default_body = [300, max(700, self.width() - 300)]
        default_editor = [max(650, self.width() - 600), 300]
        default_content = [max(480, self.height() - 250), 240]
        self.body_splitter.setSizes(self._read_sizes("body", default_body))
        self.editor_splitter.setSizes(self._read_sizes("editor", default_editor))
        self.content_splitter.setSizes(self._read_sizes("content", default_content))
        self.linked_workspace.horizontal_splitter.setSizes(
            self._read_sizes("linked_horizontal", [700, 360])
        )
        self.linked_workspace.right_splitter.setSizes(
            self._read_sizes("linked_vertical", [300, 330])
        )
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
        self._settings.setValue("layout/body", self.body_splitter.sizes())
        self._settings.setValue("layout/editor", self.editor_splitter.sizes())
        self._settings.setValue("layout/content", self.content_splitter.sizes())
        self._settings.setValue(
            "layout/linked_horizontal", self.linked_workspace.horizontal_splitter.sizes()
        )
        self._settings.setValue(
            "layout/linked_vertical", self.linked_workspace.right_splitter.sizes()
        )
        self._settings.setValue("layout/agent", self.process_hub.agent_splitter.sizes())

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        self._save_timer.stop()
        self._save_layout()
        self.process_hub.shutdown()
        return self.linked_workspace.shutdown_workers(wait_ms)
