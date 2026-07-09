from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


class FloatingPanel(QFrame):
    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        tab_text: str,
        content: QWidget | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("FloatingPanel")
        self._expanded = False
        self._content_widget: QWidget | None = None
        self.setStyleSheet(
            f"QFrame#FloatingPanel {{ background: transparent; border: none; }}"
            f"QFrame#FloatingPanelContent {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_PANEL}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.tab_button = QPushButton(tab_text)
        self.tab_button.setObjectName("PrimaryButton")
        self.tab_button.clicked.connect(lambda: self.set_expanded(not self._expanded))
        layout.addWidget(self.tab_button)

        self.content_frame = QFrame()
        self.content_frame.setObjectName("FloatingPanelContent")
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;"
        )
        content_layout.addWidget(self.title_label)

        if content is not None:
            self.set_content(content)

        layout.addWidget(self.content_frame)
        self.set_expanded(False)

    def set_content(self, widget: QWidget) -> None:
        if self._content_widget is widget:
            return
        if self._content_widget is not None:
            self.content_frame.layout().removeWidget(self._content_widget)
            self._content_widget.setParent(None)
        widget.setParent(self.content_frame)
        self.content_frame.layout().addWidget(widget)
        self._content_widget = widget

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            self.content_frame.setVisible(expanded)
            return
        self._expanded = expanded
        self.content_frame.setVisible(expanded)
        self.expanded_changed.emit(expanded)
