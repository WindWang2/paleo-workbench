"""Prototype (#1072, wayfinder map #1067): chunked-volume access API over Zarr.

Mirrors ``geoviz_seismic.loader.SeismicLoader``'s public read surface so the
existing consumers (seismic_view / renderer_3d / horizon / well-tie) can be
switched with minimal churn:

    read_inline(iline) / read_crossline(xline) / read_timeslice(sample_idx)
    read_trace(iline, xline)                     — same names, plus:

    read_voxel_window(il0, il1, xl0, xl1, t0, t1, *, lod)
    read_arbitrary_line(points, *, lod)          — horizon 追踪的前提
    ``lod=N`` on every plane read                — 金字塔级别（0 = 基础体）

LOD pyramid levels are built lazily on first use, cascaded from the previous
level (l_n from l_{n-1}), stored as sibling arrays ``<store>_l{n}`` so
existing stores never get touched. Three sampling strategies:

    stride  — [::2,::2,::2] decimation; fastest, keeps true amplitudes,
              can alias (fault edges shimmer while scrolling)
    mean    — block mean; smooths, dims reflections (polarity cancels)
    maxabs  — sign-preserving max|x| in block; preserves strongest event,
              best for QC/structure browsing at deep LOD

Integration with the existing dual-level LRU: every plane read goes through
``RamSliceCache`` with ``SliceCacheKey(volume_id, slice_type, position,
downsample_factor=(2**lod,)*3, attribute_id="raw")`` — the existing key
already carries ``downsample_factor``, so no cache-schema change is needed.

Prototype quality on purpose: single file, sync API, no cancellation tokens
(#1071 owns those), errors raise. Numbers in demo.py.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np


def _fallback_cache():
    """Tiny local LRU if geoviz_seismic isn't importable (standalone runs)."""

    class _MiniCache:
        def __init__(self, max_bytes=512 * 1024 * 1024):
            self.max_bytes, self.cur, self._d = max_bytes, 0, {}

        def get(self, key):
            if key in self._d:
                return self._d[key][0]
            return None

        def put(self, key, arr):
            b = arr.nbytes
            while self._d and self.cur + b > self.max_bytes:
                self._d.pop(next(iter(self._d)))
            self._d[key] = (arr, b)
            self.cur += b

    return _MiniCache()


def _make_key(volume_id, slice_type, position, lod):
    try:
        from geoviz_seismic.cache import SliceCacheKey

        return SliceCacheKey(
            volume_id=volume_id,
            slice_type=slice_type,
            position=int(position),
            downsample_factor=(2**lod, 2**lod, 2**lod),
        )
    except Exception:
        return (volume_id, slice_type, int(position), 2**lod)


class ChunkedVolumeReader:
    """Zarr-backed reader with lazy LOD pyramid and optional L1 cache."""

    STRATEGIES = ("stride", "mean", "maxabs")

    def __init__(
        self,
        store_path: str | Path,
        *,
        iline_start: int = 1,
        xline_start: int = 1,
        lod_strategy: str = "stride",
        max_lod: int = 4,
    ):
        import zarr

        self.path = str(store_path)
        self._zarr = zarr
        self._base = zarr.open(self.path, mode="r")
        self.iline_start = iline_start
        self.xline_start = xline_start
        self.lod_strategy = lod_strategy
        self.max_lod = max_lod
        self._levels: dict[int, object] = {0: self._base}
        self._cache = _fallback_cache()
        self.lod_build_seconds: dict[int, float] = {}

    # ------------------------------------------------------------ meta --
    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(self._base.shape)  # type: ignore[return-value]

    # ------------------------------------------------------------- LOD --
    def _decimate(self, arr) -> np.ndarray:
        s = self.lod_strategy
        if s == "stride":
            return np.asarray(arr[::2, ::2, ::2])
        if s == "mean":
            ni, nx, nt = arr.shape
            ni2, nx2, nt2 = ni // 2, nx // 2, nt // 2
            a = np.asarray(arr[: ni2 * 2, : nx2 * 2, : nt2 * 2], dtype=np.float32)
            return a.reshape(ni2, 2, nx2, 2, nt2, 2).mean(axis=(1, 3, 5))
        if s == "maxabs":
            ni, nx, nt = arr.shape
            ni2, nx2, nt2 = ni // 2, nx // 2, nt // 2
            a = np.asarray(arr[: ni2 * 2, : nx2 * 2, : nt2 * 2], dtype=np.float32)
            b = a.reshape(ni2, 2, nx2, 2, nt2, 2)
            m = np.abs(b).max(axis=(1, 3, 5))
            sign = np.sign(b.reshape(ni2, 2, nx2, 2, nt2, 2).reshape(ni2, nx2, nt2, 8))
            # take sign of the sample with max |x| per block
            flat = b.reshape(ni2, nx2, nt2, 8)
            idx = np.abs(flat).argmax(axis=-1)
            return np.take_along_axis(flat, idx[..., None], axis=-1)[..., 0]
        raise ValueError(f"unknown LOD strategy {s!r}")

    def _level(self, lod: int):
        if lod in self._levels:
            return self._levels[lod]
        if lod > self.max_lod:
            raise ValueError(f"lod={lod} exceeds max_lod={self.max_lod}")
        lower = self._level(lod - 1)  # cascade build
        from zarr.codecs import BloscCodec

        out_path = f"{self.path}_l{lod}"
        src = np.asarray(lower.shape)
        t0 = time.perf_counter()
        dst = self._zarr.create_array(
            out_path,
            shape=tuple(np.floor_divide(src, 2)),
            dtype="float32",
            chunks=(64, 128, 128),
            shards=(128, 512, 512),
            compressors=[
                BloscCodec(cname="zstd", clevel=5, shuffle=None)
            ],
            overwrite=True,
        )
        n0, nx, nt = dst.shape
        for i0 in range(0, n0, 64):
            i1 = min(i0 + 64, n0)
            dst[i0:i1, :, :] = self._decimate(lower[i0 * 2 : i1 * 2, :, :])
        self.lod_build_seconds[lod] = time.perf_counter() - t0
        self._levels[lod] = dst
        return dst

    # ---------------------------------------------------------- reads --
    def _idx_il(self, iline: int) -> int:
        i = int(iline) - self.iline_start
        nil, _, _ = self.shape
        if not 0 <= i < nil:
            raise IndexError(f"inline {iline} out of range")
        return i

    def _idx_xl(self, xline: int) -> int:
        j = int(xline) - self.xline_start
        _, nxl, _ = self.shape
        if not 0 <= j < nxl:
            raise IndexError(f"xline {xline} out of range")
        return j

    def _cached(self, slice_type: str, position: int, lod: int, fetch):
        key = _make_key(self.path, slice_type, position, lod)
        hit = self._cache.get(key)
        if hit is not None:
            return hit, True
        arr = fetch()
        self._cache.put(key, arr)
        return arr, False

    def read_inline(self, iline: int, *, lod: int = 0) -> np.ndarray:
        i = self._idx_il(iline) >> lod  # same iline VALUE at every level
        arr, _ = self._cached(
            "inline", i, lod, lambda: np.asarray(self._level(lod)[i, :, :])
        )
        return arr

    def read_crossline(self, xline: int, *, lod: int = 0) -> np.ndarray:
        j = self._idx_xl(xline) >> lod
        arr, _ = self._cached(
            "crossline", j, lod, lambda: np.asarray(self._level(lod)[:, j, :])
        )
        return arr

    def read_timeslice(self, sample_idx: int, *, lod: int = 0) -> np.ndarray:
        _, _, nt = self.shape
        k = int(sample_idx)
        if not 0 <= k < nt:
            raise IndexError(f"sample {k} out of range")
        k >>= lod
        arr, _ = self._cached(
            "timeslice", k, lod, lambda: np.asarray(self._level(lod)[:, :, k])
        )
        return arr

    def read_trace(self, iline: int, xline: int, *, lod: int = 0) -> np.ndarray:
        return np.asarray(
            self._level(lod)[self._idx_il(iline) >> lod, self._idx_xl(xline) >> lod, :]
        )

    def read_voxel_window(
        self,
        il0: int,
        il1: int,
        xl0: int,
        xl1: int,
        t0: int,
        t1: int,
        *,
        lod: int = 0,
    ) -> np.ndarray:
        """Half-open bounds in index space; used by属性 halo 读取与 AI tile 组装."""
        return np.asarray(
            self._level(lod)[il0:il1, xl0:xl1, t0:t1]
        )

    def read_arbitrary_line(
        self, points, *, lod: int = 0, interpolate: bool = True
    ) -> np.ndarray:
        """Gather traces along a polyline in (inline, xline) VALUE space.

        Nearest-trace gather by default; ``interpolate=True`` bilinearly
        blends the 4 surrounding traces (display-grade, not processing-grade).
        """
        lvl = self._level(lod)
        pts = np.asarray(points, dtype=np.float64)
        fi = (pts[:, 0] - self.iline_start) / 2**lod
        fx = (pts[:, 1] - self.xline_start) / 2**lod
        if not interpolate:
            ii = np.rint(fi).astype(int)
            jj = np.rint(fx).astype(int)
            return np.stack([np.asarray(lvl[i, j, :]) for i, j in zip(ii, jj)])
        i0 = np.floor(fi).astype(int)
        j0 = np.floor(fx).astype(int)
        di = (fi - i0)[:, None]
        dj = (fx - j0)[:, None]
        out = []
        for k in range(len(fi)):
            traces = np.stack(
                [
                    np.asarray(lvl[i0[k], j0[k], :]),
                    np.asarray(lvl[i0[k], j0[k] + 1, :]),
                    np.asarray(lvl[i0[k] + 1, j0[k], :]),
                    np.asarray(lvl[i0[k] + 1, j0[k] + 1, :]),
                ]
            )
            t00, t01, t10, t11 = traces
            out.append(
                (t00 * (1 - dj[k]) + t01 * dj[k]) * (1 - di[k])
                + (t10 * (1 - dj[k]) + t11 * dj[k]) * di[k]
            )
        return np.stack(out)

    def attach_cache(self, cache) -> None:
        """Plug in the production ``RamSliceCache`` (dual-level LRU L1)."""
        self._cache = cache


class DirectionalPrefetcher:
    """DragTracker 的原型等价物：沿运动方向后台预读 inline."""

    def __init__(self, reader: ChunkedVolumeReader, ahead: int = 4, lod: int = 0):
        import threading

        self._lock = threading.Lock()
        self._thread = None
        self.reader = reader
        self.ahead = ahead
        self.lod = lod
        self._gen = 0

    def update(self, iline: int) -> None:
        with self._lock:
            self._gen += 1
            gen = self._gen
        vals = range(int(iline) + 1, int(iline) + 1 + self.ahead)
        if self._thread and self._thread.is_alive():
            return  # previous batch still running; it will be superseded
        import threading

        def work():
            g = gen
            for v in vals:
                with self._lock:
                    if g != self._gen:
                        return
                try:
                    self.reader.read_inline(v, lod=self.lod)
                except IndexError:
                    return

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
