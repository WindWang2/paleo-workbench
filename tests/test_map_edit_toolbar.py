from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar


def test_toolbar_tools_are_exclusive(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)

    assert bar.select_btn.isChecked() is True
    assert bar.current_tool() == "select"

    bar.move_btn.click()
    assert bar.move_btn.isChecked() is True
    assert bar.select_btn.isChecked() is False
    assert bar.current_tool() == "move"

    bar.vertex_btn.click()
    assert bar.vertex_btn.isChecked() is True
    assert bar.move_btn.isChecked() is False
    assert bar.current_tool() == "vertex"


def test_toolbar_emits_tool_changed(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)
    received = []
    bar.tool_changed.connect(received.append)

    bar.line_btn.click()
    assert received == ["line"]

    bar.label_btn.click()
    assert received == ["line", "label"]


def test_toolbar_snap_and_action_signals(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)

    snaps = []
    saves = []
    demos = []
    undos = []
    redos = []
    bar.snap_toggled.connect(snaps.append)
    bar.save_draft_requested.connect(lambda: saves.append(True))
    bar.generate_demo_draft_requested.connect(lambda: demos.append(True))
    bar.undo_requested.connect(lambda: undos.append(True))
    bar.redo_requested.connect(lambda: redos.append(True))

    bar.snap_btn.click()
    assert snaps == [True]
    bar.snap_btn.click()
    assert snaps == [True, False]

    bar.undo_btn.click()
    bar.redo_btn.click()
    bar.generate_demo_draft_btn.click()
    bar.save_draft_btn.click()
    assert undos == [True]
    assert redos == [True]
    assert demos == [True]
    assert saves == [True]


def test_toolbar_generate_demo_draft_button_emits(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)

    assert bar.generate_demo_draft_btn.text() == "生成演示草稿"
    assert bar.generate_demo_draft_btn.objectName() == "SecondaryButton"

    received = []
    bar.generate_demo_draft_requested.connect(lambda: received.append(True))
    bar.generate_demo_draft_btn.click()
    assert received == [True]
