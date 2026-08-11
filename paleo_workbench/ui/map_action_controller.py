"""Central QAction state for the GIS authoring workspace."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QToolBar, QWidget

__all__ = ["MapActionController", "MapActionState"]


@dataclass(frozen=True, slots=True)
class MapActionState:
    has_active_vector_layer: bool = False
    vector_layer_writable: bool = False
    editing: bool = False
    selected_count: int = 0
    compatible_polygon_count: int = 0
    can_undo: bool = False
    can_redo: bool = False


class MapActionController(QObject):
    """One source of QAction checked/enabled state across menus and toolbars."""

    tool_requested = Signal(str)
    command_requested = Signal(str)

    _TOOL_IDS = (
        "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
        "add_point", "add_line", "add_polygon", "move_feature", "vertex",
    )

    _LABELS = {
        "pan": "Pan", "zoom_in": "Zoom In", "zoom_out": "Zoom Out",
        "full_extent": "Full Extent", "identify": "Identify", "select": "Select",
        "select_rectangle": "Rectangle Select", "clear_selection": "Clear Selection",
        "toggle_editing": "Toggle Editing", "save_edits": "Save Edits", "rollback": "Rollback",
        "add_point": "Add Point", "add_line": "Add Line", "add_polygon": "Add Polygon",
        "move_feature": "Move Feature", "vertex": "Vertex Tool", "delete_selected": "Delete Selected",
        "undo": "Undo", "redo": "Redo", "split": "Split", "merge": "Merge",
        "snapping": "Snapping", "topology": "Topological Editing", "cancel": "Cancel",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.actions: dict[str, QAction] = {}
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._build_actions()
        self.update_state(MapActionState())

    def _action(self, action_id: str, *, checkable: bool = False, shortcut: str = "") -> QAction:
        action = QAction(self._LABELS[action_id], self)
        action.setObjectName(f"MapAction:{action_id}")
        action.setCheckable(checkable)
        action.setToolTip(self._LABELS[action_id])
        action.setStatusTip(self._LABELS[action_id])
        action.setIconText(self._LABELS[action_id])
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        self.actions[action_id] = action
        return action

    def _build_actions(self) -> None:
        for action_id in self._TOOL_IDS:
            action = self._action(action_id, checkable=True)
            self._tool_group.addAction(action)
            action.triggered.connect(lambda checked=False, name=action_id: checked and self.tool_requested.emit(name))
        for action_id, shortcut in (
            ("full_extent", ""), ("clear_selection", ""), ("toggle_editing", ""),
            ("save_edits", "Ctrl+S"), ("rollback", ""), ("delete_selected", "Delete"),
            ("undo", "Ctrl+Z"), ("redo", "Ctrl+Shift+Z"), ("split", ""), ("merge", ""),
            ("snapping", ""), ("topology", ""), ("cancel", "Esc"),
        ):
            action = self._action(action_id, checkable=action_id in {"snapping", "topology", "toggle_editing"}, shortcut=shortcut)
            action.triggered.connect(lambda checked=False, name=action_id: self.command_requested.emit(name))
        self.actions["pan"].setChecked(True)

    def update_state(self, state: MapActionState) -> None:
        vector = state.has_active_vector_layer
        editable = vector and state.vector_layer_writable
        editing = editable and state.editing
        for action_id in ("identify", "select", "select_rectangle", "clear_selection"):
            self.actions[action_id].setEnabled(vector)
        self.actions["toggle_editing"].setEnabled(editable)
        if self.actions["toggle_editing"].isChecked() != editing:
            self.actions["toggle_editing"].blockSignals(True)
            self.actions["toggle_editing"].setChecked(editing)
            self.actions["toggle_editing"].blockSignals(False)
        for action_id in ("save_edits", "rollback", "add_point", "add_line", "add_polygon", "move_feature", "vertex", "snapping", "topology"):
            self.actions[action_id].setEnabled(editing)
        self.actions["undo"].setEnabled(editing and state.can_undo)
        self.actions["redo"].setEnabled(editing and state.can_redo)
        self.actions["delete_selected"].setEnabled(editing and state.selected_count > 0)
        self.actions["split"].setEnabled(editing and state.selected_count > 0)
        self.actions["merge"].setEnabled(editing and state.compatible_polygon_count >= 2)
        self.actions["cancel"].setEnabled(True)

    def toolbar(self, title: str, action_ids: tuple[str, ...], parent: QWidget | None = None) -> QToolBar:
        toolbar = QToolBar(title, parent)
        toolbar.setObjectName(f"MapToolbar:{title.replace(' ', '')}")
        toolbar.setMovable(False)
        for action_id in action_ids:
            toolbar.addAction(self.actions[action_id])
        return toolbar
