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
    assert layout.indexOf(toolbar.column_settings_slot) < layout.indexOf(toolbar.reader_btn)
    assert toolbar.column_settings_slot.layout().indexOf(button) == 0


def test_toolbar_has_remove_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.remove_btn.text() == "移出项目"


def test_toolbar_has_open_folder_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.open_folder_btn.text() == "打开目录"


def test_toolbar_has_visualize_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.visualize_btn.text() == "可视化"


def test_toolbar_remove_signal(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    received = []
    tb.remove_requested.connect(lambda: received.append(1))
    tb.remove_btn.click()
    assert received == [1]


def test_toolbar_no_catalog_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert not hasattr(tb, "catalog_btn")


def test_toolbar_clear_preview_cache_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.clear_preview_cache_btn.text() == "清除预览缓存"
    received = []
    tb.clear_preview_cache_requested.connect(lambda: received.append(1))
    tb.clear_preview_cache_btn.click()
    assert received == [1]
