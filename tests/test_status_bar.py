from paleo_workbench.ui.status_bar import StatusBar


def test_status_bar_default_text(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert "就绪" in bar.status_label.text()


def test_status_bar_coord_label(qtbot):
    """coord_label exists but is hidden/empty until update_context is called."""
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert bar.coord_label.objectName() == "StatusCoordLabel"
    # Static placeholder is gone: starts hidden with no text.
    assert bar.coord_label.text() == ""
    assert bar.coord_label.isHidden()


def test_status_bar_update_context_coords(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context(coords="X: 100  Y: 200")
    assert "100" in bar.coord_label.text()
    assert bar.coord_label.isVisible() or not bar.coord_label.isHidden()


def test_status_bar_update_context_hides_absent_fields(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context()  # no fields
    assert bar.coord_label.isHidden() or bar.coord_label.text() == ""


def test_status_bar_update_context_all_fields(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context(coords="X: 1", horizon="ZJ-2", crs="EPSG:32649", scale="50000")
    text = bar.coord_label.text()
    assert "1" in text
    assert "ZJ-2" in text
    assert "EPSG:32649" in text
    assert "50000" in text


def test_status_bar_update_context_partial_fields(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context(horizon="ZJ-3", scale="25000")
    text = bar.coord_label.text()
    assert "ZJ-3" in text
    assert "1:25000" in text
    assert "层位:" in text


def test_status_bar_update_context_keyword_only(qtbot):
    """coords/crs join with no prefix; horizon/scale get Chinese prefixes."""
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context(coords="X: 1", crs="EPSG:4326")
    assert "X: 1" in bar.coord_label.text()
    assert "EPSG:4326" in bar.coord_label.text()


def test_status_bar_set_project_name(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.set_project_name("HZ26 Demo")
    assert "HZ26 Demo" in bar.status_label.text()


def test_status_bar_object_name(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "StatusBar"


def test_status_coord_label_object_name(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert bar.coord_label.objectName() == "StatusCoordLabel"

