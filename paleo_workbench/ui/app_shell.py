from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
)

from paleo_workbench.ui.header_toolbar import HeaderToolbar
from paleo_workbench.ui.icon_rail import IconRail
from paleo_workbench.ui.menu_bar import MenuBar
from paleo_workbench.ui.page_placeholder import PagePlaceholder
from paleo_workbench.ui.sidebar import TextSidebar
from paleo_workbench.ui.status_bar import StatusBar
from paleo_workbench.ui import tokens


class AppShell(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppShell")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.menu_bar = MenuBar()
        self.header_toolbar = HeaderToolbar()
        outer.addWidget(self.menu_bar)
        outer.addWidget(self.header_toolbar)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.icon_rail = IconRail()
        self.sidebar = TextSidebar()
        self.page_stack = QStackedWidget()
        for name in tokens.PAGE_NAMES:
            self.page_stack.addWidget(PagePlaceholder(name))
        middle.addWidget(self.icon_rail)
        middle.addWidget(self.sidebar)
        middle.addWidget(self.page_stack, 1)
        outer.addLayout(middle, 1)

        self.status_bar = StatusBar()
        outer.addWidget(self.status_bar)

        self.icon_rail.page_changed.connect(self._switch_page)

    def _switch_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        self.sidebar.set_context(tokens.PAGE_NAMES[index])

    def set_project_name(self, name: str) -> None:
        self.status_bar.set_project_name(name)
