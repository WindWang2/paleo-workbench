from paleo_workbench.ui.icon_rail import IconRail
from paleo_workbench.ui import tokens


def test_icon_rail_has_nine_buttons(qtbot):
    rail = IconRail()
    qtbot.addWidget(rail)
    assert len(rail.nav_buttons) == 9
    texts = [btn.text() for btn in rail.nav_buttons]
    assert texts == tokens.PAGE_NAMES


def test_icon_rail_default_active_is_zero(qtbot):
    rail = IconRail()
    qtbot.addWidget(rail)
    assert rail.active_index == 0


def test_icon_rail_click_emits_page_changed(qtbot):
    rail = IconRail()
    qtbot.addWidget(rail)
    received: list[int] = []
    rail.page_changed.connect(lambda i: received.append(i))
    rail.nav_buttons[3].click()
    assert received == [3]


def test_icon_rail_set_active_updates_property(qtbot):
    rail = IconRail()
    qtbot.addWidget(rail)
    rail.set_active(5)
    assert rail.active_index == 5


def test_icon_rail_object_name(qtbot):
    rail = IconRail()
    qtbot.addWidget(rail)
    assert rail.objectName() == "IconRail"
