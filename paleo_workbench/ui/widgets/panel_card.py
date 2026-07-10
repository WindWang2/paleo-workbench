from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


class PanelCard(QFrame):
    """White bordered card with optional title and body layout."""

    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        self._root.setSpacing(tokens.SPACE_2)
        self.title_label = QLabel(title or "")
        self.title_label.setObjectName("SectionHeaderTitle")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE};"
            f" font-weight: {tokens.FONT_WEIGHT_TITLE}; border: none; background: transparent;"
        )
        if title:
            self._root.addWidget(self.title_label)
        else:
            self.title_label.hide()
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(tokens.SPACE_2)
        self._root.addLayout(self.body, 1)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)
