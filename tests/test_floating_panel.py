from PySide6.QtWidgets import QLabel

from paleo_workbench.ui.pages.floating_panel import FloatingPanel


def test_floating_panel_starts_collapsed_with_tab_visible(qtbot):
    panel = FloatingPanel(title="数据目录", tab_text="目录")
    qtbot.addWidget(panel)

    assert panel.is_expanded() is False
    assert panel.tab_button.isVisible() is True
    assert panel.content_frame.isVisible() is False
    assert panel.tab_button.text() == "目录"


def test_floating_panel_expands_and_collapses(qtbot):
    panel = FloatingPanel(title="数据目录", tab_text="目录")
    qtbot.addWidget(panel)
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

    panel.set_expanded(True)

    assert label.parent() is panel.content_frame
    assert label.isVisible() is True
    assert panel.title_label.text() == "操作"
