"""Tag UI Components: Badges, Tag Container, and Input Dialogs for Data Manager UI 2.0.

Also hosts the tag governance surfaces:

- :class:`TagManagerDialog` — tag CRUD / rename / merge / prune (F2)
- :class:`BulkAddTagDialog` / :class:`BulkRemoveTagDialog` — multi-tag bulk
  apply/remove on the asset selection (F3).
"""
from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.catalog import CatalogError
from paleo_workbench.ui import tokens

# Multi-tag input separators: whitespace (incl. TAB / U+3000) plus ASCII and
# full-width commas/semicolons.
_MULTI_TAG_SEPARATORS = re.compile(r"[,，;；\s]+")
_MAX_TAG_NAME_LENGTH = 128


def parse_multi_tag_input(text: str) -> list[str]:
    """Split a free-form multi-tag input into ordered, de-duplicated names."""
    seen: set[str] = set()
    names: list[str] = []
    for raw in _MULTI_TAG_SEPARATORS.split(text or ""):
        name = raw.strip().lstrip("#").strip()[:_MAX_TAG_NAME_LENGTH]
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


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


class BulkAddTagDialog(QDialog):
    """Dialog to add several tags at once (comma / semicolon separated)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量添加标签")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)

        self.label = QLabel("请输入标签名称（多个标签用逗号或分号分隔）:")
        layout.addWidget(self.label)

        self.input = QLineEdit()
        self.input.setPlaceholderText("例如: 重点井, 探井; 2026...")
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
        if not self.tag_names():
            self.error_label.setText("请至少输入一个有效的标签名称")
            return
        self.accept()

    def tag_names(self) -> list[str]:
        return parse_multi_tag_input(self.input.text())


class BulkRemoveTagDialog(QDialog):
    """Dialog listing the selected assets' tag union as checkable rows."""

    def __init__(self, candidate_tags: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量移除标签")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)

        self.label = QLabel("勾选要从选中数据移除的标签:")
        layout.addWidget(self.label)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(tokens.SPACE_1)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.checkboxes: list[QCheckBox] = []
        for tag in [t for t in (candidate_tags or []) if t and str(t).strip()]:
            checkbox = QCheckBox(str(tag), container)
            self.checkboxes.append(checkbox)
            container_layout.addWidget(checkbox)
        container_layout.addStretch()
        self._scroll.setWidget(container)
        layout.addWidget(self._scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("移除")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_tags(self) -> list[str]:
        return [cb.text() for cb in self.checkboxes if cb.isChecked()]


class TagManagerDialog(QDialog):
    """Tag governance dialog backed by the Core catalog service.

    Lists every tag with its Asset / Version usage counts and offers
    create / rename / merge / delete-unused / prune operations. Double-clicking
    a row emits :attr:`tag_selected` so the DataPage can filter the asset
    table by that tag ("查看关联数据").
    """

    tag_selected = Signal(str)
    tags_changed = Signal()

    _COLUMNS = ("标签", "Asset 使用数", "Version 使用数")

    def __init__(
        self,
        service_provider: Callable[[], Any] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("标签管理")
        self.setMinimumSize(480, 420)
        self._service_provider = service_provider or (lambda: None)
        self._rows: list[dict[str, Any]] = []
        self._load_error: str = ""

        layout = QVBoxLayout(self)

        self.hint_label = QLabel("未连接数据目录 — 标签管理不可用")
        self.hint_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索标签...")
        self.search_input.textChanged.connect(self._reload_table)
        search_row.addWidget(self.search_input, 1)
        layout.addLayout(search_row)

        self.table = QTableWidget(self)
        self.table.setColumnCount(len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._sync_row_actions)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        self.create_btn = QPushButton("新建")
        self.rename_btn = QPushButton("重命名")
        self.merge_btn = QPushButton("合并")
        self.delete_btn = QPushButton("删除无用")
        self.prune_btn = QPushButton("清理全部无用")
        self.refresh_btn = QPushButton("刷新")
        for btn in (
            self.create_btn,
            self.rename_btn,
            self.merge_btn,
            self.delete_btn,
            self.prune_btn,
            self.refresh_btn,
        ):
            btn.setObjectName("SecondaryButton")
            button_row.addWidget(btn)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.create_btn.clicked.connect(self._on_create)
        self.rename_btn.clicked.connect(self._on_rename)
        self.merge_btn.clicked.connect(self._on_merge)
        self.delete_btn.clicked.connect(self._on_delete_unused)
        self.prune_btn.clicked.connect(self._on_prune_unused)
        self.refresh_btn.clicked.connect(self._reload)

        self._reload()

    # --- data ------------------------------------------------------------------

    def _service(self) -> Any:
        try:
            return self._service_provider()
        except Exception:
            return None

    def _usage_rows(self) -> list[dict[str, Any]]:
        service = self._service()
        if service is None:
            return []
        error: str | None = None
        try:
            usage = service.tag_usage()
        except Exception as exc:
            # Catalog failures previously rendered as an empty table — the
            # user could not tell "no tags" from a broken catalog (#897).
            self._load_error = f"标签统计加载失败: {exc.__class__.__name__}"
            return []
        rows = [
            {
                "name": str(info.get("name", "")),
                "display_name": str(info.get("display_name") or info.get("name") or ""),
                "assets": int(info.get("assets", 0) or 0),
                "versions": int(info.get("versions", 0) or 0),
            }
            for info in usage.values()
        ]
        text = self.search_input.text().strip()
        if text:
            try:
                matched = {tag.name for tag in service.search_tags(text)}
            except Exception as exc:
                error = f"标签搜索失败: {exc.__class__.__name__}"
                matched = set()
            rows = [row for row in rows if row["name"] in matched]
        rows.sort(key=lambda row: row["display_name"].casefold())
        if error is not None:
            self._load_error = error
        return rows

    def _reload(self) -> None:
        self._reload_table()

    def _reload_table(self) -> None:
        """Refresh usage rows (honouring the search filter) and re-render."""
        has_service = self._service() is not None
        self._load_error = ""
        self._rows = self._usage_rows() if has_service else []
        if has_service and self._load_error:
            # Surface catalog failures instead of an indistinguishable
            # "no tags" table (#897); row actions stay disabled.
            self.hint_label.setText(self._load_error)
            self.hint_label.setVisible(True)
            self._rows = []
        elif not has_service:
            self.hint_label.setText("未连接数据目录 — 标签管理不可用")
            self.hint_label.setVisible(True)
        else:
            self.hint_label.setVisible(False)

        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            self.table.setItem(r, 0, QTableWidgetItem(row["display_name"]))
            self.table.setItem(r, 1, QTableWidgetItem(str(row["assets"])))
            self.table.setItem(r, 2, QTableWidgetItem(str(row["versions"])))

        for btn in (
            self.create_btn,
            self.rename_btn,
            self.merge_btn,
            self.delete_btn,
            self.prune_btn,
            self.refresh_btn,
        ):
            btn.setEnabled(has_service)
        self._sync_row_actions()

    def _current_row(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _sync_row_actions(self) -> None:
        """Row-scoped operations need a selected row (delete additionally
        refuses in-use tags at click time with a usage-count prompt)."""
        has_row = self._current_row() is not None
        for btn in (self.rename_btn, self.merge_btn, self.delete_btn):
            btn.setEnabled(has_row and self._service() is not None)

    # --- operations --------------------------------------------------------------

    def _notify_changed(self) -> None:
        self._reload()
        self.tags_changed.emit()

    def _on_create(self) -> None:
        service = self._service()
        if service is None:
            return
        existing = [row["display_name"] for row in self._rows] or [
            t.name for t in service.list_tags()
        ]
        dlg = TagInputDialog(existing_tags=existing, parent=self)
        dlg.setWindowTitle("新建标签")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.get_tag_name()
        if not name:
            return
        try:
            # Single-transaction entity create — no anchor-asset workaround.
            service.create_tag(name)
        except Exception as exc:
            QMessageBox.critical(self, "新建标签失败", f"新建标签失败: {exc}")
            return
        self._notify_changed()

    def _on_rename(self) -> None:
        service = self._service()
        row = self._current_row()
        if service is None or row is None:
            return
        old_name = row["display_name"]
        # The row may be stale (tag deleted elsewhere since the table loaded):
        # refuse up-front instead of presenting a bogus collision prompt.
        if not any(t.name == row["name"] for t in service.list_tags()):
            QMessageBox.warning(
                self, "标签不存在", f"标签 “{old_name}” 已不存在，请刷新后重试。"
            )
            self._reload()
            return
        dlg = TagInputDialog(existing_tags=[], parent=self)
        dlg.setWindowTitle("重命名标签")
        dlg.label.setText(f"将标签 “{old_name}” 重命名为:")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dlg.get_tag_name()
        if not new_name:
            return
        try:
            service.rename_tag(old_name, new_name, on_collision="error")
        except CatalogError as exc:
            if "already exists" not in str(exc):
                QMessageBox.critical(self, "重命名失败", f"重命名标签失败: {exc}")
                return
            answer = QMessageBox.question(
                self,
                "标签冲突",
                f"标签 “{new_name}” 已存在。\n是否将 “{old_name}” 合并到 “{new_name}”？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                service.rename_tag(old_name, new_name, on_collision="merge")
            except Exception as merge_exc:
                QMessageBox.critical(self, "合并失败", f"合并标签失败: {merge_exc}")
                self._notify_changed()
                return
        except Exception as exc:
            QMessageBox.critical(self, "重命名失败", f"重命名标签失败: {exc}")
            return
        self._notify_changed()

    def _on_merge(self) -> None:
        service = self._service()
        row = self._current_row()
        if service is None or row is None:
            return
        source = row["display_name"]
        targets = [r["display_name"] for r in self._rows if r["name"] != row["name"]]
        if not targets:
            QMessageBox.information(self, "合并标签", "没有其他标签可作为合并目标")
            return
        target, ok = QInputDialog.getItem(
            self,
            "合并标签",
            f"将 “{source}” 合并到:",
            targets,
            0,
            False,
        )
        if not ok or not target:
            return
        try:
            service.merge_tags(source, target)
        except Exception as exc:
            QMessageBox.critical(self, "合并失败", f"合并标签失败: {exc}")
            return
        self._notify_changed()

    def _on_delete_unused(self) -> None:
        service = self._service()
        row = self._current_row()
        if service is None or row is None:
            return
        in_use = row["assets"] + row["versions"]
        if in_use > 0:
            QMessageBox.information(
                self,
                "标签在使用中",
                f"标签 “{row['display_name']}” 仍关联 {row['assets']} 个资产、"
                f"{row['versions']} 个版本，无法删除。",
            )
            return
        try:
            service.delete_unused_tag(row["name"])
        except CatalogError as exc:
            QMessageBox.warning(self, "删除失败", f"删除标签失败: {exc}")
            return
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", f"删除标签失败: {exc}")
            return
        self._notify_changed()

    def _on_prune_unused(self) -> None:
        service = self._service()
        if service is None:
            return
        # Count from the FULL usage table, not the search-filtered rows:
        # prune_unused_tags is global, so the confirmation must match scope.
        try:
            unused_total = [
                info
                for info in service.tag_usage().values()
                if not info.get("assets") and not info.get("versions")
            ]
        except Exception as exc:
            QMessageBox.critical(self, "清理失败", f"读取标签使用情况失败: {exc}")
            return
        if not unused_total:
            QMessageBox.information(self, "清理无用标签", "没有可清理的无用标签")
            return
        answer = QMessageBox.question(
            self,
            "清理全部无用标签",
            f"将删除 {len(unused_total)} 个未使用的标签，继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = service.prune_unused_tags()
        except Exception as exc:
            QMessageBox.critical(self, "清理失败", f"清理无用标签失败: {exc}")
            return
        QMessageBox.information(self, "清理完成", f"已清理 {len(removed)} 个无用标签")
        self._notify_changed()

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._rows):
            self.tag_selected.emit(self._rows[row]["display_name"])
