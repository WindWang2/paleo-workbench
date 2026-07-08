from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_catalog_panel import CATEGORIES


ISSUE_STATUSES = {"missing", "warning", "failed", "error"}
REFERENCE_TYPES = {"document", "image_reference", "reference_map", "well_reference"}
RESOURCE_TYPE_LABELS = {
    **tokens.RESOURCE_LABELS,
    "spreadsheet": "表格",
    "tabular": "表格",
    "time_depth": "时深",
    "horizon": "层位",
    "well_stratification": "井分层",
    "document": "文档",
    "image_reference": "影像",
    "reference_map": "参考图",
    "well_reference": "测井参考",
    "unknown": "未知",
}


@dataclass(frozen=True)
class ColumnDefinition:
    key: str
    label: str
    required: bool = False


COLUMN_DEFINITIONS = (
    ColumnDefinition("name", "文件名", required=True),
    ColumnDefinition("type", "类型"),
    ColumnDefinition("format", "格式"),
    ColumnDefinition("status", "状态"),
    ColumnDefinition("role", "角色"),
    ColumnDefinition("size", "大小"),
    ColumnDefinition("source", "来源"),
    ColumnDefinition("path", "路径"),
)
COLUMN_BY_KEY = {column.key: column for column in COLUMN_DEFINITIONS}
DEFAULT_COLUMN_KEYS = [column.key for column in COLUMN_DEFINITIONS]
HEADERS = [column.label for column in COLUMN_DEFINITIONS]


class DataAssetTable(QWidget):
    selected_asset_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataAssetTable")
        self._resources: list[ResourceItem] = []
        self._artifacts: list[ExportArtifact] = []
        self._visible_assets: list[ResourceItem | ExportArtifact] = []
        self._selected_asset: ResourceItem | ExportArtifact | None = None
        self._category = "全部"
        self._search_text = ""
        self._visible_column_keys = list(DEFAULT_COLUMN_KEYS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table = QTableWidget(0, len(self._visible_column_keys))
        self.table.setObjectName("DataAssetGrid")
        self._apply_headers()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget#DataAssetGrid {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; gridline-color: {tokens.BORDER}; }}"
        )
        self.table.itemSelectionChanged.connect(self._emit_selection)
        layout.addWidget(self.table)

    def update_assets(
        self,
        resources: list[ResourceItem],
        artifacts: list[ExportArtifact],
    ) -> None:
        self._resources = list(resources)
        self._artifacts = list(artifacts)
        self._render()

    def set_category(self, category: str) -> None:
        self._category = category
        self._render()

    def set_search_text(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._render()

    def visible_asset_count(self) -> int:
        return len(self._visible_assets)

    def visible_column_keys(self) -> list[str]:
        return list(self._visible_column_keys)

    def set_visible_columns(self, keys: list[str]) -> None:
        requested = set(keys)
        ordered = [
            column.key
            for column in COLUMN_DEFINITIONS
            if column.key in requested or column.required
        ]
        if not ordered:
            ordered = ["name"]
        self._visible_column_keys = ordered
        self._render()

    def reset_columns(self) -> None:
        self._visible_column_keys = list(DEFAULT_COLUMN_KEYS)
        self._render()

    def set_selected_asset(self, asset: ResourceItem | ExportArtifact | None) -> None:
        self._selected_asset = asset
        self._sync_selection()

    def _render(self) -> None:
        assets: list[ResourceItem | ExportArtifact] = [
            asset
            for asset in [*self._resources, *self._artifacts]
            if self._matches_category(asset) and self._matches_search(asset)
        ]
        self._visible_assets = assets
        self.table.blockSignals(True)
        self.table.setColumnCount(len(self._visible_column_keys))
        self._apply_headers()
        self.table.setRowCount(len(assets))
        for row, asset in enumerate(assets):
            values = self._row_values(asset)
            for column, key in enumerate(self._visible_column_keys):
                value = values[key]
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, asset)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

        if not self._sync_selection() and self._selected_asset is not None:
            self._selected_asset = None
            self.selected_asset_changed.emit(None)

    def _matches_category(self, asset: ResourceItem | ExportArtifact) -> bool:
        if self._category == "全部":
            return True
        if isinstance(asset, ExportArtifact):
            return self._category == "成果"

        if self._category == "输入数据":
            return (asset.artifact_role or "input") == "input"
        if self._category == "成果":
            return (asset.artifact_role or "") in {"derived", "export"}
        if self._category == "参考资料":
            return asset.type in REFERENCE_TYPES
        if self._category == "异常":
            return asset.status in ISSUE_STATUSES

        resource_type = CATEGORIES.get(self._category)
        return asset.type == resource_type

    def _matches_search(self, asset: ResourceItem | ExportArtifact) -> bool:
        if not self._search_text:
            return True
        return self._search_text in " ".join(self._search_fields(asset)).lower()

    def _search_fields(self, asset: ResourceItem | ExportArtifact) -> list[str]:
        if isinstance(asset, ExportArtifact):
            return [
                Path(asset.output_path).name,
                asset.format,
                "成果",
                asset.output_path,
                asset.linked_id,
            ]
        return [asset.name, asset.type, asset.format, asset.status, asset.source, asset.path]

    def _row_values(self, asset: ResourceItem | ExportArtifact) -> dict[str, str]:
        if isinstance(asset, ExportArtifact):
            return {
                "name": Path(asset.output_path).name,
                "type": "成果",
                "format": asset.format,
                "status": "generated",
                "role": "成果",
                "size": "—",
                "source": "export",
                "path": asset.output_path,
            }

        size = asset.parsed_summary.get("size_bytes")
        role = asset.artifact_role or "input"
        return {
            "name": asset.name,
            "type": RESOURCE_TYPE_LABELS.get(asset.type, asset.type),
            "format": asset.format,
            "status": asset.status,
            "role": self._role_label(role),
            "size": str(size) if size is not None else "—",
            "source": asset.source,
            "path": asset.path,
        }

    def _role_label(self, role: str) -> str:
        labels = {"input": "输入", "derived": "成果", "export": "成果"}
        return labels.get(role, role)

    def _apply_headers(self) -> None:
        labels = [COLUMN_BY_KEY[key].label for key in self._visible_column_keys]
        self.table.setHorizontalHeaderLabels(labels)

    def _emit_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._selected_asset = None
            self.selected_asset_changed.emit(None)
            return
        row = rows[0].row()
        asset: Any = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._selected_asset = asset
        self.selected_asset_changed.emit(asset)

    def _asset_key(self, asset: ResourceItem | ExportArtifact | None) -> tuple[str, str] | None:
        if asset is None:
            return None
        kind = "artifact" if isinstance(asset, ExportArtifact) else "resource"
        return (kind, asset.id)

    def _sync_selection(self) -> bool:
        selected_key = self._asset_key(self._selected_asset)
        selected_row = next(
            (
                row
                for row, asset in enumerate(self._visible_assets)
                if self._asset_key(asset) == selected_key
            ),
            None,
        )
        self.table.blockSignals(True)
        self.table.clearSelection()
        if selected_row is not None:
            self.table.selectRow(selected_row)
        self.table.blockSignals(False)
        return selected_row is not None
