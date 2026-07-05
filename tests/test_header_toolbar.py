from paleo_workbench.ui.header_toolbar import HeaderToolbar


def test_header_has_four_buttons(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    texts = [btn.text() for btn in bar.buttons]
    assert texts == ["新建工程", "打开工程", "保存工程", "工程属性"]


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
