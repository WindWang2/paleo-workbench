from paleo_workbench.ui.menu_bar import MenuBar
from paleo_workbench.ui import tokens


def test_menu_bar_has_three_non_project_labels(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)
    texts = [lbl.text() for lbl in bar.labels]
    assert texts == ["视图", "工具", "帮助"]


def test_menu_bar_object_name(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "MenuBar"


def test_project_menu_contains_actions_and_search(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    assert bar.project_menu_button.text() == "工程与文件"
    assert [action.text() for action in bar.project_menu.actions()] == [
        "新建工程", "打开工程", "打开样例工程", "保存工程", "", "工程属性",
    ]
    assert bar.search_box.objectName() == "SearchBox"


def test_project_menu_actions_emit_semantic_signals(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    cases = [
        (bar.new_project_action, bar.new_project_requested),
        (bar.open_project_action, bar.open_project_requested),
        (bar.open_sample_project_action, bar.open_sample_project_requested),
        (bar.save_project_action, bar.save_project_requested),
        (bar.properties_action, bar.properties_requested),
    ]
    for action, signal in cases:
        with qtbot.waitSignal(signal, timeout=1000):
            action.trigger()


def test_tools_menu_contains_preview_settings_action(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    assert bar.tools_menu_button.text() == "工具"
    assert [action.text() for action in bar.tools_menu.actions()] == ["预览设置…"]


def test_preview_settings_action_emits_semantic_signal(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.preview_settings_requested, timeout=1000):
        bar.preview_settings_action.trigger()


def test_tools_menu_button_uses_menu_bar_button_style():
    assert "QPushButton#ProjectMenuButton," in tokens.QSS_TEMPLATE
    assert "QPushButton#ToolsMenuButton" in tokens.QSS_TEMPLATE
