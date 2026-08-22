from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.table_preview_widget import MAX_PREVIEW_CELLS, TablePreviewWidget
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel


# ---- TablePreviewWidget.copy_all ------------------------------------------------

def test_copy_all_returns_headers_and_rows_as_tsv(qtbot):
    w = TablePreviewWidget()
    qtbot.addWidget(w)
    w.load_table(("A", "B", "C"), (("1", "2", "3"), ("4", "5", "6")))
    assert w.copy_all() == "A\tB\tC\n1\t2\t3\n4\t5\t6"


def test_copy_all_respects_truncation_only_copies_displayed(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.table_preview_widget as mod
    monkeypatch.setattr(mod, "MAX_PREVIEW_CELLS", 4)  # 2 cols => keep 2 rows max
    w = TablePreviewWidget()
    qtbot.addWidget(w)
    headers = ("X", "Y")
    rows = tuple((str(i), str(i * 10)) for i in range(10))  # 10 rows
    w.load_table(headers, rows)
    assert w.truncated is True
    assert w.rowCount() == 2  # 4 // 2 == 2
    tsv = w.copy_all()
    lines = tsv.split("\n")
    # header + 2 rows = 3 lines
    assert len(lines) == 3
    assert lines[0] == "X\tY"
    assert lines[1] == "0\t0"
    assert lines[2] == "1\t10"
    # Must not contain 3rd row
    assert "2\t20" not in tsv


def test_copy_all_empty_table(qtbot):
    w = TablePreviewWidget()
    qtbot.addWidget(w)
    w.load_table((), ())
    assert w.copy_all() == ""


# ---- TablePreviewWidget Ctrl+C ---------------------------------------------------

def test_key_press_ctrl_c_copies_selected_range_as_tsv(qtbot):
    from PySide6.QtWidgets import QTableWidgetSelectionRange

    w = TablePreviewWidget()
    qtbot.addWidget(w)
    w.load_table(("A", "B", "C"), (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9")))
    # Select a rectangular range 0,0 to 1,1
    w.setRangeSelected(QTableWidgetSelectionRange(0, 0, 1, 1), True)
    fake_clip = MagicMock()
    with patch.object(QApplication, "clipboard", return_value=fake_clip):
        ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_C, Qt.ControlModifier, "c")
        w.keyPressEvent(ev)
    fake_clip.setText.assert_called_once()
    copied = fake_clip.setText.call_args[0][0]
    assert copied == "1\t2\n4\t5"


def test_key_press_ctrl_c_sub_range_single_cell(qtbot):
    from PySide6.QtWidgets import QTableWidgetSelectionRange

    w = TablePreviewWidget()
    qtbot.addWidget(w)
    w.load_table(("A", "B"), (("a", "b"), ("c", "d")))
    w.setRangeSelected(QTableWidgetSelectionRange(0, 1, 0, 1), True)
    fake_clip = MagicMock()
    with patch.object(QApplication, "clipboard", return_value=fake_clip):
        ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_C, Qt.ControlModifier, "c")
        w.keyPressEvent(ev)
    fake_clip.setText.assert_called_once_with("b")


def test_key_press_ctrl_c_no_selection_copies_nothing(qtbot):
    w = TablePreviewWidget()
    qtbot.addWidget(w)
    w.load_table(("A", "B"), (("1", "2"),))
    # Ensure no selection
    w.clearSelection()
    fake_clip = MagicMock()
    with patch.object(QApplication, "clipboard", return_value=fake_clip):
        ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_C, Qt.ControlModifier, "c")
        w.keyPressEvent(ev)
    fake_clip.setText.assert_not_called()


def test_key_press_without_ctrl_does_not_copy(qtbot):
    from PySide6.QtWidgets import QTableWidgetSelectionRange

    w = TablePreviewWidget()
    qtbot.addWidget(w)
    w.load_table(("A", "B"), (("1", "2"),))
    w.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 1), True)
    fake_clip = MagicMock()
    with patch.object(QApplication, "clipboard", return_value=fake_clip):
        ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_C, Qt.NoModifier, "c")
        w.keyPressEvent(ev)
    fake_clip.setText.assert_not_called()


# ---- DataReaderPanel table mode copy button ------------------------------------

def test_data_reader_panel_copy_all_button_writes_clipboard(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(
        PreviewResult(
            mode="table",
            title="t.csv",
            table_headers=("H1", "H2"),
            table_rows=(("a", "b"), ("c", "d")),
        )
    )
    # Find copy button by text
    btn = None
    for b in panel.findChildren(type(panel._table_copy_btn) if hasattr(panel, "_table_copy_btn") else object):
        if b.text() == "复制全部":
            btn = b
            break
    # Fallback: search by object name or text
    if btn is None:
        from PySide6.QtWidgets import QPushButton
        for b in panel.findChildren(QPushButton):
            if b.text() == "复制全部":
                btn = b
                break
    assert btn is not None, "复制全部 button not found"
    assert btn.isVisible() or panel.current_mode == "table"
    fake_clip = MagicMock()
    with patch.object(QApplication, "clipboard", return_value=fake_clip):
        qtbot.mouseClick(btn, Qt.LeftButton)
    fake_clip.setText.assert_called_once()
    copied = fake_clip.setText.call_args[0][0]
    assert "H1\tH2" in copied
    assert "a\tb" in copied
    assert "c\td" in copied


def test_data_reader_panel_copy_all_truncated_appends_message(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.table_preview_widget as mod
    monkeypatch.setattr(mod, "MAX_PREVIEW_CELLS", 4)
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(
        PreviewResult(
            mode="table",
            title="big.csv",
            table_headers=("X", "Y"),
            table_rows=tuple((str(i), str(i)) for i in range(10)),
        )
    )
    assert panel.table_preview.truncated is True
    from PySide6.QtWidgets import QPushButton
    btn = None
    for b in panel.findChildren(QPushButton):
        if b.text() == "复制全部":
            btn = b
            break
    assert btn is not None
    fake_clip = MagicMock()
    with patch.object(QApplication, "clipboard", return_value=fake_clip):
        qtbot.mouseClick(btn, Qt.LeftButton)
    copied = fake_clip.setText.call_args[0][0]
    assert panel.table_preview.truncation_message in copied
    # also check tooltip or last line contains truncation
    lines = copied.split("\n")
    assert lines[-1] == panel.table_preview.truncation_message


def test_data_reader_panel_copy_all_button_feedback(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(
        PreviewResult(mode="table", title="t", table_headers=("A",), table_rows=(("1",),))
    )
    from PySide6.QtWidgets import QPushButton
    btn = next(b for b in panel.findChildren(QPushButton) if b.text() == "复制全部")
    fake_clip = MagicMock()
    with patch.object(QApplication, "clipboard", return_value=fake_clip):
        qtbot.mouseClick(btn, Qt.LeftButton)
    assert btn.text() == "已复制"
    qtbot.wait(1500)
    assert btn.text() == "复制全部"


# ---- DataReaderPanel context menu ----------------------------------------------

def test_data_reader_panel_context_menu_open_with_system_app(qtbot, tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("hi", encoding="utf-8")
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(PreviewResult(mode="text", title="doc.txt", path=str(path), text="hi"))
    menu = panel._build_preview_context_menu()
    action = next(a for a in menu.actions() if a.text() == "用系统应用打开")
    assert action.isEnabled()
    with patch("paleo_workbench.ui.pages.data_reader_panel.QDesktopServices.openUrl") as mock_open:
        action.trigger()
    mock_open.assert_called_once()
    args, _ = mock_open.call_args
    url = args[0]
    assert isinstance(url, QUrl)
    assert url.toLocalFile() == str(path)


def test_data_reader_panel_context_menu_disabled_when_no_path(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    panel.render(PreviewResult(mode="text", title="t", text="hi", path=""))
    menu = panel._build_preview_context_menu()
    action = next(a for a in menu.actions() if a.text() == "用系统应用打开")
    assert not action.isEnabled(), "action should be disabled when no local path"
