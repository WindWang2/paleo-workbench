"""Production SEG-Y → Zarr v3 transcoder (#1077; decisions #1070/#1071,
spec branch spec/100g-seismic-architecture — merge PR #1096 for §refs).

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

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple
from typing import Callable, Iterator

import numpy as np
import segyio

logger = logging.getLogger(__name__)

__all__ = [
    "TranscodeError",
    "TranscodeParams",
    "TranscodeResult",
    "TranscodeStats",
    "_axis_spec",
    "default_workers",
    "shard_boxes",
    "transcode_segy_to_zarr",
]

DEFAULT_CHUNK = (64, 128, 128)
DEFAULT_SHARD = (128, 512, 512)


class TranscodeError(RuntimeError):
    """Raised for unstructured input or a mismatched existing store."""


def _axis_spec(vals: np.ndarray, name: str) -> tuple[int, int]:
    """(start, step) mapping logical line numbers to store indices (#1130).

    Constant positive *and* negative steps are supported (SEG-Y line
    numbering may decrease along the file). Anything that cannot be
    modelled as one linear axis — zero or varying diffs — fails closed
    with TranscodeError instead of silently degrading to step=1.
    """
    if len(vals) == 0:
        return 1, 1
    if len(vals) == 1:
        return int(vals[0]), 1
    diffs = np.diff(np.asarray(vals, dtype=np.int64))
    step = int(diffs[0])
    if step == 0 or not bool((diffs == step).all()):
        preview = ", ".join(str(int(v)) for v in vals[:8])
        raise TranscodeError(
            f"nonlinear {name} numbering cannot be mapped to "
            f"(start, step): [{preview}, ...] ({len(vals)} lines)"
        )
    return int(vals[0]), step


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
    elapsed_s: float = 0.0

    @property
    def throughput_mb_s(self) -> float:
        return self.bytes_read / self.elapsed_s / 1e6 if self.elapsed_s else 0.0


@dataclass
class TranscodeResult:
    store_path: str
    shape: tuple[int, int, int]
    stats: TranscodeStats = field(default_factory=TranscodeStats)


class ShardBox(NamedTuple):
    """Half-open shard extent plus its grid indices in the store."""

    il0: int
    il1: int
    xl0: int
    xl1: int
    t0: int
    t1: int
    gi: int  # shard-grid column (inline axis)
    gj: int  # shard-grid row (crossline axis)
    gk: int  # shard-grid depth (time axis)


def default_workers() -> int:
    """Physical cores preferred (spec §2 says min(物理核−2, 8)); logical
    cores are the fallback when psutil can't tell them apart.

    P2-A: the answer is additionally clamped by the ResourceGovernor's
    TRANSCODE allowance so one transcode cannot claim the whole machine
    when attribute/inference work is admitted too, and sheds cores under
    memory pressure."""
    cpus: int | None = None
    try:
        import psutil

        cpus = psutil.cpu_count(logical=False)
    except Exception:
        cpus = None
    cpus = cpus or os.cpu_count() or 4
    from paleo_workbench.runtime.governance import clamp_workers

    return clamp_workers("seismic.transcode", max(1, min(cpus - 2, 8)))


def shard_boxes(
    shape: tuple[int, int, int], params: TranscodeParams
) -> Iterator[ShardBox]:
    """One ShardBox per shard in the store's grid."""
    nil, nxl, nt = shape
    for gi, i0 in enumerate(range(0, nil, params.shard[0])):
        for gj, j0 in enumerate(range(0, nxl, params.shard[1])):
            for gk, t0 in enumerate(range(0, nt, params.shard[2])):
                yield ShardBox(
                    i0,
                    min(i0 + params.shard[0], nil),
                    j0,
                    min(j0 + params.shard[1], nxl),
                    t0,
                    min(t0 + params.shard[2], nt),
                    gi,
                    gj,
                    gk,
                )


def _source_identity(src: Path) -> dict[str, int]:
    """Cheap source identity for resume validation (#1141).

    Size + mtime_ns catch in-place replacement (re-export over the same
    path). A full sha256 would double the IO of every transcode; geometry
    equality is enforced separately by shape comparison.
    """
    st = src.stat()
    return {"source_size": st.st_size, "source_mtime_ns": st.st_mtime_ns}


def _volume_geometry(src: Path) -> tuple[tuple[int, int, int], dict]:
    """Shape plus the regular-grid coordinate spec for store attributes.

    The iline/xline start/step land in zarr.json so ``open_volume`` can map
    logical inline/crossline VALUES without re-reading the SEG-Y headers
    (#1080). Samples keep index semantics (segyio regular grids only).
    """
    try:
        with segyio.open(str(src), "r", ignore_geometry=False) as f:
            shape = (len(f.ilines), len(f.xlines), len(f.samples))
            ilines = np.asarray(f.ilines)
            xlines = np.asarray(f.xlines)

        il_start, il_step = _axis_spec(ilines, "iline")
        xl_start, xl_step = _axis_spec(xlines, "xline")
    except TranscodeError:
        raise
    except Exception as exc:  # unstructured or unreadable input
        raise TranscodeError(f"cannot read 3-D grid from {src}: {exc}") from exc
    attrs = {
        "source_format": "seg-y",
        "shape": list(shape),
        "iline": {"start": il_start, "step": il_step},
        "xline": {"start": xl_start, "step": xl_step},
    }
    return shape, attrs


def _volume_shape(src: Path) -> tuple[int, int, int]:
    return _volume_geometry(src)[0]


def _source_identity(src: Path) -> dict:
    """Source identity recorded at creation and re-checked on resume (#1141).

    ``source_path`` plus size/mtime: enough to fail closed when the same
    store path is resumed against a *different* SEG-Y (same geometry) —
    the mix-source hazard — while staying cheap (no content hashing of a
    100 GB file).
    """
    try:
        st = src.stat()
        return {
            "source_path": str(src),
            "source_size": st.st_size,
            "source_mtime_ns": st.st_mtime_ns,
        }
    except OSError:
        return {"source_path": str(src)}


def _check_source_identity(stored: dict, src: Path) -> None:
    """Raise TranscodeError when ``stored`` identity is not this source."""
    stored_path = stored.get("source_path")
    if stored_path is not None and stored_path != str(src):
        raise TranscodeError(
            f"existing store at resume was transcoded from {stored_path!r}, "
            f"not {str(src)!r}; refusing to mix sources — start a fresh "
            f"transcode to a new store instead of resuming"
        )
    try:
        st = src.stat()
    except OSError:
        return  # path matches; the file's absence is the caller's problem
    stored_size = stored.get("source_size")
    if stored_size is not None and int(stored_size) != st.st_size:
        raise TranscodeError(
            f"source {src} is {st.st_size} bytes but the existing store was "
            f"transcoded from {stored_size} bytes; refusing to mix sources — "
            f"start a fresh transcode to a new store instead of resuming"
        )
    stored_mtime = stored.get("source_mtime_ns")
    if stored_mtime is not None and int(stored_mtime) != st.st_mtime_ns:
        raise TranscodeError(
            f"source {src} was modified after the existing store was "
            f"transcoded (mtime changed); refusing to mix sources — start "
            f"a fresh transcode to a new store instead of resuming"
        )


def _open_or_create(
    dst: Path,
    shape,
    params: TranscodeParams,
    source: Path,
    grid_attrs: dict | None = None,
):
    import zarr
    from zarr.codecs import BloscCodec

    meta_path = dst / "zarr.json"
    if meta_path.exists():
        _validate_existing(dst, shape, params, source)
        return zarr.open(str(dst), mode="a")
    attributes = {
        **_source_identity(source),
        "source_format": "seg-y",
        "shape": list(shape),
        **_source_identity(source),
        "transcode": {
            "chunk": list(params.chunk),
            "shard": list(params.shard),
            "cname": params.cname,
            "clevel": params.clevel,
            "bitshuffle": params.bitshuffle,
        },
    }
    if grid_attrs:
        attributes.update(grid_attrs)
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
        attributes=attributes,
    )


def _validate_existing(
    dst: Path, shape, params: TranscodeParams, source: Path | None = None
) -> None:
    """Reopened arrays report inner chunks via ``arr.chunks``, so validate
    against the zarr.json itself: outer chunk grid == shard, sharding
    codec's inner chunk_shape == chunk, codec settings == params, and
    (when ``source`` is given) the store's recorded source identity matches
    the source being resumed against (#1141 — never mix sources in one
    store)."""
    import json

    try:
        meta = json.loads((dst / "zarr.json").read_text())
    except Exception as exc:
        raise TranscodeError(f"unreadable zarr.json at {dst}: {exc}") from exc
    if source is not None:
        stored_attrs = meta.get("attributes") or {}
        if stored_attrs.get("source_format") == "seg-y" or stored_attrs.get(
            "source_path"
        ):
            # Stores created before #1141 may lack the identity fields; a
            # recorded source_path alone still gets checked.
            _check_source_identity(stored_attrs, source)
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
    sharding = None
    for codec in meta.get("codecs", []):
        if codec.get("name") == "sharding_indexed":
            sharding = codec
            break
    if sharding is None:
        raise TranscodeError(f"existing store at {dst} is not sharded")
    inner = sharding.get("configuration", {}).get("chunk_shape")
    if inner != list(params.chunk):
        raise TranscodeError(
            f"existing store at {dst} has inner chunk {inner}; "
            f"expected {list(params.chunk)}"
        )
    blosc = next(
        (
            c
            for c in sharding.get("configuration", {}).get("codecs", [])
            if c.get("name") == "blosc"
        ),
        None,
    )
    if blosc is not None:
        cfg = blosc.get("configuration", {})
        want_shuffle = "bitshuffle" if params.bitshuffle else "shuffle"
        if (
            cfg.get("cname") != params.cname
            or cfg.get("clevel") != params.clevel
            or cfg.get("shuffle") != want_shuffle
        ):
            raise TranscodeError(
                f"existing store at {dst} was written with {cfg.get('cname')}"
                f"/{cfg.get('clevel')}/{cfg.get('shuffle')}; refusing to mix "
                f"codecs within one store"
            )
    # #1141: resume must continue the SAME source. A replaced SEG-Y with
    # matching geometry would otherwise mix two data versions in one store.
    stored_attrs = meta.get("attributes", {})
    if "source_size" in stored_attrs or "source_mtime_ns" in stored_attrs:
        try:
            current = _source_identity(source)
        except OSError as exc:
            raise TranscodeError(f"cannot stat transcode source {source}: {exc}") from exc
        if (
            stored_attrs.get("source_size") != current["source_size"]
            or stored_attrs.get("source_mtime_ns") != current["source_mtime_ns"]
        ):
            raise TranscodeError(
                f"existing store at {dst} was transcoded from a different "
                f"source file (size/mtime changed); refusing to resume across "
                f"sources. Delete {dst} and re-run to transcode {source} cleanly"
            )
    # Stores written before source-identity tracking carry no keys and resume
    # as before (bounded grandfather window, no new silent holes).


def _shard_is_complete(arr, box: ShardBox) -> bool:
    """Probe with a single-element read; a truncated shard fails to parse."""
    try:
        np.asarray(arr[box.il0, box.xl0, box.t0])
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
    shape, grid_attrs = _volume_geometry(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    arr = _open_or_create(dst, shape, params, src, grid_attrs)

    boxes = list(shard_boxes(shape, params))
    stats = stats or TranscodeStats()
    stats.shards_total = len(boxes)

    todo: list[ShardBox] = []
    for box in boxes:
        shard_path = dst / "c" / str(box.gi) / str(box.gj) / str(box.gk)
        if shard_path.exists():
            if _shard_is_complete(arr, box):
                stats.shards_skipped += 1
                continue
            shard_path.unlink()  # truncated mid-write: redo from scratch
        todo.append(box)

    nxl = shape[1]
    n_workers = max(1, workers or default_workers())
    tls = threading.local()
    handles: list = []
    handles_lock = threading.Lock()
    done_lock = threading.Lock()
    # Already-complete shards count toward progress so a resumed run still
    # reaches 1.0.  Boxed in a list so nested closures can bump it without
    # a `nonlocal` chain across the reader/writer split (#1077 pipeline).
    done_box = [stats.shards_skipped]
    t_start = time.perf_counter()

    def thread_segy():
        """Serial-path handle (main thread only, #1136 ownership): created
        and closed by the main thread; the multi-worker reader thread owns
        its own handle and never registers it here."""
        f = getattr(tls, "segy", None)
        if f is None:
            f = segyio.open(str(src), "r", ignore_geometry=False)
            tls.segy = f
            with handles_lock:
                handles.append(f)
        return f

    def read_slab(box: ShardBox, f) -> np.ndarray:
        slab = np.empty(
            (box.il1 - box.il0, box.xl1 - box.xl0, box.t1 - box.t0),
            dtype=np.float32,
        )
        for il in range(box.il0, box.il1):
            traces = segyio.tools.collect(
                f.trace[il * nxl + box.xl0 : il * nxl + box.xl0 + (box.xl1 - box.xl0)]
            ).astype(np.float32, copy=False)
            slab[il - box.il0] = traces[:, box.t0 : box.t1]
        return slab

    def write_slab(box: ShardBox, slab: np.ndarray) -> bool:
        """Write one shard; returns False when cancelled before the write."""
        if cancel is not None and cancel():
            return False  # never written: stays todo for the resumed run
        arr[box.il0 : box.il1, box.xl0 : box.xl1, box.t0 : box.t1] = slab
        with done_lock:
            stats.traces_read += (box.il1 - box.il0) * (box.xl1 - box.xl0)
            stats.bytes_read += (
                (box.il1 - box.il0) * (box.xl1 - box.xl0) * (box.t1 - box.t0) * 4
            )
            stats.shards_written += 1
            done_box[0] += 1
            if progress is not None:
                progress(done_box[0] / stats.shards_total)
        return True

    try:
        if n_workers == 1:
            f = thread_segy()
            for box in todo:
                if cancel is not None and cancel():
                    return _result(dst, shape, stats)
                write_slab(box, read_slab(box, f))
        else:
            # #1077: the zarr v3 sharded-write path (zstd compress + shard
            # index) serializes internally — measured on reference hardware
            # AND this host, thread-pooling the whole work() call is net
            # SLOWER than serial (GIL contention on segyio reads plus shard
            # locks inside zarr).  Overlapping stages does scale: one
            # reader thread streams slabs (segyio, ~400 MB/s) ahead of the
            # write stage, so disk reads hide under compression.  The
            # queue depth bounds in-flight slabs to ~workers x shard bytes.
            from queue import Empty, Full, Queue

            # P2-A: the in-flight window derives from the budget's streaming
            # buffer cap (was a hardcoded 1 GiB) so pressure-time budget
            # changes actually shrink the transcode working set.
            try:
                from paleo_workbench.runtime.resource_budget import active_budget

                window_bytes = active_budget().streaming_buffer_bytes
            except Exception:
                window_bytes = 1 << 30
            max_in_flight = max(2, min(n_workers, max(1, window_bytes // (
                (todo[0].il1 - todo[0].il0) * (todo[0].xl1 - todo[0].xl0)
                * (todo[0].t1 - todo[0].t0) * 4
            ))) if todo else 2)
            q: "Queue[tuple[ShardBox, np.ndarray] | None]" = Queue(
                maxsize=max_in_flight
            )
            # #1136: the reader must be able to exit on cancel even while
            # blocked on a FULL queue (the writer has stopped consuming), and
            # must own its segyio handle so the main thread never closes a
            # handle the reader is still using. ``stop`` is set by the writer
            # the moment it stops consuming; every blocking put in the reader
            # is bounded and re-checks ``stop``/cancel between attempts.
            stop = threading.Event()
            put_timeout = 0.25  # s; upper bound on reader responsiveness

            def stopped() -> bool:
                if stop.is_set():
                    return True
                return cancel is not None and cancel()

            def put_pill() -> None:
                """Hand the writer its exit sentinel. Always attempted when
                the reader exits — the writer's ``q.get()`` would otherwise
                block forever (e.g. cancel already true before the first
                slab). Skipped only once ``stop`` is set, which only the
                writer sets AFTER leaving its get-loop, so skipping cannot
                strand it."""
                while not stop.is_set():
                    try:
                        q.put(None, timeout=put_timeout)
                        break
                    except Full:
                        continue

            # Read/open failures from the reader thread land here and are
            # re-raised by the main thread after the join (see reader()).
            reader_error: list[BaseException] = []

            def reader() -> None:
                # Handle ownership (#1136): opened here, closed here — the
                # main thread's ``handles`` list stays reader-free, so its
                # finally-close can never race this thread's reads.
                #
                # read/open failures are recorded in ``reader_error`` and
                # re-raised by the main thread after the join: the pill the
                # finally sends lets the writer end "normally", so without
                # this the failed transcode would return success with an
                # incomplete store.
                try:
                    f = segyio.open(str(src), "r", ignore_geometry=False)
                except Exception as exc:
                    reader_error.append(exc)
                    put_pill()
                    return
                try:
                    for box in todo:
                        if stopped():
                            return  # slab discarded: unwritten, stays todo
                        try:
                            slab = read_slab(box, f)
                        except Exception as exc:
                            reader_error.append(exc)
                            return
                        enqueued = False
                        while not stopped():
                            try:
                                q.put((box, slab), timeout=put_timeout)
                                enqueued = True
                                break
                            except Full:
                                continue
                        if not enqueued:
                            return
                finally:
                    try:
                        f.close()
                    except Exception:
                        pass
                    put_pill()

            reader_thread = threading.Thread(
                target=reader, name="segy-transcode-reader", daemon=True
            )
            reader_thread.start()
            try:
                cancelled_here = False
                while True:
                    item = q.get()
                    if item is None:
                        break
                    if not write_slab(item[0], item[1]):
                        cancelled_here = True
                        break  # cancelled: partial store stays resumable
                if cancelled_here:
                    # #1136: drain so the reader's blocking puts release and
                    # it can reach its sentinel-exit. Without this, join()
                    # below always hits its timeout and leaks a parked
                    # thread holding an open SEG-Y handle.
                    while True:
                        if q.get() is None:
                            break
            finally:
                # Unblock the reader deterministically: signal stop, then
                # drain the queue so a reader parked on a full queue sees
                # ``stop`` on its next bounded-put retry (and its in-flight
                # slabs are released). The reader can then only be inside a
                # bounded put, a finite segyio read, or handle close, so a
                # bounded join is conclusive — no thread is left leaking.
                stop.set()
                while True:
                    try:
                        q.get_nowait()
                    except Empty:
                        break
                reader_thread.join(timeout=30)
                if reader_thread.is_alive():  # pragma: no cover - safety net
                    logger.warning(
                        "segy-transcode-reader did not exit within 30s after "
                        "stop; leaking one daemon thread (store stays valid)"
                    )
                if reader_error:
                    # The reader failed (open or slab read). The pill made the
                    # writer stop without an error of its own, so surface the
                    # failure HERE: the partial store stays resumable, but
                    # this call must not report success.
                    raise TranscodeError(
                        f"transcode failed while reading {src}: {reader_error[0]}"
                    ) from reader_error[0]
    finally:
        stats.elapsed_s = time.perf_counter() - t_start
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
