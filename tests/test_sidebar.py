from paleo_workbench.ui.sidebar import TextSidebar


def test_sidebar_default_context_label(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    assert bar.context_label.text() == "首页"


def test_sidebar_set_context_updates_label(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    bar.set_context("编图")
    assert bar.context_label.text() == "编图"


def test_sidebar_object_name(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "TextSidebar"
