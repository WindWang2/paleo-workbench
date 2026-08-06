"""Virtualized table projection for single-well Display Set (T4 / #344, ADR 0022).

On-demand cell access only — never materializes a full-length wide float grid
for the screen path. Columns = Depth + checked curve leaves (shared depth axis).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from well_log_workstation.display_set import (
    StyledTrackDescriptor,
    compose,
    leaves_from_document,
)
from well_log_workstation.las_import import ImportedCurve, ImportedWellDocument
from well_log_workstation.template_model import PlotTemplate

# Soft product tip threshold (incl. Depth column) — design §8 / #337.
SOFT_COLUMN_TIP_THRESHOLD = 64


@dataclass(frozen=True, slots=True)
class CurveColumn:
    """One curve column: identity + array views (no copy)."""

    leaf_id: str
    mnemonic: str
    title: str
    values: np.ndarray
    null_mask: np.ndarray


@dataclass(frozen=True, slots=True)
class TableProjection:
    """Logical table on one sampling axis (first-ship: document MD)."""

    axis_id: str
    depth: np.ndarray
    depth_unit: str
    columns: tuple[CurveColumn, ...]

    @property
    def row_count(self) -> int:
        return int(self.depth.size)

    @property
    def column_count(self) -> int:
        """Depth + curve columns."""
        return 1 + len(self.columns)

    @property
    def needs_soft_column_tip(self) -> bool:
        return self.column_count >= SOFT_COLUMN_TIP_THRESHOLD

    def header(self, section: int) -> str:
        if section <= 0:
            unit = self.depth_unit or "m"
            return f"Depth ({unit})" if unit else "Depth"
        col = self.columns[section - 1]
        return col.title or col.mnemonic

    def cell(self, row: int, col: int) -> float | None:
        """On-demand sample; None means null / missing."""
        if row < 0 or row >= self.row_count:
            return None
        if col == 0:
            v = float(self.depth[row])
            return v if np.isfinite(v) else None
        cidx = col - 1
        if cidx < 0 or cidx >= len(self.columns):
            return None
        curve = self.columns[cidx]
        if row >= curve.values.size:
            return None
        if curve.null_mask[row]:
            return None
        v = float(curve.values[row])
        return v if np.isfinite(v) else None


def build_table_projections(
    document: ImportedWellDocument,
    display_set: set[str] | frozenset[str],
    template: PlotTemplate,
) -> list[TableProjection]:
    """Build projection(s) for the Display Set.

    Same sampling axis (shared document depth) → one wide table.
    Curves whose length differs from the depth axis are placed on a **split**
    projection keyed by length (no implicit resample).
    """
    leaves = leaves_from_document(document)
    styled: list[StyledTrackDescriptor] = compose(leaves, display_set, template)
    if not styled:
        return [
            TableProjection(
                axis_id="md",
                depth=np.asarray(document.depth, dtype=np.float64),
                depth_unit=document.depth_unit or "m",
                columns=(),
            )
        ]

    # Group by value length vs depth length for split tables (ADR 0022 spirit).
    depth = np.asarray(document.depth, dtype=np.float64)
    groups: dict[int, list[CurveColumn]] = {}
    for desc in styled:
        curve = document.curve_by_mnemonic(desc.mnemonic)
        if curve is None:
            continue
        n = int(curve.values.size)
        groups.setdefault(n, []).append(
            CurveColumn(
                leaf_id=desc.leaf_id,
                mnemonic=curve.mnemonic,
                title=desc.title,
                values=curve.values,
                null_mask=curve.null_mask,
            )
        )

    if not groups:
        return [
            TableProjection(
                axis_id="md",
                depth=depth,
                depth_unit=document.depth_unit or "m",
                columns=(),
            )
        ]

    out: list[TableProjection] = []
    for n, cols in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if n == depth.size:
            axis_depth = depth
            axis_id = "md"
        else:
            # Independent index axis — no resample onto MD
            axis_depth = np.arange(n, dtype=np.float64)
            axis_id = f"len-{n}"
        out.append(
            TableProjection(
                axis_id=axis_id,
                depth=axis_depth,
                depth_unit=document.depth_unit or "m" if n == depth.size else "idx",
                columns=tuple(cols),
            )
        )
    return out


class LogTableModel(QAbstractTableModel):
    """Qt model over a TableProjection — virtualized via data() only."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proj: TableProjection | None = None

    def set_projection(self, projection: TableProjection | None) -> None:
        self.beginResetModel()
        self._proj = projection
        self.endResetModel()

    def projection(self) -> TableProjection | None:
        return self._proj

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._proj is None:
            return 0
        return self._proj.row_count

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._proj is None:
            return 0
        return self._proj.column_count

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or self._proj is None:
            return None
        if role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.EditRole,
        ):
            return None
        val = self._proj.cell(index.row(), index.column())
        if val is None:
            return "" if role == Qt.ItemDataRole.DisplayRole else None
        if index.column() == 0:
            return f"{val:.4f}" if role == Qt.ItemDataRole.DisplayRole else val
        return f"{val:.4g}" if role == Qt.ItemDataRole.DisplayRole else val

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or self._proj is None:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._proj.header(section)
        return str(section + 1)

    def materialize_full_grid(self) -> np.ndarray:
        """Test-only helper — must not be used by the UI hot path.

        Allocates a dense grid for contract tests that assert the model itself
        does not keep such a buffer as state.
        """
        if self._proj is None:
            return np.zeros((0, 0), dtype=np.float64)
        r, c = self._proj.row_count, self._proj.column_count
        grid = np.full((r, c), np.nan, dtype=np.float64)
        for i in range(r):
            for j in range(c):
                v = self._proj.cell(i, j)
                if v is not None:
                    grid[i, j] = v
        return grid
