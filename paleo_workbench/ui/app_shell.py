from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QPoint, QPropertyAnimation, QEasingCurve, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QStackedWidget, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

from paleo_workbench.ui.icon_rail import IconRail
from paleo_workbench.ui.deferred_page_bindings import DeferredPageBindings
from paleo_workbench.ui.menu_bar import MenuBar
from paleo_workbench.ui.page_placeholder import PagePlaceholder
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.home_page import HomePage
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
from paleo_workbench.viz.hosts.well_location_preview import (
    WellLocationPreviewStateStore,
)
from paleo_workbench.ui.sidebar import (
    SIDEBAR_DEFAULT_WIDTH,
    ContextSidebar,
    TextSidebar,
)
from paleo_workbench.ui.status_bar import StatusBar
from paleo_workbench.ui.workflow_stepper import WorkflowStepper
from paleo_workbench import tokens
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem

from paleo_workbench.ui import navigation
from paleo_workbench.ui.navigation import (
    PAGE_INDEX_DATA,
    PAGE_INDEX_HOME,
    PAGE_INDEX_MAPPING,
    PAGE_INDEX_PREPARATION,
    PAGE_INDEX_REVIEW,
    PAGE_INDEX_SEISMIC,
    PAGE_INDEX_SEQUENCE,
    PAGE_INDEX_STRATIGRAPHY,
    PAGE_INDEX_VISUALIZATION,
    PAGE_INDEX_WELL_LOG,
    PAGE_INDEX_GEOMODEL,
)


class CommandPalette(QFrame):
    """Ctrl+K quick-jump palette: searchable list of pages and stages.

    A plain child widget of the shell (no window flags, no modality), so it
    is safe under the offscreen CI platform. Filter matches page names and
    descriptions; Enter or click navigates, Esc dismisses.
    """

    _WIDTH = 360
    _HEIGHT = 320

    def __init__(self, parent, *, navigate_page, navigate_stage):
        super().__init__(parent)
        self.setObjectName("PanelCard")  # themed card chrome from the token sheet
        self._navigate_page = navigate_page
        self._navigate_stage = navigate_stage
        self._commands: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        layout.setSpacing(tokens.SPACE_2)

        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText("跳转到页面 / 阶段…")
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
                tokens.MENU_BAR_HEIGHT + tokens.SPACE_2,
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
        for index, name in enumerate(tokens.PAGE_NAMES):
            commands.append(
                {
                    "label": name,
                    "hint": tokens.PAGE_DESCRIPTIONS[index],
                    "run": lambda i=index: self._navigate_page(i),
                }
            )
        for stage in navigation.STAGE_DEFINITIONS:
            commands.append(
                {
                    "label": f"阶段 {stage['badge']} {stage['name']}",
                    "hint": "切换工作流阶段",
                    "run": lambda s=stage["index"]: self._navigate_stage(s),
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

    def eventFilter(self, source, event):  # noqa: N802 (Qt override)
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


_SIDEBAR_FLOAT_KEY = "shell:sidebar"  # M4 page:panel key convention


def _offscreen_platform() -> bool:
    """True on the headless CI platform (same check the 3D page uses).

    Float actions are inert here: a top-level FloatingPanel would open a real
    window, which offscreen CI must never do.
    """
    return os.environ.get("QT_QPA_PLATFORM", "") == "offscreen"


def _load_float_framework():
    """Load M4's float framework (feat/float-panel-framework).

    Returns ``(FloatController, LayoutPersistence)`` or ``None`` while that
    branch is unmerged — the shell then stays docked-only (float actions
    inert) instead of failing to import.
    """
    try:
        from paleo_workbench.ui.layout_persistence import LayoutPersistence
        from paleo_workbench.ui.panel_float_controller import FloatController
    except ImportError:
        return None
    return FloatController, LayoutPersistence


class SidebarResizeHandle(QFrame):
    """Thin draggable handle between the ContextSidebar and the page stack.

    Dragging applies the sidebar's docked width (clamped to the sidebar's
    sane bounds via ``set_user_width``); release emits the final width so the
    shell can persist it. Replaces the old fixed-width expanded sidebar.
    """

    drag_finished = Signal(int)

    _HANDLE_WIDTH = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarResizeHandle")
        self.setFixedWidth(self._HANDLE_WIDTH)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self._drag_active = False

    def refresh_theme(self, theme: str = "light") -> None:
        """Inline handle chrome (no generic QFrame rule in the token sheet)."""
        palette = tokens.palette_for(theme)
        self.setStyleSheet(
            f"QFrame#SidebarResizeHandle {{ background: {palette['BORDER']}; }}"
            f"QFrame#SidebarResizeHandle:hover {{ background: {palette['PRIMARY']}; }}"
        )

    def _sidebar(self):
        return getattr(self.parentWidget(), "sidebar", None)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._drag_active:
            return
        sidebar = self._sidebar()
        if sidebar is None:
            return
        cursor_x = event.globalPosition().toPoint().x()
        sidebar_left = sidebar.mapToGlobal(QPoint(0, 0)).x()
        sidebar.set_user_width(cursor_x - sidebar_left)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_active and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            sidebar = self._sidebar()
            if sidebar is not None:
                self.drag_finished.emit(sidebar.user_width())
            event.accept()


class AppShell(QWidget):
    """Application shell (M2 layout).

    One command header (MenuBar hosting menus · workflow stepper · global
    search in a single menu-bar-height row), a content row of [IconRail |
    ContextSidebar | QStackedWidget with the 11 eagerly constructed pages],
    and a StatusBar. Page ordinals and contracts are stable — see
    :mod:`paleo_workbench.ui.navigation` for the stage model.
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
        from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
        from paleo_workbench.viz.selection_context import SelectionContext
        from paleo_workbench.ui.view_coordination import ViewCoordinationController

        self.selection_context = SelectionContext()
        self.coordinate_hub = CoordinateTransformHub()
        self.view_coordination = ViewCoordinationController(
            self.selection_context, self.coordinate_hub, parent=self
        )
        self.project = project or ProjectDocument.new("Untitled Project")
        self._well_location_state_store = WellLocationPreviewStateStore()
        self._fade_anim: QPropertyAnimation | None = None
        # Opening a large project must not eagerly bind every data-heavy page.
        # These are main-thread callbacks only, keyed by page and operation so
        # repeated refreshes retain just the latest committed project state.
        self._defer_nonvisible_bindings = defer_nonvisible_bindings
        self._deferred_page_bindings = DeferredPageBindings()

        # Stage memory: track the last visited page for each stage. The
        # landing page (首页) belongs to stage ❶, so the stepper highlights
        # the first stage on launch instead of the last one.
        self._stage_subpage_memory: dict[int, int] = {
            navigation.STAGE_INDEX_DATA: PAGE_INDEX_HOME,
            navigation.STAGE_INDEX_INTERPRETATION: PAGE_INDEX_WELL_LOG,
            navigation.STAGE_INDEX_MAPPING: PAGE_INDEX_MAPPING,
            navigation.STAGE_INDEX_REVIEW: PAGE_INDEX_REVIEW,
        }

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Command header (M2): menus left, workflow stepper centered in the
        # same command row, global search right — one strip for the whole
        # command surface instead of a menu row plus a stepper row.
        self.menu_bar = MenuBar(self)
        outer.addWidget(self.menu_bar)

        self.workflow_stepper = WorkflowStepper(self)
        self.menu_bar.set_header_center(self.workflow_stepper)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.icon_rail = IconRail(self)
        self.icon_rail.setVisible(True)
        self.sidebar = ContextSidebar(self)
        self.sidebar.setVisible(True)
        self.page_stack = QStackedWidget(self)
        self.page_stack.addWidget(HomePage(self.page_stack))        # index 0 = 首页
        self.data_page = DataPage(
            project=self.project,
            well_state_store=self._well_location_state_store,
            parent=self.page_stack,
        )
        self.data_page.data_context_changed.connect(self.update_data_context)
        self.page_stack.addWidget(self.data_page)        # index 1 = 数据
        self._data_context = self._build_data_context()
        self.page_stack.addWidget(WellLogPredictionPage(self.page_stack)) # index 2 = 测井预测
        self.page_stack.addWidget(SeismicPredictionPage(self.page_stack)) # index 3 = 地震预测
        self.page_stack.addWidget(SequenceFrameworkPage(self.page_stack)) # index 4 = 层序格架
        self.page_stack.addWidget(StratigraphyCorrelationPage(self.page_stack))  # index 5 = 地层对比
        self.page_stack.addWidget(
            VisualizationPage(
                well_state_store=self._well_location_state_store,
                parent=self.page_stack,
            )
        ) # index 6 = 可视化
        self.page_stack.addWidget(PreparationPage(self.page_stack)) # index 7 = 制备
        self.mapping_page = MappingPage(self.page_stack)
        self.mapping_page.mapping_context_changed.connect(self.update_mapping_context)
        self.page_stack.addWidget(self.mapping_page)  # index 8 = 编图
        self.page_stack.addWidget(ReviewExportPage(self.page_stack)) # index 9 = 成图审核
        self.geomodel_page = GeologicalModeling3DPage(self.page_stack)
        self._run_or_defer_page_update(
            PAGE_INDEX_GEOMODEL,
            "project",
            lambda: self.geomodel_page.set_project(self.project),
        )
        self.page_stack.addWidget(self.geomodel_page)  # index 10 = 井震联合
        # 井位地图 lives inside the Data page as a collapsible panel (§18);
        # DataPage wires its own map ↔ tree sync and initial domain binding.
        self._mapping_context = self._build_mapping_context()
        self._middle_layout = middle
        middle.addWidget(self.icon_rail)
        middle.addWidget(self.sidebar)
        self.sidebar_resize_handle = SidebarResizeHandle(self)
        middle.addWidget(self.sidebar_resize_handle)
        middle.addWidget(self.page_stack, 1)
        outer.addLayout(middle, 1)

        self.status_bar = StatusBar(self)
        outer.addWidget(self.status_bar)

        # Bridge every page's selection surface onto the shared context (#1029).
        self.view_coordination.attach_app_shell(self)
        # Seismic cursor producer (#1029): the panel publishes (IL, XL, TWT)
        # cursor picks through the coordination controller. Wired HERE so the
        # panel never reaches for a global singleton.
        self._wire_seismic_cursor_producer()
        # Register the open project's wells + seismic geometry into the
        # coordinate hub so seismic→well routing has a registry (#1029).
        self.view_coordination.bind_project(self.project)

        # Ctrl+K quick-jump palette (non-modal child; offscreen safe).
        self.command_palette = CommandPalette(
            self,
            navigate_page=self._switch_page,
            navigate_stage=self._on_stepper_stage_changed,
        )

        # Constructed under a non-default theme: theme_changed only fires on
        # switches, so sync the inline palette colors once here (p2-1 r1).
        current_theme = self.theme_manager.current_theme.value
        self.workflow_stepper.refresh_theme(current_theme)
        self.sidebar.refresh_theme(current_theme)
        self.sidebar_resize_handle.refresh_theme(current_theme)

        # Signal connections
        self.workflow_stepper.stage_changed.connect(self._on_stepper_stage_changed)
        self.sidebar.subpage_selected.connect(self._switch_page)
        self.icon_rail.page_changed.connect(self._switch_page)
        self.sidebar.float_requested.connect(self._toggle_sidebar_float)
        self.sidebar_resize_handle.drag_finished.connect(
            self._persist_sidebar_docked_width
        )

        # 面板 menu (M7, shell-level wiring: every _refresh_shell rebuild
        # constructs a fresh MenuBar inside a fresh AppShell, so this stays
        # connected without app.py changes).
        self.menu_bar.sidebar_float_requested.connect(self._toggle_sidebar_float)
        self.menu_bar.reset_panels_layout_requested.connect(self._reset_panels_layout)

        # Shell sidebar float via M4's framework (registered under a stable
        # page:panel key; unmerged framework degrades to a docked-only sidebar).
        self._float_framework = _load_float_framework()
        self.sidebar_float_controller = None
        if self._float_framework is not None:
            float_controller_cls, persistence_cls = self._float_framework
            self._layout_persistence = persistence_cls()
            self.sidebar_float_controller = float_controller_cls(
                resolver=self._resolve_float_panel_widget,
                persistence=self._layout_persistence,
                title_for=lambda key: "上下文侧栏",
                parent=self,
            )
            self.sidebar_float_controller.float_changed.connect(
                self._on_sidebar_float_changed
            )
            self._restore_sidebar_layout()
        self.menu_bar.set_sidebar_float_checked(self.sidebar_is_floated())

        # Sync initial stage with the landing page (index 0 -> Stage 1: 数据与预处理)
        initial_stage = navigation.get_stage_for_page(0)
        self.workflow_stepper.set_active_stage(initial_stage)
        self.sidebar.set_stage(initial_stage, active_page_index=0)

        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """Register Stage (Ctrl+1~4), Subpage (Alt+1~4), digit (1-9/0), and
        Ctrl+K command-palette shortcuts."""
        # 1-9 and 0 digit shortcuts (backward compatibility)
        for i in range(min(10, len(tokens.PAGE_NAMES))):  # keys 1-9,0 only
            digit = str(i + 1) if i < 9 else "0"
            QShortcut(QKeySequence(digit), self,
                      lambda idx=i: self._shortcut_switch_page(idx))

        # Stage shortcuts Ctrl+1 ~ Ctrl+4
        for s in range(4):
            QShortcut(QKeySequence(f"Ctrl+{s + 1}"), self,
                      lambda stage_idx=s: self._shortcut_switch_stage(stage_idx))

        # Subpage shortcuts Alt+1 ~ Alt+4
        for p in range(4):
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

    def _shortcut_switch_stage(self, stage_idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        self._on_stepper_stage_changed(stage_idx)

    def _shortcut_switch_subpage(self, sub_idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        curr_stage = self.workflow_stepper.active_stage_index
        subpages = navigation.get_subpages_for_stage(curr_stage)
        if 0 <= sub_idx < len(subpages):
            self._switch_page(subpages[sub_idx])

    def _shortcut_switch_page(self, idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        if 0 <= idx < self.page_stack.count():
            self.icon_rail.set_active(idx)
            self._switch_page(idx)

    def _on_stepper_stage_changed(self, stage_index: int) -> None:
        target_page = self._stage_subpage_memory.get(
            stage_index, navigation.get_subpages_for_stage(stage_index)[0]
        )
        self._switch_page(target_page)

    def set_theme(self, mode) -> None:
        """Switch the application theme (#1047): palette change, same tokens."""
        self.theme_manager.set_theme(mode)

    def _on_theme_changed(self, theme: str) -> None:
        qss = self.theme_manager.get_qss()
        self.setStyleSheet(qss)
        # Components with inline token colors re-resolve against the new
        # palette so nothing stays styled for the previous theme.
        self.workflow_stepper.refresh_theme(theme)
        self.sidebar.refresh_theme(theme)
        self.sidebar_resize_handle.refresh_theme(theme)
        # top-level windows outside this shell (dialogs) follow the theme too
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)

    # --- Sidebar float / dock / reset (M7) ----------------------------

    def sidebar_is_floated(self) -> bool:
        if self.sidebar_float_controller is None:
            return False
        return self.sidebar_float_controller.is_floating(_SIDEBAR_FLOAT_KEY)

    def _toggle_sidebar_float(self) -> None:
        self._set_sidebar_floating(not self.sidebar_is_floated())

    def _set_sidebar_floating(self, floated: bool) -> None:
        # Offscreen CI must never open real windows: the float action stays
        # inert there (the same guard pattern as the 3D GL pages).
        if _offscreen_platform() or self.sidebar_float_controller is None:
            return
        if floated:
            self.sidebar_float_controller.float_panel(_SIDEBAR_FLOAT_KEY)
        else:
            self.sidebar_float_controller.dock_panel(_SIDEBAR_FLOAT_KEY)

    def _on_sidebar_float_changed(self, key: str, floating: bool) -> None:
        if key != _SIDEBAR_FLOAT_KEY:
            return
        self.sidebar.set_floated(floating)
        if floating:
            self.sidebar_resize_handle.setVisible(False)
        else:
            # FloatController reparented the sidebar back to the shell; the
            # middle QHBoxLayout does not manage plain children, so re-insert
            # at the slot between IconRail and the page stack here.
            self._middle_layout.insertWidget(1, self.sidebar)
            self._middle_layout.insertWidget(2, self.sidebar_resize_handle)
            self.sidebar_resize_handle.setVisible(True)
            self._persist_sidebar_docked_width(self.sidebar.user_width())
        self.menu_bar.set_sidebar_float_checked(floating)

    def _resolve_float_panel_widget(self, key: str):
        """M4 resolver: the shell floats exactly one panel — the sidebar."""
        return self.sidebar if key == _SIDEBAR_FLOAT_KEY else None

    def _persist_sidebar_docked_width(self, width: int) -> None:
        """Record the docked width; float geometry is persisted by the
        FloatController itself."""
        if self.sidebar_float_controller is None or self.sidebar_is_floated():
            return
        self.sidebar.set_user_width(width)  # idempotent clamp
        self._layout_persistence.save_docked_sizes(
            _SIDEBAR_FLOAT_KEY, (self.sidebar.user_width(),)
        )

    def _restore_sidebar_layout(self) -> None:
        record = self._layout_persistence.load(_SIDEBAR_FLOAT_KEY)
        if record.docked_sizes:
            self.sidebar.set_user_width(record.docked_sizes[0])
        if record.floating and not _offscreen_platform():
            # restore_saved re-floats at the saved geometry and honours a
            # user-closed (hidden) panel.
            self.sidebar_float_controller.restore_saved(
                _SIDEBAR_FLOAT_KEY, self.sidebar
            )

    def _reset_panels_layout(self) -> None:
        """面板 → 重置面板布局: clear this shell's persisted layout key and
        restore the sidebar's docked defaults. The default width is
        re-persisted last: a floated reset docks in between, which re-records
        the pre-reset width (p2-1 r1)."""
        if self.sidebar_float_controller is not None:
            self._layout_persistence.clear(_SIDEBAR_FLOAT_KEY)
        self._set_sidebar_floating(False)
        self.sidebar.set_user_width(SIDEBAR_DEFAULT_WIDTH)
        self.sidebar.toggle_collapse(False)
        self._persist_sidebar_docked_width(SIDEBAR_DEFAULT_WIDTH)

    def _switch_page(self, index: int) -> None:
        if not 0 <= index < self.page_stack.count():
            return
        self._flush_page_updates(index)
        self.page_stack.setCurrentIndex(index)
        page = self.page_stack.widget(index)
        activate = getattr(page, "activate_page", None)
        if callable(activate):
            activate()

        self.command_palette.dismiss()

        # Update Stage & Subpage state memory
        stage_idx = navigation.get_stage_for_page(index)
        self._stage_subpage_memory[stage_idx] = index
        self.workflow_stepper.set_active_stage(stage_idx)
        self.sidebar.set_stage(stage_idx, active_page_index=index)
        self.icon_rail.set_active(index)

        # The sidebar keeps the user's state across page switches (#1047):
        # visible stays visible, collapsed stays collapsed, and context
        # updates continue so any later reveal is already current.
        if index == PAGE_INDEX_DATA:
            self.sidebar.update_data_context(**self._data_context)
        elif index == PAGE_INDEX_MAPPING:
            self.sidebar.update_mapping_context(**self._mapping_context)
        else:
            self.sidebar.set_context(tokens.PAGE_NAMES[index])
        self._animate_page_fade(index)

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
        from paleo_workbench.ui.navigation import PAGE_INDEX_GEOMODEL

        geo_page = self.page_stack.widget(PAGE_INDEX_GEOMODEL)
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

    def data_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_DATA)

    def home_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_HOME)

    def mapping_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_MAPPING)

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Deterministically release project-scoped jobs before a switch.

        Page ``closeEvent`` handlers remain a last line of defence, but a
        project switch must not wait for Qt deferred deletion before closing a
        catalog or replacing native sessions.
        """
        all_joined = True
        for index in range(self.page_stack.count()):
            page = self.page_stack.widget(index)
            if page is None:
                continue
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

    def _run_or_defer_page_update(
        self, index: int, name: str, callback
    ) -> None:
        """Apply a page binding now, or retain its newest state until visit."""

        if (
            self._defer_nonvisible_bindings
            and index != PAGE_INDEX_DATA
            and index != PAGE_INDEX_HOME
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

    # --- Well Location GIS ↔ Data Manager sync (§18) -----------------
    # The map is embedded in the Data page (WellMapPanel); sync is wired
    # inside DataPage itself.


    def update_home_page(self, state: dict, steps: list, project=None) -> None:
        home = self.page_stack.widget(PAGE_INDEX_HOME)
        if hasattr(home, "update_state"):
            # Optional project enables Stage-11 readiness on the contract panel.
            try:
                home.update_state(state, steps, project=project)
            except TypeError:
                home.update_state(state, steps)

    def update_data_page(
        self,
        state: dict,
        resources: list,
        artifacts: list | None = None,
        *,
        project_path=None,
    ) -> None:
        current_artifacts = artifacts or []
        page = self.data_page_widget()
        if project_path is not None and hasattr(page, "set_project_path"):
            page.set_project_path(project_path)
        if hasattr(page, "update_state"):
            page.update_state(state, resources, current_artifacts)
        self._data_context = self._build_data_context(
            resources=resources, artifacts=current_artifacts
        )
        if self.page_stack.currentIndex() == PAGE_INDEX_DATA:
            self.sidebar.update_data_context(**self._data_context)
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
        for index in range(self.page_stack.count()):
            page = self.page_stack.widget(index)
            if page is None or not hasattr(page, "set_project_path"):
                continue
            try:
                page.set_project_path(path)
            except Exception:
                continue

    def update_data_context(self, context: dict) -> None:
        self._data_context = {
            "resource_count": context.get("resource_count", 0),
            "artifact_count": context.get("artifact_count", 0),
            "issue_count": context.get("issue_count", 0),
            "selected_name": context.get("selected_name", "未选择"),
            "selected_type": context.get("selected_type", ""),
            "selected_format": context.get("selected_format", ""),
            "reader_mode": context.get("reader_mode", "empty"),
        }
        if self.page_stack.currentIndex() == 1:
            self.sidebar.update_data_context(**self._data_context)

    def _build_data_context(
        self,
        resources: list[ResourceItem] | None = None,
        artifacts: list[ExportArtifact] | None = None,
    ) -> dict:
        current_resources = resources if resources is not None else self.project.resources
        current_artifacts = (
            artifacts if artifacts is not None else self.project.export_artifacts
        )
        issue_count = sum(
            1
            for resource in current_resources
            if resource.status in {"missing", "warning", "failed", "error"}
        )
        selected = getattr(self.data_page, "_selected_asset", None)
        selected_name = "未选择"
        selected_type = ""
        selected_format = ""
        if isinstance(selected, ResourceItem):
            selected_name = selected.name
            selected_type = selected.type
            selected_format = selected.format
        elif isinstance(selected, ExportArtifact):
            selected_name = Path(selected.output_path).name
            selected_type = "成果"
            selected_format = selected.format
        return {
            "resource_count": len(current_resources),
            "artifact_count": len(current_artifacts),
            "issue_count": issue_count,
            "selected_name": selected_name,
            "selected_type": selected_type,
            "selected_format": selected_format,
            "reader_mode": self.data_page.current_reader_mode(),
        }

    def update_well_log_prediction_page(self, prediction_tasks: list, project=None) -> None:
        page = self.page_stack.widget(PAGE_INDEX_WELL_LOG)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(prediction_tasks, project=selected_project)

        self._update_or_defer_page(PAGE_INDEX_WELL_LOG, "state", update)

    def well_log_prediction_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_WELL_LOG)

    def update_seismic_prediction_page(self, prediction_tasks: list, project=None) -> None:
        page = self.page_stack.widget(PAGE_INDEX_SEISMIC)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(prediction_tasks, project=selected_project)

        self._update_or_defer_page(PAGE_INDEX_SEISMIC, "state", update)

    def seismic_prediction_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_SEISMIC)

    def update_sequence_framework_page(self, stratigraphy) -> None:
        page = self.page_stack.widget(PAGE_INDEX_SEQUENCE)

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(stratigraphy)

        self._update_or_defer_page(PAGE_INDEX_SEQUENCE, "state", update)

    def sequence_framework_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_SEQUENCE)

    def update_stratigraphy_correlation_page(self, project=None) -> None:
        page = self.page_stack.widget(PAGE_INDEX_STRATIGRAPHY)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(selected_project)

        self._update_or_defer_page(PAGE_INDEX_STRATIGRAPHY, "state", update)

    def stratigraphy_correlation_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_STRATIGRAPHY)

    def update_visualization_page(
        self,
        resources: list,
        prediction_tasks: list,
        map_documents: list,
        project=None,
    ) -> None:
        page = self.page_stack.widget(PAGE_INDEX_VISUALIZATION)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "update_state"):
                page.update_state(
                    resources,
                    prediction_tasks,
                    map_documents,
                    project=selected_project,
                )

        self._update_or_defer_page(PAGE_INDEX_VISUALIZATION, "state", update)

    def update_preparation_page(self, tasks: list) -> None:
        page = self.page_stack.widget(PAGE_INDEX_PREPARATION)

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(tasks)

        self._update_or_defer_page(PAGE_INDEX_PREPARATION, "state", update)

    def preparation_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_PREPARATION)

    def update_mapping_page(
        self,
        map_documents: list,
        *,
        factor_tasks: list | None = None,
        project_crs: str | None = None,
    ) -> None:
        page = self.mapping_page_widget()

        def update() -> None:
            if hasattr(page, "update_state"):
                page.update_state(
                    map_documents,
                    factor_tasks=factor_tasks,
                    project_crs=project_crs,
                )
            self._mapping_context = self._build_mapping_context()
            if self.page_stack.currentIndex() == PAGE_INDEX_MAPPING:
                self.sidebar.update_mapping_context(**self._mapping_context)

        self._update_or_defer_page(PAGE_INDEX_MAPPING, "state", update)

    def update_mapping_context(self, context: dict) -> None:
        self._mapping_context = self._normalize_mapping_context(context)
        if self.page_stack.currentIndex() == PAGE_INDEX_MAPPING:
            self.sidebar.update_mapping_context(**self._mapping_context)

    def _build_mapping_context(self) -> dict:
        page = self.mapping_page_widget()
        if hasattr(page, "mapping_context"):
            return self._normalize_mapping_context(page.mapping_context())
        return self._normalize_mapping_context({})

    @staticmethod
    def _normalize_mapping_context(context: dict | None) -> dict:
        ctx = context or {}
        return {
            "map_name": ctx.get("map_name", "未选择") or "未选择",
            "horizon": ctx.get("horizon", "") or "",
            "dirty": bool(ctx.get("dirty", False)),
            "preview": bool(ctx.get("preview", False)),
        }

    def update_review_export_page(self, reports: list, map_documents: list, artifacts: list) -> None:
        page = self.page_stack.widget(PAGE_INDEX_REVIEW)

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(reports, map_documents, artifacts)

        self._update_or_defer_page(PAGE_INDEX_REVIEW, "state", update)

    def review_export_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_REVIEW)
