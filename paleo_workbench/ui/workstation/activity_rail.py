from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QToolButton, QVBoxLayout

from paleo_workbench.ui import style, tokens
from paleo_workbench.ui.workstation.common import workstation_icon

_current_density = style.current_density


def _rail_button_size() -> QSize:
    d = tokens.density_tokens(_current_density())
    return QSize(d["rail_item_size"], d["rail_item_size"] + 4)


class ActivityRail(QFrame):
    """Stable object/workspace modes, separate from document commands."""

    mode_requested = Signal(str)
    settings_requested = Signal()
    collapse_requested = Signal()

    _MODES = (
        ("project", "项目", "home.svg"),
        ("data", "数据", "data.svg"),
        ("layers", "图层", "mapping.svg"),
        ("search", "搜索", "menu-search.svg"),
        ("history", "历史", "review.svg"),
        ("workspaces", "工作区", "visualization.svg"),
    )

    # V11（01-ui-audit B1）：rail 是资源管理器的视图模式，不是页面导航。
    # tooltip 必须说清按钮做什么，避免「按了数据却到了资源树」的期望落差。
    _MODE_TOOLTIPS = {
        "project": "资源管理器 · 项目总览（井/工区/工程实体）",
        "data": "资源管理器 · 数据资源（按类型浏览数据资产）",
        "layers": "资源管理器 · 图层（编图文档与图层）",
        "search": "资源管理器 · 搜索（全工程资源检索）",
        "history": "资源管理器 · 历史（最近使用的资源）",
        "workspaces": "聚焦编图工作区（中央画布）",
    }

    def _apply_density_metrics(self) -> None:
        """密度切换：重设 rail 宽度与全部按钮尺寸（bind_metrics 回调）。"""
        self.setFixedWidth(tokens.rail_width(_current_density()))
        size = _rail_button_size()
        for button in getattr(self, "buttons", {}).values():
            button.setFixedSize(size)
        settings_btn = getattr(self, "_settings_button", None)
        if settings_btn is not None:
            settings_btn.setFixedSize(size)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationActivityRail")
        self.setFixedWidth(tokens.rail_width(_current_density()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(1)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for index, (key, label, icon_name) in enumerate(self._MODES):
            button = QToolButton(self)
            button.setObjectName("WorkstationActivityButton")
            button.setProperty("activityKey", key)
            button.setCheckable(True)
            button.setText(label)
            button.setIcon(workstation_icon(icon_name))
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setToolTip(self._MODE_TOOLTIPS.get(key, label))
            button.setAccessibleName(self._MODE_TOOLTIPS.get(key, label))
            button.setFixedSize(_rail_button_size())
            button.clicked.connect(lambda _checked=False, mode=key: self.mode_requested.emit(mode))
            self.group.addButton(button, index)
            self.buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        settings = QToolButton(self)
        settings.setObjectName("WorkstationActivityButton")
        settings.setText("设置")
        settings.setIcon(workstation_icon("menu-preview-settings.svg"))
        settings.setIconSize(QSize(18, 18))
        settings.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        settings.setToolTip("工作站设置")
        settings.setFixedSize(_rail_button_size())
        settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(settings)

        collapse = QToolButton(self)
        collapse.setObjectName("WorkstationRailCollapseButton")
        collapse.setIcon(workstation_icon("chevrons-left.svg"))
        collapse.setToolTip("折叠资源管理器")
        # 图标按钮无文字，屏幕阅读器需要显式名（V6 audit G-P1-3）。
        collapse.setAccessibleName("折叠资源管理器")
        collapse.setAccessibleDescription("折叠或展开左侧资源管理器面板")
        collapse.clicked.connect(self.collapse_requested.emit)
        # 折叠钮之下还有布局尾项；密度切换时整列重算（见 _apply_density_metrics）
        layout.addWidget(collapse)

        self.collapse_button = collapse
        self._settings_button = settings
        # 注册时机在全部按钮构造之后：bind_metrics 立即回调一次
        style.bind_metrics(self, self._apply_density_metrics)
        self.set_mode("project")

    def set_mode(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def set_explorer_expanded(self, expanded: bool) -> None:
        """Mirror the explorer state so the collapse affordance flips with it."""
        if expanded:
            self.collapse_button.setIcon(workstation_icon("chevrons-left.svg"))
            self.collapse_button.setToolTip("折叠资源管理器")
            self.collapse_button.setAccessibleName("折叠资源管理器")
        else:
            self.collapse_button.setIcon(workstation_icon("chevrons-right.svg"))
            self.collapse_button.setToolTip("展开资源管理器")
            self.collapse_button.setAccessibleName("展开资源管理器")
