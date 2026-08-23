"""Collapsible dock rails and the panel manager for the mapping workspace.

The mapping page keeps its real panel widgets (layer tree, reference panel,
chrome panel, bottom workbench); this module only owns *presentation*: a narrow
icon rail per side that expands/collapses the panel area, plus a checkable
panels menu so every panel can be toggled from one central place (the toolbar's
面板 button). Panel instances, signals, and explicit-visibility semantics are
untouched — collapsing is plain ``setVisible`` on the registered widget.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QFrame, QMenu, QToolButton, QVBoxLayout, QWidget

__all__ = ["DockRail", "MapDockManager"]

_ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons" / "map"

RAIL_WIDTH = 36
RAIL_BUTTON_SIZE = 28
RAIL_ICON_SIZE = 18


def panel_icon(name: str) -> QIcon:
    path = _ICONS_DIR / f"{name}.svg"
    return QIcon(str(path)) if path.exists() else QIcon()


class DockRail:
    """One side dock: a narrow vertical icon rail plus a collapsible panel area.

    Rail and area are *sibling* widgets (not nested in a container) so the page
    can place the area inside a ``QSplitter`` — hiding the area then actually
    returns its space to the central canvas — while the always-visible rail
    sits outside the splitter on the outer edge.
    """

    def __init__(self, side: str, parent: QWidget | None = None):
        self.side = side
        self.rail = QFrame(parent)
        self.rail.setObjectName("MapDockRail")
        self.rail.setProperty("side", side)
        self.rail.setFixedWidth(RAIL_WIDTH)
        self.rail_layout = QVBoxLayout(self.rail)
        self.rail_layout.setContentsMargins(3, 6, 3, 6)
        self.rail_layout.setSpacing(4)
        # Box layouts on this Qt build spread extra space between fixed-size
        # items unless the layout is explicitly top-aligned.
        self.rail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.area = QFrame(parent)
        self.area.setObjectName("MapDockArea")
        self.area_layout = QVBoxLayout(self.area)
        self.area_layout.setContentsMargins(0, 0, 0, 0)
        self.area_layout.setSpacing(4)

    def rail_button(self, title: str, icon_name: str) -> QToolButton:
        button = QToolButton(self.rail)
        button.setCheckable(True)
        button.setIcon(panel_icon(icon_name))
        button.setIconSize(QSize(RAIL_ICON_SIZE, RAIL_ICON_SIZE))
        button.setFixedSize(RAIL_BUTTON_SIZE, RAIL_BUTTON_SIZE)
        button.setToolTip(title)
        button.setProperty("dockRailItem", "true")
        return button

    def sync_area_visibility(self) -> None:
        """Show the panel area only while at least one docked panel is visible."""
        visible = any(
            not self.area_layout.itemAt(i).widget().isHidden()
            for i in range(self.area_layout.count())
            if self.area_layout.itemAt(i).widget() is not None
        )
        self.area.setVisible(visible)


class MapDockManager(QObject):
    """Central registry of mapping panels shown through rails, menu, and bottom toggle."""

    panel_toggled = Signal(str, bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.left_dock = DockRail("left")
        self.right_dock = DockRail("right")
        self._panels: dict[str, dict] = {}
        self._menu: QMenu | None = None
        self._bottom_widget: QWidget | None = None
        self._bottom_apply = None
        self._bottom_user_visible = True

    def add_panel(
        self,
        key: str,
        title: str,
        icon_name: str,
        widget: QWidget,
        *,
        side: str,
        checked: bool,
    ) -> None:
        """Dock ``widget`` into a side rail under a checkable rail button."""
        dock = self.left_dock if side == "left" else self.right_dock
        button = dock.rail_button(title, icon_name)
        button.toggled.connect(lambda on, k=key: self._on_rail_toggled(k, on))
        dock.area_layout.addWidget(widget, 1)
        self._panels[key] = {"title": title, "icon": icon_name, "widget": widget, "dock": dock, "button": button}
        dock.rail_layout.addWidget(button)
        button.setChecked(checked)
        widget.setVisible(checked)
        dock.sync_area_visibility()

    def register_bottom(self, key: str, title: str, icon_name: str, widget: QWidget, apply) -> None:
        """Register the bottom workbench: a left-rail bottom toggle plus menu entry.

        ``apply`` recomputes the widget's real visibility from the user
        preference combined with page mode flags (preview / canvas priority).
        """
        self._bottom_widget = widget
        self._bottom_apply = apply
        button = self.left_dock.rail_button(title, icon_name)
        button.toggled.connect(lambda on, k=key: self._on_bottom_toggled(k, on))
        self._panels[key] = {"title": title, "icon": icon_name, "widget": widget, "dock": None, "button": button}
        rail_layout = self.left_dock.rail_layout
        stretch_index = rail_layout.count()
        rail_layout.insertStretch(stretch_index, 1)
        rail_layout.addWidget(button)
        button.setChecked(True)

    def set_panel_visible(self, key: str, visible: bool) -> None:
        entry = self._panels[key]
        entry["button"].setChecked(bool(visible))

    def is_panel_visible(self, key: str) -> bool:
        return bool(self._panels[key]["button"].isChecked())

    def panel_button(self, key: str) -> QToolButton:
        return self._panels[key]["button"]

    def bottom_user_visible(self) -> bool:
        return self._bottom_user_visible

    def panels_menu(self, parent: QWidget | None = None) -> QMenu:
        """Checkable 面板 menu: one action per registered panel."""
        menu = QMenu("面板", parent)
        for key, entry in self._panels.items():
            action = QAction(panel_icon(entry["icon"]), entry["title"], menu)
            action.setObjectName(f"MapPanelMenu:{key}")
            action.setCheckable(True)
            action.setChecked(entry["button"].isChecked())
            action.toggled.connect(lambda on, k=key: self.set_panel_visible(k, on))
            menu.addAction(action)
            entry["menu_action"] = action
        self._menu = menu
        return menu

    def _on_rail_toggled(self, key: str, on: bool) -> None:
        entry = self._panels[key]
        entry["widget"].setVisible(on)
        dock = entry["dock"]
        if dock is not None:
            dock.sync_area_visibility()
        self._sync_menu_action(key, on)
        self.panel_toggled.emit(key, on)

    def _on_bottom_toggled(self, key: str, on: bool) -> None:
        self._bottom_user_visible = on
        if self._bottom_apply is not None:
            self._bottom_apply()
        self._sync_menu_action(key, on)
        self.panel_toggled.emit(key, on)

    def _sync_menu_action(self, key: str, on: bool) -> None:
        action = self._panels[key].get("menu_action")
        if action is not None and action.isChecked() != on:
            action.blockSignals(True)
            action.setChecked(on)
            action.blockSignals(False)
