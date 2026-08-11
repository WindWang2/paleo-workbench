"""Qt control surface for the authoritative native C++ layer registry.

``NativeLayerModel`` owns no copy of map-layer state: each model request resolves the
current C++ ``LayerRegistry``.  Its only UI-local state is the current selection, which
is intentionally not render state.  Canvas consumers receive zoom requests as signals
and remain responsible for applying a viewport transform.
"""
from __future__ import annotations

import math
from typing import Any

import layer_model_core
from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QFrame, QHeaderView, QLabel, QTreeView, QVBoxLayout

from paleo_workbench.ui import tokens

__all__ = ["NativeLayerModel", "NativeLayerTree"]


class NativeLayerModel(QAbstractItemModel):
    """A tree-model view of one native ``LayerRegistry``.

    The C++ registry is the sole authority for hierarchy, render order, visibility,
    opacity, names, extents, and revision counters.  Resetting after a structural
    mutation is deliberate: all model indexes are derived from C++ ordering and never
    retain Python shadow nodes.
    """

    LayerIdRole = int(Qt.ItemDataRole.UserRole) + 1
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
        return [
            layer
            for layer in self._registry.layers()
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
        if not index.isValid() or self._layer(index) is None:
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            return flags | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
        return flags | Qt.ItemFlag.ItemIsEditable

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
            if layer.opacity != max(0.0, min(1.0, opacity)):
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
            return self._registry.add_layer(layer_id, name, layer_type, parent_id)
        finally:
            self.endResetModel()

    def remove_layer(self, layer_id: str) -> bool:
        self.beginResetModel()
        try:
            removed = self._registry.remove_layer(layer_id)
        finally:
            self.endResetModel()
        if removed and self._active_layer_id == layer_id:
            self._active_layer_id = None
            self.active_layer_changed.emit(None)
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

        self.model = NativeLayerModel(registry, self)
        self.tree = QTreeView()
        self.tree.setObjectName("NativeLayerTreeView")
        self.tree.setModel(self.model)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(
            QTreeView.EditTrigger.EditKeyPressed | QTreeView.EditTrigger.SelectedClicked
        )
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self.tree.doubleClicked.connect(self._on_double_clicked)
        self.model.active_layer_changed.connect(self.active_layer_changed)
        self.model.zoom_to_layer_requested.connect(self.zoom_to_layer_requested)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.model.set_active_layer(self.model.data(current, NativeLayerModel.LayerIdRole))

    def _on_double_clicked(self, index: QModelIndex) -> None:
        layer_id = self.model.data(index, NativeLayerModel.LayerIdRole)
        if layer_id is not None:
            self.model.request_zoom_to_layer(layer_id)

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
