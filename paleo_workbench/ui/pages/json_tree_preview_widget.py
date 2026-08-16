from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTreeView

# Rows materialized per expansion step (#531): a 64 MiB payload may hold
# arrays with millions of elements, and building them in one synchronous
# loop froze the GUI for minutes. Each step is O(batch); the remaining
# items wait behind a "load next batch" sentinel the user expands.
_EXPAND_BATCH = 2000

_ROLE_CONTAINER = Qt.ItemDataRole.UserRole  # collapsed dict/list payload
_ROLE_MORE = Qt.ItemDataRole.UserRole + 1  # sentinel marker: (container, offset)


class JsonTreePreviewWidget(QTreeView):
    """Collapsible tree view for parsed JSON/GeoJSON payloads.

    Arrays longer than ``JSON_ARRAY_COLLAPSE_THRESHOLD`` (and equally large
    dicts) render as a single ``"[N items]"`` node that populates children
    lazily when expanded — in bounded batches behind a sentinel row, never
    all at once (#531).
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
        reload_needed = (
            settings.json_array_collapse_threshold != self.array_collapse_threshold
            or settings.json_expand_depth != self.expand_depth
        )
        self.array_collapse_threshold = settings.json_array_collapse_threshold
        self.expand_depth = settings.json_expand_depth
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        # Font changes apply live; only structure-affecting settings rebuild
        # the tree (each rebuild re-walks the whole payload, #531).
        if self._payload is not None and reload_needed:
            self.load_payload(self._payload, self._truncated)

    def load_payload(self, payload: object, truncated: bool = False) -> None:
        self._payload = payload
        self._truncated = truncated
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["键", "值/类型"])
        root = self._model.invisibleRootItem()
        if isinstance(payload, dict):
            if len(payload) > self.array_collapse_threshold:
                root.appendRow(self._build_row("[root]", payload, depth=0))
            else:
                for key, value in payload.items():
                    root.appendRow(self._build_row(str(key), value, depth=0))
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
            if len(value) > self.array_collapse_threshold:
                # Same hazard as huge lists: an eager dict build constructs
                # one row pair per key on the GUI thread (#531).
                val_item = QStandardItem(f"{{object · {len(value)} keys}}")
                val_item.setEditable(False)
                key_item.setEditable(False)
                key_item.setData(value, _ROLE_CONTAINER)
                return [key_item, val_item]
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
                key_item.setData(value, _ROLE_CONTAINER)
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

    @staticmethod
    def _container_items(container) -> list[tuple[str, object]]:
        if isinstance(container, dict):
            return [(str(k), v) for k, v in container.items()]
        return [(str(i), v) for i, v in enumerate(container)]

    def _append_batch(self, item, container, offset: int, depth: int) -> int:
        """Append one bounded batch of child rows; returns the new offset."""
        entries = self._container_items(container)
        batch = entries[offset : offset + _EXPAND_BATCH]
        for k, v in batch:
            item.appendRow(self._build_row(k, v, depth=depth + 1))
        return offset + len(batch)

    def _append_sentinel(self, item, container, offset: int) -> None:
        total = len(container)
        more = QStandardItem(f"… 展开加载下一批（剩余 {total - offset} 项）")
        more.setEditable(False)
        more.setData((container, offset), _ROLE_MORE)
        placeholder = QStandardItem("（点击左侧箭头加载）")
        placeholder.setEditable(False)
        more.appendRow(placeholder)
        item.appendRow([more, QStandardItem("")])

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
        if item is None:
            return
        more_state = item.data(_ROLE_MORE)
        if isinstance(more_state, tuple):
            container, offset = more_state
            parent_item = item.parent()
            if parent_item is None:
                parent_item = self._model.invisibleRootItem()
            # Materialize the next bounded batch into the CONTAINER row,
            # then move the sentinel forward (or drop it at the end).
            depth = self._index_depth(index) - 1
            new_offset = self._append_batch(parent_item, container, offset, depth)
            parent_item.removeRow(item.row())
            if new_offset < len(container):
                self._append_sentinel(parent_item, container, new_offset)
            return
        stored = item.data(_ROLE_CONTAINER)
        if isinstance(stored, (list, dict)) and item.rowCount() == 0:
            depth = self._index_depth(index)
            new_offset = self._append_batch(item, stored, 0, depth)
            if new_offset < len(stored):
                self._append_sentinel(item, stored, new_offset)

    @staticmethod
    def _index_depth(index) -> int:
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        return depth
