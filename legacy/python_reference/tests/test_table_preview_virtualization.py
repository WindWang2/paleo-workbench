"""#1039 — virtualized table preview.

The legacy ``QTableWidget`` materialized one ``QTableWidgetItem`` per cell on
the GUI thread (settings allow 2,000×200 = 400k cells; the 50k-cell cap still
allowed 50,000 widget allocations), freezing the window on large previews.
These tests pin the ``QTableView`` + ``QAbstractTableModel`` contract:

* 100,000-row previews load fast with zero per-cell item allocation,
* display/formatting data is produced lazily by the model,
* copy-visible and copy-selection still work,
* the truncation contract is preserved unchanged.
"""

from __future__ import annotations

import time

import pytest

from PySide6.QtCore import Qt

from paleo_workbench.ui.pages.table_preview_widget import (
    MAX_PREVIEW_CELLS,
    TablePreviewModel,
    TablePreviewWidget,
)


def _make_rows(n: int, cols: int = 5):
    return tuple(
        tuple(f"{r}-{c}" for c in range(cols)) for r in range(n)
    )


def test_widget_is_a_view_with_virtual_model(qtbot):
    widget = TablePreviewWidget()
    qtbot.addWidget(widget)
    from PySide6.QtWidgets import QTableView, QTableWidget

    assert isinstance(widget, QTableView)
    assert not isinstance(widget, QTableWidget)
    assert isinstance(widget.model(), TablePreviewModel)


def test_100k_rows_load_without_item_allocation(qtbot):
    widget = TablePreviewWidget()
    qtbot.addWidget(widget)

    headers = tuple(f"COL{i}" for i in range(5))
    rows = _make_rows(100_000)

    start = time.perf_counter()
    widget.load_table(headers, rows)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert widget.model().rowCount() == 100_000
    assert elapsed_ms < 1_500, f"load_table took {elapsed_ms:.0f} ms for 100k rows"
    # zero per-cell materialization: the model references the caller's row
    # tuples directly (an eager QTableWidget implementation necessarily
    # allocates one QTableWidgetItem per cell during this same call)
    assert widget.model()._rows is rows


def test_model_data_is_lazy_and_formatted(qtbot):
    model = TablePreviewModel()
    model.set_table(
        ("DEPT", "GR", "REMARK"),
        (("1000.0", "45.5", "sand"), ("1100.0", "NaN", "shale")),
    )
    assert model.rowCount() == 2
    assert model.columnCount() == 3

    index = model.index(0, 0)
    assert index.data(Qt.ItemDataRole.DisplayRole) == "1000.0"
    # depth column: bold font + right aligned + tinted background
    assert index.data(Qt.ItemDataRole.FontRole).bold()
    assert index.data(Qt.ItemDataRole.TextAlignmentRole) == int(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    assert index.data(Qt.ItemDataRole.BackgroundRole) is not None

    # numeric column: right aligned, monospace
    numeric = model.index(0, 1)
    assert numeric.data(Qt.ItemDataRole.TextAlignmentRole) == int(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    assert numeric.data(Qt.ItemDataRole.FontRole).family() == "Cascadia Code"

    # NaN keeps its gray-disabled foreground
    nan_cell = model.index(1, 1)
    assert nan_cell.data(Qt.ItemDataRole.ForegroundRole) is not None
    assert nan_cell.data(Qt.ItemDataRole.DisplayRole) == "NaN"

    # text column: no numeric alignment imposed
    text_cell = model.index(0, 2)
    assert text_cell.data(Qt.ItemDataRole.TextAlignmentRole) is None


def test_curve_definition_columns_format(qtbot):
    model = TablePreviewModel()
    model.set_table(
        ("曲线", "单位", "最小值", "最大值"),
        (("GR", "API", "0", "200"),),
    )
    tag = model.index(0, 0)
    assert tag.data(Qt.ItemDataRole.FontRole).bold()
    assert tag.data(Qt.ItemDataRole.TextAlignmentRole) == int(
        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
    )
    unit = model.index(0, 1)
    assert unit.data(Qt.ItemDataRole.FontRole) is not None


def test_header_data_vertical_numbers_rows(qtbot):
    model = TablePreviewModel()
    model.set_table(("A", "B"), (("x", "y"), ("z", "w")))
    assert model.headerData(0, Qt.Orientation.Horizontal) == "A"
    assert model.headerData(1, Qt.Orientation.Vertical) == "2"


def test_copy_all_includes_headers_and_all_visible_rows(qtbot):
    widget = TablePreviewWidget()
    qtbot.addWidget(widget)
    widget.load_table(("A", "B"), (("1", "2"), ("3", "4")))

    text = widget.copy_all()
    assert text == "A\tB\n1\t2\n3\t4"


def test_truncation_contract_preserved(qtbot):
    widget = TablePreviewWidget()
    qtbot.addWidget(widget)
    cols = 5
    total_rows = MAX_PREVIEW_CELLS // cols + 500
    widget.load_table(tuple(f"C{i}" for i in range(cols)), _make_rows(total_rows, cols))

    keep = MAX_PREVIEW_CELLS // cols
    assert widget.truncated is True
    assert widget.model().rowCount() == keep
    assert f"显示 {keep}/{total_rows} 行" in widget.truncation_message


def test_selection_copy_produces_tsv(qtbot):
    widget = TablePreviewWidget()
    qtbot.addWidget(widget)
    widget.load_table(("A", "B", "C"), _make_rows(4, 3))

    from PySide6.QtCore import QModelIndex, QItemSelectionModel

    from PySide6.QtCore import QItemSelection

    selection = QItemSelectionModel(widget.model(), widget)
    widget.setSelectionModel(selection)
    top_left = widget.model().index(0, 1)
    bottom_right = widget.model().index(1, 2)
    selection.select(
        QItemSelection(top_left, bottom_right),
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Current,
    )

    clipboard_text = {"value": None}

    from PySide6.QtWidgets import QApplication

    class _Clip:
        def setText(self, text):
            clipboard_text["value"] = text

    original = QApplication.clipboard
    QApplication.clipboard = staticmethod(lambda: _Clip())  # type: ignore[assignment]
    try:
        from PySide6.QtGui import QKeySequence
        from PySide6.QtCore import QEvent

        event = QEvent(QEvent.Type.KeyPress)
        # use a real QKeyEvent for the copy path
        from PySide6.QtGui import QKeyEvent

        key_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier,
            "c",
        )
        widget.keyPressEvent(key_event)
    finally:
        QApplication.clipboard = original  # type: ignore[assignment]

    assert clipboard_text["value"] == "0-1\t0-2\n1-1\t1-2"


def test_scrolling_only_touches_visible_data(qtbot):
    """Deep scroll must not allocate per-row state (virtualized model)."""
    widget = TablePreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(600, 400)
    widget.load_table(tuple(f"C{i}" for i in range(5)), _make_rows(100_000, 5))
    widget.show()

    start = time.perf_counter()
    widget.scrollToBottom()
    qtbot.wait(50)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert widget.model().rowCount() == 100_000
    assert elapsed_ms < 1_000, f"scroll to bottom took {elapsed_ms:.0f} ms"
