from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QWidget,
)

from paleo_workbench.ui import tokens

_ICONS_DIR = Path(__file__).parent / "assets" / "icons"


def _icon(name: str) -> QIcon:
    """Load a menu icon by filename, returning an empty QIcon if absent."""
    path = _ICONS_DIR / name
    return QIcon(str(path)) if path.exists() else QIcon()


class MenuBar(QFrame):
    """Command header: menus left, optional center widget, search right.

    The row height comes from the token sheet (the ``QFrame#MenuBar`` rule),
    so this header tracks M1 metric changes automatically. M2 redesign: the
    workflow stepper lives in this row (``set_header_center``) so the shell
    spends one command strip on the whole command surface instead of a menu
    row plus a separate stepper row.
    """

    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_project_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()
    preview_settings_requested = Signal()
    # View menu signals
    reset_layout_requested = Signal()
    toggle_sidebar_requested = Signal()
    density_changed = Signal(str)  # "comfortable" | "compact"
    # Panel/layout menu signals (M7)
    sidebar_float_requested = Signal()
    reset_panels_layout_requested = Signal()
    # Help menu signal
    about_requested = Signal()
    # Global search
    search_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MenuBar")
        self.labels: list[QPushButton] = []
        self._header_center: QWidget | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, 0)
        layout.setSpacing(tokens.SPACE_4)

        # --- 工程与文件 menu ---
        self.project_menu_button = QPushButton("工程与文件")
        self.project_menu_button.setObjectName("ProjectMenuButton")
        self.project_menu = QMenu(self.project_menu_button)
        self.new_project_action = self._add_project_action(
            "新建工程", self.new_project_requested, "menu-new.svg"
        )
        self.open_project_action = self._add_project_action(
            "打开工程", self.open_project_requested, "menu-open.svg"
        )
        self.open_sample_project_action = self._add_project_action(
            "打开样例工程", self.open_sample_project_requested, "menu-open.svg"
        )
        self.save_project_action = self._add_project_action(
            "保存工程", self.save_project_requested, "menu-save.svg"
        )
        self.project_menu.addSeparator()
        self.properties_action = self._add_project_action(
            "工程属性", self.properties_requested, "menu-properties.svg"
        )
        self.project_menu_button.setMenu(self.project_menu)
        layout.addWidget(self.project_menu_button)

        # --- 视图 menu (was a dead label, now a real dropdown) ---
        self.view_menu_button = QPushButton("视图")
        self.view_menu_button.setObjectName("ViewMenuButton")
        self.view_menu = QMenu(self.view_menu_button)
        self.reset_layout_action = self.view_menu.addAction("重置布局")
        self.reset_layout_action.triggered.connect(self.reset_layout_requested)
        self.toggle_sidebar_action = self.view_menu.addAction("收起/展开侧栏")
        self.toggle_sidebar_action.triggered.connect(self.toggle_sidebar_requested)
        self.view_menu.addSeparator()
        self._density_menu = self.view_menu.addMenu("界面密度")
        # QActionGroup enforces mutual exclusivity (one-at-a-time) natively,
        # replacing fragile manual setChecked bookkeeping.
        self._density_group = QActionGroup(self)
        self._density_group.setExclusive(True)
        self.density_comfortable_action = self._density_menu.addAction("舒适")
        self.density_comfortable_action.setCheckable(True)
        self.density_comfortable_action.setChecked(True)
        self.density_comfortable_action.triggered.connect(
            lambda: self.density_changed.emit("comfortable")
        )
        self.density_compact_action = self._density_menu.addAction("紧凑")
        self.density_compact_action.setCheckable(True)
        self.density_compact_action.triggered.connect(
            lambda: self.density_changed.emit("compact")
        )
        self._density_group.addAction(self.density_comfortable_action)
        self._density_group.addAction(self.density_compact_action)
        # --- 面板 submenu (M7): shell sidebar float/dock + persisted-layout
        # reset. A submenu of 视图 rather than a top-level button — the
        # command row's button set is pinned by tests/test_menu_bar.py.
        self.panels_menu = self.view_menu.addMenu("面板")
        self.float_sidebar_action = self.panels_menu.addAction("侧边栏浮动窗口")
        self.float_sidebar_action.setCheckable(True)
        self.float_sidebar_action.triggered.connect(self.sidebar_float_requested)
        self.panels_menu.addSeparator()
        self.reset_panels_layout_action = self.panels_menu.addAction("重置面板布局")
        self.reset_panels_layout_action.triggered.connect(
            self.reset_panels_layout_requested
        )
        self.view_menu_button.setMenu(self.view_menu)
        self.labels.append(self.view_menu_button)
        layout.addWidget(self.view_menu_button)

        # --- 工具 menu ---
        self.tools_menu_button = QPushButton("工具")
        self.tools_menu_button.setObjectName("ToolsMenuButton")
        self.tools_menu = QMenu(self.tools_menu_button)
        self.preview_settings_action = self.tools_menu.addAction("预览设置…")
        self.preview_settings_action.setIcon(_icon("menu-preview-settings.svg"))
        self.preview_settings_action.triggered.connect(
            self.preview_settings_requested
        )
        self.tools_menu_button.setMenu(self.tools_menu)
        self.labels.append(self.tools_menu_button)
        layout.addWidget(self.tools_menu_button)

        # --- 帮助 menu (was a dead label, now a real dropdown) ---
        self.help_menu_button = QPushButton("帮助")
        self.help_menu_button.setObjectName("HelpMenuButton")
        self.help_menu = QMenu(self.help_menu_button)
        self.about_action = self.help_menu.addAction("关于")
        self.about_action.triggered.connect(self.about_requested)
        self.help_menu_button.setMenu(self.help_menu)
        self.labels.append(self.help_menu_button)
        layout.addWidget(self.help_menu_button)

        layout.addStretch()

        # --- Global search box with magnifier icon ---
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索井名 / 层位 / 功能…  Ctrl+F")
        self.search_box.setToolTip("搜索井名/层位/功能 (Ctrl+F)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMaximumWidth(280)
        self._search_icon = self.search_box.addAction(
            _icon("menu-search.svg"), QLineEdit.ActionPosition.LeadingPosition
        )
        layout.addWidget(self.search_box)

        # Debounced search submission (mirrors DataToolbar's 180ms pattern).
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._emit_search)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.search_box.returnPressed.connect(self._emit_search_now)

    def set_header_center(self, widget: QWidget | None) -> None:
        """Mount *widget* in the header's flexible center slot (stepper).

        Layout becomes: menus · stretch · center · stretch · search. Passing
        ``None`` clears the slot. The stretch pair keeps the widget centered
        regardless of menu/search widths.
        """
        lay = self.layout()
        if self._header_center is not None:
            idx = lay.indexOf(self._header_center)
            lay.takeAt(idx)
            self._header_center.setParent(None)
            self._header_center = None
            # Drop the trailing stretch inserted with the previous widget.
            item = lay.itemAt(idx)
            if item is not None and item.spacerItem() is not None:
                lay.takeAt(idx)
        if widget is None:
            return
        self._header_center = widget
        idx = lay.indexOf(self.search_box)
        lay.insertWidget(idx, widget)
        lay.insertStretch(idx + 1)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _add_project_action(self, text: str, signal: Signal, icon: str = "") -> QAction:
        action = self.project_menu.addAction(text)
        if icon:
            action.setIcon(_icon(icon))
        action.triggered.connect(signal)
        return action

    def _on_search_text_changed(self, _text: str) -> None:
        self._search_timer.start()

    def _emit_search(self) -> None:
        self.search_submitted.emit(self.search_box.text())

    def _emit_search_now(self) -> None:
        self._search_timer.stop()
        self._emit_search()

    def set_density_checked(self, density: str) -> None:
        """Keep the density menu check state in sync with the active density."""
        self.density_comfortable_action.setChecked(density == "comfortable")
        self.density_compact_action.setChecked(density == "compact")

    def set_sidebar_float_checked(self, floated: bool) -> None:
        """Keep the 面板 float action in sync with the sidebar's real state."""
        self.float_sidebar_action.setChecked(floated)
