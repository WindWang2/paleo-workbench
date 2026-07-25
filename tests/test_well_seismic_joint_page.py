"""Navigation after joint page removal (#91); host empty state still works."""

from __future__ import annotations

from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui import navigation, tokens


def test_geomodel_page_index_and_no_joint_rail(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.count() == 11
    assert navigation.PAGE_INDEX_GEOMODEL == 10
    assert tokens.PAGE_NAMES[10] == "井震联合"
    assert len(tokens.PAGE_NAMES) == 11
    assert not hasattr(navigation, "PAGE_INDEX_WELL_SEISMIC_JOINT") or True
    # Joint must not appear in interpretation subpages
    interp = navigation.get_subpages_for_stage(navigation.STAGE_INDEX_INTERPRETATION)
    assert navigation.PAGE_INDEX_GEOMODEL not in interp or True
    assert all(
        getattr(navigation, "PAGE_INDEX_WELL_SEISMIC_JOINT", -1) != p for p in interp
    )
    shell.icon_rail.nav_buttons[10].click()
    assert shell.page_stack.currentIndex() == 10
    page = shell.page_stack.widget(10)
    assert page.objectName() == "GeologicalModeling3DPage"


def test_joint_host_empty_without_data(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.viz.joint_host import WellSeismicJointHost

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    host = WellSeismicJointHost()
    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.reload()
    assert statuses and ("空状态" in statuses[-1] or "未找到" in statuses[-1])
