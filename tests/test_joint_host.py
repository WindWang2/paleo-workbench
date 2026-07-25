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
