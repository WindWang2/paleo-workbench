from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens


class IconRail(QFrame):
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("IconRail")
        self._active_index = 0
        self.nav_buttons: list[QPushButton] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 8, 7, 8)
        layout.setSpacing(4)
        for index, name in enumerate(tokens.PAGE_NAMES):
            btn = QPushButton(name)
            btn.setProperty("navItem", True)
            btn.setProperty("active", index == 0)
            btn.clicked.connect(lambda _checked=False, i=index: self._on_click(i))
            self.nav_buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch()

    @property
    def active_index(self) -> int:
        return self._active_index

    def set_active(self, index: int) -> None:
        if index == self._active_index:
            return
        old = self._active_index
        self.nav_buttons[old].setProperty("active", False)
        self._active_index = index
        self.nav_buttons[index].setProperty("active", True)
        self.nav_buttons[old].style().unpolish(self.nav_buttons[old])
        self.nav_buttons[old].style().polish(self.nav_buttons[old])
        self.nav_buttons[index].style().unpolish(self.nav_buttons[index])
        self.nav_buttons[index].style().polish(self.nav_buttons[index])

    def _on_click(self, index: int) -> None:
        self.set_active(index)
        self.page_changed.emit(index)
