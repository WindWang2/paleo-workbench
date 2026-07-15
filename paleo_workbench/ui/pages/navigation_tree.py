"""Left-pane smart-group tree (DEVONthink three-pane, Phase A).

A ``QTreeWidget`` with a 全部 (all) node, four group headers (输入数据/成果/
参考资料/异常) and the resource-type leaves nested under 输入数据. Selecting
a type leaf — or the 全部 node — emits :pyattr:`category_changed` with the
same category-name strings :class:`FilterIndex` consumes. Group headers are
non-selectable; selecting one only expands/collapses it and emits nothing.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.filter_index import CATEGORIES, compute_category_counts

# Top-level group headers. These carry no filter key (UserRole is None) so
# selecting them is a no-op for filtering — they only group their children.
# Flat category leaves (no group nodes). Each file is counted exactly once
# under its type, no overlap.
TYPE_LEAVES = [
    "测井", "地震", "层位", "井分层", "时深",
    "表格", "文档", "影像", "参考图", "测井参考", "未知",
]


class NavigationTree(QTreeWidget):
    category_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavigationTree")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setStyleSheet(
            f"QTreeWidget#NavigationTree {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        self.setMinimumWidth(180)
        # Programmatic setCurrentItem() (used by tests and to restore
        # selection) fires currentItemChanged, not itemClicked. Wiring the
        # handler here covers both mouse clicks and programmatic selection.
        self.currentItemChanged.connect(self._on_current_changed)
        self._build_nodes()

    def _build_nodes(self) -> None:
        all_item = QTreeWidgetItem(self, ["全部 0"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, "全部")
        for leaf in TYPE_LEAVES:
            leaf_item = QTreeWidgetItem(self, [f"{leaf} 0"])
            leaf_item.setData(0, Qt.ItemDataRole.UserRole, leaf)

    def update_counts(self, resources: list, artifacts: list) -> None:
        counts = compute_category_counts(resources, artifacts)
        for i in range(self.topLevelItemCount()):
            self._update_node_count(self.topLevelItem(i), counts)
        # QTreeWidget keeps currentItem() across setText calls, so selection
        # is preserved without explicit restoration.

    def _update_node_count(self, item: QTreeWidgetItem, counts: dict) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        label = self._label_of(item)
        count = counts.get(key, 0) if key else 0
        item.setText(0, f"{label} {count}")

    @staticmethod
    def _label_of(item: QTreeWidgetItem) -> str:
        # Labels are stored as "<label> <count>"; strip the trailing count.
        return item.text(0).rsplit(" ", 1)[0]

    def find_group(self, label: str) -> QTreeWidgetItem | None:
        """Alias for find_category_item (no group nodes anymore)."""
        return self.find_category_item(label)

    def find_category_item(self, label: str) -> QTreeWidgetItem | None:
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if self._label_of(top) == label:
                return top
        return None

    def selected_category(self) -> str:
        current = self.currentItem()
        if current is None:
            return "全部"
        key = current.data(0, Qt.ItemDataRole.UserRole)
        return key if key is not None else "全部"

    def _on_current_changed(
        self, current: QTreeWidgetItem, _previous: QTreeWidgetItem
    ) -> None:
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key is not None:
            self.category_changed.emit(key)
