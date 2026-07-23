"""WellTable viewer for the preparation page (ISS-PREP-01)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens

_COLUMNS = (
    ("name", "井名"),
    ("x", "X"),
    ("y", "Y"),
    ("z", "Z"),
    ("H_s", "Hs"),
    ("H_t", "Ht"),
    ("R_s", "Rs"),
    ("q", "q"),
    ("b_i", "b"),
    ("qc_flag", "QC"),
    ("qc_z_star", "z*"),
)

_QC_COLORS = {
    "ok": tokens.SUCCESS,
    "outlier": tokens.WARNING,
    "invalid_ratio": tokens.ERROR_RED,
    "missing": tokens.TEXT_SECONDARY,
}


class WellTablePanel(QFrame):
    """Read-only tabular view of a WellTable with QC highlighting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellTablePanel")
        self._table_id: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        outer.setSpacing(tokens.SPACE_2)

        header = QHBoxLayout()
        self.title_label = QLabel("井点表 WellTable")
        self.title_label.setObjectName("MapDockTitle")
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.summary_label = QLabel("0 行")
        self.summary_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
        )
        header.addWidget(self.summary_label)
        self.run_qc_btn = QPushButton("运行 MAD/砂地比 QC")
        self.run_qc_btn.setObjectName("SecondaryButton")
        self.run_qc_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.run_qc_btn.setToolTip("对当前井点表执行砂地比约束与 MAD 异常检测")
        header.addWidget(self.run_qc_btn)
        outer.addLayout(header)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setObjectName("WellTableGrid")
        self.table.setHorizontalHeaderLabels([c[1] for c in _COLUMNS])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {tokens.BG_SIDEBAR}; border: 1px solid {tokens.BORDER}; }}"
        )
        outer.addWidget(self.table, 1)

        self.empty_label = QLabel("暂无井点。从单因素 sample_points 或工程 well_tables 同步。")
        self.empty_label.setObjectName("EmptyStateLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.empty_label)

    def update_from_well_table(self, well_table) -> None:
        """Render *well_table* rows (or clear when None)."""
        self.table.setRowCount(0)
        if well_table is None or not getattr(well_table, "rows", None):
            self._table_id = None
            self.title_label.setText("井点表 WellTable")
            self.summary_label.setText("0 行")
            self.empty_label.show()
            self.table.hide()
            return

        self._table_id = getattr(well_table, "id", None)
        name = getattr(well_table, "name", "") or "WellTable"
        horizon = getattr(well_table, "target_horizon", "") or ""
        ftype = getattr(well_table, "factor_type", "") or ""
        parts = [name]
        if horizon:
            parts.append(horizon)
        if ftype:
            parts.append(ftype)
        self.title_label.setText(" · ".join(parts))

        rows = list(well_table.rows)
        self.table.setRowCount(len(rows))
        flag_counts: dict[str, int] = {}
        for r, row in enumerate(rows):
            values = [
                getattr(row, "name", "") or "",
                _fmt(getattr(row, "x", None)),
                _fmt(getattr(row, "y", None)),
                _fmt(getattr(row, "z", None)),
                _fmt(getattr(row, "H_s", None)),
                _fmt(getattr(row, "H_t", None)),
                _fmt(getattr(row, "R_s", None)),
                _fmt(getattr(row, "q", None)),
                _fmt(getattr(row, "b_i", None)),
                str(getattr(row, "qc_flag", "ok") or "ok"),
                _fmt(getattr(row, "qc_z_star", None)),
            ]
            flag = str(getattr(row, "qc_flag", "ok") or "ok")
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
            color = QColor(_QC_COLORS.get(flag, tokens.TEXT_PRIMARY))
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 9:  # QC column
                    item.setForeground(color)
                self.table.setItem(r, c, item)

        bits = [f"{len(rows)} 行"]
        for k in ("ok", "outlier", "invalid_ratio", "missing"):
            if flag_counts.get(k):
                bits.append(f"{k}:{flag_counts[k]}")
        self.summary_label.setText(" · ".join(bits))
        self.empty_label.hide()
        self.table.show()

    def current_table_id(self) -> str | None:
        return self._table_id


def _fmt(value) -> str:
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(f) >= 1000 or (abs(f) > 0 and abs(f) < 0.001):
        return f"{f:.4g}"
    return f"{f:.4f}".rstrip("0").rstrip(".")
