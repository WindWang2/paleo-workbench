"""LOD interactive render path (#1082): policy, prefetcher, chunked worker.

LodPolicy is a pure state machine (injected clock). DirectionalPrefetcher
and ChunkedSliceWorker run REAL threads/Qt signals against a REAL zarr
store produced by the production transcoder. No GL context is needed —
the worker is the interactive read path, rendering happens in the view.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

pytestmark = pytest.mark.usefixtures("qapp")

from PySide6.QtWidgets import QApplication  # noqa: E402

from geoviz_seismic.chunked_worker import ChunkedSliceWorker  # noqa: E402
from geoviz_seismic.lod import DirectionalPrefetcher, LodPolicy  # noqa: E402
from paleo_workbench.seismic_transcode import (  # noqa: E402
    TranscodeParams,
    transcode_segy_to_zarr,
)

NIL, NXL, NT = 32, 36, 40
PARAMS = TranscodeParams(chunk=(8, 16, 16), shard=(32, 32, 32), clevel=1)


def _write_segy(path: Path, seed: int = 9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.3).astype(np.float32)
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
def store(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("lod")
    segy = tmp / "v.segy"
    cube = _write_segy(segy)
    dst = tmp / "store"
    transcode_segy_to_zarr(segy, dst, params=PARAMS)
    return dst, cube


# --------------------------------------------------------------- LodPolicy


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds: float):
        self.t += seconds


def test_policy_demotes_when_reads_blow_frame_budget():
    clock = FakeClock()
    p = LodPolicy(max_lod=3, frame_budget_ms=16.0, idle_ms=250.0, clock=clock)
    p.begin_interaction()
    assert p.select_lod() == 0
    # lod0 reads consistently over budget -> demote step by step
    p.record_read(0, 40.0)
    p.record_read(0, 42.0)
    assert p.select_lod() == 1
    p.record_read(1, 44.0)
    assert p.select_lod() == 2
    p.record_read(2, 9.0)  # within budget now
    assert p.select_lod() == 2
    assert p.select_lod() == 2  # stable while in budget


def test_policy_idle_refinement_walks_to_lod0():
    clock = FakeClock()
    p = LodPolicy(max_lod=3, idle_ms=250.0, clock=clock)
    p._current = 2
    p.end_interaction()
    clock.advance(0.3)
    assert p.refine_step() == 1
    clock.advance(0.3)
    assert p.refine_step() == 0
    clock.advance(0.3)
    assert p.refine_step() is None  # already at lod0
    # interaction resets the idle path and latency memory
    p.record_read(0, 99.0)
    p.begin_interaction()
    clock.advance(5.0)
    assert not p.idle_refine_ready()


def test_policy_frame_smoothing():
    p = LodPolicy()
    for v in (10, 20, 30):
        p.record_frame(v)
    assert p.smoothed_frame_ms() == pytest.approx(20.0)


# ------------------------------------------------------ DirectionalPrefetcher


def test_prefetcher_follows_direction_and_generation():
    reads: list[tuple[int, int]] = []
    done = threading.Event()

    def read(pos, lod):
        reads.append((pos, lod))
        if len(reads) >= 4:
            done.set()

    pf = DirectionalPrefetcher(read, ahead=4)
    pf.update(10, lod=0)  # first position establishes baseline
    pf.update(12, lod=0)  # moving up
    assert done.wait(2.0)
    pf.cancel()
    assert all(pos > 12 for pos, _ in reads), f"prefetch must lead upward: {reads}"
    assert all(lod == 0 for _, lod in reads)


def test_prefetcher_new_generation_supersedes_batch():
    reads: list[int] = []
    gate = threading.Event()

    def read(pos, lod):
        gate.wait(1.0)
        reads.append(pos)

    pf = DirectionalPrefetcher(read, ahead=3)
    pf.update(100, lod=0)  # baseline only (no direction yet)
    pf.update(101, lod=0)  # batch [102..104] starts, blocked on the gate
    pf.update(104, lod=0)  # newer generation supersedes it
    gate.set()
    time.sleep(0.2)
    pf.cancel()
    # Cancellation is exact for not-yet-started reads; the ONE in-flight
    # read may complete (check-then-act between generation test and IO).
    assert len(reads) <= 1, f"superseded batch continued: {reads}"
    if reads:
        assert reads[0] == 102


# -------------------------------------------------------- ChunkedSliceWorker


def _drain_events(ms: float = 20.0):
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    time.sleep(ms / 1000.0)
    if app is not None:
        app.processEvents()


def _wait_signals(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _drain_events(10.0)
        if cond():
            return True
    return False


def test_worker_serves_requests_from_real_store(store):
    dst, cube = store
    worker = ChunkedSliceWorker()
    got: list[tuple[str, int, int, np.ndarray]] = []
    worker.slice_ready.connect(
        lambda t, pos, data, gen: got.append((t, pos, gen, np.array(data)))
    )
    try:
        worker.set_store(str(dst), generation=7)
        worker.request("inline", 5, 7)
        assert _wait_signals(lambda: len(got) >= 1), f"no slice_ready, got={got}"
        t, pos, gen, data = got[0]
        assert (t, pos, gen) == ("inline", 5, 7)
        np.testing.assert_allclose(data, cube[4], atol=1e-6)
    finally:
        worker.stop()


def test_worker_latest_positions_refine_after_idle(store):
    dst, cube = store
    worker = ChunkedSliceWorker()
    got: list[tuple[str, int, int, np.ndarray]] = []
    worker.slice_ready.connect(
        lambda t, pos, data, gen: got.append((t, pos, gen, np.array(data)))
    )
    try:
        worker.set_store(str(dst), generation=1)
        # Force a demoted level so the idle path has two refinements to walk
        # (lod2 serve -> lod1 refine -> lod0 refine).
        worker.policy._current = 2
        worker.request("inline", 3, 1)
        assert _wait_signals(lambda: len(got) >= 1)
        assert got[0][3].shape == (NXL // 4, NT // 4)  # served at lod2
        assert _wait_signals(lambda: len(got) >= 3, timeout=6.0), (
            f"idle refinement did not reach lod0: {[(g[0], g[3].shape) for g in got]}"
        )
        final = got[-1]
        assert final[1] == 3
        np.testing.assert_allclose(final[3], cube[2], atol=1e-6)
        # refinement walked strictly finer planes
        assert got[1][3].shape == (NXL // 2, NT // 2)
    finally:
        worker.stop()


def test_worker_generation_guard_drops_stale_requests(store):
    dst, _ = store
    worker = ChunkedSliceWorker()
    got: list[tuple[int, int]] = []
    worker.slice_ready.connect(lambda t, pos, data, gen: got.append((pos, gen)))
    try:
        worker.set_store(str(dst), generation=1)
        worker.set_store(str(dst), generation=2)
        worker.request("inline", 3, 1)  # stale generation
        worker.request("inline", 4, 2)
        assert _wait_signals(lambda: len(got) >= 1)
        assert all(g == 2 for _, g in got), f"stale generation leaked: {got}"
    finally:
        worker.stop()


def test_worker_reports_unreadable_store(tmp_path):
    worker = ChunkedSliceWorker()
    errors: list[tuple[str, int, int]] = []
    worker.read_error.connect(lambda t, pos, gen: errors.append((t, pos, gen)))
    try:
        worker.set_store(str(tmp_path / "nope"), generation=1)
        worker.request("inline", 1, 1)
        assert _wait_signals(lambda: len(errors) >= 1), "no read_error for bad store"
    finally:
        worker.stop()
