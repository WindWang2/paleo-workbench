from PySide6.QtCore import Qt

from paleo_workbench.ui.header_toolbar import HeaderToolbar


def test_header_has_five_buttons(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    texts = [btn.text() for btn in bar.buttons]
    assert texts == [
        "新建工程",
        "打开工程",
        "打开样例工程",
        "保存工程",
        "工程属性",
    ]


def test_header_primary_button_object_name(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    assert bar.buttons[0].objectName() == "PrimaryButton"
    for btn in bar.buttons[1:]:
        assert btn.objectName() == "SecondaryButton"


def test_header_search_box_placeholder(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    assert "搜索" in bar.search_box.placeholderText()
    assert bar.search_box.objectName() == "SearchBox"


def test_header_object_name(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "HeaderToolbar"


def test_toolbar_emits_new_project_signal(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.new_project_requested, timeout=1000):
        qtbot.mouseClick(bar.new_project_btn, Qt.MouseButton.LeftButton)


def test_toolbar_emits_open_project_signal(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.open_project_requested, timeout=1000):
        qtbot.mouseClick(bar.open_project_btn, Qt.MouseButton.LeftButton)


def test_sample_project_button_emits(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    assert bar.open_sample_project_btn.text() == "打开样例工程"
    with qtbot.waitSignal(bar.open_sample_project_requested, timeout=1000):
        bar.open_sample_project_btn.click()


def test_toolbar_emits_save_project_signal(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.save_project_requested, timeout=1000):
        qtbot.mouseClick(bar.save_project_btn, Qt.MouseButton.LeftButton)


def test_toolbar_emits_properties_signal(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.properties_requested, timeout=1000):
        qtbot.mouseClick(bar.properties_btn, Qt.MouseButton.LeftButton)
