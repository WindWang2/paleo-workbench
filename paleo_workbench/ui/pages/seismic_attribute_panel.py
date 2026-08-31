from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QFrame, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from paleo_workbench.seismic_attributes import available_kernels
from paleo_workbench.ui import tokens

# Kernel ids the attribute pipeline can actually compute today, with their
# user-facing labels. Anything not wired here must NOT appear as a selectable
# option — the old list advertised 17 labels with exactly 1 implementation.
_COMPUTABLE_LABELS = {
    "c3": "相干(C3)",
    "envelope": "包络",
    "rms_amplitude": "RMS振幅",
    "instantaneous_frequency": "瞬时频率",
    "instantaneous_phase": "瞬时相位",
    "sweetness": "甜点",
    "relative_impedance": "相对阻抗",
    "dip_il": "Dip_IL",
    "dip_xl": "Dip_XL",
    "dip_azimuth": "方位角",
    "curvature_mean": "平均曲率",
}

_ATTRIBUTE_GROUPS = (
    ("振幅属性", ("包络", "RMS振幅", "相对阻抗")),
    ("频率属性", ("瞬时频率", "瞬时相位", "甜点")),
    ("连续性属性", ("相干(C3)",)),
    ("构造属性", ("Dip_IL", "Dip_XL", "方位角", "平均曲率")),
    ("未实现", ("高斯曲率", "最大曲率", "RGB融合")),
)

_LABEL_TO_KERNEL = {label: kernel for kernel, label in _COMPUTABLE_LABELS.items()}


class SeismicAttributePanel(QFrame):
    """Attribute selector over the kernels the pipeline can really compute.

    Every enabled leaf maps to a wired kernel id; unimplemented reference
    labels are greyed out under an explicit 未实现 group instead of
    pretending to be options.
    """

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
        self.attribute_tree.setObjectName("SeismicAttributeTree")
        self.attribute_tree.setHeaderHidden(True)
        self._populate_tree()
        self.attribute_tree.expandAll()
        self.attribute_tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.attribute_tree, 1)

    def _populate_tree(self) -> None:
        computable = set(available_kernels())
        for group_label, labels in _ATTRIBUTE_GROUPS:
            group = QTreeWidgetItem([group_label])
            for label in labels:
                item = QTreeWidgetItem([label])
                kernel = _LABEL_TO_KERNEL.get(label)
                if kernel is None or kernel not in computable:
                    item.setDisabled(True)
                    item.setForeground(0, QBrush(QColor(tokens.TEXT_SECONDARY)))
                group.addChild(item)
            self.attribute_tree.addTopLevelItem(group)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.childCount() == 0 and not item.isDisabled():
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
