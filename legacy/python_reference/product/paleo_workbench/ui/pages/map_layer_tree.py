from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.modelview.reconcile import reconcile_widget_items
from paleo_workbench.viz.mapping_helpers import field_value

LAYER_KEYS = ("facies", "well", "line", "label")
LAYER_LABELS = {
    "facies": "相带",
    "well": "井",
    "line": "线",
    "label": "注记",
}

# reconcile 稳定键命名空间（V11 D2 ⑮）：clear+rebuild → 键差分，项身份/
# 展开态/选中行/滚动位置在文档选择切换间保持。
_ROOT_KEY = "__root__"
_REF_GROUP_KEY = "refgroup"


def _document_key(doc: Any) -> str:
    doc_id = str(field_value(doc, "id", "") or "")
    return f"doc:{doc_id}" if doc_id else f"doc@{id(doc)}"


def _reference_layer_key(layer: Any) -> str:
    layer_id = str(getattr(layer, "id", "") or "")
    return f"ref:{layer_id}" if layer_id else f"ref@{id(layer)}"


class MapLayerTree(QFrame):
    """Document list plus per-layer visibility and lock controls."""

    document_selected = Signal(object)
    layer_visibility_changed = Signal(str, bool)
    layer_lock_changed = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapLayerTree")
        self.setMinimumWidth(220)

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
        # 当前正在展开图层子树的文档（reconcile 回调取参考层用；回退路径
        # 下可能与 _active_document 不同——旧实现同样按“被填充文档”取值）。
        self._populated_document: Any = None
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
            item.setText(1, "⊘" if locked else "")
            self._suppress_item_changed = False
        self.layer_lock_changed.emit(layer_key, locked)

    def layer_is_visible(self, layer_key: str) -> bool:
        return self._layer_visible.get(layer_key, True)

    def layer_is_locked(self, layer_key: str) -> bool:
        return self._layer_locked.get(layer_key, False)

    # -- 键差分同步 ------------------------------------------------------------

    def _rebuild_tree(self) -> None:
        """把 (documents + active document 的图层子树) 同步进树。

        键差分（reconcile_widget_items）：文档/图层键集不变时零结构操作
        ——项身份、展开态、选中行与滚动位置在重建间原样保留；图层只在
        活动（或回退末位）文档下展开，切换活动文档即键集迁移。
        """
        self._suppress_item_changed = True
        tree_signals_blocked = self.tree.blockSignals(True)
        try:
            items = reconcile_widget_items(
                self.tree,
                [_ROOT_KEY],
                make_item=self._make_root_item,
                update_item=self._update_root_item,
            )
            root = items[_ROOT_KEY]

            doc_items = reconcile_widget_items(
                self.tree,
                [_document_key(doc) for doc in self._documents],
                make_item=self._make_document_item,
                update_item=self._update_document_item,
                parent_item=root,
            )
            self._doc_items = [doc_items[_document_key(doc)] for doc in self._documents]

            active = self._active_document
            populated: QTreeWidgetItem | None = None
            for doc, item in zip(self._documents, self._doc_items):
                if active is not None and doc is active:
                    self._reconcile_document_children(item, doc)
                    populated = item
            if active is None and self._doc_items:
                # Fallback: attach layers to last document if no explicit active
                self._reconcile_document_children(self._doc_items[-1], self._documents[-1])
                populated = self._doc_items[-1]
            for doc, item in zip(self._documents, self._doc_items):
                if item is not populated:
                    # 非活动文档不带图层子树（与旧 clear+rebuild 行为一致）
                    reconcile_widget_items(
                        self.tree,
                        [],
                        make_item=lambda key: QTreeWidgetItem(),
                        update_item=lambda item, key: None,
                        parent_item=item,
                    )
        finally:
            self.tree.blockSignals(tree_signals_blocked)
            self._suppress_item_changed = False

    def _make_root_item(self, key: str) -> QTreeWidgetItem:
        root = QTreeWidgetItem(["图件"])
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        return root

    def _update_root_item(self, item: QTreeWidgetItem, key: str) -> None:
        if item.text(0) != "图件":
            item.setText(0, "图件")
        item.setExpanded(True)

    def _make_document_item(self, key: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(["未命名图件"])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return item

    def _update_document_item(self, item: QTreeWidgetItem, key: str) -> None:
        doc = next(
            (d for d in self._documents if _document_key(d) == key), None
        )
        name = field_value(doc, "name", "") or "未命名图件" if doc is not None else "未命名图件"
        if item.text(0) != name:
            item.setText(0, name)
        item.setData(0, Qt.ItemDataRole.UserRole, doc)
        # 展开不在此强制：活动文档的展开由激活路径（set_active_document /
        # _on_current_item_changed / 首次填充子树）负责——同键刷新时保留
        # 用户手动收起的展开状态（V11 D2 ⑮ 的保持目标）。

    def _reconcile_document_children(self, parent: QTreeWidgetItem, document: Any) -> None:
        """活动文档的子树：4 个编辑图层 + （有参考层时）参考图层组。"""
        self._populated_document = document
        ref_layers = list(getattr(document, "reference_layers", []) or [])
        child_keys = [f"layer:{key}" for key in LAYER_KEYS]
        if ref_layers:
            child_keys.append(_REF_GROUP_KEY)
        first_population = parent.childCount() == 0
        items = reconcile_widget_items(
            self.tree,
            child_keys,
            make_item=self._make_document_child_item,
            update_item=self._update_document_child_item,
            parent_item=parent,
        )
        self._layer_items = {
            key: items[f"layer:{key}"] for key in LAYER_KEYS
        }
        # 仅首次填充（切换活动文档 / 初始绑定）时展开；同键刷新保留用户
        # 手动收起的状态。
        if first_population:
            parent.setExpanded(True)
        if not ref_layers:
            return
        ref_group = items[_REF_GROUP_KEY]
        ref_first = ref_group.childCount() == 0
        reconcile_widget_items(
            self.tree,
            [_reference_layer_key(layer) for layer in ref_layers],
            make_item=self._make_reference_item,
            update_item=self._update_reference_item,
            parent_item=ref_group,
        )
        if ref_first:
            ref_group.setExpanded(True)

    def _make_document_child_item(self, key: str) -> QTreeWidgetItem:
        if key == _REF_GROUP_KEY:
            group = QTreeWidgetItem(["参考图层"])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            return group
        item = QTreeWidgetItem(["", ""])
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsSelectable
        )
        return item

    def _update_document_child_item(self, item: QTreeWidgetItem, key: str) -> None:
        if key == _REF_GROUP_KEY:
            if item.text(0) != "参考图层":
                item.setText(0, "参考图层")
            return
        layer_key = key.split(":", 1)[1]
        label = LAYER_LABELS[layer_key]
        if item.text(0) != label:
            item.setText(0, label)
        item.setData(0, Qt.ItemDataRole.UserRole, ("layer", layer_key))
        visible = self._layer_visible.get(layer_key, True)
        item.setCheckState(
            0, Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
        )
        lock_mark = "⊘" if self._layer_locked.get(layer_key, False) else ""
        if item.text(1) != lock_mark:
            item.setText(1, lock_mark)

    def _make_reference_item(self, key: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(["", ""])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return item

    def _update_reference_item(self, item: QTreeWidgetItem, key: str) -> None:
        layer = next(
            (
                ref
                for ref in (getattr(self._populated_document, "reference_layers", []) or [])
                if _reference_layer_key(ref) == key
            ),
            None,
        )
        name = getattr(layer, "name", "未命名参考图层") if layer is not None else "未命名参考图层"
        status = getattr(layer, "status", "") if layer is not None else ""

        if status == "offline":
            name = f"{name} (离线)"
        elif status == "failed":
            name = f"{name} (失败)"
        if item.text(0) != name:
            item.setText(0, name)
        item.setData(0, Qt.ItemDataRole.UserRole, ("reference_layer", layer))

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
