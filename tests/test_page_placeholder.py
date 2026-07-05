from paleo_workbench.ui.page_placeholder import PagePlaceholder


def test_page_placeholder_shows_page_name(qtbot):
    widget = PagePlaceholder("首页")
    qtbot.addWidget(widget)
    assert "首页" in widget.name_label.text()


def test_page_placeholder_has_stretch(qtbot):
    widget = PagePlaceholder("数据")
    qtbot.addWidget(widget)
    assert widget.layout().count() >= 2
