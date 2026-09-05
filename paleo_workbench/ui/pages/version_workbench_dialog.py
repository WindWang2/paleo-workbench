"""VersionWorkbenchDialog — single-asset version timeline workbench (D6).

Lists EVERY version of one catalog asset newest-first (版本 / 阶段 / 校验和 /
大小 / 生成 Run / 时间 / 源), with a selection-driven detail panel (metadata
pretty JSON, lineage parents, producing run details, recorded vs resolved
payload path) and the gated lifecycle actions 提升为正式数据 / 打开位置 /
对比元数据 / 删除版本 / 还原版本.

All reads and writes go through :class:`~paleo_workbench.catalog.service.
DataCatalogService` — never SQLite or payload files directly. Committed
DataVersions are immutable: promote copies to a NEW OUTPUT version and
trash/restore only flip the tombstone, always via the service. Single-asset
reads are small, so calls run synchronously on the GUI thread and NOTHING is
cached across mutations — the timeline is reloaded from the service after
every successful action and :attr:`versions_changed` is emitted.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.catalog.models import CatalogError, DataStage, DataVersion
from paleo_workbench.ui import tokens

_STAGE_DISPLAY = {
    DataStage.RAW: "RAW",
    DataStage.DERIVED: "DERIVED",
    DataStage.INTERMEDIATE: "INTERMEDIATE",
    DataStage.OUTPUT: "OUTPUT",
}

_TRASHED_STAGE_DISPLAY = "已删除"

_MISSING = "—"


def _stage_display(version: DataVersion) -> str:
    """Timeline 阶段 cell: lifecycle stage, or 已删除 for trashed versions."""
    if version.trashed:
        return _TRASHED_STAGE_DISPLAY
    return _STAGE_DISPLAY.get(DataStage(version.stage), str(version.stage))


def _checksum_display(sha256: str | None) -> str:
    return sha256[:12] if sha256 else _MISSING


def _short_id(value: str | None, keep: int = 12) -> str:
    """Shortened entity id for dense table cells (run ids etc.)."""
    if not value:
        return _MISSING
    return value if len(value) <= keep else value[:keep]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _value_display(value: Any) -> str:
    if value is None:
        return _MISSING
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class _VersionCompareDialog(QDialog):
    """Two-version field/metadata diff (D6 对比元数据). Strictly read-only."""

    def __init__(self, parent=None, *, versions: tuple[DataVersion, DataVersion]) -> None:
        super().__init__(parent)
        newer, older = versions
        self.setWindowTitle(
            f"对比元数据: v{newer.version_number} ↔ v{older.version_number}"
        )
        self.resize(720, 440)

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["字段", f"v{newer.version_number}", f"v{older.version_number}", "结果"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        rows: list[tuple[str, str, str]] = [
            ("阶段", _stage_display(newer), _stage_display(older)),
            (
                "大小",
                str(tokens.format_size(newer.size_bytes)),
                str(tokens.format_size(older.size_bytes)),
            ),
            ("校验和", newer.sha256 or _MISSING, older.sha256 or _MISSING),
            ("格式", newer.format or _MISSING, older.format or _MISSING),
            ("创建时间", newer.created_at[:19], older.created_at[:19]),
            ("生成 Run", _short_id(newer.run_id), _short_id(older.run_id)),
        ]
        for key in sorted(set(newer.metadata) | set(older.metadata)):
            rows.append(
                (
                    f"元数据 · {key}",
                    _value_display(newer.metadata.get(key)),
                    _value_display(older.metadata.get(key)),
                )
            )
        for label, left, right in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(label))
            self.table.setItem(row, 1, QTableWidgetItem(left))
            self.table.setItem(row, 2, QTableWidgetItem(right))
            marker = QTableWidgetItem("同" if left == right else "异")
            if left != right:
                marker.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 3, marker)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)


class VersionWorkbenchDialog(QDialog):
    """版本工作台: version timeline + detail + lifecycle actions for ONE asset."""

    # Emitted after every successful service mutation (promote/trash/restore)
    # so the host page can refresh its own views.
    versions_changed = Signal()

    def __init__(
        self,
        parent=None,
        *,
        service_provider: Callable,
        asset_id: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("版本工作台 (Version Workbench)")
        self.resize(940, 640)
        self._service_provider = service_provider
        self._asset_id = asset_id
        # Parallel to the table rows; rebuilt wholesale by reload_versions().
        self._versions: list[DataVersion] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        # -- header: asset identity + current pointer + total count -----------
        header = QHBoxLayout()
        self.header_label = QLabel("版本工作台")
        self.header_label.setWordWrap(True)
        self.header_label.setStyleSheet(
            f"font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
            f" color: {tokens.TEXT_PRIMARY};"
        )
        header.addWidget(self.header_label, 1)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        header.addWidget(self.count_label)
        layout.addLayout(header)

        # -- version timeline (newest first) ----------------------------------
        self.versions_table = QTableWidget(0, 7)
        self.versions_table.setHorizontalHeaderLabels(
            ["版本", "阶段", "校验和", "大小", "生成 Run", "时间", "源"]
        )
        self.versions_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.versions_table.horizontalHeader().setStretchLastSection(True)
        self.versions_table.verticalHeader().setVisible(False)
        self.versions_table.verticalHeader().setDefaultSectionSize(28)
        self.versions_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        # ExtendedSelection: exactly-two selection gates 对比元数据.
        self.versions_table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection
        )
        self.versions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.versions_table.setAlternatingRowColors(True)
        self.versions_table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.versions_table, 1)

        # -- detail panel ------------------------------------------------------
        self.detail_title_label = QLabel("版本详情")
        self.detail_title_label.setStyleSheet(
            f"font-weight: 600; color: {tokens.TEXT_PRIMARY};"
        )
        layout.addWidget(self.detail_title_label)

        self.detail_parents_label = QLabel("父版本: —")
        self.detail_parents_label.setWordWrap(True)
        layout.addWidget(self.detail_parents_label)

        self.detail_run_label = QLabel("生成 Run: —")
        self.detail_run_label.setWordWrap(True)
        layout.addWidget(self.detail_run_label)

        run_params_caption = QLabel("Run 参数:")
        run_params_caption.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        layout.addWidget(run_params_caption)
        self.detail_run_params = QPlainTextEdit()
        self.detail_run_params.setReadOnly(True)
        self.detail_run_params.setMaximumHeight(72)
        self.detail_run_params.setStyleSheet(
            f"font-family: {tokens.FONT_FAMILY_MONO};"
            f" font-size: {tokens.FONT_SIZE_STATUS};"
        )
        self.detail_run_params.setPlaceholderText("—")
        layout.addWidget(self.detail_run_params)

        self.detail_path_label = QLabel("记录路径: —")
        self.detail_path_label.setWordWrap(True)
        layout.addWidget(self.detail_path_label)

        self.detail_resolved_label = QLabel("解析位置: —")
        self.detail_resolved_label.setWordWrap(True)
        layout.addWidget(self.detail_resolved_label)

        meta_caption = QLabel("元数据 (JSON):")
        meta_caption.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        layout.addWidget(meta_caption)
        self.detail_meta_text = QPlainTextEdit()
        self.detail_meta_text.setReadOnly(True)
        self.detail_meta_text.setStyleSheet(
            f"font-family: {tokens.FONT_FAMILY_MONO};"
            f" font-size: {tokens.FONT_SIZE_STATUS};"
        )
        layout.addWidget(self.detail_meta_text, 1)

        # -- actions -----------------------------------------------------------
        buttons = QHBoxLayout()
        self.promote_btn = QPushButton("提升为正式数据…")
        self.promote_btn.setObjectName("SecondaryButton")
        self.promote_btn.setToolTip("将选中版本复制为新的不可变正式成果 (OUTPUT) 版本")
        self.promote_btn.clicked.connect(self._on_promote_clicked)
        buttons.addWidget(self.promote_btn)

        self.open_btn = QPushButton("打开位置")
        self.open_btn.setObjectName("SecondaryButton")
        self.open_btn.setToolTip("在文件管理器中打开版本载荷所在目录")
        self.open_btn.clicked.connect(self._on_open_clicked)
        buttons.addWidget(self.open_btn)

        self.compare_btn = QPushButton("对比元数据")
        self.compare_btn.setObjectName("SecondaryButton")
        self.compare_btn.setToolTip("按住 Ctrl 选择恰好两个版本后对比")
        self.compare_btn.clicked.connect(self._on_compare_clicked)
        buttons.addWidget(self.compare_btn)

        self.trash_btn = QPushButton("删除版本")
        self.trash_btn.setObjectName("SecondaryButton")
        self.trash_btn.clicked.connect(self._on_trash_clicked)
        buttons.addWidget(self.trash_btn)

        self.restore_btn = QPushButton("还原版本")
        self.restore_btn.setObjectName("SecondaryButton")
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        buttons.addWidget(self.restore_btn)

        buttons.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self.reload_versions()

    # -- data loading ----------------------------------------------------------

    def reload_versions(self) -> None:
        """Re-read asset + versions from the service (cache nothing)."""
        service = self._service_provider()
        if service is None:
            self.header_label.setText("未连接数据目录（请先打开项目）")
            self.count_label.setText("")
            self._versions = []
            self.versions_table.setRowCount(0)
            self._show_detail(None)
            self._sync_action_buttons()
            return
        asset = service.get_asset(self._asset_id)
        # list_versions returns ascending version_number; the timeline is
        # newest-first.
        self._versions = list(reversed(service.list_versions(self._asset_id)))
        current = next(
            (v for v in self._versions if v.id == asset.current_version_id), None
        )
        current_text = f"v{current.version_number}" if current is not None else _MISSING
        self.header_label.setText(
            f"{asset.name} · {asset.type} · 当前 {current_text}"
        )
        self.count_label.setText(f"共 {len(self._versions)} 个版本")

        self.versions_table.setRowCount(len(self._versions))
        for row, version in enumerate(self._versions):
            is_current = version.id == asset.current_version_id
            cells = [
                f"v{version.version_number}" + ("（当前）" if is_current else ""),
                _stage_display(version),
                _checksum_display(version.sha256),
                str(tokens.format_size(version.size_bytes)),
                _short_id(version.run_id),
                version.created_at[:19],
                "托管" if version.managed else "外部",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, version.id)
                if version.trashed:
                    item.setForeground(Qt.GlobalColor.gray)
                self.versions_table.setItem(row, col, item)

        self.versions_table.clearSelection()
        self._show_detail(None)
        self._sync_action_buttons()

    # -- selection -------------------------------------------------------------

    def _selected_rows(self) -> list[int]:
        return sorted(
            {
                index.row()
                for index in self.versions_table.selectionModel().selectedIndexes()
            }
        )

    def _single_selection(self) -> DataVersion | None:
        rows = self._selected_rows()
        if len(rows) != 1:
            return None
        return self._versions[rows[0]]

    def _on_selection_changed(self) -> None:
        rows = self._selected_rows()
        self._show_detail(self._versions[rows[0]] if len(rows) == 1 else None)
        self._sync_action_buttons()

    def _sync_action_buttons(self) -> None:
        rows = self._selected_rows()
        version = self._versions[rows[0]] if len(rows) == 1 else None
        has_single = version is not None
        self.promote_btn.setEnabled(has_single and not version.trashed)
        self.trash_btn.setEnabled(has_single and not version.trashed)
        self.restore_btn.setEnabled(has_single and version.trashed)
        self.compare_btn.setEnabled(len(rows) == 2)
        payload_exists = False
        if has_single:
            service = self._service_provider()
            if service is not None:
                payload_exists = service.resolve_path(version).is_file()
        self.open_btn.setEnabled(has_single and payload_exists)

    # -- detail rendering --------------------------------------------------------

    def _show_detail(self, version: DataVersion | None) -> None:
        if version is None:
            self.detail_title_label.setText("版本详情")
            self.detail_parents_label.setText("父版本: —")
            self.detail_run_label.setText("生成 Run: —")
            self.detail_run_params.setPlainText("")
            self.detail_path_label.setText("记录路径: —")
            self.detail_resolved_label.setText("解析位置: —")
            self.detail_meta_text.setPlainText("")
            return
        service = self._service_provider()
        parents: list[DataVersion] = []
        run = None
        resolved = None
        if service is not None:
            lineage = service.get_lineage(version.id)
            parents = list(lineage["parents"])
            run = lineage["run"]
            resolved = service.resolve_path(version)

        self.detail_title_label.setText(
            f"版本详情 · v{version.version_number} ({version.id})"
        )
        self.detail_parents_label.setText(
            "父版本: "
            + (", ".join(parent.id for parent in parents) if parents else _MISSING)
        )
        if run is not None:
            self.detail_run_label.setText(
                f"生成 Run: {run.operation} · 状态 {run.status or _MISSING}"
                f" · generator {run.generator or _MISSING}"
                f" · {run.created_at[:19]}"
            )
            self.detail_run_params.setPlainText(_json_text(run.parameters))
        else:
            self.detail_run_label.setText("生成 Run: —")
            self.detail_run_params.setPlainText("")
        self.detail_path_label.setText("记录路径: " + (version.path or _MISSING))
        if resolved is not None and resolved.is_file():
            self.detail_resolved_label.setText(f"解析位置: {resolved}")
        else:
            self.detail_resolved_label.setText("解析位置: 源文件缺失")
        self.detail_meta_text.setPlainText(_json_text(version.metadata))

    # -- actions -----------------------------------------------------------------

    def _confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _finish_mutation(self) -> None:
        """Reload from the service, then announce the change to the host."""
        self.reload_versions()
        self.versions_changed.emit()

    def _on_promote_clicked(self) -> None:
        version = self._single_selection()
        service = self._service_provider()
        if version is None or version.trashed or service is None:
            return
        if not self._confirm(
            "提升为正式数据",
            f"将 v{version.version_number} 复制为新的不可变正式成果 (OUTPUT) 版本？"
            "（源版本保持不变以保留溯源）",
        ):
            return
        try:
            service.promote_version(version.id)
        except CatalogError as exc:
            QMessageBox.critical(self, "提升失败", f"提升版本失败: {exc}")
            return
        self._finish_mutation()

    def _on_open_clicked(self) -> None:
        version = self._single_selection()
        service = self._service_provider()
        if version is None or service is None:
            return
        resolved = service.resolve_path(version)
        if not resolved.is_file():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved.parent)))

    def _on_compare_clicked(self) -> None:
        rows = self._selected_rows()
        if len(rows) != 2:
            return
        # Rows are newest-first, so the lower row index is the newer version.
        compare = _VersionCompareDialog(
            self, versions=(self._versions[rows[0]], self._versions[rows[1]])
        )
        compare.exec()

    def _on_trash_clicked(self) -> None:
        version = self._single_selection()
        service = self._service_provider()
        if version is None or version.trashed or service is None:
            return
        if not self._confirm(
            "删除版本",
            f"将 v{version.version_number} 移入回收站？载荷将移入 trash/，"
            "可随时在版本工作台还原。",
        ):
            return
        try:
            service.trash_version(version.id, reason="版本工作台删除")
        except CatalogError as exc:
            QMessageBox.critical(self, "删除失败", f"删除版本失败: {exc}")
            return
        self._finish_mutation()

    def _on_restore_clicked(self) -> None:
        version = self._single_selection()
        service = self._service_provider()
        if version is None or not version.trashed or service is None:
            return
        if not self._confirm(
            "还原版本", f"将 v{version.version_number} 从回收站还原？"
        ):
            return
        try:
            service.restore_version(version.id)
        except CatalogError as exc:
            QMessageBox.critical(self, "还原失败", f"还原版本失败: {exc}")
            return
        self._finish_mutation()
