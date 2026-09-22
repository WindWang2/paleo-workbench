"""Accessible Qt Widgets editor for Legacy well-log curve visibility/groups."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens
from paleo_workbench.viz.well_log_track_layout import (
    CurveGroupLimitError,
    CurveTrackLayout,
    curve_keys_for,
    default_curve_track_layout,
)

_CURVE_KEY_ROLE = Qt.ItemDataRole.UserRole


class _CurveLayoutTree(QTreeWidget):
    """Tree that interprets an internal drop as “merge this curve onto that”."""

    merge_requested = Signal(str, str)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        source_key = source.data(0, _CURVE_KEY_ROLE) if source is not None else None
        target_key = target.data(0, _CURVE_KEY_ROLE) if target is not None else None
        event.ignore()
        if source_key and target_key and source_key != target_key:
            self.merge_requested.emit(str(source_key), str(target_key))


class CurveTrackSettingsDialog(QDialog):
    """Choose visible curves and create/release up-to-three-curve groups."""

    def __init__(self, curves, layout: CurveTrackLayout | None, parent=None):
        super().__init__(parent)
        self.setObjectName("CurveTrackSettingsDialog")
        self.setWindowTitle("井道显示设置")
        self.setMinimumWidth(440)
        self._curves = tuple(curves)
        self._names = {
            key: str(getattr(curve, "name", "未命名曲线"))
            for key, curve in zip(curve_keys_for(self._curves), self._curves)
        }
        self.layout = layout or default_curve_track_layout(self._curves)
        self._rebuilding = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_3)

        help_text = QLabel(
            "默认显示 6 个井道（包含 GR）。勾选控制显示；"
            "将一条曲线拖到另一条曲线上即可合并，每组最多 3 条。"
        )
        help_text.setWordWrap(True)
        help_text.setObjectName("WorkFieldLabel")
        outer.addWidget(help_text)

        self.tree = _CurveLayoutTree()
        self.tree.setObjectName("CurveTrackSettingsTree")
        self.tree.setHeaderLabels(["井道 / 合并组", "显示"])
        self.tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.merge_requested.connect(self.merge_curve)
        outer.addWidget(self.tree, 1)

        self.status_label = QLabel("选择一条合并组后可解除合并。")
        self.status_label.setObjectName("WorkFieldValue")
        outer.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.unmerge_btn = QPushButton("解除合并")
        self.unmerge_btn.setObjectName("SecondaryButton")
        self.unmerge_btn.setToolTip("把当前合并组恢复为独立井道")
        self.unmerge_btn.clicked.connect(self._unmerge_selected)
        actions.addWidget(self.unmerge_btn)
        self.reset_btn = QPushButton("恢复默认")
        self.reset_btn.setObjectName("SecondaryButton")
        self.reset_btn.clicked.connect(self._restore_default)
        actions.addWidget(self.reset_btn)
        actions.addStretch(1)
        outer.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        self._rebuilding = True
        self.tree.clear()
        for group in self.layout.groups:
            if len(group) == 1:
                self.tree.addTopLevelItem(self._curve_item(group[0]))
                continue

            # A merged group is a real parent, never a disguised curve. Its
            # children preserve all original curve names and controls.
            group_item = QTreeWidgetItem(
                ["+".join(self._names.get(key, key) for key in group), ""]
            )
            group_item.setData(0, _CURVE_KEY_ROLE, group[0])
            group_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            for key in group:
                group_item.addChild(self._curve_item(key))
            self.tree.addTopLevelItem(group_item)
            group_item.setExpanded(True)
        self._rebuilding = False

    def _curve_item(self, key: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._names.get(key, key), ""])
        item.setData(0, _CURVE_KEY_ROLE, key)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        item.setCheckState(
            1,
            Qt.CheckState.Checked
            if key in self.layout.visible_curve_keys
            else Qt.CheckState.Unchecked,
        )
        return item

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._rebuilding or column != 1:
            return
        key = str(item.data(0, _CURVE_KEY_ROLE) or "")
        if key:
            self.layout = self.layout.with_visible(
                key, item.checkState(1) == Qt.CheckState.Checked
            )

    def merge_curve(self, curve_key: str, onto: str) -> bool:
        try:
            self.layout = self.layout.merge(curve_key, onto=onto)
        except CurveGroupLimitError as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText("已合并井道。")
        self._rebuild_tree()
        return True

    def unmerge_curve(self, curve_key: str) -> bool:
        before = self.layout.group_for(curve_key)
        self.layout = self.layout.unmerge(curve_key)
        if len(before) <= 1:
            self.status_label.setText("当前井道尚未合并。")
            return False
        self.status_label.setText("已解除合并。")
        self._rebuild_tree()
        return True

    def _unmerge_selected(self) -> None:
        item = self.tree.currentItem()
        key = str(item.data(0, _CURVE_KEY_ROLE) or "") if item is not None else ""
        if not key:
            self.status_label.setText("请选择需要解除的合并井道。")
            return
        self.unmerge_curve(key)

    def _restore_default(self) -> None:
        self.layout = default_curve_track_layout(self._curves)
        self.status_label.setText("已恢复默认 6 个井道。")
        self._rebuild_tree()
