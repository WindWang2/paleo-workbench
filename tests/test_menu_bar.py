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


def test_view_menu_contains_layout_actions(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    assert bar.view_menu_button.text() == "视图"
    texts = [action.text() for action in bar.view_menu.actions()]
    assert "重置布局" in texts
    assert "收起/展开侧栏" in texts
    # the separator renders as an empty-text action
    assert "" in texts
    assert "界面密度" in texts


def test_view_menu_actions_emit_semantic_signals(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.reset_layout_requested, timeout=1000):
        bar.reset_layout_action.trigger()
    with qtbot.waitSignal(bar.toggle_sidebar_requested, timeout=1000):
        bar.toggle_sidebar_action.trigger()


def test_density_submenu_emits_density_changed(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.density_changed, timeout=1000) as blocker:
        bar.density_compact_action.trigger()
    assert blocker.args == ["compact"]

    with qtbot.waitSignal(bar.density_changed, timeout=1000) as blocker:
        bar.density_comfortable_action.trigger()
    assert blocker.args == ["comfortable"]


def test_help_menu_contains_about_action(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    assert bar.help_menu_button.text() == "帮助"
    assert [action.text() for action in bar.help_menu.actions()] == ["关于"]


def test_about_action_emits_signal(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.about_requested, timeout=1000):
        bar.about_action.trigger()


def test_view_and_help_menu_buttons_use_menu_bar_button_style():
    assert "QPushButton#ViewMenuButton," in tokens.QSS_TEMPLATE
    assert "QPushButton#HelpMenuButton" in tokens.QSS_TEMPLATE


def test_search_box_has_leading_icon(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    leading = bar.search_box.actions()
    assert len(leading) >= 1


def test_search_submitted_emits_on_debounce(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.search_submitted, timeout=1000) as blocker:
        bar.search_box.setText("HZ21")
    assert blocker.args == ["HZ21"]


def test_search_return_pressed_emits_immediately(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.search_submitted, timeout=1000) as blocker:
        bar.search_box.returnPressed.emit()
    assert blocker.args == [bar.search_box.text()]

