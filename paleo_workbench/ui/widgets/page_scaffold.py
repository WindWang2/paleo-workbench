from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.widgets.section_header import SectionHeader


class PageScaffold(QWidget):
    def __init__(self, title: str | None = None, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("PageScaffold")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        self._layout.setSpacing(tokens.SPACE_3)
        self.header: SectionHeader | None = None
        if title:
            self.header = SectionHeader(title, subtitle=subtitle)
            self._layout.addWidget(self.header)
        self.body_widget: QWidget | None = None
        self._body_index = self._layout.count()

    def set_body(self, widget: QWidget) -> None:
        if self.body_widget is not None:
            self._layout.removeWidget(self.body_widget)
            self.body_widget.setParent(None)
        self.body_widget = widget
        self._layout.addWidget(widget, 1)
