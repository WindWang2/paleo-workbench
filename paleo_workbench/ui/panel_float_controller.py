"""FloatController: float docked panels into top-level windows — and back."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Signal
from PySide6.QtWidgets import QSplitter, QWidget

from paleo_workbench.ui.dock_manager import dock_manager
from paleo_workbench.ui.floating_panel import FloatingPanel
from paleo_workbench.ui.layout_persistence import LayoutPersistence

#: Smallest sensible floating window when the docked widget never got a size.
DEFAULT_FLOAT_SIZE = QSize(420, 320)

#: Offset from the dock parent's top-left when no saved geometry exists.
DEFAULT_FLOAT_OFFSET = 48


@dataclass
class _FloatRecord:
    """Dock context captured at float time so dock-back can restore it."""

    widget: QWidget
    dock_parent: QWidget
    dock_geometry: QRect
    splitter: QSplitter | None
    splitter_index: int | None
    restore_sizes: list[int] | None


def _registry_title(key: str) -> str:
    """Resolve a floating window title from the shared panel registry."""
    title = dock_manager.panel_title(key)
    if title:
        return title
    return key.rpartition(":")[2] or key


class FloatController(QObject):
    """Owns the float state of page panels, keyed by an opaque caller string.

    For every floating panel the controller records ``(widget, dock_parent,
    splitter_index, restore_sizes)``; docking back reinserts the widget at the
    recorded splitter index and restores the recorded sizes. The conventional
    key shape is ``page:panel`` (``"mapping:layer_tree"``) — it namespaces the
    persisted layout entries per page.

    Args:
        resolver: optional ``key -> QWidget`` lookup used when a caller floats
            by key only.
        persistence: optional :class:`LayoutPersistence`; ``None`` disables
            persistence entirely (tests and offscreen CI stay hermetic).
        title_for: optional ``key -> str`` for floating window titles; the
            default consults the panel registry in
            :mod:`paleo_workbench.ui.dock_manager`.
        parent: QObject parent; when it is a widget, floating windows are
            parented to it so their lifetime follows the shell's.

    Offscreen CI stays inert: nothing floats until :meth:`float_panel` or
    :meth:`toggle` is called, so no top-level window is ever created at
    startup.

    Caveat: the recorded splitter index (and sizes) are exact only while the
    splitter's membership is unchanged between float and dock-back —
    float/dock of *other* panels in between shifts or clamps the restore
    slot (dock-back clamps the index to the current child count).
    """

    float_changed = Signal(str, bool)  # (panel key, is_floating)

    def __init__(
        self,
        resolver: Callable[[str], QWidget | None] | None = None,
        persistence: LayoutPersistence | None = None,
        title_for: Callable[[str], str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._resolver = resolver
        self._persistence = persistence
        self._title_for = title_for or _registry_title
        self._floats: dict[str, _FloatRecord] = {}
        self._panels: dict[str, FloatingPanel] = {}

    # --- API -------------------------------------------------------------

    def float_panel(
        self, key: str, widget: QWidget | None = None, *, geometry: QRect | None = None
    ) -> bool:
        """Float ``key``'s widget into a :class:`FloatingPanel`.

        Returns True when the widget is now floating; False when it was
        already floating or could not be resolved.
        """
        if key in self._floats:
            return False
        widget = widget if widget is not None else self._resolve(key)
        if widget is None:
            return False

        dock_parent = widget.parentWidget()
        splitter = self._enclosing_splitter(widget)
        record = _FloatRecord(
            widget=widget,
            dock_parent=dock_parent,
            dock_geometry=widget.geometry(),
            splitter=splitter,
            splitter_index=splitter.indexOf(widget) if splitter is not None else None,
            restore_sizes=list(splitter.sizes()) if splitter is not None else None,
        )

        panel = self._ensure_panel(key)
        panel.set_content(widget)
        # Floating implies revealing: a widget restored as docked-hidden would
        # otherwise surface as an empty floating window.
        widget.setVisible(True)
        if geometry is None:
            geometry = self._default_geometry(widget, dock_parent)
        panel.setGeometry(geometry)
        panel.show()
        self._floats[key] = record

        if self._persistence is not None:
            self._persistence.save_float(key, geometry)
            if any(record.restore_sizes or []):
                self._persistence.save_docked_sizes(key, record.restore_sizes)

        self.float_changed.emit(key, True)
        return True

    def dock_panel(self, key: str) -> bool:
        """Dock ``key``'s widget back at its recorded splitter slot.

        Returns True on success; False when the key was not floating or the
        recorded dock parent no longer exists (the panel then stays floating
        instead of orphaning the widget).
        """
        record = self._floats.get(key)
        if record is None:
            return False
        try:
            self._reinsert(record)
        except RuntimeError:
            # Dock parent destroyed (its C++ side is gone): keep the record so
            # the panel stays afloat rather than dropping the widget.
            return False
        del self._floats[key]

        panel = self._panels.pop(key, None)
        if panel is not None:
            panel.close()
            panel.deleteLater()

        if self._persistence is not None:
            self._persistence.save_dock(key, record.restore_sizes or [])

        self.float_changed.emit(key, False)
        return True

    def toggle(self, key: str, widget: QWidget | None = None) -> bool:
        """Float a docked panel, or dock a floating one."""
        if self.is_floating(key):
            return self.dock_panel(key)
        return self.float_panel(key, widget)

    def is_floating(self, key: str) -> bool:
        return key in self._floats

    def floating_keys(self) -> tuple[str, ...]:
        return tuple(self._floats)

    def floating_panel(self, key: str) -> FloatingPanel | None:
        """The live floating window for ``key``, if any."""
        return self._panels.get(key)

    def restore_saved(self, key: str, widget: QWidget | None = None) -> bool:
        """Re-apply a persisted layout for ``key`` (safe no-op when empty).

        Called per key after the owning page is built — pages are eagerly
        constructed in ``AppShell.__init__``, so a widget is always available
        to restore into. Returns True when any saved state was applied.
        """
        if self._persistence is None:
            return False
        saved = self._persistence.load(key)
        if saved.is_empty:
            return False
        if saved.floating:
            if not self.float_panel(key, widget, geometry=saved.geometry):
                return False
            if not saved.visible:
                panel = self._panels.get(key)
                if panel is not None:
                    panel.hide()
                # Belt and suspenders: hideEvent already reports the hide,
                # but keep the explicit write so the store can never disagree
                # with the UI (P1-1: a desync would revive a panel the user
                # hid on the next launch).
                self._persistence.save_visibility(key, False)
            return True

        widget = widget if widget is not None else self._resolve(key)
        if widget is None:
            return False
        if saved.docked_sizes:
            splitter = self._enclosing_splitter(widget)
            if splitter is not None:
                splitter.setSizes(list(saved.docked_sizes))
        if not saved.visible:
            widget.setVisible(False)
        return True

    # --- internals ---------------------------------------------------------

    def _resolve(self, key: str) -> QWidget | None:
        if self._resolver is None:
            return None
        return self._resolver(key)

    def _ensure_panel(self, key: str) -> FloatingPanel:
        panel = self._panels.get(key)
        if panel is None:
            parent = self.parent() if isinstance(self.parent(), QWidget) else None
            panel = FloatingPanel(key, self._title_for(key), parent)
            panel.dock_back_requested.connect(self.dock_panel)
            panel.visibility_changed.connect(self._on_panel_visibility_changed)
            self._panels[key] = panel
        return panel

    def _on_panel_visibility_changed(self, key: str, visible: bool) -> None:
        if self._persistence is not None and key in self._floats:
            self._persistence.save_visibility(key, visible)

    @staticmethod
    def _enclosing_splitter(widget: QWidget) -> QSplitter | None:
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QSplitter):
                return parent
            parent = parent.parentWidget()
        return None

    @staticmethod
    def _default_geometry(widget: QWidget, dock_parent: QWidget | None) -> QRect:
        size = widget.size().expandedTo(DEFAULT_FLOAT_SIZE)
        if dock_parent is not None:
            origin = dock_parent.mapToGlobal(dock_parent.rect().topLeft())
        else:
            origin = QPoint(DEFAULT_FLOAT_OFFSET, DEFAULT_FLOAT_OFFSET)
        origin += QPoint(DEFAULT_FLOAT_OFFSET, DEFAULT_FLOAT_OFFSET)
        return QRect(origin, size)

    def _reinsert(self, record: _FloatRecord) -> None:
        """Put the widget back into its dock context (raises RuntimeError
        when the dock parent's C++ side is gone).

        The recorded index is used as-is, clamped to the current child count:
        it is exact only while the splitter's membership is unchanged since
        the float (see the class docstring caveat).
        """
        widget = record.widget
        splitter = record.splitter
        if splitter is not None and record.splitter_index is not None:
            index = min(record.splitter_index, splitter.count())
            splitter.insertWidget(index, widget)
            if record.restore_sizes:
                splitter.setSizes(list(record.restore_sizes))
        else:
            widget.setParent(record.dock_parent)
            widget.setGeometry(record.dock_geometry)
        widget.setVisible(True)
