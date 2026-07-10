from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from paleo_workbench.ui import tokens
from paleo_workbench.ui.widgets import (
    EmptyStateLabel,
    PageScaffold,
    PanelCard,
    SectionHeader,
    ToolbarStrip,
)


def test_panel_card_object_name_and_padding(qtbot):
    card = PanelCard(title="标题")
    qtbot.addWidget(card)
    assert card.objectName() == "PanelCard"
    assert card.title_label.text() == "标题"
    # body layout uses PANEL_PADDING
    lay = card.layout()
    m = lay.contentsMargins()
    assert m.left() == tokens.PANEL_PADDING


def test_section_header(qtbot):
    h = SectionHeader("区块", subtitle="说明")
    qtbot.addWidget(h)
    assert h.objectName() == "SectionHeader"
    assert h.title_label.text() == "区块"
    assert h.subtitle_label.text() == "说明"


def test_toolbar_strip(qtbot):
    strip = ToolbarStrip()
    qtbot.addWidget(strip)
    assert strip.objectName() == "ToolbarStrip"
    btn = QPushButton("X")
    strip.add_widget(btn)
    assert strip.layout().count() >= 1


def test_empty_state_label(qtbot):
    lab = EmptyStateLabel("暂无数据")
    qtbot.addWidget(lab)
    assert lab.objectName() == "EmptyStateLabel"
    assert lab.text() == "暂无数据"
    assert lab.alignment() & Qt.AlignmentFlag.AlignCenter


def test_page_scaffold_margins(qtbot):
    page = PageScaffold(title="页面")
    qtbot.addWidget(page)
    assert page.objectName() == "PageScaffold"
    m = page.layout().contentsMargins()
    assert m.left() == tokens.PAGE_MARGIN
    assert m.top() == tokens.PAGE_MARGIN
    body = QLabel("content")
    page.set_body(body)
    assert page.body_widget is body
