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
    assert toolbar.reader_btn.text() == "预览栏"
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


# --- programmatic tag filter state (#413) ------------------------------------

def test_toolbar_programmatic_tag_selection_is_authoritative(qtbot):
    """current_tag_selection() must read the filter state, not the lazily
    built menu-action mirror: a programmatic apply (Tag Manager 查看关联数据)
    with the menu never opened must not read back as empty (#413)."""
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)
    toolbar.set_tag_candidates(["X", "Y"])

    toolbar.apply_tag_selection(["X"], "and")

    assert toolbar._selected_tags == ["X"]
    assert toolbar.current_tag_selection() == ["X"]
    assert toolbar.current_tag_operator() == "and"

    # Opening the menu must show the same state (checked == active filter).
    toolbar._rebuild_tag_filter_menu()
    checked = [a.text() for a in toolbar._tag_check_actions if a.isChecked()]
    assert checked == ["X"]


def test_toolbar_manual_tag_menu_toggle_still_updates_selection(qtbot):
    """The manual menu-toggle path keeps working unchanged."""
    toolbar = DataToolbar()
    qtbot.addWidget(toolbar)
    toolbar.set_tag_candidates(["X", "Y"])
    toolbar._rebuild_tag_filter_menu()
    received = []
    toolbar.tag_filter_changed.connect(lambda tags, op: received.append((list(tags), op)))

    x_action = next(a for a in toolbar._tag_check_actions if a.text() == "X")
    x_action.setChecked(True)

    assert toolbar.current_tag_selection() == ["X"]
    assert toolbar._selected_tags == ["X"]
    assert received == [(["X"], "and")]

    x_action.setChecked(False)
    assert toolbar.current_tag_selection() == []
    assert received[-1] == ([], "and")
