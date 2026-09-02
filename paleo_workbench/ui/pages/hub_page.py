"""Hub container pages for the UI-v2 Ribbon shell.

A hub hosts the former stand-alone pages (now *sub-modules*) behind a pill
switcher row and a ``QStackedWidget``. Hubs forward ``activate_page`` and
expose their sub-module widgets so the shell and controllers can keep
talking to the concrete pages they already know.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens


class HubPage(QWidget):
    """Container hosting one hub's sub-module pages behind a pill switcher."""

    submodule_changed = Signal(int, str)  # hub_index, submodule key
    page_activated = Signal(int, str)  # emitted for UI and programmatic switches

    def __init__(self, hub_index: int, parent=None):
        super().__init__(parent)
        self.hub_index = hub_index
        self._keys: list[str] = []
        self._buttons: list[QPushButton] = []
        self._pages: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._switcher_host = QWidget(self)
        self._switcher_host.setObjectName("SubmoduleSwitcher")
        switcher = QHBoxLayout(self._switcher_host)
        switcher.setContentsMargins(
            tokens.PAGE_MARGIN, tokens.SPACE_1, tokens.PAGE_MARGIN, tokens.SPACE_1
        )
        switcher.setSpacing(tokens.SPACE_1)
        self._switcher_layout = switcher

        self._stack = QStackedWidget(self)
        layout.addWidget(self._switcher_host)
        layout.addWidget(self._stack, 1)

    def add_submodule(self, key: str, title: str, page: QWidget) -> None:
        """Register a sub-module page under *key* with a switcher pill."""
        self._keys.append(key)
        self._pages[key] = page
        self._stack.addWidget(page)
        btn = QPushButton(title)
        btn.setObjectName("SubmodulePill")
        btn.setProperty("active", False)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(
            lambda _checked=False, k=key: self.switch_to(k, emit=True)
        )
        self._buttons.append(btn)
        self._switcher_layout.addWidget(btn)
        # A single-sub-module hub has no visible switcher (可视化)。
        self._switcher_host.setVisible(len(self._keys) > 1)

    def finish(self) -> None:
        self._switcher_layout.addStretch(1)

    # --- switching ------------------------------------------------------

    def switch_to(self, key: str, *, emit: bool = False) -> None:
        """Activate the sub-module *key* (no-op when unknown)."""
        page = self._pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        for btn, k in zip(self._buttons, self._keys):
            btn.setProperty("active", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        activate = getattr(page, "activate_page", None)
        if callable(activate):
            activate()
        self.page_activated.emit(self.hub_index, key)
        if emit:
            self.submodule_changed.emit(self.hub_index, key)

    def current_key(self) -> str:
        index = self._stack.currentIndex()
        if 0 <= index < len(self._keys):
            return self._keys[index]
        return ""

    def current_page(self) -> QWidget | None:
        """The currently active sub-module widget."""
        return self._stack.currentWidget()

    def page(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    def activate_page(self) -> None:
        """Forward the shell's page-activation to the current sub-module."""
        page = self._stack.currentWidget()
        activate = getattr(page, "activate_page", None)
        if callable(activate):
            activate()
