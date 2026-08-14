"""Deep-audit regressions (2026-08-14): seismic volume source, joint host LOD,
and the seismic attribute worker signal/typing contract."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.seismic_volume_source import (
    SeismicVolumeSource,
    clear_seismic_source_registry,
    get_shared_seismic_source,
)
from paleo_workbench.viz.seismic_volume_cache import reset_global_seismic_cache


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_seismic_source_registry()
    reset_global_seismic_cache()
    yield
    clear_seismic_source_registry()
    reset_global_seismic_cache()


def _write_mini_segy(path: Path, *, n_il: int = 8, n_xl: int = 10, n_s: int = 16) -> Path:
    """Write a tiny structured SEG-Y via segyio (skip if segyio missing)."""
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
                tr = np.linspace(0.0, 1.0, n_s, dtype=np.float32) + 0.01 * ili + 0.001 * xli
                f.header[ili * n_xl + xli] = {
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                }
                f.trace[ili * n_xl + xli] = tr
    return path


def _write_unstructured_segy(path: Path, *, n_traces: int = 100, n_s: int = 16) -> Path:
    """Write a headerless SEG-Y whose IL/XL headers carry no real geometry.

    All INLINE_3D/CROSSLINE_3D headers are identical, so the geoviz loader
    falls back to its unstructured mode (``ilines is None``) and ``inspect()``
    reports the mocked 1 inline x N crosslines pseudo geometry.
    """
    segyio = pytest.importorskip("segyio")
    spec = segyio.spec()
    spec.format = 1
    spec.samples = list(range(n_s))
    spec.tracecount = n_traces
    with segyio.create(str(path), spec) as f:
        for i in range(n_traces):
            f.header[i] = {
                segyio.TraceField.INLINE_3D: 0,
                segyio.TraceField.CROSSLINE_3D: 0,
            }
            f.trace[i] = np.full(n_s, float(i), dtype=np.float32)
    return path


# --- F1: unstructured-SEGY pseudo detection + guarded slice reads ---------------


def test_unstructured_segy_binds_pseudo_and_blocks_slice_reads(tmp_path: Path):
    segy = _write_unstructured_segy(tmp_path / "unstructured.sgy")
    src = SeismicVolumeSource(segy)
    meta = src.metadata()

    # The loader's 1 x N mock must not be accepted as real survey geometry.
    assert meta.is_pseudo
    assert not meta.has_geometry
    assert meta.n_inlines == 1
    assert meta.n_crosslines == 100

    # Slice reads raise the clear contract error instead of a raw
    # TypeError/AttributeError from the loader's unstructured handle.
    for reader in (src.read_inline, src.read_crossline, src.read_timeslice):
        with pytest.raises(RuntimeError, match="structured SEGY geometry"):
            reader(0)

    # The preview path stays usable (pseudo fallback) instead of crashing.
    vol, _warning = src.read_preview(max_dim=8, max_budget=512)
    assert vol is None or vol.ndim == 3
    src.close()


def test_structured_segy_still_binds_real_geometry(tmp_path: Path):
    segy = _write_mini_segy(tmp_path / "mini.sgy")
    src = SeismicVolumeSource(segy)
    meta = src.metadata()
    assert meta.has_geometry
    assert not meta.is_pseudo
    assert src.read_inline(0).shape == (10, 16)
    src.close()


# --- F2: shared registry invalidation when the file is replaced ------------------


def test_shared_source_reopened_when_file_replaced(tmp_path: Path):
    segy = _write_mini_segy(tmp_path / "reg.sgy", n_il=8, n_xl=10, n_s=16)
    a = get_shared_seismic_source(segy)
    assert a.metadata().n_inlines == 8

    # Replace the SEGY at the same path (new size + forced new mtime).
    _write_mini_segy(tmp_path / "reg.sgy", n_il=6, n_xl=5, n_s=12)
    os.utime(segy, ns=(0, 0))

    b = get_shared_seismic_source(segy)
    assert b is not a, "registry must not pin the stale pre-replacement source"
    assert a._closed
    assert b.metadata().source_id != a.metadata().source_id
    assert b.metadata().n_inlines == 6


def test_shared_source_reused_while_file_unchanged(tmp_path: Path):
    segy = _write_mini_segy(tmp_path / "same.sgy")
    a = get_shared_seismic_source(segy)
    assert get_shared_seismic_source(segy) is a


# --- F3: progressive L1 starts after the OwnedWorkerJob release ------------------


def test_joint_host_progressive_lod_after_release(qtbot, monkeypatch):
    from PySide6.QtCore import QObject, Signal

    from paleo_workbench.viz import joint_host as mod

    host = mod.WellSeismicJointHost()
    if host.scene is None:
        pytest.skip("geoviz joint scene unavailable")
    volume = np.zeros((4, 4, 4), dtype=np.float32)

    class _FastWorker(QObject):
        finished = Signal(object, str, int, int)
        failed = Signal(str, int)

        def __init__(self, segy_path: str, *, generation: int = 0, lod: int = 0):
            super().__init__()
            self._generation = int(generation)
            self._lod = int(lod)

        def run(self) -> None:  # Slot
            self.finished.emit(volume, "", self._generation, self._lod)

    monkeypatch.setattr(mod, "PreviewVolumeWorker", _FastWorker)
    host._paths = mod.JointAssetPaths(segy=Path("fake.sgy"), source="test")
    statuses: list[str] = []
    host.status_changed.connect(statuses.append)
    try:
        host._start_volume_worker("fake.sgy")

        # L0 result is delivered while OwnedWorkerJob still owns the thread
        # (its queued release lands afterwards) — L1 must nevertheless load.
        # Phases are transient, so assert on the recorded progression.
        qtbot.waitUntil(lambda: any("已加载 L1" in s for s in statuses), timeout=5_000)
        qtbot.waitUntil(lambda: not host._volume_job.is_running, timeout=5_000)

        joined = "\n".join(statuses)
        assert "已加载 L0" in joined, "L0 preview must be delivered first"
        assert "精细化中 (L1)" in joined, "progressive L1 refinement must be scheduled"
        assert host._volume_phase == "L1_READY"
        l0_idx = next(i for i, s in enumerate(statuses) if "已加载 L0" in s)
        l1_idx = next(i for i, s in enumerate(statuses) if "精细化中 (L1)" in s)
        assert l0_idx < l1_idx
    finally:
        host.shutdown()


# --- F4: TD tables parsed once per phase, not once per tops line ----------------


def test_joint_reload_parses_td_tables_once_per_phase(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.project.models import ProjectDocument, ResourceItem
    from paleo_workbench.viz import joint_host as mod

    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    td_dir = tmp_path / "td"
    td_dir.mkdir()
    (td_dir / "TD_A1.dat").write_text(
        "# Well : A1\n0 0 0 0\n100 50 50 100\n200 100 100 200\n",
        encoding="utf-8",
    )
    well_head = tmp_path / "ExportWellHead.dat"
    well_head.write_text("A1 0 0 0 100 0 0\n", encoding="utf-8")
    tops = tmp_path / "wells_tops.txt"
    tops.write_text(
        "\n".join(f"A1 H{i} {100 * i}" for i in range(1, 6)) + "\n",
        encoding="utf-8",
    )
    project = ProjectDocument.new("tdq")
    project.resources.extend(
        [
            ResourceItem(
                id="res:wh", name=well_head.name, path=str(well_head),
                type="well_head", format="dat",
            ),
            ResourceItem(
                id="res:td", name="TD_A1.dat", path=str(td_dir / "TD_A1.dat"),
                type="time_depth", format="dat",
            ),
            ResourceItem(
                id="res:tops", name=tops.name, path=str(tops),
                type="well_tops", format="txt",
            ),
        ]
    )

    calls: list[str] = []
    real = mod.load_td_tables

    def counting_load(td):
        calls.append(str(td))
        return real(td)

    monkeypatch.setattr(mod, "load_td_tables", counting_load)

    host = mod.WellSeismicJointHost()
    if host.scene is None:
        pytest.skip("geoviz joint scene unavailable")
    host.set_project(project)
    host.reload()

    # One parse for wells/survey + one for the tops file — NOT one per top line
    # (previously 1 + n_tops parses on the GUI thread per reload).
    assert calls, "reload should resolve the TD directory"
    assert len(calls) == 2
    host.shutdown()


# --- F5/F6: AttributeTaskWorker typing + unshadowed QThread.finished -------------


def test_attribute_worker_exports_any_and_does_not_shadow_qthread_finished():
    import typing

    import paleo_workbench.viz.seismic_3d_api as api
    from paleo_workbench.viz.seismic_3d_api import AttributeTaskWorker

    # F5: ``Any`` is imported (was an F821 in annotations).
    assert api.Any is typing.Any
    # F6: the ndarray signal is renamed; QThread.finished stays the inherited one.
    assert "result_ready" in AttributeTaskWorker.__dict__
    assert "finished" not in AttributeTaskWorker.__dict__


def test_attribute_worker_emits_result_ready_and_thread_finished(qtbot):
    from paleo_workbench.viz.seismic_3d_api import AttributeTaskWorker

    rng = np.random.default_rng(7)
    volume = rng.standard_normal((8, 8, 12)).astype(np.float32)
    worker = AttributeTaskWorker(volume=volume, attribute_type="coherence_3d")

    results: list[np.ndarray] = []
    thread_done: list[bool] = []
    worker.result_ready.connect(results.append)
    # QThread.finished carries no arguments; connecting it proves it is the
    # inherited thread signal again instead of the ndarray result signal.
    worker.finished.connect(lambda: thread_done.append(True))

    worker.start()
    qtbot.waitUntil(lambda: bool(results) and bool(thread_done), timeout=5_000)

    assert results[0].shape == volume.shape
    assert results[0].dtype == np.float32
