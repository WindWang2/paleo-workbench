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


# ------------------------------------------------- #1194 marker durability


@pytest.mark.skipif(
    not Path("/proc/self").exists(), reason="fd->path resolution needs /proc"
)
def test_band_data_fsynced_before_marker_and_marker_body_fsynced(
    volume, tmp_path, monkeypatch
):
    """#1194: per band, the shard files the band touched are fsynced
    BEFORE the band marker is created, and the marker's own body is
    fsynced (not just its parent directory)."""
    import os as _os

    _, reader, _ = volume
    dst = tmp_path / "attr_fsync"
    done_dir = dst.parent / f"{dst.name}.done"
    events: list[str] = []
    real_fsync = _os.fsync

    def fsync_spy(fd):
        try:
            path = _os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            path = f"fd:{fd}"
        events.append(path)
        return real_fsync(fd)

    monkeypatch.setattr(_os, "fsync", fsync_spy)
    job = VolumeAttributeJob(reader, dst, "c3", band_inlines=18)  # 2 bands
    job.run(TaskContext(task_id="t"))

    marker0 = str(done_dir / "band_000000")
    marker18 = str(done_dir / "band_000018")
    # the marker FILE BODY is fsynced for every band, and the marker dir too
    assert marker0 in events
    assert marker18 in events
    assert str(done_dir) in events
    # marker content intact through the open→write→fsync→close path
    assert (done_dir / "band_000018").read_text() == "ok"
    # band shard data hits the disk before the marker that claims it:
    # between the two markers there is a shard-file fsync (band 1's data),
    # and the first shard fsync precedes the first marker.
    shard_events = [
        (i, p) for i, p in enumerate(events) if f"{dst}/c/" in p
    ]
    assert shard_events, "band shard files must be fsynced at all"
    i0 = events.index(marker0)
    i18 = events.index(marker18)
    assert shard_events[0][0] < i0, "band data fsync must precede its marker"
    assert any(i0 < i < i18 for i, _ in shard_events), (
        "second band's data fsync must land between its predecessor's "
        "marker and its own"
    )
    # #1194 residual: the DIRECTORIES holding those shards are fsynced too —
    # shard bytes alone are not durable if the newly created c/<gi>/<gj>
    # entries are lost. Every shard file's parent directory (plus the store
    # root and the chunk root) must appear, before the band's marker.
    shard_files = {p for _, p in shard_events if not p.endswith("zarr.json")}
    parents = {str(Path(p).parent) for p in shard_files}
    assert parents, "expected at least one shard file under c/"
    assert parents <= set(events), (
        f"shard directories were not fsynced: missing {parents - set(events)}"
    )
    assert str(dst / "c") in events
    assert str(dst) in events
    parent_indices = [events.index(p) for p in parents if p in events]
    assert max(parent_indices) < i0, (
        "directory fsyncs must precede the band marker that claims the data"
    )


# ------------------------------------------- source identity in banding spec


def test_band_spec_switching_source_volume_recomputes(volume, tmp_path):
    """Source identity in the banding spec: two same-shape source volumes,
    same kernel, same band size, SAME reused output store — the second
    volume must NOT trust the first one's band markers (mixed-source DERIVED
    guard); every band recomputes and the result matches the second volume.
    """
    _, reader_a, _ = volume
    # Source B: identical geometry, different data (different seed).
    segy_b = tmp_path / "v_b.segy"
    cube_b = _write_segy(segy_b, seed=99)
    store_b = tmp_path / "store_b"
    transcode_segy_to_zarr(segy_b, store_b, params=PARAMS)
    reader_b = open_volume(store_b)

    dst = tmp_path / "attr_mix"
    job_a = VolumeAttributeJob(reader_a, dst, "c3", band_inlines=18)
    job_b = VolumeAttributeJob(reader_b, dst, "c3", band_inlines=18)
    assert job_a._banding_spec() != job_b._banding_spec(), (
        "same-shape different-source jobs must carry different banding specs"
    )

    job_a.run(TaskContext(task_id="a"))
    assert job_a.completed_bands() == {0, 18}

    # Reuse the store for source B: spec mismatch must discard A's markers
    # and recompute every band (no band may be skipped).
    import paleo_workbench.seismic_attributes as sa

    compute_calls: list[int] = []
    orig = sa.compute_block

    def spy(rd, name, i0, i1, *a, **kw):
        compute_calls.append(i0)
        return orig(rd, name, i0, i1, *a, **kw)

    sa.compute_block = spy
    try:
        stats = job_b.run(TaskContext(task_id="b"))
    finally:
        sa.compute_block = orig
    assert compute_calls == [0, 18], "second source must recompute ALL bands"
    assert stats["bands"] == 2
    # The store now holds B's attribute volume, not a mix of A and B.
    out = zarr.open(str(dst), mode="r")
    np.testing.assert_allclose(
        np.asarray(out[:, :, :]),
        _full_reference(cube_b),
        rtol=1e-6,
        atol=1e-7,
    )


# ------------------------------------------------- #1161 band identity


def test_band_markers_are_identified_by_first_inline(volume, tmp_path):
    """#1161: markers name the band's first INLINE, not its position."""
    _, reader, _ = volume
    dst = tmp_path / "attr_ident"
    job = VolumeAttributeJob(reader, dst, "c3", band_inlines=16)  # 0,16,32
    job.run(TaskContext(task_id="t"))
    names = sorted(p.name for p in job._done_dir().iterdir())
    assert names == ["band_000000", "band_000016", "band_000032"]


def test_band_size_change_invalidates_markers_and_recomputes(volume, tmp_path):
    """#1161: resume with a DIFFERENT band_inlines must not skip misaligned
    bands — old markers are discarded, every band recomputed, and the
    result equals a one-shot full run."""
    cube, reader, _ = volume
    from paleo_workbench.runtime import TaskCancelled

    dst = tmp_path / "attr_reband"
    ref = _full_reference(cube)

    # half-run at band_inlines=16: band 0 done, then cancelled
    job = VolumeAttributeJob(reader, dst, "c3", band_inlines=16)
    ctx = TaskContext(task_id="t")
    original_report = ctx.report_progress

    state = {"n": 0}

    def one_then_cancel(done, total=None, message=""):
        state["n"] += 1
        if state["n"] >= 1:
            ctx.cancelled.set()
        original_report(done, total, message)

    ctx._progress_cb = one_then_cancel
    with pytest.raises(TaskCancelled):
        job.run(ctx)
    assert job.completed_bands() == {0}

    # resume at band_inlines=9: banding changed → markers reset, 4 fresh
    # bands (36/9), output identical to a one-shot run
    job2 = VolumeAttributeJob(reader, dst, "c3", band_inlines=9)
    stats = job2.run(TaskContext(task_id="t2"))
    assert stats["bands"] == 4
    assert job2.completed_bands() == {0, 9, 18, 27}
    out = zarr.open(str(dst), mode="r")
    np.testing.assert_allclose(
        np.asarray(out[:, :, :]), ref, rtol=1e-6, atol=1e-7
    )


# ------------------------------------------------- #1146 band derivation


def test_derive_band_inlines_bounded_and_monotonic():
    from paleo_workbench.seismic_attributes import (
        BAND_INLINES_MAX,
        BAND_INLINES_MIN,
        _BAND_COPIES,
        derive_band_inlines,
    )

    shape = (500, 600, 800)  # bytes/inline = 600*800*4 = 1.92 MiB
    halo = (5, 5, 5)
    budgets = [256 << 20, 1 << 30, 2 << 30, 5 << 30, 20 << 30]
    bands = [
        derive_band_inlines(shape, halo=halo, budget_bytes=b) for b in budgets
    ]
    for b in bands:
        assert BAND_INLINES_MIN <= b <= BAND_INLINES_MAX
    assert bands == sorted(bands), "band size must not shrink as budget grows"

    # mid-range (unclamped) budgets respect the share bound:
    # copies*(band+2*halo_il)*bytes_per_inline <= share*budget (+1 inline slack)
    bytes_per_inline = 600 * 800 * 4
    for band, budget in zip(bands, budgets):
        if BAND_INLINES_MIN < band < BAND_INLINES_MAX:
            working = _BAND_COPIES * (band + 2 * halo[0]) * bytes_per_inline
            assert working <= 0.25 * budget + _BAND_COPIES * bytes_per_inline

    # tiny budget clamps to the floor (progress guarantee, bounded batch)
    assert (
        derive_band_inlines(shape, halo=halo, budget_bytes=1) == BAND_INLINES_MIN
    )
    # huge budget clamps to the ceiling (no 12-20 GB RSS regression)
    assert (
        derive_band_inlines(shape, halo=halo, budget_bytes=1 << 40)
        == BAND_INLINES_MAX
    )


def test_volume_attribute_job_default_band_derives_from_budget(
    volume, tmp_path, monkeypatch
):
    """#1146: constructing VolumeAttributeJob without band_inlines derives
    the band size from the budget, not a hardcoded 64."""
    import paleo_workbench.seismic_attributes as sa

    _, reader, _ = volume
    seen = {}

    def fake_derive(shape, *, halo=(0, 0, 0), budget_bytes=None, **kw):
        seen["shape"] = shape
        seen["halo"] = halo
        return 11

    monkeypatch.setattr(sa, "derive_band_inlines", fake_derive)
    job = sa.VolumeAttributeJob(reader, tmp_path / "x", "c3")
    assert job.band_inlines == 11
    assert seen["shape"] == tuple(reader.shape)
    assert seen["halo"] == sa.attribute_halo("c3")


def test_start_attribute_job_passes_budget_derived_band(tmp_path, monkeypatch):
    """#1146: the lifecycle queries the active budget and passes the
    derived band size into the job (transcode-style budget coupling).

    Self-contained store (the module fixture's store is MOVED by whichever
    catalog test consumes it first)."""
    from paleo_workbench.runtime import resource_budget
    import paleo_workbench.seismic_attributes as sa

    work = tmp_path / "w"
    work.mkdir(parents=True)
    _, store = _write_small_segy(work)
    reader = open_volume(store)
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project)
    sched = TaskScheduler(max_workers=1)
    try:
        raw = catalog.link_external(work / "roi.segy", name="v", type="seismic")
        run = catalog.register_run("segy-to-zarr", input_version_ids=[raw.id])
        derived = catalog.register_derived_store(
            name="seismic store", store_path=store, run_id=run.id,
            parent_version_ids=[raw.id], type="seismic", format="zarr-v3",
        )
        catalog.update_run_status(run.id, "complete")

        # pin a small budget: 8 GB machine -> 1.25 GiB streaming buffer
        monkeypatch.setattr(
            resource_budget, "_ACTIVE", resource_budget.ResourceBudget.for_total_ram_gb(8)
        )
        recorded = {}
        real_cls = sa.VolumeAttributeJob

        class Recorder(real_cls):
            def __init__(self, reader, dst, name="c3", **kw):
                recorded["band_inlines"] = kw.get("band_inlines")
                super().__init__(reader, dst, name, **kw)

        monkeypatch.setattr(sa, "VolumeAttributeJob", Recorder)
        handle = start_attribute_job(catalog, derived.id, "c3", scheduler=sched)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and handle.state not in (
            TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED
        ):
            time.sleep(0.05)
        assert handle.state == TaskState.DONE, f"job failed: {handle.error}"

        expected = sa.derive_band_inlines(
            tuple(reader.shape),
            halo=sa.attribute_halo("c3"),
            budget_bytes=resource_budget.active_budget().streaming_buffer_bytes,
        )
        assert recorded["band_inlines"] == expected
        assert 8 <= recorded["band_inlines"] <= 64
        # the band plan is pinned in the run parameters for provenance
        attr_runs = [
            r for r in catalog.document.runs if r.operation == "attribute:c3"
        ]
        assert attr_runs and attr_runs[-1].parameters.get("band_inlines") == expected
    finally:
        sched.shutdown(wait=True, timeout=10.0)
        catalog.close()


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


def test_provider_entry_roi_returns_correct_result(tmp_path):
    """#1132: the provider ROI path must call roi_attribute with bounds and
    return the same window the direct call produces."""
    from paleo_workbench.providers.base import ProviderContext
    from paleo_workbench.providers.builtin.seismic_attribute import (
        SeismicAttributeProvider,
    )
    from paleo_workbench.providers.execution import execute_provider
    from paleo_workbench.providers.refs import SeismicVolumeRef

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
