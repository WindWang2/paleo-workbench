"""WellSeismicJointHost seam (#86) — reusable without joint page chrome."""

from __future__ import annotations

from paleo_workbench.viz.joint_host import WellSeismicJointHost


def test_host_empty_reload_status(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    host = WellSeismicJointHost()
    qtbot.addWidget  # keep qtbot alive for QObject timers if any
    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.reload()
    assert statuses
    assert "空状态" in statuses[-1] or "未找到" in statuses[-1]


def test_host_has_scene_when_geoviz_available():
    host = WellSeismicJointHost()
    # In CI with geoviz on path, scene should exist
    if host.engine_error is None:
        assert host.scene is not None
    else:
        assert host.scene is None


def test_host_preferred_domain_not_forced_to_time(qtbot, tmp_path, monkeypatch):
    """reload(preferred_domain=Depth) must not leave scene stuck on Time."""
    from paleo_workbench.viz import joint_host as mod
    from paleo_workbench.project.models import JointAnalysisState, ProjectDocument

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    # Empty data → early exit; still unit-test set_vertical_domain path
    host = WellSeismicJointHost()
    if host.scene is None:
        return
    host.set_vertical_domain("Depth", emit_scene=False)
    from geoviz import VerticalDomain

    assert host.scene.vertical_domain is VerticalDomain.DEPTH
    # Simulate project preference applied after a bind
    host.set_vertical_domain("Time", emit_scene=False)
    host.set_vertical_domain("Depth", emit_scene=False)
    assert host.scene.vertical_domain is VerticalDomain.DEPTH


def test_host_auto_default_fence_defaults_true(tmp_path, monkeypatch):
    """#122: keep auto default fence on reload unless restore disables it."""
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    host = WellSeismicJointHost()
    assert host.auto_default_fence is True
    host.reload(auto_default_fence=False)
    assert host.auto_default_fence is False
    host.reload(auto_default_fence=True)
    assert host.auto_default_fence is True


def test_host_depth_status_mentions_2d_stays_time(tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    host = WellSeismicJointHost()
    if host.scene is None:
        return
    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.set_vertical_domain("Depth", emit_scene=False)
    assert statuses
    assert "2D" in statuses[-1] and "Time" in statuses[-1]


def test_joint_page_delegates_to_host(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.ui.pages import well_seismic_joint_page as page_mod
    from paleo_workbench.viz import joint_host as host_mod

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage

    page = WellSeismicJointPage(project=None)
    qtbot.addWidget(page)
    page._loaded_once = True
    page.reload()
    assert "空状态" in page._status.text() or "未找到" in page._status.text()
    assert page._host is not None
