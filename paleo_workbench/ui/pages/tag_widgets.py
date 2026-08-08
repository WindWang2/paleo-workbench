"""Tag UI Components: Badges, Tag Container, and Input Dialogs for Data Manager UI 2.0.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens


class TagBadge(QWidget):
    """Interactive tag badge displaying label and optional remove ('x') button."""
    remove_requested = Signal(str)

    def __init__(self, tag_name: str, removable: bool = True, parent=None):
        super().__init__(parent)
        self.tag_name = tag_name.strip()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        self.label = QLabel(f"#{self.tag_name}")
        self.label.setStyleSheet(
            f"color: {tokens.PRIMARY}; font-size: 11px; font-weight: 500;"
        )
        layout.addWidget(self.label)

        if removable:
            self.remove_btn = QPushButton("×")
            self.remove_btn.setFixedSize(14, 14)
            self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.remove_btn.setToolTip("移除标签")
            self.remove_btn.setStyleSheet(
                f"QPushButton {{ border: none; background: transparent; color: {tokens.TEXT_SECONDARY};"
                f" font-size: 12px; font-weight: bold; padding: 0px; }}"
                f"QPushButton:hover {{ color: {tokens.ERROR_RED}; }}"
            )
            self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.tag_name))
            layout.addWidget(self.remove_btn)

        self.setStyleSheet(
            f"QWidget {{ background-color: {tokens.BG_SIDEBAR}; border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; }}"
        )


class TagContainerWidget(QWidget):
    """Displays tag badges and provides an add button."""
    tag_added = Signal(str)
    tag_removed = Signal(str)

    def __init__(self, removable: bool = True, parent=None):
        super().__init__(parent)
        self._tags: list[str] = []
        self._removable = removable

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(tokens.SPACE_1)

        self.add_btn = QPushButton("+ 标签")
        self.add_btn.setObjectName("SecondaryButton")
        self.add_btn.setToolTip("添加新标签")
        self.add_btn.setFixedHeight(22)
        self.add_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 0px 6px; border-radius: {tokens.RADIUS_BUTTON}px; }}"
        )
        self.add_btn.clicked.connect(self._prompt_add_tag)
        self._layout.addWidget(self.add_btn)

        self._layout.addStretch()

    def set_tags(self, tags: list[str]) -> None:
        self._tags = [t.strip() for t in tags if t.strip()]

        # Clear existing badges (keep add_btn and stretch)
        while self._layout.count() > 2:
            item = self._layout.takeAt(0)
            if item.widget() and item.widget() is not self.add_btn:
                item.widget().deleteLater()

        # Re-add tag badges before add_btn
        for tag in self._tags:
            badge = TagBadge(tag, removable=self._removable)
            badge.remove_requested.connect(self._on_remove_tag)
            self._layout.insertWidget(self._layout.count() - 2, badge)

    def tags(self) -> list[str]:
        return list(self._tags)

    def _on_remove_tag(self, tag_name: str) -> None:
        if tag_name in self._tags:
            self._tags.remove(tag_name)
            self.set_tags(self._tags)
            self.tag_removed.emit(tag_name)

    def _prompt_add_tag(self) -> None:
        dlg = TagInputDialog(existing_tags=self._tags, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_tag = dlg.get_tag_name()
            if new_tag and new_tag not in self._tags:
                self._tags.append(new_tag)
                self.set_tags(self._tags)
                self.tag_added.emit(new_tag)


class TagInputDialog(QDialog):
    """Dialog to input a new tag name."""

    def __init__(self, existing_tags: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加标签")
        self.setMinimumWidth(280)
        self._existing = [t.lower() for t in (existing_tags or [])]

        layout = QVBoxLayout(self)

        self.label = QLabel("请输入标签名称:")
        layout.addWidget(self.label)

        self.input = QLineEdit()
        self.input.setPlaceholderText("例如: 重点井, 探井, 2026...")
        layout.addWidget(self.input)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {tokens.ERROR_RED}; font-size: 11px;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        name = self.get_tag_name()
        if not name:
            self.error_label.setText("标签名称不能为空")
            return
        if name.lower() in self._existing:
            self.error_label.setText("该标签已存在")
            return
        self.accept()

    def get_tag_name(self) -> str:
        return self.input.text().strip().lstrip("#")
