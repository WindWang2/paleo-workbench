from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QToolButton, QVBoxLayout

from paleo_workbench.ui.workstation.common import workstation_icon


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationActivityRail")
        self.setFixedWidth(54)

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
            button.setToolTip(label)
            button.setFixedSize(48, 52)
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
        settings.setFixedSize(48, 52)
        settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(settings)

        collapse = QToolButton(self)
        collapse.setObjectName("WorkstationRailCollapseButton")
        collapse.setIcon(workstation_icon("chevrons-left.svg"))
        collapse.setToolTip("折叠资源管理器")
        collapse.clicked.connect(self.collapse_requested.emit)
        layout.addWidget(collapse)

        self.collapse_button = collapse
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
        else:
            self.collapse_button.setIcon(workstation_icon("chevrons-right.svg"))
            self.collapse_button.setToolTip("展开资源管理器")
