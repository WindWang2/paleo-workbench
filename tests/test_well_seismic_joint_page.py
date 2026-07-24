"""WellSeismicJointPage navigation and empty state (#59)."""

from __future__ import annotations

from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui import navigation, tokens


def test_joint_page_index_and_nav(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.count() == 12
    assert navigation.PAGE_INDEX_WELL_SEISMIC_JOINT == 11
    assert tokens.PAGE_NAMES[11] == "井震联合"
    assert navigation.PAGE_INDEX_WELL_SEISMIC_JOINT in navigation.get_subpages_for_stage(
        navigation.STAGE_INDEX_INTERPRETATION
    )
    shell.icon_rail.nav_buttons[11].click()
    assert shell.page_stack.currentIndex() == 11
    page = shell.page_stack.widget(11)
    assert page.objectName() == "WellSeismicJointPage"


def test_joint_page_empty_without_data(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.ui.pages import well_seismic_joint_page as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage

    page = WellSeismicJointPage(project=None)
    qtbot.addWidget(page)
    page._loaded_once = True  # avoid double
    page.reload()
    assert "空状态" in page._status.text() or "未找到" in page._status.text()
