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

# #1146: one band materializes, per inline, the halo-expanded input block,
# a contiguous float32 copy, and the kernel output — modelled as 3 resident
# copies of (band + 2*inline-halo) inlines of n_xl*n_t*4 bytes.
_BAND_COPIES = 3
# Fraction of the streaming-buffer budget a single band batch may occupy.
_BAND_RAM_SHARE = 0.25
BAND_INLINES_MIN = 8
BAND_INLINES_MAX = 64


# #1146: worst-case in-flight multiple of one inline slab, measured per
# kernel family (c3 ≈ 5x: slab + ones + reflect pad + output; float64
# rms-style paths ≈ 7-8x). One conservative factor for all kernels.
ATTRIBUTE_PEAK_FACTOR = 8
ATTRIBUTE_MIN_BAND_INLINES = 1
ATTRIBUTE_SHARD = (128, 512, 512)


def derive_band_inlines(
    shape_or_n_xl: tuple[int, int, int] | int,
    n_t: int | None = None,
    *,
    halo: tuple[int, int, int] = (0, 0, 0),
    budget_bytes: int | None = None,
    band_ram_share: float = _BAND_RAM_SHARE,
    min_inlines: int = BAND_INLINES_MIN,
    max_inlines: int = BAND_INLINES_MAX,
    peak_factor: int = ATTRIBUTE_PEAK_FACTOR,
) -> int:
    """Band size (inlines) for the full-volume job, derived from the
    ResourceGovernor's active budget (#1146).

    Previously a hardcoded ``band_inlines=64`` ignored the budget entirely
    (12-20 GB resident per batch on large volumes — an order of magnitude
    over the provider admission estimate). The derivation bounds one band's
    working set to ``band_ram_share`` of the budget's streaming buffer:

        3 copies x (band + 2*halo_il) inlines x n_xl*n_t*4 bytes <= share

    and clamps to ``[min_inlines, max_inlines]`` so tiny budgets still make
    progress and huge budgets cannot reintroduce the RSS blow-up. Exposed
    for the provider side so its ResourceProfile RAM estimate and the job's
    actual batch size stay aligned.
    """
    if n_t is not None:
        shape = (100, int(shape_or_n_xl), int(n_t))
        halo = (1, 0, 0)
    else:
        shape = shape_or_n_xl
    n_il, n_xl, n_t_val = (int(v) for v in shape)
    bytes_per_inline = max(1, n_xl * n_t_val * 4)
    halo_il = int(halo[0]) if halo else 0
    if budget_bytes is None:
        try:
            from paleo_workbench.runtime.resource_budget import active_budget

            budget_bytes = active_budget().streaming_buffer_bytes
        except Exception:
            budget_bytes = 5 << 30
    band_budget = max(1, int(float(budget_bytes) * float(band_ram_share)))
    raw = band_budget // (_BAND_COPIES * bytes_per_inline) - 2 * halo_il
    # Clamp: tiny budgets still make progress (floor), huge budgets cannot
    # reintroduce the 64-inline RSS blow-up (ceiling). The last band's
    # remainder is handled by band_bounds, so n_il needs no special case.
    band = max(1, raw)
    return max(min_inlines, min(max_inlines, band))


@dataclass
class AttributeJobStats:
    bands_total: int = 0
    bands_done: int = 0
    elapsed_s: float = 0.0


class VolumeAttributeJob:
    """Banded, resumable full-volume attribute run (#1084).

    Same kernel and halo semantics as :func:`roi_attribute` — the only
    difference is scheduling and output: bands stream into a float32 zarr
    store (chunk/shard grid matches the seismic spec), completed bands carry
    ``.done/band_<i0>`` marker files — identified by the band's FIRST
    INLINE (#1161), so markers can never be misread as positional indices
    after the band layout changes — and are written only after the band's
    shard data is fsynced (#1194), so cancel/crash resume skips finished
    bands exactly like the transcoder skips finished shards.

    ``band_inlines=None`` (the default) derives the band size from the
    ResourceGovernor's active budget via :func:`derive_band_inlines`
    (#1146); an explicit value is honoured as-is.
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
        if band_inlines is None:
            band_inlines = derive_band_inlines(
                tuple(reader.shape), halo=attribute_halo(name)
            )
        self.band_inlines = int(band_inlines)
        self.use_gpu = use_gpu
        self.stats = AttributeJobStats()

    # ------------------------------------------------------------ layout --
    def band_bounds(self) -> list[tuple[int, int]]:
        n_il = self.reader.shape[0]
        step = self.band_inlines
        return [(i, min(i + step, n_il)) for i in range(0, n_il, step)]

    def _source_identity(self) -> dict:
        """Identity of the source volume this job reads (source-mix guard).

        Same scheme as the transcoder's ``_source_identity`` (#1141): the
        reader's zarr store path plus size/mtime — cheap (no content hashing
        of a huge store) yet enough to tell two same-shape volumes apart
        when the active volume switches under a reused attribute store.
        Readers without a ``path`` (in-memory test fakes) contribute no
        identity fields, matching the pre-fix spec for them.
        """
        from paleo_workbench.seismic_transcode import _source_identity

        path = getattr(self.reader, "path", None)
        if not path:
            return {}
        return _source_identity(Path(str(path)))

    def _banding_spec(self) -> dict:
        """Identity of the band layout this job will produce (#1161).

        Includes the SOURCE volume identity: without it, switching the
        active volume and recomputing the same kernel/band/shape attribute
        into a reused store would make #1161's marker trust reuse the
        previous volume's bands — mixed-source DERIVED output. A spec
        mismatch discards the markers and recomputes every band.
        """
        spec = {
            "attribute": self.name,
            "band_inlines": self.band_inlines,
            "shape": [int(v) for v in self.reader.shape],
        }
        spec.update(self._source_identity())
        return spec

    def _open_or_create_output(self):
        import zarr

        meta = self.dst / "zarr.json"
        if meta.exists():
            arr = zarr.open(str(self.dst), mode="a")
            attrs = dict(arr.attrs or {})
            stored_banding = attrs.get("banding")
            if stored_banding != self._banding_spec():
                # #1161: the existing store was laid out for a different
                # banding (band size, volume shape, or attribute). The old
                # markers describe bands that no longer exist at those
                # positions — invalidate them and start the band plan over.
                logger.warning(
                    "attribute store %s has banding %s but this job wants "
                    "%s; discarding old band markers and recomputing",
                    self.dst,
                    stored_banding,
                    self._banding_spec(),
                )
                self._invalidate_done_markers()
                if attrs.get("shape") != self._banding_spec()["shape"]:
                    arr = self._create_output_array(overwrite=True)
                else:
                    arr.attrs["banding"] = self._banding_spec()
            return arr
        return self._create_output_array(overwrite=False)

    def _create_output_array(self, *, overwrite: bool):
        import zarr
        from zarr.codecs import BloscCodec

        self.dst.mkdir(parents=True, exist_ok=True)
        return zarr.create_array(
            str(self.dst),
            shape=tuple(self.reader.shape),
            dtype="float32",
            chunks=(64, 128, 128),
            shards=(128, 512, 512),
            compressors=[BloscCodec(cname="zstd", clevel=5, shuffle="shuffle")],
            overwrite=overwrite,
            attributes={
                "attribute": self.name,
                "shape": list(self.reader.shape),
                "kind": "attribute-volume",
                "banding": self._banding_spec(),
            },
        )

    def _done_dir(self) -> Path:
        return self.dst.parent / f"{self.dst.name}.done"

    def _invalidate_done_markers(self) -> None:
        """Drop all band markers (banding changed, #1161)."""
        done = self._done_dir()
        if not done.is_dir():
            return
        for f in done.iterdir():
            if f.name.startswith("band_"):
                try:
                    f.unlink()
                except OSError:
                    logger.exception("could not remove stale marker %s", f)

    def completed_bands(self) -> set[int]:
        """First-inline numbers of bands whose markers exist (#1161)."""
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

    # ------------------------------------------------- durability (#1194) --
    @staticmethod
    def _fsync_path(path: Path) -> None:
        """fsync one path — a data file (flush its pages) or a directory
        (flush its entries); both take an O_RDONLY fd on Linux."""
        import os

        try:
            fd = os.open(str(path), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def _shard_inline_extent(self) -> int:
        """Shard size along the inline axis, from the store's zarr.json."""
        import json

        try:
            meta = json.loads((self.dst / "zarr.json").read_text())
            grid = (
                meta.get("chunk_grid", {}).get("configuration", {}).get("chunk_shape")
            )
            if grid and int(grid[0]) > 0:
                return int(grid[0])
        except Exception:
            pass
        return 128  # the layout this job itself creates

    def _fsync_band_shards(self, i0: int, i1: int) -> None:
        """fsync the shard files AND directory entries this band touched (#1194).

        zarr has no per-write durability hook, so the store's ``c/<gi>/…``
        shard files covered by the band's inline span are fsynced directly
        BEFORE the band marker lands — a crash can then never persist a
        done-marker ahead of its data (which would register a store with
        missing bands as a complete DERIVED volume). fsyncing the files alone
        is not enough on Linux: the shard bytes can be durable while the
        NEWLY CREATED ``c/<gi>`` / ``c/<gi>/<gj>`` directory entries that name
        them are still only in memory, so a crash right after the marker
        could leave shards with no directory entries at all. Every directory
        level the band covered is therefore fsynced too, deepest-first
        (child entries before the parent that names them), deduped across
        the band's shard range.
        """
        shard_il = self._shard_inline_extent()
        if shard_il <= 0:
            return
        chunks_root = self.dst / "c"
        if not chunks_root.is_dir():
            return
        dirs: set[Path] = set()
        for gi in range(i0 // shard_il, (i1 - 1) // shard_il + 1):
            col = chunks_root / str(gi)
            if not col.is_dir():
                continue
            dirs.add(col)
            for f in col.rglob("*"):
                if f.is_file():
                    self._fsync_path(f)
                    dirs.add(f.parent)
        if dirs:
            dirs.add(chunks_root)
            dirs.add(self.dst)
        for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
            self._fsync_path(d)

    def _mark_band_done(self, i0: int) -> None:
        import os

        done = self._done_dir()
        done.mkdir(parents=True, exist_ok=True)
        marker = done / f"band_{i0:06d}"
        # #1194: marker body durable (open→write→fsync→close) BEFORE its
        # directory entry is durable, and both AFTER the band's shard data
        # was fsynced by the caller.
        fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, b"ok")
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_path(done)

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
        # Band identity = first inline (#1161); markers are only trusted
        # after _open_or_create_output validated the banding layout.
        finished = self.completed_bands()
        n_il, n_xl, n_t = self.reader.shape
        for i0, i1 in bounds:
            ctx.check_cancelled()
            if i0 in finished:
                self.stats.bands_done += 1
                ctx.report_progress(self.stats.bands_done, self.stats.bands_total)
                continue
            result = compute_block(
                self.reader, self.name, i0, i1, 0, n_xl, 0, n_t,
                use_gpu=self.use_gpu,
            )
            ctx.check_cancelled()
            arr[i0:i1, :, :] = result
            self._fsync_band_shards(i0, i1)
            self._mark_band_done(i0)
            self.stats.bands_done += 1
            ctx.report_progress(self.stats.bands_done, self.stats.bands_total)
        self.stats.elapsed_s = time.perf_counter() - t0
        return {
            "bands": self.stats.bands_total,
            "elapsed_s": self.stats.elapsed_s,
            "attribute": self.name,
        }
