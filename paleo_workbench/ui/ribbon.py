"""Ribbon command bar for the UI-v2 shell (variant A: tabs are the pages).

Layout: one 40px top row (app badge · page tabs · stretch · global search)
above a 92px command body. The body is a ``QStackedWidget`` of *contexts* —
one context per (hub, sub-module) pair, each a horizontal row of
:class:`RibbonGroup` boxes (buttons on top, group caption at the bottom,
Office-style). The shell switches both the active tab and the body context;
command wiring lives in the shell, this widget is pure chrome + signals.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens

_ICONS_DIR = Path(__file__).parent / "assets" / "icons"


def _icon(name: str) -> QIcon:
    """Load a ribbon icon by filename, returning an empty QIcon if absent."""
    path = _ICONS_DIR / name
    return QIcon(str(path)) if path.exists() else QIcon()


class RibbonGroup(QFrame):
    """One command group: a row of buttons above a bottom caption."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonGroup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 2)
        layout.setSpacing(2)
        self._button_row = QHBoxLayout()
        self._button_row.setContentsMargins(0, 0, 0, 0)
        self._button_row.setSpacing(4)
        layout.addLayout(self._button_row)
        caption = QLabel(title)
        caption.setObjectName("RibbonGroupCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)
        # Slack goes BELOW the caption, never between buttons and caption.
        layout.addStretch(1)
        self.buttons: list[QToolButton] = []

    def add_button(
        self,
        text: str,
        *,
        icon: str = "",
        tooltip: str = "",
        on_click=None,
        checkable: bool = False,
    ) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("RibbonButton")
        btn.setText(text)
        if icon:
            btn.setIcon(_icon(icon))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if tooltip:
            btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        # Never elide the label: QToolButton shrinks to icon width otherwise.
        min_width = btn.fontMetrics().horizontalAdvance(text) + 18
        if icon:
            min_width += btn.iconSize().width() + 6
        btn.setMinimumWidth(min_width)
        if on_click is not None:
            btn.clicked.connect(on_click)
        self.buttons.append(btn)
        self._button_row.addWidget(btn)
        return btn

    def add_widget(self, widget: QWidget) -> None:
        self._button_row.addWidget(widget)


class _RibbonContextBody(QFrame):
    """Horizontal row of groups for one (hub, sub-module) context."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonBody")
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(8, 2, 8, 2)
        self._row.setSpacing(0)
        self.groups: list[RibbonGroup] = []

    def add_group(self, title: str) -> RibbonGroup:
        if self.groups:
            sep = QFrame(self)
            sep.setObjectName("RibbonGroupSeparator")
            sep.setFrameShape(QFrame.Shape.VLine)
            self._row.addWidget(sep)
        group = RibbonGroup(title, self)
        self.groups.append(group)
        self._row.addWidget(group)
        return group

    def finish(self) -> None:
        """Call after the last group: push everything left."""
        self._row.addStretch(1)


class RibbonBar(QFrame):
    """The whole ribbon: page-tab row + stacked command bodies."""

    tab_changed = Signal(int)
    search_submitted = Signal(str)
    collapsed_changed = Signal(bool)
    # 工程 group (数据 tab) — same contract the old MenuBar exposed to app.py
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_project_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()
    # 视图 / 工具
    preview_settings_requested = Signal()
    about_requested = Signal()
    density_changed = Signal(str)  # "comfortable" | "compact"

    def __init__(self, tab_titles: list[str], parent=None):
        super().__init__(parent)
        self._panel_provider = None
        self.setObjectName("RibbonBar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- top row: app badge · page tabs · stretch · search · app menu ---
        top = QHBoxLayout()
        top.setContentsMargins(tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, 0)
        top.setSpacing(tokens.SPACE_2)
        badge = QLabel("paleo_workbench · 古地理工作台")
        badge.setObjectName("RibbonAppBadge")
        top.addWidget(badge)
        top.addSpacing(tokens.SPACE_3)

        self._tab_buttons: list[QPushButton] = []
        self._tab_row = QHBoxLayout()
        self._tab_row.setSpacing(2)
        _tab_icons = {
            "数据": "data.svg",
            "井": "well-log.svg",
            "地震": "seismic.svg",
            "编图": "mapping.svg",
            "可视化": "visualization.svg",
        }
        for index, title in enumerate(tab_titles):
            btn = QPushButton(title)
            icon_name = _tab_icons.get(title, "")
            if icon_name:
                btn.setIcon(_icon(icon_name))
            btn.setObjectName("RibbonTab")
            btn.setProperty("active", False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)
            btn.clicked.connect(
                lambda _checked=False, i=index: self.tab_changed.emit(i)
            )
            self._tab_buttons.append(btn)
            self._tab_row.addWidget(btn)
        top.addLayout(self._tab_row)
        top.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索井名 / 层位 / 功能…  Ctrl+F")
        self.search_box.setToolTip("搜索井名/层位/功能 (Ctrl+F)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMaximumWidth(280)
        self.search_box.addAction(
            _icon("menu-search.svg"), QLineEdit.ActionPosition.LeadingPosition
        )
        top.addWidget(self.search_box)

        # Office-style collapsible command body: the button (and Ctrl+F1,
        # wired by the shell) hides the group row, leaving only page tabs.
        self._collapsed = False
        self._collapse_button = QPushButton("▴")
        self._collapse_button.setObjectName("RibbonCollapseButton")
        self._collapse_button.setToolTip("折叠功能区 (Ctrl+F1)")
        self._collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_button.setFlat(True)
        self._collapse_button.clicked.connect(
            lambda: self.set_collapsed(not self._collapsed)
        )
        top.addWidget(self._collapse_button)

        self._app_menu_button = QPushButton("⋮")
        self._app_menu_button.setObjectName("RibbonAppMenuButton")
        self._app_menu_button.setToolTip("应用菜单")
        self._app_menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        app_menu = QMenu(self._app_menu_button)
        # 工程命令全局收进应用菜单 — 不再在每个 Ribbon 上下文重复一组按钮。
        for title, signal, shortcut, icon_name in (
            ("新建工程", self.new_project_requested, "Ctrl+N", "menu-new.svg"),
            ("打开工程", self.open_project_requested, "Ctrl+O", "menu-open.svg"),
            ("打开样例", self.open_sample_project_requested, "", "menu-open.svg"),
            ("保存工程", self.save_project_requested, "Ctrl+S", "menu-save.svg"),
            ("工程属性", self.properties_requested, "", "menu-properties.svg"),
        ):
            action = app_menu.addAction(
                _icon(icon_name),
                f"{title}  {shortcut}" if shortcut else title,
            )
            action.triggered.connect(signal.emit)
        app_menu.addSeparator()
        self.preview_settings_action = app_menu.addAction(
            _icon("menu-preview-settings.svg"), "预览设置…"
        )
        self.preview_settings_action.triggered.connect(
            self.preview_settings_requested
        )
        self.about_action = app_menu.addAction("关于")
        self.about_action.triggered.connect(self.about_requested)
        self._app_menu_button.setMenu(app_menu)
        top.addWidget(self._app_menu_button)

        top_host = QFrame(self)
        top_host.setObjectName("RibbonTopRow")
        top_host.setLayout(top)
        top_host.setFixedHeight(tokens.MENU_BAR_HEIGHT)
        layout.addWidget(top_host)

        # --- command body: one stacked context per (hub, sub-module) ---
        self._body_stack = QStackedWidget(self)
        self._body_stack.setObjectName("RibbonBodyStack")
        self._body_stack.setFixedHeight(68)
        self._contexts: dict[str, _RibbonContextBody] = {}
        layout.addWidget(self._body_stack)

        # Debounced search submission (mirrors the old MenuBar's 180ms).
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._emit_search)
        self.search_box.textChanged.connect(lambda _t: self._search_timer.start())
        self.search_box.returnPressed.connect(self._emit_search_now)

        self._active_tab = -1
        self._current_key = ""

    # --- collapse ---------------------------------------------------------

    def set_collapsed(self, collapsed: bool) -> None:
        """Hide the command body, leaving only the page-tab row."""
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._body_stack.setVisible(not collapsed)
        self._collapse_button.setText("▾" if collapsed else "▴")
        self._collapse_button.setToolTip(
            "展开功能区 (Ctrl+F1)" if collapsed else "折叠功能区 (Ctrl+F1)"
        )
        self.collapsed_changed.emit(collapsed)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    # --- contexts -----------------------------------------------------

    def add_context(self, key: str) -> _RibbonContextBody:
        """Register a command body under *key* (``"<hub>:<submodule>"``)."""
        body = _RibbonContextBody(self)
        self._contexts[key] = body
        self._body_stack.addWidget(body)
        return body

    def set_context(self, key: str) -> None:
        body = self._contexts.get(key)
        if body is not None:
            self._current_key = key
            self._body_stack.setCurrentWidget(body)

    # --- panel show/hide (right-click menu) ------------------------------

    def set_panel_provider(self, provider) -> None:
        """Install the shell callback returning the CURRENT page's panel
        entries (see ``floatable_panel_entries`` for the entry shape)."""
        self._panel_provider = provider

    def contextMenuEvent(self, event) -> None:
        """Right-click: manage the current page's panels (显隐/浮动)."""
        self._build_context_menu().exec(event.globalPos())

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        entries = self._panel_provider() if self._panel_provider else []
        if entries:
            for entry in entries:
                action = menu.addAction(entry["title"])
                action.setCheckable(True)
                action.setChecked(bool(entry["visible"]))
                action.toggled.connect(
                    lambda checked, e=entry: e["set_visible"](checked)
                )
                float_action = menu.addAction(f"浮动 · {entry['title']}")
                float_action.setCheckable(True)
                float_action.setChecked(bool(entry["floating"]))
                float_action.toggled.connect(
                    lambda _checked, e=entry: e["toggle_float"]()
                )
            menu.addSeparator()
            show_all = menu.addAction("全部显示")
            show_all.triggered.connect(
                lambda: [e["set_visible"](True) for e in entries]
            )
            menu.addSeparator()
        collapse = menu.addAction("折叠功能区" if not self._collapsed else "展开功能区")
        collapse.triggered.connect(self.toggle_collapsed)
        return menu

    def context(self, key: str) -> _RibbonContextBody | None:
        return self._contexts.get(key)

    # --- tabs -----------------------------------------------------------

    def set_active_tab(self, index: int) -> None:
        """Highlight the active page tab (does not emit tab_changed)."""
        if not 0 <= index < len(self._tab_buttons):
            return
        self._active_tab = index
        for i, btn in enumerate(self._tab_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    @property
    def active_tab(self) -> int:
        return self._active_tab

    # --- 工程 group helper -----------------------------------------------

    def populate_project_group(self, body: _RibbonContextBody) -> RibbonGroup:
        """The shared 工程 group (新建/打开/样例/保存/属性) for a context."""
        group = body.add_group("工程")
        group.add_button(
            "新建工程", icon="menu-new.svg", tooltip="新建工程 (Ctrl+N)",
            on_click=self.new_project_requested.emit,
        )
        group.add_button(
            "打开工程", icon="menu-open.svg", tooltip="打开工程 (Ctrl+O)",
            on_click=self.open_project_requested.emit,
        )
        group.add_button(
            "打开样例", icon="menu-open.svg", tooltip="打开样例工程",
            on_click=self.open_sample_project_requested.emit,
        )
        group.add_button(
            "保存工程", icon="menu-save.svg", tooltip="保存工程 (Ctrl+S)",
            on_click=self.save_project_requested.emit,
        )
        group.add_button(
            "工程属性", icon="menu-properties.svg", tooltip="工程属性",
            on_click=self.properties_requested.emit,
        )
        return group

    # --- search -----------------------------------------------------------

    def _emit_search(self) -> None:
        self.search_submitted.emit(self.search_box.text())

    def _emit_search_now(self) -> None:
        self._search_timer.stop()
        self._emit_search()
