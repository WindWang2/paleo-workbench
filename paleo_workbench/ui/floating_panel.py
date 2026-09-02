"""FloatingPanel: a top-level window hosting a reparented dock panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizeGrip,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens


class FloatingPanel(QWidget):
    """Top-level window that hosts a panel widget while it is floated.

    Created lazily by the
    :class:`~paleo_workbench.ui.panel_float_controller.FloatController` on the
    first float, so the offscreen CI run never instantiates a real window by
    default (CommandPalette's policy inverted: floating is user-initiated, so
    this one is a genuine ``Qt.Window`` top-level). Themes come for free —
    top-level widgets inherit the app-level QSS that the theme manager
    republishes on every switch (``AppShell._on_theme_changed``).

    Signals:
        dock_back_requested(str): the dock-back button was clicked; carries
            the panel key.
        visibility_changed(str, bool): the panel became visible or hidden
            while hosting content; carries key and new visibility. Emitted
            from ``showEvent``/``hideEvent`` (so close, hide, and any future
            hiding path all report), but never for an empty window — an
            empty panel's lifecycle is controller cleanup, not panel state.
    """

    dock_back_requested = Signal(str)
    visibility_changed = Signal(str, bool)

    def __init__(self, key: str, title: str, parent=None) -> None:
        super().__init__(parent)
        self._key = key
        self.setWindowTitle(title)
        # A real top-level window even when a parent widget is handed over.
        self.setWindowFlags(Qt.WindowType.Window)
        self.setObjectName("FloatingPanel")
        self.setMinimumSize(240, 180)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1
        )
        root.setSpacing(tokens.SPACE_1)

        # Thin custom title bar: title · dock-back · close.
        title_bar = QWidget(self)
        title_bar.setObjectName("FloatingPanelTitleBar")
        bar_layout = QHBoxLayout(title_bar)
        bar_layout.setContentsMargins(tokens.SPACE_2, 0, 0, 0)
        bar_layout.setSpacing(tokens.SPACE_1)
        self.title_label = QLabel(title, title_bar)
        self.title_label.setObjectName("FloatingPanelTitle")
        bar_layout.addWidget(self.title_label)
        bar_layout.addStretch(1)
        self.dock_back_button = QToolButton(title_bar)
        self.dock_back_button.setText("⇲")
        self.dock_back_button.setToolTip("停靠回原位 (Dock back)")
        self.dock_back_button.clicked.connect(self._emit_dock_back)
        bar_layout.addWidget(self.dock_back_button)
        self.close_button = QToolButton(title_bar)
        self.close_button.setText("✕")
        self.close_button.setToolTip("隐藏浮动面板 (Hide)")
        self.close_button.clicked.connect(self.close)
        bar_layout.addWidget(self.close_button)
        root.addWidget(title_bar)

        # Central slot for the reparented panel widget.
        self.content_host = QWidget(self)
        self.content_host.setObjectName("FloatingPanelContent")
        self._content_layout = QVBoxLayout(self.content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.content_host, 1)

        # Bottom-right resize grip.
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(self))
        root.addLayout(grip_row)

    @property
    def key(self) -> str:
        return self._key

    # --- content slot ---------------------------------------------------

    def set_content(self, widget: QWidget) -> None:
        """Reparent ``widget`` into the central slot.

        No replace semantics: the slot hosts exactly one widget per float,
        and a second ``set_content`` call stacks another widget instead of
        swapping (the caller is expected to dock-back or ``take_content``
        first).
        """
        self._content_layout.addWidget(widget)

    def take_content(self) -> QWidget | None:
        """Detach the hosted widget (reparented to top-level) and return it."""
        item = self._content_layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.setParent(None)
        return widget

    def set_panel_title(self, title: str) -> None:
        self.setWindowTitle(title)
        self.title_label.setText(title)

    # --- window behaviour -------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._emit_visibility(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # close() hides too, so dock-back-close, the hide button, Alt+F4 and
        # any direct hide() all report exactly once through here.
        self._emit_visibility(False)
        super().hideEvent(event)

    def _emit_visibility(self, visible: bool) -> None:
        # Only panels hosting content report visibility: an empty window's
        # show/hide is controller lifecycle, not user-visible panel state
        # (dock-back closes an emptied window and must stay silent).
        if self._content_layout.count():
            self.visibility_changed.emit(self._key, visible)

    def _emit_dock_back(self) -> None:
        self.dock_back_requested.emit(self._key)
