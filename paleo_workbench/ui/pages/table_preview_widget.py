from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QSizePolicy,
    QTableView,
)

from paleo_workbench.ui import tokens

# Defensive payload bound only: the virtualized model removed the per-cell
# widget allocation that made 50k cells the freeze threshold (#1039), so the
# cap now merely guards against pathological parser output far beyond the
# settings maximum (2,000 rows × 200 cols = 400k cells). It is NOT used to
# hide reasonably sized tables from virtualized rendering.
MAX_PREVIEW_CELLS = 1_000_000

_DEPTH_HEADERS = frozenset({"DEPT", "DEPTH", "深度"})

_MONO = QFont("Cascadia Code", 9)
_MONO_BOLD = QFont("Cascadia Code", 9)
_MONO_BOLD.setBold(True)

# Highlight brushes resolve from the ACTIVE theme palette (#1047): fixed
# light-token brushes left dark themes with unreadable tints.
_THEMED_BRUSHES: dict[str, dict[str, QBrush]] = {}


def _themed_brushes() -> dict[str, QBrush]:
    from paleo_workbench.ui.theme import theme_manager

    theme = theme_manager.current_theme.value
    cached = _THEMED_BRUSHES.get(theme)
    if cached is None:
        palette = tokens.palette_for(theme)
        cached = {
            "depth_fg": QBrush(QColor(palette["PRIMARY"])),
            "depth_bg": QBrush(QColor(palette["BG_SELECTION"])),
            "tag_fg": QBrush(QColor(palette["TEAL"])),
            "tag_bg": QBrush(QColor(palette["BG_SEARCH"])),
            "unit_fg": QBrush(QColor(palette["TEXT_SECONDARY"])),
            "nan_fg": QBrush(QColor(palette["PRIMARY_DISABLED"])),
        }
        _THEMED_BRUSHES[theme] = cached
    return cached

_ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter


class _CellRef:
    """Minimal read-only stand-in for QTableWidgetItem (legacy accessors)."""

    __slots__ = ("_text",)

    def __init__(self, text: str, _alignment) -> None:
        self._text = text

    def text(self) -> str:
        return self._text

# Column auto-fit only samples this many leading rows: resizeColumnsToContents
# walks every row, which reintroduces an O(rows × columns) pass on load.
_AUTO_FIT_SAMPLE_ROWS = 400


def _is_number(val: str) -> bool:
    if val == "NaN":
        return True
    try:
        float(val)
        return True
    except ValueError:
        return False


class TablePreviewModel(QAbstractTableModel):
    """Virtual model over detached row tuples (#1039).

    Cell text and formatting are computed on demand in ``data()`` for the
    visible viewport only — loading a 100,000-row preview allocates no
    per-cell widget or item, and scrolling never touches off-screen rows.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._headers: tuple[str, ...] = ()
        self._rows: tuple[tuple[str, ...], ...] = ()
        self._depth_column: int = -1
        self._is_curve_def: bool = False

    # -- population ---------------------------------------------------------

    def set_table(
        self,
        headers: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
    ) -> None:
        self.beginResetModel()
        self._headers = tuple(str(h) for h in headers)
        self._rows = rows
        self._depth_column = -1
        for index, header in enumerate(self._headers):
            if header.upper() in _DEPTH_HEADERS:
                self._depth_column = index
                break
        self._is_curve_def = (
            len(self._headers) >= 3 and self._headers[0] in ("曲线", "Mnemonic")
        )
        self.endResetModel()

    # -- Qt model contract --------------------------------------------------

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Orientation.Vertical and 0 <= section < len(self._rows):
            return str(section + 1)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row = index.row()
        column = index.column()
        if not (0 <= row < len(self._rows) and 0 <= column < len(self._headers)):
            return None
        raw = self._rows[row][column] if column < len(self._rows[row]) else None
        val_str = str(raw).strip() if raw is not None else ""

        if role == Qt.ItemDataRole.DisplayRole:
            return val_str

        brushes = _themed_brushes()

        # 1. Depth column (DEPT / DEPTH / 深度)
        if column == self._depth_column:
            if role == Qt.ItemDataRole.FontRole:
                return _MONO_BOLD
            if role == Qt.ItemDataRole.ForegroundRole:
                return brushes["depth_fg"]
            if role == Qt.ItemDataRole.BackgroundRole:
                return brushes["depth_bg"]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(_ALIGN_RIGHT)

        # 2. Curve mnemonic tag formatting in curve definition table
        elif self._is_curve_def and column == 0:
            if role == Qt.ItemDataRole.FontRole:
                return _MONO_BOLD
            if role == Qt.ItemDataRole.ForegroundRole:
                return brushes["tag_fg"]
            if role == Qt.ItemDataRole.BackgroundRole:
                return brushes["tag_bg"]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(_ALIGN_CENTER)

        # 3. Unit column formatting
        elif self._is_curve_def and column == 1:
            if role == Qt.ItemDataRole.FontRole:
                return _MONO
            if role == Qt.ItemDataRole.ForegroundRole:
                return brushes["unit_fg"]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(_ALIGN_CENTER)

        # 4. Numeric curve data formatting
        elif _is_number(val_str):
            if role == Qt.ItemDataRole.FontRole:
                return _MONO
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(_ALIGN_RIGHT)
            if role == Qt.ItemDataRole.ForegroundRole and val_str == "NaN":
                return brushes["nan_fg"]

        return None

    # -- programmatic access --------------------------------------------------

    def row_text(self, row: int) -> list[str]:
        """Formatted cell strings of one row (copy/export path)."""
        if not 0 <= row < len(self._rows):
            return []
        source = self._rows[row]
        return [
            (str(source[c]).strip() if c < len(source) and source[c] is not None else "")
            for c in range(len(self._headers))
        ]

    @property
    def headers(self) -> tuple[str, ...]:
        return self._headers


class TablePreviewWidget(QTableView):
    """Virtualized table preview: QTableView + TablePreviewModel (#1039).

    The legacy QTableWidget materialized one QTableWidgetItem per cell on the
    GUI thread (up to MAX_PREVIEW_CELLS), freezing the window on large
    previews. The model computes display data lazily for the viewport, so
    100,000 rows open without per-cell allocation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = TablePreviewModel(self)
        self.setModel(self._model)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.auto_fit_columns = True
        self.truncated = False
        self.truncation_message = ""

        # Alternating-row tint comes from the global themed sheet
        # (tokens.build_qss provides alternate-background-color for
        # QTableView across every palette — a widget-level light tint here
        # broke dark/high-contrast themes, #1047 review).
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setDefaultSectionSize(28)

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        self.auto_fit_columns = settings.auto_fit_columns
        mode = (
            QHeaderView.ResizeMode.ResizeToContents
            if self.auto_fit_columns
            else QHeaderView.ResizeMode.Interactive
        )
        self.horizontalHeader().setSectionResizeMode(mode)

    # -- QTableWidget-compatible accessors used by host panels -------------

    def rowCount(self) -> int:  # noqa: N802
        return self._model.rowCount()

    def columnCount(self) -> int:  # noqa: N802
        return self._model.columnCount()

    def rowHeight(self, row: int) -> int:  # noqa: N802
        return self.verticalHeader().sectionSize(row)

    def columnWidth(self, column: int) -> int:  # noqa: N802
        return self.horizontalHeader().sectionSize(column)

    def item(self, row: int, column: int):  # noqa: N802
        """Read-only on-demand cell reference (legacy accessor).

        Nothing is allocated at load or scroll time; the lightweight wrapper
        only exists for code that explicitly asks for a cell — the eager
        materialization that froze the GUI is gone (#1039).
        """
        index = self._model.index(row, column)
        if not index.isValid():
            return None
        return _CellRef(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            index.data(Qt.ItemDataRole.TextAlignmentRole),
        )

    def horizontalHeaderItem(self, column: int):  # noqa: N802
        if not 0 <= column < len(self._model.headers):
            return None
        return _CellRef(self._model.headers[column], None)

    def setRangeSelected(self, table_range, select: bool) -> None:  # noqa: N802
        """Legacy QTableWidget selection entry (range-based).

        Maps onto the view's QItemSelectionModel so copy/selection semantics
        survive the virtualization unchanged (#1039).
        """
        if not select:
            return
        from PySide6.QtCore import QItemSelection

        top_left = self._model.index(table_range.topRow(), table_range.leftColumn())
        bottom_right = self._model.index(
            table_range.bottomRow(), table_range.rightColumn()
        )
        selection_model = self.selectionModel()
        if selection_model is None:
            return
        selection_model.select(
            QItemSelection(top_left, bottom_right),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Current,
        )

    def load_table(
        self,
        headers: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
    ) -> None:
        self.truncated = False
        self.truncation_message = ""
        n_cols = len(headers)
        visible_rows = rows
        if n_cols > 0 and len(rows) * n_cols > MAX_PREVIEW_CELLS:
            keep = max(1, MAX_PREVIEW_CELLS // n_cols)
            visible_rows = rows[:keep]
            self.truncated = True
            self.truncation_message = (
                f"表格预览已截断：显示 {keep}/{len(rows)} 行"
                f"（上限 {MAX_PREVIEW_CELLS} 单元格）"
            )
        if self.truncated:
            self.setToolTip(self.truncation_message)
            self.setStatusTip(self.truncation_message)
        else:
            self.setToolTip("")
            self.setStatusTip("")
        self._model.set_table(tuple(headers), tuple(visible_rows))

        if self.auto_fit_columns:
            hdr = self.horizontalHeader()
            n_cols = self._model.columnCount()
            # Fit from a bounded SAMPLE of leading rows: Qt's
            # resizeColumnsToContents walks every row, which would reintroduce
            # the O(rows × columns) load-time pass this widget removed (#1039).
            hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            hdr.setStretchLastSection(False)
            sample_rows = [
                self._model.row_text(r)
                for r in range(min(self._model.rowCount(), _AUTO_FIT_SAMPLE_ROWS))
            ]
            metrics = self.fontMetrics()
            for col in range(n_cols):
                width = metrics.horizontalAdvance(self._model.headers[col]) + 24
                for cells in sample_rows:
                    if col < len(cells):
                        width = max(width, metrics.horizontalAdvance(cells[col]) + 24)
                hdr.resizeSection(col, max(width + 16, 75))
            hdr.setStretchLastSection(True)

    def copy_all(self) -> str:
        """返回当前显示表格的 TSV（含表头），仅复制已截断后的可见行。"""
        model = self._model
        n_cols = model.columnCount()
        if n_cols == 0:
            return ""
        headers = list(model.headers)
        lines: list[str] = ["\t".join(headers)]
        for r in range(model.rowCount()):
            lines.append("\t".join(model.row_text(r)))
        # 无数据行时仅返回表头
        if model.rowCount() == 0:
            return "\t".join(headers)
        return "\n".join(lines)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        is_copy = False
        try:
            if event.matches(QKeySequence.StandardKey.Copy):
                is_copy = True
        except Exception:
            pass
        if not is_copy and event.key() == Qt.Key.Key_C and bool(
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            is_copy = True
        if is_copy:
            indexes = self.selectedIndexes()
            if not indexes:
                event.accept()
                return
            by_row: dict[int, list[tuple[int, str]]] = {}
            for index in indexes:
                by_row.setdefault(index.row(), []).append(
                    (index.column(), str(index.data()) or "")
                )
            lines: list[str] = []
            for row in sorted(by_row):
                cells = sorted(by_row[row])
                lines.append("\t".join(text for _, text in cells))
            text = "\n".join(lines)
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(text)
            event.accept()
            return
        super().keyPressEvent(event)
