from PySide6.QtWidgets import QLabel

from paleo_workbench.ui.pages.floating_panel import FloatingPanel


def test_floating_panel_starts_collapsed_with_tab_visible(qtbot):
    panel = FloatingPanel(title="数据目录", tab_text="目录")
    qtbot.addWidget(panel)
    panel.show()

    assert panel.is_expanded() is False
    assert panel.tab_button.isVisible() is True
    assert panel.content_frame.isVisible() is False
    assert panel.tab_button.text() == "目录"


def test_floating_panel_expands_and_collapses(qtbot):
    panel = FloatingPanel(title="数据目录", tab_text="目录")
    qtbot.addWidget(panel)
    panel.show()
    received = []
    panel.expanded_changed.connect(received.append)

    panel.set_expanded(True)
    panel.set_expanded(False)

    assert received == [True, False]
    assert panel.is_expanded() is False
    assert panel.content_frame.isVisible() is False


def test_floating_panel_accepts_content_widget(qtbot):
    label = QLabel("内容")
    panel = FloatingPanel(title="操作", tab_text="操作", content=label)
    qtbot.addWidget(panel)
    panel.show()

    panel.set_expanded(True)

    assert label.parent() is panel.content_frame
    assert label.isVisible() is True
    assert panel.title_label.text() == "操作"


def test_floating_panel_does_not_show_parentless_widget_on_init(qtbot):
    panel = FloatingPanel(title="数据目录", tab_text="目录")
    qtbot.addWidget(panel)

    assert panel.isVisible() is False


def test_floating_panel_set_content_replaces_existing_widget(qtbot):
    first = QLabel("旧内容")
    second = QLabel("新内容")
    panel = FloatingPanel(title="操作", tab_text="操作", content=first)
    qtbot.addWidget(panel)
    panel.show()

    panel.set_content(second)
    panel.set_expanded(True)

    assert panel.content_frame.layout().count() == 2
    assert first.parent() is None
    assert second.parent() is panel.content_frame
    assert second.isVisible() is True
