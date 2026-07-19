from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from paleo_workbench.ui import tokens


_ATTRIBUTE_GROUPS = (
    ("振幅属性", ("振幅", "包络", "RMS振幅")),
    ("频率属性", ("瞬时频率",)),
    ("连续性属性", ("甜点",)),
    ("结构属性", ("瞬时相位",)),
)


class SeismicAttributePanel(QFrame):
    """Reference-style seismic attribute selector without new analysis logic."""

    attribute_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicAttributePanel")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("地震属性")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.attribute_tree = QTreeWidget()
        self.attribute_tree.setObjectName("WorkListWidget")
        self.attribute_tree.setHeaderHidden(True)
        self._populate_tree()
        self.attribute_tree.expandAll()
        self.attribute_tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.attribute_tree, 1)

    def _populate_tree(self) -> None:
        for group_label, labels in _ATTRIBUTE_GROUPS:
            group = QTreeWidgetItem([group_label])
            for label in labels:
                group.addChild(QTreeWidgetItem([label]))
            self.attribute_tree.addTopLevelItem(group)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.childCount() == 0:
            self.attribute_changed.emit(item.text(0))

    def set_selected_attribute(self, label: str) -> None:
        """Synchronize the visual selection without triggering a new request."""
        target = str(label or "").strip()
        for group_index in range(self.attribute_tree.topLevelItemCount()):
            group = self.attribute_tree.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.text(0) == target:
                    self.attribute_tree.setCurrentItem(child)
                    return

    def selected_attribute(self) -> str:
        item = self.attribute_tree.currentItem()
        if item is not None and item.childCount() == 0:
            return item.text(0)
        return "振幅"
