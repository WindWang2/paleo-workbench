from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTreeView


class JsonTreePreviewWidget(QTreeView):
    """Collapsible tree view for parsed JSON/GeoJSON payloads.

    Arrays longer than ``JSON_ARRAY_COLLAPSE_THRESHOLD`` render as a single
    ``"[N items]"`` node that populates children lazily when expanded.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(False)
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["键", "值/类型"])
        self.setModel(self._model)
        self.expanded.connect(self._on_expanded)
        self.array_collapse_threshold = 100
        self.expand_depth = 2
        self._payload: object | None = None
        self._truncated = False

    def apply_settings(self, settings) -> None:
        self.array_collapse_threshold = settings.json_array_collapse_threshold
        self.expand_depth = settings.json_expand_depth
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        if self._payload is not None:
            self.load_payload(self._payload, self._truncated)

    def load_payload(self, payload: object, truncated: bool = False) -> None:
        self._payload = payload
        self._truncated = truncated
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["键", "值/类型"])
        root = self._model.invisibleRootItem()
        if isinstance(payload, dict):
            for key, value in payload.items():
                root.appendRow(self._build_row(str(key), value, depth=0))
        elif isinstance(payload, list):
            root.appendRow(self._build_row("[root]", payload, depth=0))
        else:
            root.appendRow(self._build_row("[root]", payload, depth=0))
        self._expand_initial_depth()

    # Hard cap on nesting before a deep user payload overflows the interpreter
    # stack (Python's default recursion limit is ~1000 and each level here
    # costs several frames). Deeper levels render as a placeholder node.
    _MAX_BUILD_DEPTH = 64

    def _build_row(self, key: str, value: object, *, depth: int = 0):
        key_item = QStandardItem(key)
        if depth >= self._MAX_BUILD_DEPTH:
            val_item = QStandardItem("…")
            val_item.setEditable(False)
            key_item.setEditable(False)
            return [key_item, val_item]
        if isinstance(value, dict):
            val_item = QStandardItem(f"{{object · {len(value)} keys}}")
            val_item.setEditable(False)
            for k, v in value.items():
                key_item.appendRow(self._build_row(str(k), v, depth=depth + 1))
            return [key_item, val_item]
        if isinstance(value, list):
            if len(value) > self.array_collapse_threshold:
                val_item = QStandardItem(f"[{len(value)} items]")
                val_item.setEditable(False)
                key_item.setEditable(False)
                key_item.setData(value, Qt.ItemDataRole.UserRole)
                return [key_item, val_item]
            val_item = QStandardItem(f"[list · {len(value)}]")
            val_item.setEditable(False)
            for i, v in enumerate(value):
                key_item.appendRow(self._build_row(str(i), v, depth=depth + 1))
            return [key_item, val_item]
        val_item = QStandardItem(str(value))
        val_item.setEditable(False)
        key_item.setEditable(False)
        return [key_item, val_item]

    def _expand_initial_depth(self) -> None:
        def visit(parent, depth: int) -> None:
            if depth >= self.expand_depth:
                return
            for row in range(self._model.rowCount(parent)):
                index = self._model.index(row, 0, parent)
                if self._model.hasChildren(index):
                    self.expand(index)
                    visit(index, depth + 1)

        visit(self.rootIndex(), 0)

    def _on_expanded(self, index):
        item = self._model.itemFromIndex(index)
        stored = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(stored, list) and item.rowCount() == 0:
            depth = self._index_depth(index)
            for i, v in enumerate(stored):
                item.appendRow(self._build_row(str(i), v, depth=depth + 1))

    @staticmethod
    def _index_depth(index) -> int:
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        return depth
