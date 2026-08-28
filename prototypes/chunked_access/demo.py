"""Demo driver for the chunked-access prototype (#1072).

Prints a markdown table of the numbers the API draft cites:

  quick2g (internal NVMe): LOD build cost + plane latency per lod,
  cache hit, prefetch hit, trace reads, arbitrary line.
  g100 (external USB-NTFS): cold plane reads at lod 0.

Usage:
  python prototypes/chunked_access/demo.py \
      --quick2g /path/to/q2g_z_mix64 [--g100 /path/to/g100_z_64cube_noshuf]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from reader import ChunkedVolumeReader, DirectionalPrefetcher


def timed(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return out, (time.perf_counter() - t0) * 1e3


def p50(xs):
    return float(np.percentile(np.asarray(xs), 50))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick2g", type=Path, required=True)
    ap.add_argument("--g100", type=Path, default=None)
    ap.add_argument("--strategy", default="stride", choices=ChunkedVolumeReader.STRATEGIES)
    args = ap.parse_args()

    print(f"# chunked-access prototype demo（LOD 策略 = {args.strategy}）\n")

    # ---------------- quick2g: LOD story ----------------
    r = ChunkedVolumeReader(args.quick2g, lod_strategy=args.strategy)
    nil, nxl, nt = r.shape
    print(f"quick2g store: {args.quick2g} shape={r.shape}")

    print("\n## 懒构建 LOD（级联 ::2）")
    for lod in (1, 2):
        r._level(lod)
        print(f"- l{lod}: {r.lod_build_seconds[lod]:.1f} s, shape={r._level(lod).shape}")

    print("\n## 切片延迟 p50 ms（n=10，LOD0=冷、LOD≥1 构建后）")
    rng = np.random.default_rng(5)
    rows = []
    for axis, reader_fn, size in (
        ("inline", r.read_inline, nil),
        ("crossline", r.read_crossline, nxl),
        ("timeslice", r.read_timeslice, nt),
    ):
        idxs = rng.choice(size, 20, replace=False)
        row = [axis]
        for lod in (0, 1, 2):
            lat = []
            for i in idxs:
                r._cache._d.clear() if hasattr(r._cache, "_d") else None
                _, ms = timed(reader_fn, int(i), lod=lod)
                lat.append(ms)
            row.append(f"{p50(lat):.0f}")
        rows.append(row)
    print("| axis | lod0 | lod1 | lod2 |\n|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(row) + " |")

    print("\n## L1 缓存命中")
    _, cold = timed(r.read_inline, 800)
    _, warm = timed(r.read_inline, 800)
    _, warm2 = timed(r.read_inline, 800)
    print(f"- inline 1234: 冷 {cold:.0f} ms → 热 {min(warm, warm2):.2f} ms")

    print("\n## 方向预读（DirectionalPrefetcher, ahead=4）")
    pf = DirectionalPrefetcher(r, ahead=4)
    lat_after = []
    for i in range(400, 408):
        pf.update(i)
        _, ms = timed(r.read_inline, i)
        lat_after.append(ms)
        time.sleep(0.35)
    print(f"- 拖拽序列 8 张 inline p50: {p50(lat_after):.0f} ms（含预读命中）")

    print("\n## 单道与任意线")
    lat = []
    for k in range(50):
        _, ms = timed(r.read_trace, 300 + (k % 40) * 9, 300 + (k % 50) * 13)
        lat.append(ms)
    print(f"- read_trace ×50: p50 {p50(lat):.0f} ms")
    pts = list(zip(np.linspace(50, 950, 100), np.linspace(100, 900, 100)))
    _, ms = timed(r.read_arbitrary_line, pts)
    print(f"- read_arbitrary_line（100 点双线性）: {ms:.0f} ms")

    # ---------------- g100: cold reads ----------------
    if args.g100:
        print(f"\n# g100 store（外置 USB-NTFS，冷）: {args.g100}")
        g = ChunkedVolumeReader(args.g100)
        gn = g.shape
        _, ms_il = timed(g.read_inline, 2500)
        lat_xl = []
        for j in (1200, 2600, 3800):
            _, ms = timed(g.read_crossline, j)
            lat_xl.append(ms)
        _, ms_ts = timed(g.read_timeslice, 500)
        print(f"- read_inline(2500): {ms_il:.0f} ms")
        print(f"- read_crossline p50(3 抽样): {p50(lat_xl):.0f} ms")
        print(f"- read_timeslice(500): {ms_ts:.0f} ms")
        _, ms_tr = timed(g.read_trace, 2500, 2500)
        print(f"- read_trace(2500,2500): {ms_tr:.0f} ms")
        win, ms_w = timed(
            g.read_voxel_window, 2400, 2464, 2400, 2464, 400, 600
        )
        print(
            f"- read_voxel_window(64×64×200): {ms_w:.0f} ms shape={win.shape}"
        )


if __name__ == "__main__":
    main()
