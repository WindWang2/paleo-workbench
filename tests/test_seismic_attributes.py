"""Out-of-core seismic attributes (#1083/#1084): kernel/halo parity contracts.

The scientific-correctness core of the attribute story: for a window-local
operator, band+halo output MUST equal full-memory output on the same
samples — any band-boundary seam is a BLOCKER. Also pins the resumable
band-marker protocol and the DERIVED/DataRun registration.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

from geoviz_seismic import open_volume  # noqa: E402
from paleo_workbench.catalog.service import DataCatalogService  # noqa: E402
from paleo_workbench.runtime import TaskContext, TaskScheduler, TaskState  # noqa: E402
from paleo_workbench.seismic_attributes import (  # noqa: E402
    VolumeAttributeJob,
    attribute_halo,
    compute_block,
    roi_attribute,
)
from paleo_workbench.seismic_lifecycle import start_attribute_job  # noqa: E402
from paleo_workbench.seismic_transcode import (  # noqa: E402
    TranscodeParams,
    transcode_segy_to_zarr,
)

# Small enough for a full-memory reference; > 2*halo on every axis so both
# interior and clamped-edge bands are exercised.
NIL, NXL, NT = 36, 40, 48
PARAMS = TranscodeParams(chunk=(8, 16, 16), shard=(32, 32, 32), clevel=1)
HALO = attribute_halo("c3")  # (5, 5, 5)


def _write_segy(path: Path, seed: int = 21) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.5).astype(np.float32)
    # A few coherent events so C3 has structure to lock onto.
    cube[8:12, 10:30, 20:28] += 2.0
    cube[20:26, :, 5:10] -= 1.5
    spec = segyio.spec()
    spec.ilines = list(range(1, NIL + 1))
    spec.xlines = list(range(1, NXL + 1))
    spec.samples = list(range(NT))
    spec.format = 5
    with segyio.create(str(path), spec) as f:
        for il in range(NIL):
            for xl in range(NXL):
                i = il * NXL + xl
                f.header[i] = {
                    segyio.TraceField.INLINE_3D: il + 1,
                    segyio.TraceField.CROSSLINE_3D: xl + 1,
                    segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                }
                f.trace[i] = cube[il, xl]
    return cube


@pytest.fixture(scope="module")
def volume(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("attr")
    segy = tmp / "v.segy"
    cube = _write_segy(segy)
    store = tmp / "store"
    transcode_segy_to_zarr(segy, store, params=PARAMS)
    reader = open_volume(store)
    return cube, reader, store


def _full_reference(cube: np.ndarray) -> np.ndarray:
    from geoviz_seismic.attributes import compute_coherence_c3

    return compute_coherence_c3(cube, win_il=5, win_xl=5, win_t=5)


# ------------------------------------------------------------------- ROI


def test_roi_matches_full_memory_reference(volume):
    cube, reader, _ = volume
    ref = _full_reference(cube)
    il0, il1, xl0, xl1, t0, t1 = 6, 26, 8, 30, 10, 40
    got = roi_attribute(reader, (il0, il1, xl0, xl1, t0, t1))
    assert got.shape == (il1 - il0, xl1 - xl0, t1 - t0)
    expected = ref[il0:il1, xl0:xl1, t0:t1]
    # Same kernel invoked on the same neighbourhoods: bitwise equality is
    # the contract; allow float-identical allclose as the formal assert.
    np.testing.assert_allclose(got, expected, rtol=1e-6, atol=1e-7)
    assert np.array_equal(got, expected), "band/halo output must be bitwise-identical"


def test_roi_at_survey_edges_matches_reference(volume):
    """Clamped halos reproduce the full-volume edge behaviour."""
    cube, reader, _ = volume
    ref = _full_reference(cube)
    got = roi_attribute(reader, (0, 12, 0, 15, 0, 20))
    np.testing.assert_allclose(got, ref[0:12, 0:15, 0:20], rtol=1e-6, atol=1e-7)
    got2 = roi_attribute(reader, (NIL - 10, NIL, NXL - 12, NXL, NT - 15, NT))
    np.testing.assert_allclose(
        got2, ref[NIL - 10 :, NXL - 12 :, NT - 15 :], rtol=1e-6, atol=1e-7
    )


def test_roi_never_reads_outside_window_plus_halo(volume):
    """Out-of-core guarantee: the reader must not be asked for the whole
    volume — pin the requested window span via a spy reader."""
    _, reader, _ = volume
    calls: list[tuple] = []

    class SpyReader:
        shape = reader.shape
        geometry = reader.geometry

        def read_voxel_window(self, *args, **kwargs):
            calls.append(args)
            return reader.read_voxel_window(*args, **kwargs)

    roi_attribute(SpyReader(), (10, 18, 10, 20, 10, 30))
    assert len(calls) == 1, "ROI must be ONE batched voxel-window read"
    il0, il1, xl0, xl1, t0, t1 = calls[0]
    assert (il1 - il0) <= 8 + 2 * HALO[0]
    assert (xl1 - xl0) <= 10 + 2 * HALO[1]
    assert (t1 - t0) <= 20 + 2 * HALO[2]


# ----------------------------------------------------------- band parity


def test_band_output_matches_full_reference_everywhere(volume):
    """Every band, including clamped first/last: interior == full-memory."""
    cube, reader, _ = volume
    ref = _full_reference(cube)
    band = 7  # does not divide NIL: uneven last band
    for i0 in range(0, NIL, band):
        i1 = min(i0 + band, NIL)
        got = compute_block(reader, "c3", i0, i1, 0, NXL, 0, NT)
        np.testing.assert_allclose(
            got, ref[i0:i1], rtol=1e-6, atol=1e-7,
            err_msg=f"band [{i0}:{i1}) diverged from full-memory reference",
        )
        assert np.array_equal(got, ref[i0:i1])


# -------------------------------------------------------- full-volume job


def test_full_volume_job_output_and_shape(volume, tmp_path):
    cube, reader, _ = volume
    dst = tmp_path / "attr_out"
    job = VolumeAttributeJob(reader, dst, "c3", band_inlines=9)
    ctx = TaskContext(task_id="test")
    stats = job.run(ctx)
    assert stats["bands"] == (NIL + 8) // 9
    out = zarr.open(str(dst), mode="r")
    assert tuple(out.shape) == (NIL, NXL, NT)
    ref = _full_reference(cube)
    np.testing.assert_allclose(
        np.asarray(out[:, :, :]), ref, rtol=1e-6, atol=1e-7
    )


def test_job_resume_skips_completed_bands(volume, tmp_path):
    _, reader, _ = volume
    dst = tmp_path / "attr_resume"
    job = VolumeAttributeJob(reader, dst, "c3", band_inlines=9)
    # Simulate a previously completed first band (marker only, honest: the
    # marker protocol is what resume trusts — a marker without data is a
    # corrupt state the probe would rewrite via zarr read failure).
    done = dst.parent / f"{dst.name}.done"
    done.mkdir(parents=True)
    (done / "band_000000").write_text("ok")

    compute_calls: list[tuple[int, int]] = []
    import paleo_workbench.seismic_attributes as sa

    orig = sa.compute_block

    def spy(rd, name, i0, i1, *a, **kw):
        compute_calls.append((i0, i1))
        return orig(rd, name, i0, i1, *a, **kw)

    sa.compute_block = spy
    try:
        stats = job.run(TaskContext(task_id="t"))
    finally:
        sa.compute_block = orig
    # band 0 (inlines 0-8) skipped: first computed band starts at 9
    assert compute_calls[0][0] == 9
    assert stats["bands"] == 4  # 36/9
    assert len(compute_calls) == 3


def test_job_cancel_keeps_completed_bands(volume, tmp_path):
    _, reader, _ = volume
    from paleo_workbench.runtime import TaskCancelled

    dst = tmp_path / "attr_cancel"
    job = VolumeAttributeJob(reader, dst, "c3", band_inlines=9)
    ctx = TaskContext(task_id="t")
    # Cancel after the second band's compute — first two bands stay done.
    original_report = ctx.report_progress

    state = {"n": 0}

    def counting_report(done, total=None, message=""):
        state["n"] += 1
        if state["n"] >= 2:
            ctx.cancelled.set()
        original_report(done, total, message)

    ctx._progress_cb = counting_report
    with pytest.raises(TaskCancelled):
        job.run(ctx)
    assert job.completed_bands() == {0}
    # resume completes the rest
    stats = job.run(TaskContext(task_id="t2"))
    assert stats["bands"] == 4


# --------------------------------------------------------- lifecycle glue


def test_attribute_job_registers_derived_and_run(volume, tmp_path):
    cube, reader, store = volume
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project)
    sched = TaskScheduler(max_workers=1)
    try:
        # register the chunked store as a DERIVED version first (transcode
        # output equivalent) so the attribute job has a catalog source
        raw = catalog.link_external(store.parent / "v.segy", name="v", type="seismic")
        run = catalog.register_run("segy-to-zarr", input_version_ids=[raw.id])
        derived = catalog.register_derived_store(
            name="seismic store", store_path=store, run_id=run.id,
            parent_version_ids=[raw.id], type="seismic", format="zarr-v3",
        )
        catalog.update_run_status(run.id, "complete")

        handle = start_attribute_job(catalog, derived.id, "c3", scheduler=sched)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and handle.state not in (
            TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED
        ):
            time.sleep(0.05)
        assert handle.state == TaskState.DONE, f"job failed: {handle.error}"

        # DERIVED attribute version with lineage to the seismic store
        attr_versions = [
            v for v in catalog.document.versions
            if v.metadata.get("attribute") == "c3"
        ]
        assert len(attr_versions) == 1
        av = attr_versions[0]
        assert av.stage.value == "derived"
        assert derived.id in av.parent_version_ids
        attr_run = catalog.get_run(av.run_id)
        assert attr_run.operation == "attribute:c3"
        assert attr_run.status.lower() == "complete"
        assert derived.id in attr_run.input_version_ids
        # the attribute store itself is readable through open_volume
        vol = open_volume(catalog.resolve_path(av))
        assert vol.shape == (NIL, NXL, NT)
    finally:
        sched.shutdown(wait=True, timeout=10.0)
        catalog.close()


# ------------------------------------------------- #1132 provider ROI entry


def _write_small_segy(path):
    """Self-sufficient 12x12x16 volume (the module fixture's store is
    mutated by the catalog test above; ROI entry must not depend on it)."""
    from pathlib import Path as _Path  # noqa: F401  (kept local: test-only helper)

    import numpy as _np

    from paleo_workbench.seismic_transcode import TranscodeParams as _Params
    from paleo_workbench.seismic_transcode import transcode_segy_to_zarr as _transcode

    nil, nxl, nt = 12, 12, 16
    rng = _np.random.default_rng(7)
    cube = (rng.standard_normal((nil, nxl, nt)) * 0.5).astype(_np.float32)
    cube[3:6, 3:9, 5:10] += 2.0
    spec = segyio.spec()
    spec.ilines = list(range(1, nil + 1))
    spec.xlines = list(range(1, nxl + 1))
    spec.samples = list(range(nt))
    spec.format = 5
    segy = path / "roi.segy"
    with segyio.create(str(segy), spec) as f:
        for il in range(nil):
            for xl in range(nxl):
                i = il * nxl + xl
                f.header[i] = {
                    segyio.TraceField.INLINE_3D: il + 1,
                    segyio.TraceField.CROSSLINE_3D: xl + 1,
                    segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                }
                f.trace[i] = cube[il, xl]
    store = path / "roi_store"
    _transcode(segy, store, params=_Params(chunk=(4, 4, 4), shard=(8, 8, 8), clevel=1))
    return cube, store


def test_provider_entry_roi_returns_correct_result(tmp_path, monkeypatch):
    """#1132: the provider ROI path must call roi_attribute with bounds and
    return the same window the direct call produces."""
    import paleo_workbench.providers.execution as execution_module
    from paleo_workbench.providers.base import ProviderContext
    from paleo_workbench.providers.builtin.seismic_attribute import (
        SeismicAttributeProvider,
    )
    from paleo_workbench.providers.execution import execute_provider
    from paleo_workbench.providers.refs import SeismicVolumeRef

    class _NullLease:
        def release(self) -> None:
            pass

    # Admission (5 GiB full-volume profile) depends on machine pressure;
    # this contract is about ROI plumbing, covered hermetically here
    # (admission itself is pinned by governor tests).
    monkeypatch.setattr(
        execution_module, "_governor_lease", lambda *args: _NullLease()
    )

    cube, store = _write_small_segy(tmp_path)
    provider = SeismicAttributeProvider("c3", {})
    bounds = {"il0": 2, "il1": 10, "xl0": 2, "xl1": 10, "t0": 2, "t1": 14}
    result = execute_provider(
        provider,
        inputs={"volume": SeismicVolumeRef(volume_id="v", path=str(store))},
        parameters={"roi": bounds},
        context=ProviderContext(work_dir=str(tmp_path)),
    )
    got = result.artifacts[0].value
    assert isinstance(got, np.ndarray)
    assert got.shape == (8, 8, 12)
    np.testing.assert_allclose(
        got, _full_reference(cube)[2:10, 2:10, 2:14], rtol=1e-6, atol=1e-7
    )
    assert result.diagnostics["mode"] == "roi"


def test_attribute_provider_cancel_propagates_task_cancelled(tmp_path):
    """#1137: a cancelled full-volume attribute run must raise TaskCancelled,
    never a washed ProviderExecutionError."""
    from types import SimpleNamespace

    from paleo_workbench.providers.base import ProviderContext
    from paleo_workbench.providers.builtin.seismic_attribute import (
        SeismicAttributeProvider,
    )
    from paleo_workbench.providers.errors import ProviderExecutionError
    from paleo_workbench.providers.refs import SeismicVolumeRef
    from paleo_workbench.runtime.task_scheduler import TaskCancelled

    _cube, store = _write_small_segy(tmp_path)
    provider = SeismicAttributeProvider("c3", {})
    context = ProviderContext(
        work_dir=str(tmp_path),
        cancel=SimpleNamespace(is_cancelled=True),
    )
    with pytest.raises(TaskCancelled):
        try:
            provider.execute(
                {"volume": SeismicVolumeRef(volume_id="v", path=str(store))},
                {"output_dir": str(tmp_path / "attr_out")},
                context,
            )
        except ProviderExecutionError as exc:
            raise AssertionError(f"cancel was washed: {exc}") from exc


def test_band_inlines_derived_from_budget_not_constant():
    """#1146: band width follows budget/geometry; explicit values honored."""
    from paleo_workbench.seismic_attributes import (
        ATTRIBUTE_PEAK_FACTOR,
        VolumeAttributeJob,
        derive_band_inlines,
    )

    budget = 5 * 1024**3
    small = derive_band_inlines(40, 48, budget_bytes=budget)
    huge = derive_band_inlines(2000, 2000, budget_bytes=budget)
    assert small > huge >= 1
    # Peak math holds by construction.
    assert 2000 * 2000 * 4 * huge * ATTRIBUTE_PEAK_FACTOR <= budget + 2000 * 2000 * 4 * ATTRIBUTE_PEAK_FACTOR
    assert derive_band_inlines(0, 0, budget_bytes=budget) >= 1

    class _Reader:
        shape = (100, 40, 48)

    job = VolumeAttributeJob(_Reader(), "/tmp/x", "c3")
    assert job.band_inlines == derive_band_inlines(40, 48)
    explicit = VolumeAttributeJob(_Reader(), "/tmp/x", "c3", band_inlines=9)
    assert explicit.band_inlines == 9


def test_attribute_provider_ram_estimate_matches_band_peak():
    """#1146: admission estimate is the same order as a derived band peak."""
    from paleo_workbench.providers.builtin.seismic_attribute import SeismicAttributeProvider

    estimate = SeismicAttributeProvider("c3", {}).descriptor.resource_profile.estimated_ram_bytes
    assert estimate >= 4 * 1024**3


def test_band_data_and_marker_fsynced_before_done(tmp_path, monkeypatch):
    """#1194: band shard files + marker content are fsynced before the
    band is trusted on resume."""
    import os as _os

    from paleo_workbench.runtime import TaskContext
    from paleo_workbench.seismic_attributes import VolumeAttributeJob

    _cube, store = _write_small_segy(tmp_path)
    dst = tmp_path / "attr_out"
    job = VolumeAttributeJob(open_volume(store), dst, "c3", band_inlines=12)

    opened: dict[int, str] = {}
    real_open, real_fsync = _os.open, _os.fsync
    fsynced: list[str] = []

    def _spy_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        try:
            opened[fd] = str(path)
        except Exception:
            pass
        return fd

    def _spy_fsync(fd):
        fsynced.append(opened.get(fd, fd))
        return real_fsync(fd)

    monkeypatch.setattr(_os, "open", _spy_open)
    monkeypatch.setattr(_os, "fsync", _spy_fsync)
    job.run(TaskContext(task_id="t"))
    marker = str(dst.parent / f"{dst.name}.done" / "band_000000")
    assert marker in fsynced  # marker content, not just the directory
    # Windows 用反斜杠：统一分隔符后再匹配分片路径。
    shard_hits = [p for p in fsynced
                  if isinstance(p, str) and "/c/" in p.replace("\\", "/")]
    assert shard_hits, "band shard files must be fsynced before marking done"
