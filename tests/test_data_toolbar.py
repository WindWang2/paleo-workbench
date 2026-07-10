from PySide6.QtWidgets import QPushButton

from paleo_workbench.ui.pages.data_toolbar import DataToolbar


def test_data_toolbar_exposes_actions_and_search(qtbot):
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)
    received = []
    toolbar.search_changed.connect(received.append)

    toolbar.search_box.setText("well")
    # Search is debounced (~180ms); wait for emit.
    qtbot.wait(200)

    assert toolbar.import_btn.text() == "导入文件"
    assert toolbar.import_folder_btn.text() == "导入目录"
    assert toolbar.rescan_btn.text() == "重新扫描"
    assert toolbar.catalog_btn.text() == "目录"
    assert toolbar.reader_btn.text() == "阅读器"
    assert received[-1] == "well"


def test_data_toolbar_search_is_debounced(qtbot):
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)
    received = []
    toolbar.search_changed.connect(received.append)

    toolbar.search_box.setText("w")
    toolbar.search_box.setText("we")
    toolbar.search_box.setText("well")
    assert received == []

    qtbot.wait(200)
    assert received == ["well"]


def test_data_toolbar_rehomes_column_settings_button(qtbot):
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)
    button = QPushButton("列设置")

    toolbar.set_column_settings_button(button)

    assert toolbar.column_settings_slot is not toolbar
    assert button.parent() is toolbar.column_settings_slot

    layout = toolbar.layout()
    assert layout.indexOf(toolbar.column_settings_slot) < layout.indexOf(toolbar.catalog_btn)
    assert layout.indexOf(toolbar.column_settings_slot) < layout.indexOf(toolbar.reader_btn)
    assert toolbar.column_settings_slot.layout().indexOf(button) == 0


def test_toolbar_catalog_button_checkable(qtbot):
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)

    assert toolbar.catalog_btn.isCheckable() is True
    assert toolbar.reader_btn.isCheckable() is True
