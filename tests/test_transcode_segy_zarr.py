"""Tests for the SEG-Y → Zarr v3 production transcoder (#1077)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

from paleo_workbench.seismic_transcode import (  # noqa: E402
    TranscodeError,
    TranscodeParams,
    transcode_segy_to_zarr,
)

# Irregular shape on purpose: exercises edge chunks/shards
# (chunk 64×128×128 / shard 128×512×512 all fail to divide evenly).
NIL, NXL, NT = 150, 300, 200


def _write_segy(path: Path, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.4).astype(np.float32)
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
def segy_volume(tmp_path_factory) -> tuple[Path, np.ndarray]:
    path = tmp_path_factory.mktemp("segy") / "small.segy"
    return path, _write_segy(path)


def _shard_plan():
    """Shard grid boxes for (NIL, NXL, NT) under the default params."""
    from paleo_workbench.seismic_transcode import shard_boxes

    return list(shard_boxes((NIL, NXL, NT), TranscodeParams()))


def test_params_land_in_zarr_json(segy_volume, tmp_path):
    src, _ = segy_volume
    dst = tmp_path / "store"
    transcode_segy_to_zarr(src, dst)
    meta = json.loads((dst / "zarr.json").read_text())
    assert meta["chunk_grid"]["configuration"]["chunk_shape"] == [128, 512, 512]
    codecs = meta["codecs"]
    sharding = next(c for c in codecs if c["name"] == "sharding_indexed")
    assert sharding["configuration"]["chunk_shape"] == [64, 128, 128]
    blosc = next(
        c for c in sharding["configuration"]["codecs"] if c["name"] == "blosc"
    )
    cfg = blosc["configuration"]
    assert cfg["cname"] == "zstd"
    assert cfg["clevel"] == 5
    assert cfg["shuffle"] == "shuffle"  # byte shuffle ON, bitshuffle OFF (#1070)


def test_readback_parity_full_volume(segy_volume, tmp_path):
    src, cube = segy_volume
    dst = tmp_path / "store"
    result = transcode_segy_to_zarr(src, dst)
    assert tuple(result.shape) == (NIL, NXL, NT)
    arr = zarr.open(str(dst), mode="r")
    got = np.asarray(arr[:, :, :])
    assert got.dtype == np.float32
    np.testing.assert_array_equal(got, cube)


def test_attributes_record_source(segy_volume, tmp_path):
    src, _ = segy_volume
    dst = tmp_path / "store"
    transcode_segy_to_zarr(src, dst)
    arr = zarr.open(str(dst), mode="r")
    attrs = dict(arr.attrs)
    assert attrs["source_format"] == "seg-y"
    assert attrs["transcode"]["bitshuffle"] is False
    assert attrs["shape"] == [NIL, NXL, NT]


def test_resume_skips_completed_shards(segy_volume, tmp_path):
    src, cube = segy_volume
    dst = tmp_path / "store"

    # Run 1: cancel after the first shard completes.
    progress1 = []
    state = {"done": 0}

    def prog(frac: float) -> None:
        state["done"] += 1
        progress1.append(frac)

    transcode_segy_to_zarr(
        src, dst, progress=prog, cancel=lambda: state["done"] >= 1, workers=1
    )
    assert progress1[-1] < 1.0  # stopped early, partial store
    boxes = _shard_plan()
    assert len(boxes) >= 2  # fixture guarantees resumable remainder

    # Run 2: full run over the partial store; only remaining shards read traces.
    result = transcode_segy_to_zarr(src, dst)
    expected_max = sum(
        (b.il1 - b.il0) * (b.xl1 - b.xl0) for b in boxes[1:]
    )
    assert result.stats.shards_skipped == 1
    assert result.stats.traces_read <= expected_max
    assert result.stats.traces_read > 0

    arr = zarr.open(str(dst), mode="r")
    np.testing.assert_array_equal(np.asarray(arr[:, :, :]), cube)


def test_truncated_shard_is_redone(segy_volume, tmp_path):
    src, cube = segy_volume
    dst = tmp_path / "store"
    transcode_segy_to_zarr(src, dst)
    # Corrupt one shard file: truncate to simulate a kill mid-write.
    shard_files = sorted((dst / "c").rglob("*"))
    real = [p for p in shard_files if p.is_file()]
    assert real
    victim = real[0]
    data = victim.read_bytes()
    victim.write_bytes(data[: len(data) // 2])
    result = transcode_segy_to_zarr(src, dst)
    assert result.stats.shards_written >= 1  # the corrupt one was redone
    arr = zarr.open(str(dst), mode="r")
    np.testing.assert_array_equal(np.asarray(arr[:, :, :]), cube)


def test_parallel_workers_match_serial(segy_volume, tmp_path):
    src, cube = segy_volume
    dst = tmp_path / "store"
    result = transcode_segy_to_zarr(src, dst, workers=4)
    assert result.stats.shards_written == len(_shard_plan())
    arr = zarr.open(str(dst), mode="r")
    np.testing.assert_array_equal(np.asarray(arr[:, :, :]), cube)


def test_progress_monotonic_to_one(segy_volume, tmp_path):
    src, _ = segy_volume
    seen = []
    transcode_segy_to_zarr(src, tmp_path / "store", progress=seen.append)
    assert seen == sorted(seen)
    assert seen[-1] == 1.0


def test_rejects_mismatched_existing_store(segy_volume, tmp_path):
    src, _ = segy_volume
    dst = tmp_path / "store"
    transcode_segy_to_zarr(src, dst)
    bad = TranscodeParams(chunk=(32, 128, 128), shard=(64, 512, 512))
    with pytest.raises(TranscodeError):
        transcode_segy_to_zarr(src, dst, params=bad)


# ------------------------------------------------------------- #1136 cancel


def _reader_threads_alive() -> int:
    return sum(
        1
        for t in threading.enumerate()
        if t.name == "segy-transcode-reader" and t.is_alive()
    )


def test_cancel_parallel_reader_thread_exits_and_store_resumes(segy_volume, tmp_path):
    """#1136: cancelling mid-transcode must not strand the reader thread on
    a full queue (bounded puts + stop signal), must not close its segyio
    handle from under it, and must leave a resumable partial store."""
    src, cube = segy_volume
    dst = tmp_path / "store"
    assert _reader_threads_alive() == 0

    state = {"done": 0}

    def prog(frac: float) -> None:
        state["done"] += 1

    result = transcode_segy_to_zarr(
        src, dst, progress=prog, cancel=lambda: state["done"] >= 1, workers=3
    )
    # function returned (no hang), no exception leaked, reader really exited
    assert _reader_threads_alive() == 0
    assert result.stats.shards_written >= 1
    assert (
        result.stats.shards_written + result.stats.shards_skipped
        < result.stats.shards_total
    ), "cancel must stop before the whole store is written"

    # partial store is resumable: same source completes and matches bit-exact
    result2 = transcode_segy_to_zarr(src, dst)
    assert result2.stats.shards_skipped >= 1
    arr = zarr.open(str(dst), mode="r")
    np.testing.assert_array_equal(np.asarray(arr[:, :, :]), cube)
    assert _reader_threads_alive() == 0


def test_cancel_immediately_returns_cleanly(segy_volume, tmp_path):
    """Cancel already true at start: reader never blocks, writer exits."""
    src, _ = segy_volume
    dst = tmp_path / "store"
    result = transcode_segy_to_zarr(src, dst, cancel=lambda: True, workers=2)
    assert result.stats.shards_written == 0
    assert _reader_threads_alive() == 0


# ------------------------------------------------- #1141 source identity


def test_resume_rejects_different_source_same_geometry(segy_volume, tmp_path):
    """#1141: a partial store resumed against a DIFFERENT SEG-Y (same shape)
    must fail closed instead of producing a mixed-source DERIVED volume."""
    src, cube = segy_volume
    other = tmp_path / "other.segy"
    _write_segy(other, seed=99)  # identical geometry, different content
    dst = tmp_path / "store"

    state = {"done": 0}
    transcode_segy_to_zarr(
        src,
        dst,
        progress=lambda f: state.__setitem__("done", state["done"] + 1),
        cancel=lambda: state["done"] >= 1,
        workers=1,
    )
    with pytest.raises(TranscodeError, match="refusing to mix sources"):
        transcode_segy_to_zarr(other, dst)

    # the ORIGINAL source still resumes (identity matches)
    result = transcode_segy_to_zarr(src, dst)
    assert result.stats.shards_skipped >= 1
    arr = zarr.open(str(dst), mode="r")
    np.testing.assert_array_equal(np.asarray(arr[:, :, :]), cube)


def test_resume_rejects_in_place_modified_source(segy_volume, tmp_path):
    """#1141: same path, same size, rewritten content — the size/mtime
    identity must catch an in-place source swap."""
    src, _ = segy_volume
    dst = tmp_path / "store"
    state = {"done": 0}
    transcode_segy_to_zarr(
        src,
        dst,
        progress=lambda f: state.__setitem__("done", state["done"] + 1),
        cancel=lambda: state["done"] >= 1,
        workers=1,
    )
    _write_segy(src, seed=123)  # same size (same shape/dtype), new mtime
    with pytest.raises(TranscodeError, match="refusing to mix sources"):
        transcode_segy_to_zarr(src, dst)


import os  # noqa: E402

QUICK2G = Path(
    os.environ.get(
        "PALEO_QUICK2G_SEGY",
        "/home/kevin/projects/paleo_project/data/bench/synthetic_quick2g.segy",
    )
)


@pytest.mark.skipif(not QUICK2G.exists(), reason="quick2g volume not present")
def test_quick2g_end_to_end(tmp_path):
    """Local-NVMe integration gate (#1077 acceptance): bit-exact readback,
    >=1.2x on-disk ratio, parallel throughput above the 95 MB/s single-thread
    benchmark baseline."""
    result = transcode_segy_to_zarr(QUICK2G, tmp_path / "q2g")
    nil, nxl, nt = result.shape
    src_data_bytes = nil * nxl * nt * 4
    ratio = src_data_bytes / max(result.stats.store_bytes, 1)
    assert ratio >= 1.2

    arr = zarr.open(str(tmp_path / "q2g"), mode="r")
    with segyio.open(str(QUICK2G), "r", ignore_geometry=False) as f:
        for il_idx in (0, nil // 2, nil - 1):  # slab-wise, memory-bounded
            expected = np.asarray(f.iline[il_idx + 1], dtype=np.float32)
            np.testing.assert_array_equal(
                np.asarray(arr[il_idx, :, :]), expected
            )

    assert result.stats.throughput_mb_s > 95  # beats single-thread baseline
