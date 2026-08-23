"""Central QAction state for the GIS authoring workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import QToolBar, QWidget

__all__ = ["MapActionController", "MapActionState"]

_MAP_ICONS_DIR = Path(__file__).parent / "assets" / "icons" / "map"


def _map_icon(action_id: str) -> QIcon:
    """Load a QGIS-theme toolbar icon, returning an empty QIcon if absent."""
    path = _MAP_ICONS_DIR / f"{action_id}.svg"
    return QIcon(str(path)) if path.exists() else QIcon()


@dataclass(frozen=True, slots=True)
class MapActionState:
    has_active_vector_layer: bool = False
    vector_layer_writable: bool = False
    editing: bool = False
    selected_count: int = 0
    compatible_polygon_count: int = 0
    can_undo: bool = False
    can_redo: bool = False
    can_previous_extent: bool = False
    can_next_extent: bool = False


class MapActionController(QObject):
    """One source of QAction checked/enabled state across menus and toolbars."""

    tool_requested = Signal(str)
    command_requested = Signal(str)

    _TOOL_IDS = (
        "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
        "measure_distance", "add_point", "add_line", "add_polygon", "move_feature", "vertex",
    )

    _LABELS = {
        "pan": "平移", "zoom_in": "放大", "zoom_out": "缩小",
        "full_extent": "全图", "previous_extent": "上一视图", "next_extent": "下一视图",
        "refresh": "刷新", "identify": "识别", "select": "选择",
        "select_rectangle": "框选", "measure_distance": "测距",
        "clear_selection": "清除选择", "select_all": "全选", "invert_selection": "反选",
        "toggle_editing": "开始编辑", "save_edits": "保存编辑", "rollback": "回滚",
        "add_point": "添加点", "add_line": "添加线", "add_polygon": "添加面",
        "move_feature": "移动要素", "vertex": "节点编辑", "delete_selected": "删除所选",
        "undo": "撤销", "redo": "重做", "split": "分割", "merge": "合并",
        "snapping": "捕捉", "topology": "拓扑编辑", "cancel": "取消",
    }

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.actions: dict[str, QAction] = {}
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._build_actions()
        self.update_state(MapActionState())

    def _action(self, action_id: str, *, checkable: bool = False, shortcut: str = "") -> QAction:
        action = QAction(_map_icon(action_id), self._LABELS[action_id], self)
        action.setObjectName(f"MapAction:{action_id}")
        action.setCheckable(checkable)
        action.setToolTip(self._LABELS[action_id])
        action.setStatusTip(self._LABELS[action_id])
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            # The window also binds Ctrl+S to project save. Keep this mapping
            # action's shortcut confined to the editing widget tree so the two
            # don't collide into an ambiguous "Ctrl+S" shortcut.
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.actions[action_id] = action
        return action

    def _build_actions(self) -> None:
        for action_id in self._TOOL_IDS:
            action = self._action(action_id, checkable=True)
            self._tool_group.addAction(action)
            action.triggered.connect(lambda checked=False, name=action_id: checked and self.tool_requested.emit(name))
        for action_id, shortcut in (
            ("full_extent", ""), ("previous_extent", ""), ("next_extent", ""), ("refresh", ""),
            ("clear_selection", ""), ("select_all", ""), ("invert_selection", ""), ("toggle_editing", ""),
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
        for action_id in ("identify", "select", "select_rectangle", "clear_selection", "select_all", "invert_selection"):
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
        self.actions["previous_extent"].setEnabled(state.can_previous_extent)
        self.actions["next_extent"].setEnabled(state.can_next_extent)
        self.actions["cancel"].setEnabled(True)

    def toolbar(
        self,
        title: str,
        action_ids: tuple[str | tuple[str, ...], ...],
        parent: QWidget | None = None,
    ) -> QToolBar:
        """Build an icon-only toolbar.

        ``action_ids`` entries are either a single action id or a nested tuple
        of ids forming a logical group; a separator is inserted between groups.
        Flat tuples of ids remain supported for compatibility.
        """
        toolbar = QToolBar(title, parent)
        toolbar.setObjectName(f"MapToolbar:{title.replace(' ', '')}")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.setIconSize(QSize(18, 18))
        for index, entry in enumerate(action_ids):
            ids = entry if isinstance(entry, tuple) else (entry,)
            if index and isinstance(entry, tuple):
                toolbar.addSeparator()
            for action_id in ids:
                toolbar.addAction(self.actions[action_id])
        return toolbar
