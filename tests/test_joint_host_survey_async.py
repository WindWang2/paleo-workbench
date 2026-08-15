"""Joint host: SEG-Y survey metadata scans run off the GUI thread (C09)."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.project.models import ProjectDocument, ResourceItem


def _write_mini_segy(path: Path, *, n_il: int = 8, n_xl: int = 10, n_s: int = 16) -> Path:
    segyio = pytest.importorskip("segyio")
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


def test_joint_reload_scans_segy_off_gui_thread_and_caches(qtbot, tmp_path, monkeypatch):
    """Survey corners + volume metadata must scan once, on a worker thread (C09)."""
    import paleo_workbench.viz.joint_segy_survey as jss
    from paleo_workbench.viz.joint_host import WellSeismicJointHost

    segy = _write_mini_segy(tmp_path / "cube.sgy")
    project = _project_with_segy(tmp_path, segy)

    calls = {"count": 0, "thread": None}

    def fake_corners(segy_path):
        calls["count"] += 1
        calls["thread"] = threading.current_thread().name
        return (
            (1.0, 1.0, 0.0, 0.0),
            (1.0, 2.0, 100.0, 0.0),
            (2.0, 2.0, 100.0, 100.0),
            {"n_samples": 16, "dt_ms": 1.0, "t0_ms": 0.0, "source": "test"},
        )

    monkeypatch.setattr(jss, "survey_corners_from_segy", fake_corners)

    host = WellSeismicJointHost()
    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.set_project(project)
    host.reload()

    def _loaded():
        return host._volume_phase in (
            "METADATA_READY",
            "L0_LOADING",
            "L0_READY",
            "L1_READY",
        ) or any("元数据就绪" in s for s in statuses)

    qtbot.waitUntil(_loaded, timeout=20_000)
    assert calls["count"] == 1
    # The full trace-header scans ran on the worker thread, not the GUI thread.
    assert calls["thread"] != threading.current_thread().name
    assert host.survey_meta.get("source") == "test"
    assert host._source_backed_access is not None

    # A second reload reuses the cached payload — no repeat scan.
    host.reload()
    qtbot.waitUntil(
        lambda: host._volume_phase in ("L0_LOADING", "L0_READY", "L1_READY"),
        timeout=20_000,
    )
    assert calls["count"] == 1
    host.shutdown()


def test_joint_reload_segy_metadata_failure_falls_back(qtbot, tmp_path, monkeypatch):
    """A failed metadata pass still reports status and starts the preview worker."""
    import paleo_workbench.viz.joint_segy_survey as jss
    from paleo_workbench.viz.joint_host import WellSeismicJointHost

    segy = _write_mini_segy(tmp_path / "cube2.sgy")
    project = _project_with_segy(tmp_path, segy)

    def boom(segy_path):
        raise RuntimeError("corners scan failed")

    monkeypatch.setattr(jss, "survey_corners_from_segy", boom)

    host = WellSeismicJointHost()
    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    host.set_project(project)
    host.reload()

    qtbot.waitUntil(
        lambda: any("SEG-Y 元数据读取失败" in s for s in statuses), timeout=20_000
    )
    # Dense-fallback preview worker still starts.
    qtbot.waitUntil(
        lambda: host._volume_phase in ("L0_LOADING", "L0_READY", "L1_READY"),
        timeout=20_000,
    )
    host.shutdown()
