"""Qt control surface for the authoritative native C++ layer registry.

``NativeLayerModel`` owns no copy of map-layer state: each model request resolves the
current C++ ``LayerRegistry``.  Its only UI-local state is the current selection, which
is intentionally not render state.  Canvas consumers receive zoom requests as signals
and remain responsible for applying a viewport transform.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QMimeData, QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QLabel,
    QMenu,
    QTreeView,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens

_ICONS_DIR = Path(__file__).parent / "assets" / "icons" / "map"


def _tree_icon(name: str) -> QIcon:
    path = _ICONS_DIR / f"{name}.svg"
    return QIcon(str(path)) if path.exists() else QIcon()

# ``layer_model_core`` is an opt-in C++ build. Importing it at module scope made
# this module — and every parent up to ``AppShell`` and the ``paleo-workbench``
# entry point — unimportable on installs that did not build it (#878). Only the
# ``LayerType`` enum is needed here, and always alongside a live registry that
# cannot exist without the extension, so a guarded import is sufficient.
try:  # pragma: no cover - exercised by the absent-extension contract test
    import layer_model_core
except ImportError:  # pragma: no cover
    layer_model_core = None

__all__ = ["NativeLayerModel", "NativeLayerTree"]


class NativeLayerModel(QAbstractItemModel):
    """A tree-model view of one native ``LayerRegistry``.

    The C++ registry is the sole authority for hierarchy, render order, visibility,
    opacity, names, extents, and revision counters.  Resetting after a structural
    mutation is deliberate: all model indexes are derived from C++ ordering and never
    retain Python shadow nodes.
    """

    LayerIdRole = int(Qt.ItemDataRole.UserRole) + 1
    MimeType = "application/x-paleo-workbench-layer-id"
    active_layer_changed = Signal(object)
    layer_changed = Signal(str)
    zoom_to_layer_requested = Signal(str, object)

    def __init__(self, registry: Any, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._active_layer_id: str | None = None
        self._id_to_token: dict[str, int] = {}
        self._token_to_id: dict[int, str] = {}
        self._next_token = 1

    @property
    def registry(self):
        return self._registry

    @property
    def active_layer_id(self) -> str | None:
        return self._active_layer_id

    def _token_for(self, layer_id: str) -> int:
        token = self._id_to_token.get(layer_id)
        if token is None:
            token = self._next_token
            self._next_token += 1
            self._id_to_token[layer_id] = token
            self._token_to_id[token] = layer_id
        return token

    def _id_from_index(self, index: QModelIndex) -> str | None:
        if not index.isValid():
            return None
        return self._token_to_id.get(index.internalId())

    def _layer(self, index: QModelIndex):
        layer_id = self._id_from_index(index)
        return None if layer_id is None else self._registry.get(layer_id)

    def _children(self, parent_id: str | None) -> list[Any]:
        wanted_parent = parent_id or ""
        # Display order is the REVERSE of the registry z-order: the panel's
        # top row shows the layer drawn last (topmost), matching mainstream
        # GIS panels (QGIS/ArcGIS). The registry stays authoritative — its
        # flat index 0 = bottom, drawn first (native layer_model.hpp).
        return [
            layer
            for layer in reversed(self._registry.layers())
            if self._registry.parent_id(layer.id) == wanted_parent
        ]

    def _index_for_id(self, layer_id: str, column: int = 0) -> QModelIndex:
        layer = self._registry.get(layer_id)
        if layer is None:
            return QModelIndex()
        parent_id = self._registry.parent_id(layer_id)
        siblings = self._children(parent_id)
        for row, sibling in enumerate(siblings):
            if sibling.id == layer_id:
                return self.createIndex(row, column, self._token_for(layer_id))
        return QModelIndex()

    # QAbstractItemModel -----------------------------------------------------
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 2

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() and parent.column() != 0:
            return 0
        return len(self._children(self._id_from_index(parent)))

    def index(
        self, row: int, column: int, parent: QModelIndex = QModelIndex()
    ) -> QModelIndex:  # noqa: N802
        if row < 0 or column < 0 or column >= self.columnCount(parent):
            return QModelIndex()
        children = self._children(self._id_from_index(parent))
        if row >= len(children):
            return QModelIndex()
        return self.createIndex(row, column, self._token_for(children[row].id))

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: N802
        layer_id = self._id_from_index(index)
        if layer_id is None:
            return QModelIndex()
        parent_id = self._registry.parent_id(layer_id)
        return QModelIndex() if not parent_id else self._index_for_id(parent_id)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        layer = self._layer(index)
        if layer is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return layer.name
            if index.column() == 1:
                return f"{layer.opacity:.0%}"
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
        if role == self.LayerIdRole:
            return layer.id
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [layer.type.name]
            if layer.crs:
                parts.append(layer.crs)
            if layer.source_ref:
                parts.append(layer.source_ref)
            return " · ".join(parts)
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("图层", "不透明度")[section] if section < 2 else None
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        layer = self._layer(index)
        if layer is None:
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= (
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            if layer.type == layer_model_core.LayerType.Group:
                flags |= Qt.ItemFlag.ItemIsDropEnabled
            return flags
        return flags | Qt.ItemFlag.ItemIsEditable

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [self.MimeType]

    def mimeData(self, indexes) -> QMimeData:  # noqa: N802
        layer_ids = []
        for index in indexes:
            if index.column() != 0:
                continue
            layer_id = self._id_from_index(index)
            if layer_id and layer_id not in layer_ids:
                layer_ids.append(layer_id)
        mime = QMimeData()
        mime.setData(self.MimeType, json.dumps(layer_ids).encode("utf-8"))
        return mime

    def supportedDropActions(self):  # noqa: N802
        return Qt.DropAction.MoveAction

    def dropMimeData(self, data, action, row, column, parent) -> bool:  # noqa: N802
        if action == Qt.DropAction.IgnoreAction:
            return True
        if action != Qt.DropAction.MoveAction or not data.hasFormat(self.MimeType):
            return False
        try:
            layer_ids = json.loads(bytes(data.data(self.MimeType)).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError):
            return False
        if not isinstance(layer_ids, list) or len(layer_ids) != 1:
            return False
        layer_id = str(layer_ids[0])
        layer = self._registry.get(layer_id)
        if layer is None:
            return False
        parent_id = self._id_from_index(parent) or ""
        if parent_id and self._registry.get(parent_id).type != layer_model_core.LayerType.Group:
            parent_id = self._registry.parent_id(parent_id)
        siblings = self._children(parent_id)
        if row < 0:
            row = len(siblings)
        row = max(0, min(int(row), len(siblings)))
        self.beginResetModel()
        try:
            if not self._registry.set_parent(layer_id, parent_id):
                return False
            # The native registry stores authoritative flat z-order. Convert a
            # tree sibling insertion to the corresponding absolute position.
            # ``siblings`` is DISPLAY order (top = highest z), so the dropped
            # layer takes the registry index of the layer it lands on in the
            # panel; dropping below the last row means the very bottom (0).
            if siblings:
                if row >= len(siblings):
                    absolute = 0
                else:
                    absolute = self._registry.index_of(siblings[row].id)
            else:
                absolute = self._registry.size - 1
            self._registry.move_layer(layer_id, max(0, int(absolute)))
        finally:
            self.endResetModel()
        self.layer_changed.emit(layer_id)
        return True

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        layer = self._layer(index)
        if layer is None:
            return False
        changed = False
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            visible = value == Qt.CheckState.Checked or value is True
            if layer.visible != visible:
                layer.visible = visible
                changed = True
        elif index.column() == 0 and role == Qt.ItemDataRole.EditRole:
            name = str(value)
            if layer.name != name:
                layer.name = name
                changed = True
        elif index.column() == 1 and role == Qt.ItemDataRole.EditRole:
            try:
                opacity = float(value)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(opacity):
                return False
            # Clamp the value identically to the guard: assigning the raw
            # value let out-of-range opacity (e.g. 5, -3) persist into the
            # authoritative native LayerRegistry.
            opacity = max(0.0, min(1.0, opacity))
            if layer.opacity != opacity:
                layer.opacity = opacity
                changed = True
        if not changed:
            return False
        self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.DisplayRole])
        self.layer_changed.emit(layer.id)
        return True

    # Native-registry operations --------------------------------------------
    def refresh(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def add_layer(
        self,
        layer_id: str,
        name: str,
        layer_type: Any,
        *,
        parent_id: str = "",
    ):
        self.beginResetModel()
        try:
            layer = self._registry.add_layer(layer_id, name, layer_type, parent_id)
        finally:
            self.endResetModel()
        self.layer_changed.emit(layer.id)
        return layer

    def remove_layer(self, layer_id: str) -> bool:
        self.beginResetModel()
        try:
            removed = self._registry.remove_layer(layer_id)
        finally:
            self.endResetModel()
        if removed and self._active_layer_id == layer_id:
            self._active_layer_id = None
            self.active_layer_changed.emit(None)
        if removed:
            self.layer_changed.emit(layer_id)
        return removed

    def move_layer(self, layer_id: str, new_index: int) -> bool:
        self.beginResetModel()
        try:
            moved = self._registry.move_layer(layer_id, new_index)
        finally:
            self.endResetModel()
        if moved:
            self.layer_changed.emit(layer_id)
        return moved

    def set_active_layer(self, layer_id: str | None) -> bool:
        if layer_id is not None and self._registry.get(layer_id) is None:
            return False
        if self._active_layer_id == layer_id:
            return True
        self._active_layer_id = layer_id
        self.active_layer_changed.emit(layer_id)
        return True

    def request_zoom_to_layer(self, layer_id: str) -> bool:
        layer = self._registry.get(layer_id)
        if layer is None:
            return False
        self.zoom_to_layer_requested.emit(layer_id, layer.extent)
        return True


class NativeLayerTree(QFrame):
    """Compact, keyboard-accessible ``QTreeView`` for native map layers."""

    active_layer_changed = Signal(object)
    zoom_to_layer_requested = Signal(str, object)
    add_layer_requested = Signal()
    properties_requested = Signal(str)
    export_layer_requested = Signal(str)

    def __init__(self, registry: Any, parent=None):
        super().__init__(parent)
        self.setObjectName("NativeLayerTree")
        self.setMinimumWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("原生图层")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        # Layer management lives entirely on the tree's right-click menu — no
        # always-visible button row (the panel stays a clean layer list).
        self.add_layer_action = QAction(_tree_icon("tree-add-layer"), "添加图层", self)
        self.add_group_action = QAction(_tree_icon("tree-add-group"), "添加分组", self)
        self.remove_action = QAction(_tree_icon("tree-remove"), "移除图层", self)
        self.move_up_action = QAction(_tree_icon("tree-move-up"), "上移", self)
        self.move_down_action = QAction(_tree_icon("tree-move-down"), "下移", self)
        self.zoom_action = QAction(_tree_icon("tree-zoom"), "缩放至图层", self)
        self.properties_action = QAction(_tree_icon("tree-properties"), "属性", self)

        self.model = NativeLayerModel(registry, self)
        self.tree = QTreeView()
        self.tree.setObjectName("NativeLayerTreeView")
        self.tree.setModel(self.model)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(
            QTreeView.EditTrigger.EditKeyPressed | QTreeView.EditTrigger.SelectedClicked
        )
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self.tree.doubleClicked.connect(self._on_double_clicked)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.model.active_layer_changed.connect(self.active_layer_changed)
        self.model.zoom_to_layer_requested.connect(self.zoom_to_layer_requested)
        self.add_layer_action.triggered.connect(self.add_layer_requested.emit)
        self.add_group_action.triggered.connect(self._add_group)
        self.remove_action.triggered.connect(self._remove_current)
        self.move_up_action.triggered.connect(lambda: self._move_current(1))
        self.move_down_action.triggered.connect(lambda: self._move_current(-1))
        self.zoom_action.triggered.connect(self._zoom_current)
        self.properties_action.triggered.connect(self._properties_current)
        self._sync_action_state()

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.model.set_active_layer(self.model.data(current, NativeLayerModel.LayerIdRole))
        self._sync_action_state()

    def _on_double_clicked(self, index: QModelIndex) -> None:
        layer_id = self.model.data(index, NativeLayerModel.LayerIdRole)
        if layer_id is not None:
            self.model.request_zoom_to_layer(layer_id)

    def _current_layer_id(self) -> str | None:
        return self.model.data(self.tree.currentIndex(), NativeLayerModel.LayerIdRole)

    def _sync_action_state(self) -> None:
        layer_id = self._current_layer_id()
        layer = self.model.registry.get(layer_id) if layer_id else None
        has_layer = layer is not None
        self.remove_action.setEnabled(has_layer)
        self.zoom_action.setEnabled(has_layer)
        self.properties_action.setEnabled(has_layer)
        # Display convention: top row = highest z (drawn last). "Move Up"
        # raises the z-order (index + 1), "Move Down" lowers it.
        self.move_up_action.setEnabled(
            has_layer and self.model.registry.index_of(layer_id) + 1 < self.model.registry.size
        )
        self.move_down_action.setEnabled(
            has_layer and self.model.registry.index_of(layer_id) > 0
        )

    def _add_group(self) -> None:
        from uuid import uuid4

        layer_id = f"group_{uuid4().hex[:12]}"
        self.model.add_layer(layer_id, "Group", layer_model_core.LayerType.Group)
        self.expand_all()

    def _remove_current(self) -> None:
        layer_id = self._current_layer_id()
        if layer_id:
            self.model.remove_layer(layer_id)
        self._sync_action_state()

    def _move_current(self, delta: int) -> None:
        layer_id = self._current_layer_id()
        if layer_id is None:
            return
        self.model.move_layer(layer_id, self.model.registry.index_of(layer_id) + delta)
        self._sync_action_state()

    def _zoom_current(self) -> None:
        layer_id = self._current_layer_id()
        if layer_id:
            self.model.request_zoom_to_layer(layer_id)

    def _properties_current(self) -> None:
        layer_id = self._current_layer_id()
        if layer_id:
            self.properties_requested.emit(layer_id)

    def _select_row_at(self, position) -> None:
        """Right-click selects the layer under the cursor (QGIS panel behavior)."""
        index = self.tree.indexAt(position)
        if index.isValid():
            self.tree.setCurrentIndex(index)

    def _build_context_menu(self) -> QMenu:
        """All layer management actions, icon-labeled, for the tree's right-click menu."""
        menu = QMenu(self)
        menu.addAction(self.add_layer_action)
        menu.addAction(self.add_group_action)
        menu.addSeparator()
        menu.addAction(self.zoom_action)
        menu.addAction(self.properties_action)
        menu.addSeparator()
        menu.addAction(self.move_up_action)
        menu.addAction(self.move_down_action)
        menu.addAction(self.remove_action)
        layer_id = self._current_layer_id()
        if layer_id:
            menu.addSeparator()
            menu.addAction(
                _tree_icon("tree-export"),
                "导出图层",
                lambda: self.export_layer_requested.emit(layer_id),
            )
        return menu

    def _show_context_menu(self, position) -> None:
        self._select_row_at(position)
        self._build_context_menu().exec(self.tree.viewport().mapToGlobal(position))

    def set_active_layer(self, layer_id: str | None) -> bool:
        if not self.model.set_active_layer(layer_id):
            return False
        if layer_id is not None:
            index = self.model._index_for_id(layer_id)
            if index.isValid():
                self.tree.setCurrentIndex(index)
                self.tree.scrollTo(index)
        else:
            self.tree.clearSelection()
        return True

    def expand_all(self) -> None:
        self.tree.expandAll()
