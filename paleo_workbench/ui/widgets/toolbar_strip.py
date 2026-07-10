from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QWidget

from paleo_workbench.ui import tokens


class ToolbarStrip(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolbarStrip")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        self._layout.setSpacing(tokens.SPACE_1)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_stretch(self) -> None:
        self._layout.addStretch(1)
