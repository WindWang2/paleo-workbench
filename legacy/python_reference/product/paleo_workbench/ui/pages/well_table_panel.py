"""WellTable viewer for the preparation page (ISS-PREP-01).

V11 Model/View 迁移（goal §8 / 01-ui-audit D2 ①）：井点表是 rank-1 的
item-per-cell 风险面（11 列 × 潜在 10 万采样点行，此前每次刷新全量重建
QTableWidgetItem）。现改 ``QTableView + ObjectTableModel`` 虚拟化——
行数 = len(rows)、data() 按需取值，零 item 分配；``set_rows`` 差分重置 +
:class:`StableSelection` 跨刷新保选择；QC 着色经 ``ColumnSpec.foreground_role``
返回 token 名（主题切换后 :meth:`ObjectTableModel.refresh_display` 重取）。
表格外观统一走全局 QSS + :func:`bind_table_defaults`（不再页内重述）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from paleo_workbench.ui import style, tokens
from paleo_workbench.ui.components.states import PwbEmptyState
from paleo_workbench.ui.modelview import (
    ColumnSpec,
    ObjectTableModel,
    StableSelection,
    bind_table_defaults,
)

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

# qc_flag → 前景 token 名（ObjectTableModel 经 style.palette 取色，
# 主题切换后由 refresh_display 重取；不再页内缓存 QColor）。
_QC_TOKENS = {
    "ok": "SUCCESS",
    "outlier": "WARNING",
    "invalid_ratio": "ERROR_RED",
    "missing": "TEXT_SECONDARY",
}


class _WellTableView(QTableView):
    """QTableView + 兼容访问器（差分测试沿用 QTableWidget 的 rowCount()）。"""

    def rowCount(self) -> int:  # noqa: N802
        model = self.model()
        return 0 if model is None else model.rowCount()


def _numeric(field: str):
    def value(row) -> str:
        return _fmt(getattr(row, field, None))

    return value


def _qc_flag(row) -> str:
    return str(getattr(row, "qc_flag", "ok") or "ok")


def _qc_token(row) -> str | None:
    return _QC_TOKENS.get(_qc_flag(row))


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
        self.summary_label.setObjectName("WorkstationPanelFootnote")
        header.addWidget(self.summary_label)
        self.run_qc_btn = QPushButton("运行 MAD/砂地比 QC")
        self.run_qc_btn.setObjectName("SecondaryButton")
        style.track_control_height(self.run_qc_btn)
        self.run_qc_btn.setToolTip("对当前井点表执行砂地比约束与 MAD 异常检测")
        header.addWidget(self.run_qc_btn)
        outer.addLayout(header)

        self._model = ObjectTableModel(
            columns=[
                ColumnSpec("name", "井名", lambda row: str(getattr(row, "name", "") or "")),
                ColumnSpec("x", "X", _numeric("x")),
                ColumnSpec("y", "Y", _numeric("y")),
                ColumnSpec("z", "Z", _numeric("z")),
                ColumnSpec("H_s", "Hs", _numeric("H_s")),
                ColumnSpec("H_t", "Ht", _numeric("H_t")),
                ColumnSpec("R_s", "Rs", _numeric("R_s")),
                ColumnSpec("q", "q", _numeric("q")),
                ColumnSpec("b_i", "b", _numeric("b_i")),
                ColumnSpec("qc_flag", "QC", _qc_flag, foreground_role=_qc_token),
                ColumnSpec("qc_z_star", "z*", _numeric("qc_z_star")),
            ],
            key_of=lambda row: str(getattr(row, "well_id", "") or id(row)),
            parent=self,
        )
        self.table = _WellTableView()
        self.table.setObjectName("WellTableGrid")
        self.table.setModel(self._model)
        bind_table_defaults(self.table)
        outer.addWidget(self.table, 1)

        self.empty_label = PwbEmptyState(
            "暂无井点",
            "从单因素 sample_points 或工程 well_tables 同步。",
            parent=self,
        )
        outer.addWidget(self.empty_label)

        self._selection = StableSelection(self.table)

    def update_from_well_table(self, well_table) -> None:
        """Render *well_table* rows (or clear when None)."""
        if well_table is None or not getattr(well_table, "rows", None):
            self._table_id = None
            self.title_label.setText("井点表 WellTable")
            self.summary_label.setText("0 行")
            self._model.set_rows([])
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
        # 跨刷新保选择：差分 set_rows 前按稳定键捕获，行集未变时连
        # dataChanged 之外的选择信号都不会抖动。
        selected_keys = self._selection.capture()
        self._model.set_rows(rows)
        self._selection.restore(selected_keys)

        flag_counts: dict[str, int] = {}
        for row in rows:
            flag = _qc_flag(row)
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

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
