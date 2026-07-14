from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_table_columns import (
    COLUMN_BY_KEY,
    COLUMN_TOOLTIPS,
)

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


class AssetTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._assets: list[ResourceItem | ExportArtifact] = []
        self._filtered_rows: list[int] = []
        self._column_keys: list[str] = []

    def set_column_keys(self, keys: list[str]) -> None:
        self.beginResetModel()
        self._column_keys = list(keys)
        self.endResetModel()

    def set_assets(self, assets: list[ResourceItem | ExportArtifact]) -> None:
        self.beginResetModel()
        self._assets = list(assets)
        # Default: all rows visible until filter applied
        self._filtered_rows = list(range(len(self._assets)))
        self.endResetModel()

    def set_filtered_rows(self, rows: list[int]) -> None:
        self.beginResetModel()
        self._filtered_rows = list(rows)
        self.endResetModel()

    def set_assets_filtered(
        self,
        assets: list[ResourceItem | ExportArtifact],
        rows: list[int],
        column_keys: list[str] | None = None,
    ) -> None:
        """Apply assets, filtered rows, and optional columns in one model reset."""
        self.beginResetModel()
        if column_keys is not None:
            self._column_keys = list(column_keys)
        self._assets = list(assets)
        self._filtered_rows = list(rows)
        self.endResetModel()

    def asset_at(self, view_row: int) -> ResourceItem | ExportArtifact | None:
        if view_row < 0 or view_row >= len(self._filtered_rows):
            return None
        return self._assets[self._filtered_rows[view_row]]

    def assets(self) -> list[ResourceItem | ExportArtifact]:
        return list(self._assets)

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._filtered_rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._column_keys)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if section < 0 or section >= len(self._column_keys):
                return None
            key = self._column_keys[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return COLUMN_BY_KEY[key].label
            if role == Qt.ItemDataRole.ToolTipRole:
                return COLUMN_TOOLTIPS.get(key, COLUMN_BY_KEY[key].label)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        asset = self.asset_at(index.row())
        if asset is None:
            return None
        key = self._column_keys[index.column()]
        return self._row_values(asset).get(key, "")

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

    @staticmethod
    def _role_label(role: str) -> str:
        labels = {"input": "输入", "derived": "成果", "export": "成果"}
        return labels.get(role, role)
