from paleo_workbench.ui.menu_bar import MenuBar


def test_menu_bar_has_four_labels(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)
    texts = [lbl.text() for lbl in bar.labels]
    assert texts == ["工程与文件", "视图", "工具", "帮助"]


def test_menu_bar_object_name(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "MenuBar"
