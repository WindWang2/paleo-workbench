"""Tests for the SEG-Y → Zarr v3 production transcoder (#1077)."""
from __future__ import annotations

import json
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
    src, _ = segy_volume
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
        (i1 - i0) * (j1 - j0) for (i0, i1, j0, j1, _t0, _t1) in boxes[1:]
    )
    assert result.stats.shards_skipped == 1
    assert result.stats.traces_read <= expected_max
    assert result.stats.traces_read > 0

    arr = zarr.open(str(dst), mode="r")
    cube = _write_segy(tmp_path / "again.segy", seed=7)  # deterministic source
    np.testing.assert_array_equal(np.asarray(arr[:, :, :]), cube)


def test_truncated_shard_is_redone(segy_volume, tmp_path):
    src, _ = segy_volume
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
    cube = _write_segy(tmp_path / "again2.segy", seed=7)
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


QUICK2G = Path(
    "/home/kevin/projects/paleo_project/data/bench/synthetic_quick2g.segy"
)


@pytest.mark.skipif(not QUICK2G.exists(), reason="quick2g volume not present")
def test_quick2g_compression_ratio(tmp_path):
    result = transcode_segy_to_zarr(QUICK2G, tmp_path / "q2g")
    src_bytes = QUICK2G.stat().st_size - 3600 - 240 * (1024 * 1024)
    ratio = src_bytes / max(result.stats.store_bytes, 1)
    assert ratio >= 1.2  # spec acceptance: >= 1.2x on the synthetic volume
