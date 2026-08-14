from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.mapping_helpers import field_value

LAYER_KEYS = ("facies", "well", "line", "label")
LAYER_LABELS = {
    "facies": "相带",
    "well": "井",
    "line": "线",
    "label": "注记",
}


class MapLayerTree(QFrame):
    """Document list plus per-layer visibility and lock controls."""

    document_selected = Signal(object)
    layer_visibility_changed = Signal(str, bool)
    layer_lock_changed = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapLayerTree")
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("图件与图层")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setObjectName("MapLayerTreeWidget")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(True)
        layout.addWidget(self.tree, 1)

        self._documents: list[Any] = []
        self._active_document: Any = None
        self._doc_items: list[QTreeWidgetItem] = []
        self._layer_items: dict[str, QTreeWidgetItem] = {}
        self._layer_locked: dict[str, bool] = {k: False for k in LAYER_KEYS}
        self._layer_visible: dict[str, bool] = {k: True for k in LAYER_KEYS}
        self._suppress_item_changed = False

        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.itemChanged.connect(self._on_item_changed)

        self._rebuild_tree()

    def set_documents(self, documents: list | tuple | None) -> None:
        self._documents = list(documents or [])
        self._rebuild_tree()

    def set_active_document(self, document) -> None:
        self._active_document = document
        self._rebuild_tree()
        if document is None:
            return
        for item in self._doc_items:
            if item.data(0, Qt.ItemDataRole.UserRole) is document:
                self.tree.setCurrentItem(item)
                item.setExpanded(True)
                break

    def set_layer_locked(self, layer_key: str, locked: bool) -> None:
        if layer_key not in LAYER_KEYS:
            return
        if self._layer_locked.get(layer_key) == locked:
            return
        self._layer_locked[layer_key] = locked
        item = self._layer_items.get(layer_key)
        if item is not None:
            self._suppress_item_changed = True
            item.setText(1, "🔒" if locked else "")
            self._suppress_item_changed = False
        self.layer_lock_changed.emit(layer_key, locked)

    def layer_is_visible(self, layer_key: str) -> bool:
        return self._layer_visible.get(layer_key, True)

    def layer_is_locked(self, layer_key: str) -> bool:
        return self._layer_locked.get(layer_key, False)

    def _rebuild_tree(self) -> None:
        self._suppress_item_changed = True
        self.tree.clear()
        self._doc_items = []
        self._layer_items = {}

        root = QTreeWidgetItem(["图件"])
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tree.addTopLevelItem(root)
        root.setExpanded(True)

        active = self._active_document
        for doc in self._documents:
            name = field_value(doc, "name", "") or "未命名图件"
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.ItemDataRole.UserRole, doc)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            root.addChild(item)
            self._doc_items.append(item)

            if active is not None and doc is active:
                self._populate_layers(item)
                self._populate_reference_layers(item, doc)

        if active is None and self._doc_items:
            # Fallback: attach layers to last document if no explicit active
            self._populate_layers(self._doc_items[-1])
            self._populate_reference_layers(self._doc_items[-1], self._documents[-1])

        self._suppress_item_changed = False

    def _populate_layers(self, parent: QTreeWidgetItem) -> None:
        for key in LAYER_KEYS:
            label = LAYER_LABELS[key]
            layer_item = QTreeWidgetItem([label, ""])
            layer_item.setData(0, Qt.ItemDataRole.UserRole, ("layer", key))
            layer_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            visible = self._layer_visible.get(key, True)
            layer_item.setCheckState(
                0,
                Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked,
            )
            if self._layer_locked.get(key, False):
                layer_item.setText(1, "🔒")
            parent.addChild(layer_item)
            self._layer_items[key] = layer_item
            parent.setExpanded(True)

    def _populate_reference_layers(self, parent: QTreeWidgetItem, document: Any) -> None:
        ref_layers = getattr(document, "reference_layers", [])
        if not ref_layers:
            return

        ref_group = QTreeWidgetItem(["参考图层"])
        ref_group.setFlags(Qt.ItemFlag.ItemIsEnabled)
        parent.addChild(ref_group)

        for layer in ref_layers:
            name = getattr(layer, "name", "未命名参考图层")
            status = getattr(layer, "status", "")
            
            if status == "offline":
                name = f"{name} (离线)"
            elif status == "failed":
                name = f"{name} (失败)"

            item = QTreeWidgetItem([name, ""])
            item.setData(0, Qt.ItemDataRole.UserRole, ("reference_layer", layer))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            ref_group.addChild(item)
            
        ref_group.setExpanded(True)

    def _on_current_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return
        if isinstance(data, tuple) and data and data[0] == "layer":
            # Selecting a layer does not change document
            return
        if isinstance(data, tuple) and data and data[0] == "reference_layer":
            # Reference-layer rows are not map documents; treating them as one
            # emitted a raw tuple as the active document and crashed the host
            # page's load_document() with AttributeError.
            return
        # Document node
        if data is not self._active_document:
            self._active_document = data
            self._rebuild_tree()
            for item in self._doc_items:
                if item.data(0, Qt.ItemDataRole.UserRole) is data:
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(item)
                    item.setExpanded(True)
                    self.tree.blockSignals(False)
                    break
            self.document_selected.emit(data)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._suppress_item_changed:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not (isinstance(data, tuple) and data and data[0] == "layer"):
            return
        layer_key = data[1]
        if column == 0:
            visible = item.checkState(0) == Qt.CheckState.Checked
            if self._layer_visible.get(layer_key) != visible:
                self._layer_visible[layer_key] = visible
                self.layer_visibility_changed.emit(layer_key, visible)
