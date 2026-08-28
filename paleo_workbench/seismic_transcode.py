"""Production SEG-Y → Zarr v3 transcoder (#1077, spec §1-§2 / ADR 0061-0062).

Writes the chunked store defined by the 100G-volume architecture spec:
chunk (64, 128, 128), shard (128, 512, 512), zstd clevel 5 without
bitshuffle. The work unit is one *shard*: a shard is read from the SEG-Y
as contiguous trace ranges and written to the store in a single array
assignment, so a shard file on disk is always complete-or-absent. Resume
therefore needs no state file — each existing shard is probed with a
single-element read (a truncated shard fails its index parse) and skipped
when it answers.

Concurrency is a thread pool over shards; each worker keeps its own
``segyio`` handle (segyio files are not documented thread-safe). Peak RAM
is bounded by ``workers × shard bytes`` (8 × 128 MiB by default), inside
the spec §7 streaming-pool budget.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import segyio

__all__ = [
    "TranscodeError",
    "TranscodeParams",
    "TranscodeResult",
    "TranscodeStats",
    "default_workers",
    "shard_boxes",
    "transcode_segy_to_zarr",
]

DEFAULT_CHUNK = (64, 128, 128)
DEFAULT_SHARD = (128, 512, 512)


class TranscodeError(RuntimeError):
    """Raised for unstructured input or a mismatched existing store."""


@dataclass(frozen=True)
class TranscodeParams:
    chunk: tuple[int, int, int] = DEFAULT_CHUNK
    shard: tuple[int, int, int] = DEFAULT_SHARD
    cname: str = "zstd"
    clevel: int = 5
    # Spec (#1070): bitshuffle OFF — it costs 3-7x read latency for ~3% ratio.
    # Byte shuffle stays ON: that is the configuration the benchmark measured
    # (zarr serializes ``shuffle=None`` as byte-shuffle, matching h5py's
    # ``shuffle=True``), so ON is the number the spec's decision rests on.
    bitshuffle: bool = False


@dataclass
class TranscodeStats:
    shards_total: int = 0
    shards_written: int = 0
    shards_skipped: int = 0
    traces_read: int = 0
    bytes_read: int = 0
    store_bytes: int = 0


@dataclass
class TranscodeResult:
    store_path: str
    shape: tuple[int, int, int]
    stats: TranscodeStats = field(default_factory=TranscodeStats)


def default_workers() -> int:
    return max(1, min((os.cpu_count() or 4) - 2, 8))


def shard_boxes(
    shape: tuple[int, int, int], params: TranscodeParams
) -> Iterator[tuple[int, int, int, int, int, int]]:
    """Half-open (il0, il1, xl0, xl1, t0, t1) boxes, one per shard."""
    nil, nxl, nt = shape
    for i0 in range(0, nil, params.shard[0]):
        for j0 in range(0, nxl, params.shard[1]):
            for t0 in range(0, nt, params.shard[2]):
                yield (
                    i0,
                    min(i0 + params.shard[0], nil),
                    j0,
                    min(j0 + params.shard[1], nxl),
                    t0,
                    min(t0 + params.shard[2], nt),
                )


def _volume_shape(src: Path) -> tuple[int, int, int]:
    try:
        with segyio.open(str(src), "r", ignore_geometry=False) as f:
            return len(f.ilines), len(f.xlines), len(f.samples)
    except Exception as exc:  # unstructured or unreadable input
        raise TranscodeError(f"cannot read 3-D grid from {src}: {exc}") from exc


def _open_or_create(dst: Path, shape, params: TranscodeParams, source: Path):
    import zarr
    from zarr.codecs import BloscCodec

    meta_path = dst / "zarr.json"
    if meta_path.exists():
        _validate_existing(dst, shape, params)
        return zarr.open(str(dst), mode="a")
    return zarr.create_array(
        str(dst),
        shape=shape,
        dtype="float32",
        chunks=params.chunk,
        shards=params.shard,
        compressors=[
            BloscCodec(
                cname=params.cname,  # type: ignore[arg-type]
                clevel=params.clevel,
                shuffle="bitshuffle" if params.bitshuffle else "shuffle",
            )
        ],
        overwrite=False,
        attributes={
            "source_path": str(source),
            "source_format": "seg-y",
            "shape": list(shape),
            "transcode": {
                "chunk": list(params.chunk),
                "shard": list(params.shard),
                "cname": params.cname,
                "clevel": params.clevel,
                "bitshuffle": params.bitshuffle,
            },
        },
    )


def _validate_existing(dst: Path, shape, params: TranscodeParams) -> None:
    """Reopened arrays report inner chunks via ``arr.chunks``, so validate
    against the zarr.json itself: outer chunk grid == shard, sharding
    codec's inner chunk_shape == chunk."""
    import json

    try:
        meta = json.loads((dst / "zarr.json").read_text())
    except Exception as exc:
        raise TranscodeError(f"unreadable zarr.json at {dst}: {exc}") from exc
    if list(meta.get("shape", [])) != list(shape):
        raise TranscodeError(
            f"existing store at {dst} has shape {meta.get('shape')}; "
            f"expected {list(shape)}"
        )
    grid = meta.get("chunk_grid", {}).get("configuration", {}).get("chunk_shape")
    if grid != list(params.shard):
        raise TranscodeError(
            f"existing store at {dst} has shard grid {grid}; expected "
            f"{list(params.shard)}"
        )
    for codec in meta.get("codecs", []):
        if codec.get("name") == "sharding_indexed":
            inner = codec.get("configuration", {}).get("chunk_shape")
            if inner != list(params.chunk):
                raise TranscodeError(
                    f"existing store at {dst} has inner chunk {inner}; "
                    f"expected {list(params.chunk)}"
                )
            return
    raise TranscodeError(f"existing store at {dst} is not sharded")


def _shard_file(dst: Path, i: int, j: int, k: int) -> Path:
    return dst / "c" / str(i) / str(j) / str(k)


def _shard_is_complete(arr, box) -> bool:
    """Probe with a single-element read; a truncated shard fails to parse."""
    i0, _i1, j0, _j1, t0, _t1 = box
    try:
        np.asarray(arr[i0, j0, t0])
        return True
    except Exception:
        return False


def transcode_segy_to_zarr(
    src: str | Path,
    dst: str | Path,
    *,
    params: TranscodeParams = TranscodeParams(),
    workers: int | None = None,
    progress: Callable[[float], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    stats: TranscodeStats | None = None,
) -> TranscodeResult:
    """Transcode a structured 3-D SEG-Y into the spec's chunked zarr store.

    Safe to re-run: completed shards are probed and skipped, truncated
    shards (killed mid-write) are deleted and rewritten. ``cancel`` stops
    before the next shard and keeps the partial store resumable.
    """
    src, dst = Path(src), Path(dst)
    shape = _volume_shape(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    arr = _open_or_create(dst, shape, params, src)

    boxes = list(shard_boxes(shape, params))
    stats = stats or TranscodeStats()
    stats.shards_total = len(boxes)

    todo: list[tuple[int, int, int, int, int, int]] = []
    for box in boxes:
        i0, _i1, j0, _j1, t0, _t1 = box
        key = _shard_file(dst, i0 // params.shard[0], j0 // params.shard[1], t0 // params.shard[2])
        if key.exists():
            if _shard_is_complete(arr, box):
                stats.shards_skipped += 1
                continue
            key.unlink()  # truncated mid-write: redo from scratch
        todo.append(box)

    nil, nxl, nt = shape
    n_workers = max(1, workers or default_workers())
    tls = threading.local()
    handles: list = []
    handles_lock = threading.Lock()
    done_lock = threading.Lock()
    done = 0

    def handle():
        f = getattr(tls, "segy", None)
        if f is None:
            f = segyio.open(str(src), "r", ignore_geometry=False)
            tls.segy = f
            with handles_lock:
                handles.append(f)
        return f

    def work(box):
        nonlocal done
        if cancel is not None and cancel():
            return  # never started: stays todo for the resumed run
        i0, i1, j0, j1, t0, t1 = box
        f = handle()
        slab = np.empty((i1 - i0, j1 - j0, t1 - t0), dtype=np.float32)
        for il in range(i0, i1):
            traces = segyio.tools.collect(
                f.trace[il * nxl + j0 : il * nxl + j0 + (j1 - j0)]
            ).astype(np.float32, copy=False)
            slab[il - i0] = traces[:, t0:t1]
        arr[i0:i1, j0:j1, t0:t1] = slab
        with done_lock:
            stats.traces_read += (i1 - i0) * (j1 - j0)
            stats.bytes_read += (i1 - i0) * (j1 - j0) * (t1 - t0) * 4
            stats.shards_written += 1
            done += 1
            if progress is not None:
                progress(done / stats.shards_total)

    try:
        if n_workers == 1:
            for box in todo:
                if cancel is not None and cancel():
                    return _result(dst, shape, stats)
                work(box)
        else:
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures = []
                for box in todo:
                    if cancel is not None and cancel():
                        break
                    futures.append(pool.submit(work, box))
                for fut in futures:
                    fut.result()
    finally:
        for f in handles:
            try:
                f.close()
            except Exception:
                pass
    return _result(dst, shape, stats)


def _result(dst: Path, shape, stats: TranscodeStats) -> TranscodeResult:
    stats.store_bytes = sum(
        p.stat().st_size for p in dst.rglob("*") if p.is_file()
    )
    return TranscodeResult(str(dst), tuple(shape), stats)
