"""Joint host: non-SEGY asset parsing runs off the GUI thread (#503).

Well-head parse, TD tables (loaded once, not twice), the tops conversion and
the LAS preview reads used to run synchronously inside the queued
``_on_survey_meta_ready`` slot (and in the no-SEGY reload branch), freezing
the GUI after C09 had already moved only the SEG-Y scans to a worker.
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from paleo_workbench.project.models import ProjectDocument, ResourceItem


def _write_mini_segy(path: Path, *, n_il: int = 8, n_xl: int = 10, n_s: int = 16) -> Path:
    segyio = pytest.importorskip("segyio")
    import numpy as np

    spec = segyio.spec()
    spec.sorting = 2  # inline sorting
    spec.format = 1
    spec.samples = list(range(n_s))
    spec.ilines = list(range(1, n_il + 1))
    spec.xlines = list(range(1, n_xl + 1))
    with segyio.create(str(path), spec) as f:
        for ili, il in enumerate(spec.ilines):
            for xli, xl in enumerate(spec.xlines):
                tr = np.linspace(0.0, 1.0, n_s, dtype=np.float32) + 0.01 * ili
                f.header[ili * n_xl + xli] = {
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                }
                f.trace[ili * n_xl + xli] = tr
    return path


def _project_with_segy(tmp_path: Path, segy: Path) -> ProjectDocument:
    project = ProjectDocument.new("Joint")
    project.resources.append(
        ResourceItem(name="cube.sgy", path=str(segy), type="seismic", format="sgy")
    )
    return project


def _fake_paths(tmp_path: Path, *, segy: Path | None) -> SimpleNamespace:
    from paleo_workbench.viz.joint_asset_resolver import JointAssetPaths

    well_head = tmp_path / "wellhead.csv"
    well_head.write_text("A1,1.0,1.0\n", encoding="utf-8")
    td_dir = tmp_path / "td"
    td_dir.mkdir(exist_ok=True)
    (td_dir / "A1.td").write_text("0 0\n1000 2000\n", encoding="utf-8")
    tops = tmp_path / "tops.dat"
    tops.write_text("# tops\nA1 TopA 850.0\n", encoding="utf-8")
    las = tmp_path / "A1.las"
    las.write_text("~VER\n", encoding="utf-8")
    return JointAssetPaths(
        segy=segy,
        well_head=well_head,
        well_head_asset_id="wh-asset-1",
        td_dir=td_dir,
        tops=tops,
        horizons=[],
        las_files=[las],
        source="project",
    )


def _recorders(monkeypatch, host):
    """Record thread + payload for every blocking parse the host triggers."""
    import paleo_workbench.viz.joint_host as jh

    calls = {
        "well_heads": {"thread": None, "count": 0},
        "td": {"thread": None, "count": 0},
        "las": {"thread": None, "count": 0},
    }
    applied: dict = {}

    def fake_parse_well_heads(path, identity_registry=None):
        calls["well_heads"]["count"] += 1
        calls["well_heads"]["thread"] = threading.current_thread().name
        return SimpleNamespace(
            wells=[SimpleNamespace(name="A1")],
            identity_registry=SimpleNamespace(asset_id="wh-asset-1"),
        )

    def fake_load_td_tables(td_dir):
        calls["td"]["count"] += 1
        calls["td"]["thread"] = threading.current_thread().name
        return {"A1": SimpleNamespace(md_to_time_ms=lambda md: md * 2.0)}

    def fake_load_las_preview(path, fast=False):
        calls["las"]["count"] += 1
        calls["las"]["thread"] = threading.current_thread().name
        return SimpleNamespace(
            well_name="A1",
            curves=[SimpleNamespace(name="GR", depth=[1.0, 2.0], values=[10.0, 20.0])],
        )

    monkeypatch.setattr(jh, "parse_well_heads", fake_parse_well_heads)
    monkeypatch.setattr(jh, "load_td_tables", fake_load_td_tables)
    import geoviz

    monkeypatch.setattr(geoviz, "load_las_preview", fake_load_las_preview)

    scene = host._scene
    monkeypatch.setattr(
        scene, "set_wells", lambda wells, td_tables=None: applied.__setitem__(
            "wells", (wells, td_tables)
        )
    )
    monkeypatch.setattr(
        scene, "set_formation_tops", lambda t: applied.__setitem__("tops", t)
    )
    monkeypatch.setattr(
        scene, "set_well_curves", lambda c: applied.__setitem__("curves", c)
    )
    monkeypatch.setattr(
        scene,
        "set_survey_from_corners",
        lambda *a, **k: applied.__setitem__("survey", (a, k)),
    )
    return calls, applied


def test_joint_assets_parse_off_gui_thread_and_td_loaded_once(
    qtbot, tmp_path, monkeypatch
):
    """After the SEG-Y scan, the well/td/tops/LAS parse must leave the GUI thread."""
    import paleo_workbench.viz.joint_host as jh
    import paleo_workbench.viz.joint_segy_survey as jss

    segy = _write_mini_segy(tmp_path / "cube.sgy")

    def fake_corners(segy_path):
        return (
            (1.0, 1.0, 0.0, 0.0),
            (1.0, 10.0, 100.0, 0.0),
            (8.0, 10.0, 100.0, 100.0),
            {"n_samples": 16, "dt_ms": 1.0, "t0_ms": 0.0, "source": "test"},
        )

    monkeypatch.setattr(jss, "survey_corners_from_segy", fake_corners)

    host = jh.WellSeismicJointHost()
    assert host._scene is not None
    paths = _fake_paths(tmp_path, segy=segy)
    monkeypatch.setattr(
        jh, "resolve_joint_assets", lambda project, repo_root=None: paths
    )
    calls, applied = _recorders(monkeypatch, host)

    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.set_project(_project_with_segy(tmp_path, segy))
    host.reload()

    def _applied():
        # set_project pre-clears the scene with empty calls; only a payload
        # with real wells (and converted tops + curves) counts as applied.
        wells = applied.get("wells")
        return (
            bool(wells and wells[0])
            and bool(applied.get("tops"))
            and bool(applied.get("curves"))
            and "survey" in applied
        )

    qtbot.waitUntil(_applied, timeout=20_000)

    # Every blocking parse ran on a worker thread, never the GUI thread.
    gui_thread = threading.current_thread().name
    assert calls["well_heads"]["thread"] is not None
    assert calls["well_heads"]["thread"] != gui_thread
    assert calls["las"]["thread"] != gui_thread
    assert calls["td"]["thread"] != gui_thread
    # TD tables were parsed exactly ONCE for both consumers (the old flow
    # re-parsed the whole directory for the tops conversion).
    assert calls["td"]["count"] == 1

    # Payload applied to the scene in order with converted tops.
    wells, td_tables = applied["wells"]
    assert [w.name for w in wells] == ["A1"]
    assert set(td_tables) == {"A1"}
    assert applied["tops"] == {"A1": [("TopA", 1700.0)]}  # 850 m * 2 ms/m
    assert "A1" in applied["curves"] and "GR" in applied["curves"]["A1"]
    assert "survey" in applied
    host.shutdown()


def test_joint_no_segy_assets_also_off_gui_thread(qtbot, tmp_path, monkeypatch):
    """The no-SEGY reload branch must parse off the GUI thread too (#503)."""
    import paleo_workbench.viz.joint_host as jh

    host = jh.WellSeismicJointHost()
    assert host._scene is not None
    paths = _fake_paths(tmp_path, segy=None)
    monkeypatch.setattr(
        jh, "resolve_joint_assets", lambda project, repo_root=None: paths
    )
    calls, applied = _recorders(monkeypatch, host)

    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.set_project(ProjectDocument.new("NoSegy"))
    host.reload()

    def _done():
        return any("已加载井/测网（无 SEGY）" in s for s in statuses)

    qtbot.waitUntil(_done, timeout=20_000)
    assert calls["well_heads"]["thread"] != threading.current_thread().name
    assert calls["las"]["thread"] != threading.current_thread().name
    wells = applied.get("wells")
    assert wells and wells[0], f"scene never received parsed wells: {applied}"
    host.shutdown()


def test_joint_no_segy_assets_failure_clears_scene_and_reports(
    qtbot, tmp_path, monkeypatch
):
    """A parse failure in the no-SEGY path must clear the scene honestly."""
    import paleo_workbench.viz.joint_host as jh

    host = jh.WellSeismicJointHost()
    assert host._scene is not None
    paths = _fake_paths(tmp_path, segy=None)
    monkeypatch.setattr(
        jh, "resolve_joint_assets", lambda project, repo_root=None: paths
    )
    calls, applied = _recorders(monkeypatch, host)

    def boom(path, identity_registry=None):
        raise RuntimeError("well head exploded")

    monkeypatch.setattr(jh, "parse_well_heads", boom)

    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.set_project(ProjectDocument.new("NoSegy"))
    host.reload()

    def _failed():
        return any("加载失败" in s for s in statuses)

    qtbot.waitUntil(_failed, timeout=20_000)
    assert any("well head exploded" in s for s in statuses)
    # Honest-empty scene after the failed bind.
    assert applied.get("wells") == ([], None)
    host.shutdown()
