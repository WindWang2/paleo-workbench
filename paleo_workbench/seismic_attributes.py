"""Out-of-core seismic attributes: one band kernel for ROI and full volume
(#1083 / #1084).

The SAME kernel + halo semantics serve both flows:

- **ROI interactive** (:func:`roi_attribute`): the user draws a box on a
  seismic view; the interior bounds are expanded by the kernel's halo and
  fetched with ONE :meth:`ChunkedVolumeReader.read_voxel_window` call
  (chunk-coverage batch read — never per-point IO, never the whole volume),
  the native kernel runs off the GUI thread, and the halo is cropped so the
  result equals a full-volume computation on those samples.
- **Full-volume background job** (:class:`VolumeAttributeJob`): inline bands
  of ``band_inlines`` (+ halo) stream through the identical kernel into a
  float32 zarr store; completed bands carry a marker file so a cancelled or
  crashed run resumes without recomputing; progress/cancel run through the
  scheduler's TaskContext.

Correctness contract (pinned by tests): for any interior sample, band+halo
output == full-memory kernel output on the same volume (window-local
operator, so the halo fully determines the result). Band-boundary seams are
a BLOCKER by definition of that contract.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

logger = logging.getLogger(__name__)


def _kernel_c3(block: np.ndarray, **kw) -> np.ndarray:
    from geoviz_seismic.attributes import compute_coherence_c3

    return compute_coherence_c3(block, **kw)


def _time_axis_kernel(fn_name: str, **defaults):
    """Wrap an engine along-time-axis attribute into the kernel contract.

    The engine's envelope/phase/frequency/impedance family takes
    ``(data, axis=-1, ...)`` and has no GPU switch — the wrapper absorbs
    ``use_gpu`` so :func:`compute_block` can call every kernel uniformly.
    """
    def kernel(block: np.ndarray, **kw) -> np.ndarray:
        from geoviz_seismic import attributes as engine_attributes

        kw.pop("use_gpu", None)
        fn = getattr(engine_attributes, fn_name)
        return fn(block, **{**defaults, **kw})

    return kernel


def _dip_kernel(component: str):
    """dip_il / dip_xl / dip_azimuth from the engine's structural suite."""

    def kernel(block: np.ndarray, **kw) -> np.ndarray:
        from geoviz_seismic.attributes import compute_azimuth, compute_dip

        kw.pop("use_gpu", None)
        dip_il, dip_xl = compute_dip(block, axis_il=0, axis_xl=1, axis_t=2)
        if component == "dip_il":
            return dip_il
        if component == "dip_xl":
            return dip_xl
        return compute_azimuth(dip_il, dip_xl)

    return kernel


def _curvature_kernel(block: np.ndarray, **kw) -> np.ndarray:
    from geoviz_seismic.attributes import compute_curvature

    return compute_curvature(block, **kw)


# name -> (callable, default half-window kwargs, per-axis half-window sizes)
# Halos are the minimal per-axis neighborhoods each operator reads (a
# gradient costs 1 sample; smoothing windows cost their half-window), so a
# halo block reproduces full-volume output exactly at every interior sample.
KERNELS: dict[str, tuple[Callable[..., np.ndarray], dict, tuple[int, int, int]]] = {
    "c3": (_kernel_c3, {"win_il": 5, "win_xl": 5, "win_t": 5}, (5, 5, 5)),
    "envelope": (_time_axis_kernel("compute_envelope", axis=-1), {}, (0, 0, 2)),
    "instantaneous_phase": (
        _time_axis_kernel("compute_instantaneous_phase", axis=-1),
        {},
        (0, 0, 2),
    ),
    "instantaneous_frequency": (
        _time_axis_kernel("compute_instantaneous_frequency", sample_interval=1.0, axis=-1),
        {},
        (0, 0, 4),
    ),
    "rms_amplitude": (
        _time_axis_kernel("compute_rms_amplitude", window=10, axis=-1),
        {},
        (0, 0, 10),
    ),
    "sweetness": (
        _time_axis_kernel("compute_sweetness", sample_interval=1.0, axis=-1),
        {},
        (0, 0, 4),
    ),
    "relative_impedance": (
        _time_axis_kernel("compute_relative_impedance", axis=-1),
        {},
        (0, 0, 2),
    ),
    "dip_il": (_dip_kernel("dip_il"), {}, (2, 2, 2)),
    "dip_xl": (_dip_kernel("dip_xl"), {}, (2, 2, 2)),
    "dip_azimuth": (_dip_kernel("dip_azimuth"), {}, (2, 2, 2)),
    "curvature_mean": (
        _curvature_kernel,
        # Reach per axis: slope gradient ±1 + slope smoothing ±win + double
        # second derivative ±2 ⇒ ±(1 + win + 2).
        {"kind": "mean", "win_il": 3, "win_xl": 3, "win_t": 3},
        (6, 6, 6),
    ),
}


# Trace-global kernels operate through a full-trace FFT (Hilbert transform):
# their value at ANY sample depends on the whole trace, so no finite halo can
# reproduce full-volume output inside a cropped TIME window. They are exact
# in the banded full-volume job (bands slice inlines only — every trace is
# complete) and MUST NOT be offered on cropped-time ROIs.
TRACE_GLOBAL_KERNELS = frozenset(
    {
        "envelope",
        "instantaneous_phase",
        "instantaneous_frequency",
        "sweetness",
        "relative_impedance",
    }
)


def attribute_halo(name: str) -> tuple[int, int, int]:
    """Per-axis halo (samples) the kernel needs around an interior block."""
    try:
        return KERNELS[name][2]
    except KeyError:
        raise ValueError(f"unknown attribute kernel {name!r}") from None


def available_kernels() -> list[str]:
    return sorted(KERNELS)


def _pad_short_axis(
    block: np.ndarray,
    axis: int,
    deficit: int,
    pad_low: bool,
    pad_high: bool,
) -> np.ndarray:
    """Reflect-pad ONE axis of a halo block up to the kernel window size.

    The kernel shrinks its window when an input axis is shorter than
    ``2*half+1`` (``wil = min(2*win+1, n)``). A halo block that is clamped
    at a SURVEY edge can legitimately be that short (e.g. a last inline
    band); to keep full-volume semantics the block is padded on the clamped
    side with the same reflect mode the kernel applies at survey
    boundaries. Windows of cropped interior positions then contain exactly
    the values the full-volume run saw — never a shrunk window, never fake
    data (interior cut sides already carry real halo).
    """
    if deficit <= 0:
        return block
    low = deficit if pad_low else 0
    high = deficit if pad_high else 0
    if low == 0 and high == 0:
        return block
    pad = [(0, 0)] * block.ndim
    pad[axis] = (low, high)
    return np.pad(block, pad, mode="reflect")


def compute_block(
    reader: Any,
    name: str,
    il0: int,
    il1: int,
    xl0: int,
    xl1: int,
    t0: int,
    t1: int,
    *,
    use_gpu: bool = False,
) -> np.ndarray:
    """Compute *name* over the interior window, halo handled internally.

    Reads ``[il0-h:il1+h, xl0-h:xl1+h, t0-h:t1+h]`` (clamped at survey
    edges) in ONE batched voxel-window read, runs the kernel, crops back to
    the interior. Output shape == interior shape; values equal a
    full-volume computation on the same samples.
    """
    fn, kwargs, halo = KERNELS[name]
    n_il, n_xl, n_t = reader.shape
    hi, hx, ht = halo
    r_il0, r_il1 = max(0, il0 - hi), min(n_il, il1 + hi)
    r_xl0, r_xl1 = max(0, xl0 - hx), min(n_xl, xl1 + hx)
    r_t0, r_t1 = max(0, t0 - ht), min(n_t, t1 + ht)
    if r_il1 <= r_il0 or r_xl1 <= r_xl0 or r_t1 <= r_t0:
        raise ValueError(f"empty attribute window [{il0}:{il1},{xl0}:{xl1},{t0}:{t1}]")
    block = reader.read_voxel_window(r_il0, r_il1, r_xl0, r_xl1, r_t0, r_t1)
    block = np.ascontiguousarray(block, dtype=np.float32)
    # Window-size parity: a clamped block shorter than the kernel window
    # must not let the kernel shrink the window (see _pad_short_axis).
    # Low-side pads shift where the interior sits inside `block`.
    pad_low = [0, 0, 0]
    spans = (
        (r_il0, r_il1, n_il, hi, 0),
        (r_xl0, r_xl1, n_xl, hx, 1),
        (r_t0, r_t1, n_t, ht, 2),
    )
    for lo, hi_end, n, half, axis in spans:
        length = hi_end - lo
        need = 2 * half + 1
        if length < need and length < n:
            # Full-axis blocks keep the kernel's own (identical) shrink.
            # Partial blocks pad on the INTERIOR-CUT side: that padding is
            # unreachable by cropped windows (they stay inside real data ∪
            # survey-edge reflect), while padding a survey edge would
            # distort the kernel's own reflect pattern there.
            deficit = need - length
            block = _pad_short_axis(
                block, axis, deficit,
                pad_low=lo > 0,
                pad_high=hi_end < n,
            )
            if lo > 0:
                pad_low[axis] = deficit
    result = fn(block, use_gpu=use_gpu, **kwargs)
    out = result[
        pad_low[0] + il0 - r_il0 : pad_low[0] + il0 - r_il0 + (il1 - il0),
        pad_low[1] + xl0 - r_xl0 : pad_low[1] + xl0 - r_xl0 + (xl1 - xl0),
        pad_low[2] + t0 - r_t0 : pad_low[2] + t0 - r_t0 + (t1 - t0),
    ]
    return np.ascontiguousarray(out)


def roi_attribute(
    reader: Any,
    bounds: tuple[int, int, int, int, int, int],
    name: str = "c3",
    *,
    use_gpu: bool = False,
) -> np.ndarray:
    """Interactive ROI attribute (#1083). ``bounds`` are half-open base-index
    inline/xline/time bounds — one halo-expanded batch read, kernel, crop.

    Trace-global (FFT) kernels are refused for cropped time windows: their
    output would silently differ from the full-volume computation, which is
    exactly the seam this module exists to prevent. Expand the ROI to the
    full time extent (caller's choice) to use them honestly.
    """
    il0, il1, xl0, xl1, t0, t1 = (int(b) for b in bounds)
    if name in TRACE_GLOBAL_KERNELS and (t0 != 0 or t1 != int(reader.shape[2])):
        raise ValueError(
            f"attribute {name!r} is trace-global (full-trace FFT); "
            "crop the map extent instead of the time window, or compute it "
            "as a full-volume attribute job"
        )
    return compute_block(
        reader, name, il0, il1, xl0, xl1, t0, t1, use_gpu=use_gpu
    )


# ------------------------------------------------------------------------ #
# Full-volume banded job (#1084)
# ------------------------------------------------------------------------ #


@dataclass
class AttributeJobStats:
    bands_total: int = 0
    bands_done: int = 0
    elapsed_s: float = 0.0


# #1146: worst-case in-flight multiple of one inline slab, measured per
# kernel family (c3 ≈ 5x: slab + ones + reflect pad + output; float64
# rms-style paths ≈ 7-8x). One conservative factor for all kernels.
ATTRIBUTE_PEAK_FACTOR = 8
ATTRIBUTE_MIN_BAND_INLINES = 1


def _attribute_budget_bytes() -> int:
    """Bytes one attribute band may peak at (operator budget, not a constant)."""
    try:
        from paleo_workbench.runtime.resource_budget import active_budget

        return int(active_budget().streaming_buffer_bytes)
    except Exception:
        return 5 * 1024**3


def derive_band_inlines(
    n_xl: int,
    n_t: int,
    *,
    budget_bytes: int | None = None,
    peak_factor: int = ATTRIBUTE_PEAK_FACTOR,
) -> int:
    """Inline count per band such that peak temp stays within budget (#1146).

    ``bytes_per_inline × band × peak_factor ≤ budget``; always ≥ 1 so
    degenerate volumes still run (slowly) instead of refusing.
    """
    budget = int(budget_bytes) if budget_bytes else _attribute_budget_bytes()
    per_inline = max(1, int(n_xl) * max(1, int(n_t)) * 4)
    band = max(ATTRIBUTE_MIN_BAND_INLINES, budget // (per_inline * max(1, peak_factor)))
    return int(band)


class VolumeAttributeJob:
    """Banded, resumable full-volume attribute run (#1084).

    Same kernel and halo semantics as :func:`roi_attribute` — the only
    difference is scheduling and output: bands stream into a float32 zarr
    store (chunk/shard grid matches the seismic spec), completed bands carry
    ``.done/band_<k>`` marker files (written AFTER the slab lands, fsynced),
    so cancel/crash resume skips finished bands exactly like the transcoder
    skips finished shards.
    """

    def __init__(
        self,
        reader: Any,
        dst_store: str | Path,
        name: str = "c3",
        *,
        band_inlines: int | None = None,
        use_gpu: bool = False,
    ):
        if name not in KERNELS:
            raise ValueError(f"unknown attribute kernel {name!r}")
        self.reader = reader
        self.dst = Path(dst_store)
        self.name = name
        # #1146: None derives from the operator memory budget and the
        # volume geometry; an explicit positive value is honored verbatim
        # (tests, resume-shape stability).
        if band_inlines is None:
            n_xl = int(reader.shape[1])
            n_t = int(reader.shape[2])
            self.band_inlines = derive_band_inlines(n_xl, n_t)
        else:
            self.band_inlines = max(1, int(band_inlines))
        self.use_gpu = use_gpu
        self.stats = AttributeJobStats()

    # ------------------------------------------------------------ layout --
    def band_bounds(self) -> list[tuple[int, int]]:
        n_il = self.reader.shape[0]
        step = self.band_inlines
        return [(i, min(i + step, n_il)) for i in range(0, n_il, step)]

    def _open_or_create_output(self):
        import zarr
        from zarr.codecs import BloscCodec

        meta = self.dst / "zarr.json"
        if meta.exists():
            return zarr.open(str(self.dst), mode="a")
        self.dst.mkdir(parents=True, exist_ok=True)
        return zarr.create_array(
            str(self.dst),
            shape=tuple(self.reader.shape),
            dtype="float32",
            chunks=(64, 128, 128),
            shards=(128, 512, 512),
            compressors=[BloscCodec(cname="zstd", clevel=5, shuffle="shuffle")],
            overwrite=False,
            attributes={
                "attribute": self.name,
                "shape": list(self.reader.shape),
                "kind": "attribute-volume",
            },
        )

    def _done_dir(self) -> Path:
        return self.dst.parent / f"{self.dst.name}.done"

    def completed_bands(self) -> set[int]:
        done = self._done_dir()
        out: set[int] = set()
        if not done.is_dir():
            return out
        for f in done.iterdir():
            if f.name.startswith("band_"):
                try:
                    out.add(int(f.name[5:]))
                except ValueError:
                    continue
        return out

    def _mark_band_done(self, k: int) -> None:
        import os

        done = self._done_dir()
        done.mkdir(parents=True, exist_ok=True)
        marker = done / f"band_{k:06d}"
        marker.write_text("ok")
        try:
            fd = os.open(done, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    # ---------------------------------------------------------------- run --
    def run(
        self,
        ctx: Any,
    ) -> dict[str, Any]:
        """Scheduler entry point (TaskContext). Cancel-safe and resumable."""
        t0 = time.perf_counter()
        arr = self._open_or_create_output()
        bounds = self.band_bounds()
        self.stats.bands_total = len(bounds)
        finished = self.completed_bands()
        n_il, n_xl, n_t = self.reader.shape
        for k, (i0, i1) in enumerate(bounds):
            ctx.check_cancelled()
            if k in finished:
                self.stats.bands_done += 1
                ctx.report_progress(self.stats.bands_done, self.stats.bands_total)
                continue
            result = compute_block(
                self.reader, self.name, i0, i1, 0, n_xl, 0, n_t,
                use_gpu=self.use_gpu,
            )
            ctx.check_cancelled()
            arr[i0:i1, :, :] = result
            self._mark_band_done(k)
            self.stats.bands_done += 1
            ctx.report_progress(self.stats.bands_done, self.stats.bands_total)
        self.stats.elapsed_s = time.perf_counter() - t0
        return {
            "bands": self.stats.bands_total,
            "elapsed_s": self.stats.elapsed_s,
            "attribute": self.name,
        }
