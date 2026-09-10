"""Modeless dialog host for tool pages (数据制备 / 成图审核).

These pages are workflows over the central 编图 document. They must not
occupy a dock that competes with the map; a closable dialog keeps the
canvas in place.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QWidget,
)


class ToolPageDialog(QDialog):
    """Hosts one tool page, restoring it to its hub stack on close."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToolPageDialog")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1080, 720)
        self.setMinimumSize(720, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._body, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._page: QWidget | None = None
        self._home: QWidget | None = None

    def present(self, page: QWidget, title: str, home: QWidget | None) -> None:
        if page is self._page and self.isVisible():
            self.setWindowTitle(title)
            self.raise_()
            self.activateWindow()
            return
        self._release()
        self._page = page
        self._home = home
        self._body.addWidget(page)
        page.show()
        self.setWindowTitle(title)
        self.show()
        self.raise_()
        self.activateWindow()

    def _release(self) -> None:
        page = self._page
        home = self._home
        self._page = None
        self._home = None
        if page is None:
            return
        self._body.removeWidget(page)
        if home is not None and hasattr(home, "addWidget"):
            home.addWidget(page)
        elif home is not None:
            page.setParent(home)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._release()
        super().closeEvent(event)

    def reject(self) -> None:
        self._release()
        super().reject()
