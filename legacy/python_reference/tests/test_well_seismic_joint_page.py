"""Navigation after joint page removal (#91); host empty state still works."""

from __future__ import annotations

from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui import navigation, tokens


def test_geomodel_lives_in_seismic_hub(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.count() == 5
    assert tokens.PAGE_NAMES[10] == "井震联合"
    assert len(tokens.PAGE_NAMES) == 11
    # The Well-Seismic-Joint page index was removed from the navigation module
    # when it merged into the geomodel page; the legacy name must be gone.
    assert not hasattr(navigation, "PAGE_INDEX_WELL_SEISMIC_JOINT")
    # The merged geomodel page is the 地震 hub's 井震联合 3D sub-module
    # (legacy flat index 10 maps there).
    assert navigation.LEGACY_PAGE_TO_HUB[10] == (
        navigation.PAGE_INDEX_SEISMIC, "geomodel",
    )
    shell.navigate_to(navigation.PAGE_INDEX_SEISMIC, "geomodel")
    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_SEISMIC
    assert shell.hub_seismic.current_key() == "geomodel"
    page = shell.hub_seismic.page("geomodel")
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


def test_joint_page_combos_preserve_user_selection(qtbot):
    """scene_updated refreshes must not silently reset the user's well choice."""
    from PySide6.QtWidgets import QComboBox

    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage

    class FakeHost:
        def __init__(self, names):
            self._names = names

        def well_names(self):
            return self._names

    page = WellSeismicJointPage.__new__(WellSeismicJointPage)
    page._well_a = QComboBox()
    page._well_b = QComboBox()
    page._host = FakeHost(["W1", "W2", "W3"])

    page._fill_well_combos()
    assert page._well_a.currentText() == "W1"
    assert page._well_b.currentText() == "W2"  # legacy default: index 1

    # User picks a different pair, then a scene refresh re-fills.
    page._well_a.setCurrentText("W3")
    page._well_b.setCurrentText("W1")
    page._fill_well_combos()
    assert page._well_a.currentText() == "W3"
    assert page._well_b.currentText() == "W1"

    # A well disappears from the survey: fall back to defaults, not stale text.
    page._host = FakeHost(["W1"])
    page._fill_well_combos()
    assert page._well_a.currentText() == "W1"
    assert page._well_b.currentText() == "W1"


def test_geomodel_page_loads_on_first_switch(qtbot):
    """Geomodel page must load its joint data on the very first page switch with deferred bindings."""
    from paleo_workbench.project.models import ProjectDocument

    doc = ProjectDocument.new("DeferredTestProject")
    shell = AppShell(project=doc, defer_nonvisible_bindings=True)
    qtbot.addWidget(shell)

    geomodel_page = shell.geomodel_page
    assert geomodel_page._joint_loaded_once is False

    # Switch to the 地震 hub's 井震联合 3D sub-module for the first time
    shell.navigate_to(navigation.PAGE_INDEX_SEISMIC, "geomodel")

    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_SEISMIC
    assert shell.hub_seismic.current_key() == "geomodel"
    assert geomodel_page._project is doc
    assert geomodel_page._joint_loaded_once is True

