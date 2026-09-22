"""WellSeismicJointHost seam (#86) — reusable without joint page chrome."""

from __future__ import annotations

import pytest

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
    if host.engine_error is not None:
        pytest.skip(f"geoviz unavailable in this environment: {host.engine_error}")
    assert host.scene is not None


def test_host_preferred_domain_not_forced_to_time(qtbot, tmp_path, monkeypatch):
    """Domain switching is fail-closed: Depth needs a transform, Time always works."""
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    # Empty data → early exit; still unit-test set_vertical_domain path
    host = WellSeismicJointHost()
    if host.scene is None:
        pytest.skip(f"geoviz unavailable: {host.engine_error}")
    from geoviz import VerticalDomain, select_depth_transform

    # Without a time-depth transform, Depth is refused (never faked with V0).
    assert host.set_vertical_domain("Depth", emit_scene=False) is False
    assert host.scene.vertical_domain is VerticalDomain.TIME
    host.set_vertical_domain("Time", emit_scene=False)
    # With an explicit transform (e.g. synthetic demo), Depth applies and a
    # reload(preferred_domain=...) restore keeps it — not forced back to Time.
    host.scene.set_depth_transform(select_depth_transform(constant_v0=True))
    assert host.set_vertical_domain("Depth", emit_scene=False) is True
    assert host.scene.vertical_domain is VerticalDomain.DEPTH
    host.set_vertical_domain("Time", emit_scene=False)
    assert host.set_vertical_domain("Depth", emit_scene=False) is True
    assert host.scene.vertical_domain is VerticalDomain.DEPTH


def test_host_auto_default_fence_defaults_false(tmp_path, monkeypatch):
    """Time-slice well-connect: do not auto-pair the first two wells."""
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    host = WellSeismicJointHost()
    assert host.auto_default_fence is False
    host.reload(auto_default_fence=True)
    assert host.auto_default_fence is True
    host.reload(auto_default_fence=False)
    assert host.auto_default_fence is False


def test_host_depth_unavailable_status_and_unified_domain(tmp_path, monkeypatch):
    """Without a transform the host refuses Depth and says why; 2D/3D stay unified."""
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    host = WellSeismicJointHost()
    if host.scene is None:
        pytest.skip(f"geoviz unavailable: {host.engine_error}")
    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    assert host.set_vertical_domain("Depth", emit_scene=False) is False
    assert statuses
    assert "不可用" in statuses[-1]
    assert "Time" in statuses[-1]
    from geoviz import VerticalDomain, select_depth_transform

    assert host.scene.vertical_domain is VerticalDomain.TIME
    host.scene.set_depth_transform(select_depth_transform(constant_v0=True))
    assert host.set_vertical_domain("Depth", emit_scene=False) is True
    assert "同域" in statuses[-1]
    assert host.scene.vertical_domain is VerticalDomain.DEPTH


def test_host_loads_gr_using_each_las_curve_depth_samples(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.project.models import ProjectDocument, ResourceItem
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    well_head = tmp_path / "ExportWellHead.dat"
    well_head.write_text("A1 0 0 0 100 0 0\n", encoding="utf-8")
    las = tmp_path / "A1.las"
    las.write_text(
        "\n".join(
            [
                "~Version",
                "VERS. 2.0",
                "WRAP. NO",
                "~Well",
                "STRT.M 0",
                "STOP.M 100",
                "STEP.M 50",
                "NULL. -999.25",
                "WELL. A1",
                "~Curve",
                "DEPT.M : Depth",
                "GR.API : Gamma Ray",
                "~Ascii",
                "0 10",
                "50 20",
                "100 30",
            ]
        ),
        encoding="utf-8",
    )
    project = ProjectDocument.new("gr")
    project.resources.extend(
        [
            ResourceItem(
                id="res:wells",
                name=well_head.name,
                path=str(well_head),
                type="well_head",
                format="dat",
            ),
            ResourceItem(
                id="res:las",
                name=las.name,
                path=str(las),
                type="well_log",
                format="las",
            ),
        ]
    )
    host = WellSeismicJointHost()
    host.set_project(project)

    host.reload()
    # The LAS/well parse runs in the assets worker (#503); wait for the
    # no-SEGY load to land before asserting on the scene.
    qtbot.waitUntil(
        lambda: host.scene.gr_value_range() is not None, timeout=10_000
    )

    assert host.scene.gr_value_range() == pytest.approx((10.4, 29.6))
    host.shutdown()


def test_joint_page_delegates_to_host(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage

    page = WellSeismicJointPage(project=None)
    qtbot.addWidget(page)
    page._loaded_once = True
    page.reload()
    assert "空状态" in page._status.text() or "未找到" in page._status.text()
    assert page._host is not None
