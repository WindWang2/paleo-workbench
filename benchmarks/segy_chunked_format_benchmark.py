#!/usr/bin/env python3
"""Benchmark SEG-Y → chunked-format conversion and access (#1070, map #1067).

Compares Zarr v3 (sharding + Blosc) against HDF5 (chunked + hdf5plugin ZSTD)
on the deterministic synthetic volumes from generate_synthetic_segy.py.

Subcommands (each prints a markdown result row / block to stdout):

  convert    SEG-Y → store, reports wall time, throughput, on-disk size/ratio
  slices     random full-slice reads per axis (inline/crossline/timeslice),
             p50/p95 latency
  traces     random single-trace batch reads (well-tie scenario)
  threads    8-thread concurrent random slice reads vs serial (speedup)
  prefetch   interactive slice latency while a sequential sweep runs (per axis)
  lod        build a ::2 decimated pyramid level (Zarr), report cost + read

Volume axis order is (inline, crossline, time) everywhere. Conversion writes
inline batches aligned to the shard/chunk inline dimension so each shard is
materialized once (partial shard rewrites are the slow path).

Device baseline note (#1069): the full100g volume lives on an external
USB-NTFS drive; quick2g on internal NVMe. Record the device with every row.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np
import segyio

# ---------------------------------------------------------------- helpers --


def segy_shape(path: Path) -> tuple[int, int, int]:
    with segyio.open(path, "r", ignore_geometry=False) as f:
        return len(f.ilines), len(f.xlines), len(f.samples)


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def pct(samples: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(samples), q))


def _batch_size(shard_il: int, nxl: int, nt: int, budget_bytes: float = 2.5e9) -> int:
    """Inline batch that fills shards but stays under a RAM budget."""
    per_inline = nxl * nt * 4
    n = max(1, shard_il)
    while n > 1 and n * per_inline > budget_bytes:
        n //= 2
    return n


def read_inline_slab(f, il_idx: int) -> np.ndarray:
    return np.asarray(f.iline[il_idx + 1], dtype=np.float32)


# --------------------------------------------------------------- convert --


def convert_zarr(
    src: Path,
    dst: Path,
    chunk: tuple[int, int, int],
    shard: tuple[int, int, int] | None,
    cname: str = "zstd",
    clevel: int = 5,
    shuffle: str | None = "bitshuffle",
    progress_every: int = 1000,
) -> dict:
    import zarr
    from zarr.codecs import BloscCodec

    nil, nxl, nt = segy_shape(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    compressors = [
        BloscCodec(
            cname=cname,  # type: ignore[arg-type]
            clevel=clevel,
            shuffle=shuffle,  # type: ignore[arg-type]
        )
    ]
    kwargs: dict = dict(
        shape=(nil, nxl, nt),
        dtype="float32",
        chunks=chunk,
        compressors=compressors,
        overwrite=True,
    )
    if shard is not None:
        kwargs["shards"] = shard
    arr = zarr.create_array(str(dst), **kwargs)

    batch = _batch_size(shard[0] if shard else chunk[0], nxl, nt)
    t0 = time.perf_counter()
    with segyio.open(src, "r", ignore_geometry=False) as f:
        for i0 in range(0, nil, batch):
            i1 = min(i0 + batch, nil)
            slabs = np.stack([read_inline_slab(f, i) for i in range(i0, i1)])
            arr[i0:i1, :, :] = slabs
            if (i1 // batch) % max(1, (nil // batch) // 10) == 0 or i1 == nil:
                el = time.perf_counter() - t0
                done = i1 * nxl * nt * 4
                print(
                    f"  iline {i1}/{nil}  {done/1e9:.1f} GB in {el:.0f}s "
                    f"({done/el/1e6:.0f} MB/s)",
                    flush=True,
                )
    elapsed = time.perf_counter() - t0
    size = dir_size(dst)
    src_bytes = nil * nxl * nt * 4
    return {
        "format": "zarr",
        "config": f"chunk={chunk} shard={shard} {cname}{clevel} shuffle={shuffle}",
        "src_bytes": src_bytes,
        "store_bytes": size,
        "ratio": src_bytes / max(size, 1),
        "elapsed_s": round(elapsed, 1),
        "throughput_mb_s": round(src_bytes / elapsed / 1e6, 1),
    }


def convert_hdf5(
    src: Path,
    dst: Path,
    chunk: tuple[int, int, int],
    clevel: int = 5,
    progress_every: int = 1000,
) -> dict:
    import hdf5plugin  # noqa: F401 — must load before h5py inits its C library
    import h5py

    nil, nxl, nt = segy_shape(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    batch = _batch_size(chunk[0], nxl, nt)
    t0 = time.perf_counter()
    with segyio.open(src, "r", ignore_geometry=False) as f, h5py.File(
        dst, "w"
    ) as hf:
        dset = hf.create_dataset(
            "data",
            shape=(nil, nxl, nt),
            dtype="f4",
            chunks=chunk,
            shuffle=True,
            **hdf5plugin.Zstd(clevel=clevel),
        )
        for i0 in range(0, nil, batch):
            i1 = min(i0 + batch, nil)
            slabs = np.stack([read_inline_slab(f, i) for i in range(i0, i1)])
            dset[i0:i1, :, :] = slabs
            if (i1 // batch) % max(1, (nil // batch) // 10) == 0 or i1 == nil:
                el = time.perf_counter() - t0
                done = i1 * nxl * nt * 4
                print(
                    f"  iline {i1}/{nil}  {done/1e9:.1f} GB in {el:.0f}s "
                    f"({done/el/1e6:.0f} MB/s)",
                    flush=True,
                )
    elapsed = time.perf_counter() - t0
    size = dir_size(dst)
    src_bytes = nil * nxl * nt * 4
    return {
        "format": "hdf5",
        "config": f"chunk={chunk} zstd{clevel} shuffle=True",
        "src_bytes": src_bytes,
        "store_bytes": size,
        "ratio": src_bytes / max(size, 1),
        "elapsed_s": round(elapsed, 1),
        "throughput_mb_s": round(src_bytes / elapsed / 1e6, 1),
    }


# ---------------------------------------------------------------- stores --


def open_store(path: Path, kind: str):
    import hdf5plugin  # noqa: F401 — must load before h5py inits its C library

    if kind == "zarr":
        import zarr

        return zarr.open(str(path), mode="r")
    import h5py

    hf = h5py.File(path, "r", rdcc_nbytes=256 * 2**20, rdcc_nslots=523, rdcc_w0=1)
    return hf["data"]


# ---------------------------------------------------------------- benches --


def _read_axis(store, axis: str, idx: int):
    if axis == "inline":
        return store[idx, :, :]
    if axis == "crossline":
        return store[:, idx, :]
    return store[:, :, idx]


def bench_slices(store, shape, n: int, seed: int = 42) -> dict:
    nil, nxl, nt = shape
    rng = random.Random(seed)
    out = {}
    for axis, size in (("inline", nil), ("crossline", nxl), ("timeslice", nt)):
        idxs = rng.sample(range(size), min(n, size))
        # one warm-up read per axis
        _read_axis(store, axis, idxs[0])
        lat: list[float] = []
        for i in idxs:
            t0 = time.perf_counter()
            _read_axis(store, axis, i)
            lat.append((time.perf_counter() - t0) * 1e3)
        out[axis] = {
            "p50_ms": round(pct(lat, 50), 1),
            "p95_ms": round(pct(lat, 95), 1),
            "mean_ms": round(float(np.mean(lat)), 1),
        }
    return out


def bench_traces(store, shape, n: int, seed: int = 7) -> dict:
    nil, nxl, nt = shape
    rng = random.Random(seed)
    pairs = [(rng.randrange(nil), rng.randrange(nxl)) for _ in range(n)]
    store[pairs[0][0], pairs[0][1], :]  # warm-up
    t0 = time.perf_counter()
    for i, j in pairs:
        store[i, j, :]
    total = (time.perf_counter() - t0) * 1e3
    return {"n": n, "total_ms": round(total, 1), "per_trace_ms": round(total / n, 2)}


def bench_threads(store, shape, threads: int, n: int, seed: int = 11) -> dict:
    """Concurrent random slice reads vs serial.

    Serial and threaded passes use *different* random job sets: reusing one
    set makes the second pass hit warm caches (rdcc / page cache) and
    overstates speedup.
    """
    from concurrent.futures import ThreadPoolExecutor

    nil, nxl, nt = shape

    def jobs(seed_: int):
        rng = random.Random(seed_)
        return [
            (
                rng.choice(("inline", "crossline", "timeslice")),
                rng.randrange(nil),
            )
            for _ in range(n)
        ]

    def run(js):
        for axis, i in js:
            size = nt if axis == "timeslice" else (nxl if axis == "crossline" else nil)
            _read_axis(store, axis, i % size)

    def run_one(job):
        axis, i = job
        size = nt if axis == "timeslice" else (nxl if axis == "crossline" else nil)
        return _read_axis(store, axis, i % size)

    serial_jobs = jobs(seed)
    threaded_jobs = jobs(seed + 1000)
    t0 = time.perf_counter()
    run(serial_jobs)
    serial = time.perf_counter() - t0

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        list(ex.map(run_one, threaded_jobs))
    threaded = time.perf_counter() - t0
    return {
        "threads": threads,
        "serial_s": round(serial, 2),
        "threaded_s": round(threaded, 2),
        "speedup": round(serial / threaded, 2),
    }


def bench_prefetch(store, shape, n: int = 20, seed: int = 13) -> dict:
    """Interactive timeslice latency while a sequential inline sweep runs."""
    nil, nxl, nt = shape
    rng = random.Random(seed)
    idxs = rng.sample(range(nt), min(n, nt))

    def measure() -> list[float]:
        lat = []
        for i in idxs:
            t0 = time.perf_counter()
            store[:, :, i]
            lat.append((time.perf_counter() - t0) * 1e3)
        return lat

    solo = measure()  # warm + solo baseline
    stop = threading.Event()

    def sweep():
        i = 0
        while not stop.is_set():
            store[i % nil, :, :]
            i += 1

    th = threading.Thread(target=sweep, daemon=True)
    th.start()
    try:
        busy = measure()
    finally:
        stop.set()
        th.join(timeout=5)
    return {
        "solo_p50_ms": round(pct(solo, 50), 1),
        "busy_p50_ms": round(pct(busy, 50), 1),
        "degradation": f"x{pct(busy, 50) / max(pct(solo, 50), 1e-9):.1f}",
    }


def build_lod_zarr(src_store: Path, dst: Path, chunk, shard) -> dict:
    """Decimate by 2 along all axes (::2) into a level-1 pyramid array."""
    import zarr
    from zarr.codecs import BloscCodec

    base = zarr.open(str(src_store), mode="r")
    nil, nxl, nt = base.shape
    l1_shape = (nil // 2, nxl // 2, nt // 2)
    arr = zarr.create_array(
        str(dst),
        shape=l1_shape,
        dtype="float32",
        chunks=chunk,
        shards=shard,
        compressors=[BloscCodec(cname="zstd", clevel=5, shuffle="bitshuffle")],
        overwrite=True,
    )
    t0 = time.perf_counter()
    step = 64
    for i0 in range(0, l1_shape[0], step):
        i1 = min(i0 + step, l1_shape[0])
        arr[i0:i1, :, :] = base[i0 * 2 : i1 * 2 : 2, ::2, ::2]
    elapsed = time.perf_counter() - t0
    size = dir_size(dst)
    base_slice_ms: list[float] = []
    rng = random.Random(3)
    for _ in range(10):
        t1 = time.perf_counter()
        base[rng.randrange(nil), :, :]
        base_slice_ms.append((time.perf_counter() - t1) * 1e3)
    l1_slice_ms: list[float] = []
    for _ in range(10):
        t1 = time.perf_counter()
        arr[rng.randrange(l1_shape[0]), :, :]
        l1_slice_ms.append((time.perf_counter() - t1) * 1e3)
    return {
        "l1_shape": l1_shape,
        "build_s": round(elapsed, 1),
        "l1_store_bytes": size,
        "base_slice_p50_ms": round(pct(base_slice_ms, 50), 1),
        "l1_slice_p50_ms": round(pct(l1_slice_ms, 50), 1),
    }


# ------------------------------------------------------------------- CLI --


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def shape3(txt: str) -> tuple[int, int, int]:
        return tuple(int(v) for v in txt.split(","))  # type: ignore[return-value]

    c = sub.add_parser("convert")
    c.add_argument("--src", type=Path, required=True)
    c.add_argument("--dst", type=Path, required=True)
    c.add_argument("--kind", choices=["zarr", "hdf5"], required=True)
    c.add_argument("--chunk", type=shape3, required=True)
    c.add_argument("--shard", type=shape3, default=None)
    c.add_argument("--cname", default="zstd")
    c.add_argument("--clevel", type=int, default=5)
    c.add_argument("--noshuffle", action="store_true")

    for name in ("slices", "traces", "threads", "prefetch"):
        c = sub.add_parser(name)
        c.add_argument("--store", type=Path, required=True)
        c.add_argument("--kind", choices=["zarr", "hdf5"], required=True)
        if name == "slices":
            c.add_argument("--n", type=int, default=50)
        if name == "traces":
            c.add_argument("--n", type=int, default=500)
        if name == "threads":
            c.add_argument("--threads", type=int, default=8)
            c.add_argument("--n", type=int, default=64)

    c = sub.add_parser("lod")
    c.add_argument("--store", type=Path, required=True)
    c.add_argument("--dst", type=Path, required=True)
    c.add_argument("--chunk", type=shape3, required=True)
    c.add_argument("--shard", type=shape3, default=None)

    c = sub.add_parser("shape")
    c.add_argument("--src", type=Path, required=True)

    args = ap.parse_args(argv)
    if args.cmd == "shape":
        print(json.dumps(segy_shape(args.src)))
        return 0
    if args.cmd == "convert":
        if args.kind == "zarr":
            facts = convert_zarr(
                args.src, args.dst, args.chunk, args.shard,
                cname=args.cname, clevel=args.clevel,
                shuffle=None if args.noshuffle else "bitshuffle",
            )
        else:
            facts = convert_hdf5(args.src, args.dst, args.chunk, clevel=args.clevel)
        print("RESULT " + json.dumps(facts, ensure_ascii=False))
        return 0

    if args.cmd == "lod":
        out = build_lod_zarr(args.store, args.dst, args.chunk, args.shard)
        print("RESULT " + json.dumps(out, ensure_ascii=False))
        return 0

    store = open_store(args.store, args.kind)
    if args.cmd == "slices":
        out = bench_slices(store, store.shape, args.n)
    elif args.cmd == "traces":
        out = bench_traces(store, store.shape, args.n)
    elif args.cmd == "threads":
        out = bench_threads(store, store.shape, args.threads, args.n)
    elif args.cmd == "prefetch":
        out = bench_prefetch(store, store.shape)
    print("RESULT " + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
