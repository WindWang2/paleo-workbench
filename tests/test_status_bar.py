from paleo_workbench.ui.status_bar import StatusBar


def test_status_bar_default_text(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert "就绪" in bar.status_label.text()


def test_status_bar_coord_label(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert "X" in bar.coord_label.text()
    assert "CGCS2000" in bar.coord_label.text()


def test_status_bar_set_project_name(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.set_project_name("HZ26 Demo")
    assert "HZ26 Demo" in bar.status_label.text()


def test_status_bar_object_name(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "StatusBar"
