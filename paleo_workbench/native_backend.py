"""NativeEngineBackend: Deep module for C++ native extension management and fallback dispatch.

Centralizes C++ pybind11 extension discovery (`seismic_3d_core`, `well_log_core`,
`map_edit_core`), pure-Python fallback implementations, GIL-release policies, and
geoviz visualization engine hook injections.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import math
from pathlib import Path
import re
from typing import Any, Callable, Generator
import warnings

import numpy as np

# ---------------------------------------------------------------------------
# Native Module Imports (Seam Discovery)
# ---------------------------------------------------------------------------
try:
    import seismic_3d_core
    _HAS_SEISMIC_3D_CPP = True
except ImportError:  # pragma: no cover
    seismic_3d_core = None  # type: ignore
    _HAS_SEISMIC_3D_CPP = False

try:
    import well_log_core
    _HAS_WELL_LOG_CPP = True
except ImportError:  # pragma: no cover
    well_log_core = None  # type: ignore
    _HAS_WELL_LOG_CPP = False

try:
    import map_edit_core
    _HAS_MAP_EDIT_CPP = True
except ImportError:  # pragma: no cover
    map_edit_core = None  # type: ignore
    _HAS_MAP_EDIT_CPP = False

try:
    import grid_render_core
    _HAS_GRID_RENDER_CPP = True
except ImportError:  # pragma: no cover
    grid_render_core = None  # type: ignore
    _HAS_GRID_RENDER_CPP = False

# Feature -> loaded module (may be None) for source-origin classification.
_NATIVE_MODULES = {
    "seismic_3d": seismic_3d_core,
    "well_log": well_log_core,
    "map_edit": map_edit_core,
    "grid_render": grid_render_core,
}


def _repo_root() -> Path:
    """Monorepo root (the directory that contains ``paleo_workbench/``)."""
    return Path(__file__).resolve().parent.parent


def _module_origin(mod: Any) -> str:
    """Classify where a native module was loaded from.

    Returns ``"missing"`` when the module could not be imported, ``"repo_root"``
    when the module resolves to a binary sitting directly at the repository root
    (a committed .so that shadows freshly built modules on ``sys.path[0]`` —
    see packaging #435), or ``"installed"`` for any other location (editable
    in-place build under ``native/<pkg>``, site-packages, …).
    """
    if mod is None:
        return "missing"
    module_path = Path(getattr(mod, "__file__", "") or "")
    if not module_path.is_absolute():
        return "installed"
    try:
        if module_path.resolve().parent == _repo_root():
            return "repo_root"
    except OSError:  # pragma: no cover — path resolution edge cases
        pass
    return "installed"


def native_status(feature: str) -> str:
    """Native engine status for ``feature``: ``"fresh"``, ``"stale"`` or ``"missing"``.

    Unlike :func:`has_cpp` (which only reflects import success), this
    distinguishes a genuinely absent module (``"missing"``) from one that
    resolved to a committed binary at the repository root (``"stale"``) — the
    shadowing failure mode from packaging #435 where the CI "freshly built"
    assert would otherwise pass vacuously.
    """
    origin = _module_origin(_NATIVE_MODULES.get(feature))
    if origin == "repo_root":
        return "stale"
    if origin == "missing":
        return "missing"
    return "fresh"


def native_version(feature: str) -> str | None:
    """``__version__`` of the loaded native module for ``feature``, if exposed.

    ``None`` when the module is missing or was built without build metadata
    (committed binaries predate ``__version__``; the geo-viz-engine-built
    ``map_edit_core`` exposes it once the engine side adds it — see #435).
    """
    mod = _NATIVE_MODULES.get(feature)
    if mod is None:
        return None
    return getattr(mod, "__version__", None)


def _py_render_grid_rgba(
    grid_z: np.ndarray,
    mask: "np.ndarray | None",
    lut: np.ndarray,
    lo: float,
    hi: float,
    gamma: float,
    opacity: int,
) -> np.ndarray:
    """Pure-Python parity fallback for ``grid_render_core.render_grid_rgba``.

    Byte-identical contract to the C++ hot path (see
    ``native/grid_render_core/src/grid_render_core.cpp``): non-finite cells and masked
    cells become fully-transparent black; values clamp to the ramp endpoints; the LUT
    index is selected by truncation toward zero; alpha is ``lut_alpha * opacity / 255``.
    """
    gz = np.ascontiguousarray(grid_z, dtype=np.float32)
    if gz.ndim != 2:
        # Parity with the C++ binding's argument validation.
        raise ValueError("grid_z must be a 2-D (height, width) float32 array")
    height, width = gz.shape
    lut_buf = np.ascontiguousarray(lut, dtype=np.uint8)
    if lut_buf.ndim != 2 or lut_buf.shape[0] < 1 or lut_buf.shape[1] != 4:
        # Parity with the C++ binding: malformed LUTs raise instead of
        # silently returning an all-zero raster (issue #446).
        raise ValueError(
            "lut must be a (lut_size, 4) RGBA uint8 array with at least one entry"
        )
    out = np.zeros((height, width, 4), dtype=np.uint8)
    if not (gamma > 0.0):
        gamma = 1.0
    have_range = (hi - lo) > 0.0
    inv_denom = (1.0 / (hi - lo)) if have_range else 0.0
    max_idx = lut_buf.shape[0] - 1

    finite = np.isfinite(gz)
    valid = finite
    if mask is not None:
        mask_buf = np.ascontiguousarray(mask, dtype=np.uint8)
        if mask_buf.ndim != 2 or mask_buf.shape != gz.shape:
            # Parity with the C++ binding: a mis-shaped mask raises instead of
            # silently broadcasting (issue #446).
            raise ValueError("mask must match grid_z shape")
        valid = valid & (mask_buf != 0)

    with np.errstate(invalid="ignore", over="ignore"):
        if have_range:
            t = (gz - np.float32(lo)) * np.float32(inv_denom)
        else:
            t = np.zeros_like(gz, dtype=np.float32)
        t = np.clip(t, np.float32(0.0), np.float32(1.0))
        if gamma != 1.0:
            t = np.power(t, np.float32(gamma))
        idx = (t * np.float32(max_idx)).astype(np.int32)  # truncation toward zero
    idx = np.clip(idx, 0, max_idx)
    colors = lut_buf[idx]  # (H, W, 4)
    out[..., 0:3] = colors[..., 0:3]
    out[..., 3] = ((colors[..., 3].astype(np.int32) * int(opacity)) // 255).astype(np.uint8)
    out[~valid] = 0
    return out


# ---------------------------------------------------------------------------
# Pure-Python Fallback Implementations
# ---------------------------------------------------------------------------
def _py_fast_slice_extract(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    # Parity with the pybind11 `int` caster: values outside the C++ int range
    # raise TypeError on the native path before any other validation.
    if not (-(2**31) <= int(axis) < 2**31) or not (-(2**31) <= int(index) < 2**31):
        raise TypeError(
            f"axis and index must fit in a C++ int (got axis={axis}, index={index})"
        )
    # float32 dtype contract: the C++ side accepts any numeric dtype via
    # forcecast and downcasts to float32 (issue #446), so the fallback does
    # the same instead of silently preserving float64.
    vol = np.asarray(volume, dtype=np.float32)
    if vol.ndim != 3:
        raise RuntimeError("Input volume must be 3D")
    axis_idx = int(axis) % vol.ndim
    dim = vol.shape[axis_idx]
    if dim == 0:
        raise IndexError(f"cannot slice axis {axis_idx} of an empty volume")
    if int(index) < 0 or int(index) >= dim:
        raise IndexError(f"slice index {index} out of range for axis {axis_idx} (size {dim})")
    indexer = [slice(None)] * vol.ndim
    indexer[axis_idx] = int(index)
    return vol[tuple(indexer)].copy()


def _py_fast_slice_to_indexed8(
    volume: np.ndarray, axis: int, index: int, value_range: tuple[float, float] | None = None
) -> tuple[np.ndarray, float, float]:
    """Pure-Python parity fallback for ``seismic_3d_core.fast_slice_to_indexed8``.

    Mirrors the C++ hot path (``native/seismic_3d_core/src/seismic_3d_core.cpp``):
    non-finite samples are excluded from the min/max stretch; every element
    contributes to the min/max (min/max-preserving — the old stride-4 sample
    could skip both extrema on large time slices); an optional ``value_range``
    ``(vmin, vmax)`` overrides the per-slice stretch so all slices of a volume
    share one color mapping; non-finite pixels render as 0; and a degenerate
    (constant / all-invalid) range fills 0 and reports ``(0.0, 0.0)``.
    """
    slice_data = _py_fast_slice_extract(volume, axis, index)
    if value_range is not None:
        v_min = float(value_range[0])
        v_max = float(value_range[1])
    else:
        flat = slice_data.reshape(-1)
        finite = flat[np.isfinite(flat)]
        if finite.size > 0:
            v_min = float(finite.min())
            v_max = float(finite.max())
        else:
            v_min = v_max = 0.0
    if (
        v_min >= v_max
        or not math.isfinite(v_min)
        or not math.isfinite(v_max)
    ):
        return np.zeros(slice_data.shape, dtype=np.uint8), 0.0, 0.0
    inv_range = np.float32(255.0) / np.float32(v_max - v_min)
    with np.errstate(invalid="ignore", over="ignore"):
        norm = (slice_data.astype(np.float32) - np.float32(v_min)) * inv_range
    norm = np.clip(norm, np.float32(0.0), np.float32(255.0))
    out = norm.astype(np.uint8)  # truncation toward zero, like the C++ cast
    out[~np.isfinite(slice_data)] = 0
    return out, v_min, v_max


def _py_fast_resample_volume_3d(
    volume: np.ndarray, target_shape: tuple[int, int, int]
) -> np.ndarray:
    vol = np.asarray(volume, dtype=np.float32)
    s0, s1, s2 = vol.shape
    if s0 == 0 or s1 == 0 or s2 == 0:
        raise ValueError("cannot resample a volume with a zero-sized dimension")
    if len(target_shape) != 3:
        raise ValueError("target_shape must have exactly 3 elements")
    t0, t1, t2 = target_shape
    if t0 <= 0 or t1 <= 0 or t2 <= 0:
        raise ValueError("target_shape elements must all be positive")
    # Mirror the C++ peak-preserving stride-block decimation (issue #419)
    # exactly: each target cell aggregates its source stride block and keeps
    # the sample with the largest |value| (sign preserved, first-wins ties);
    # a block containing any NaN yields NaN. The block bounds use the same
    # float32 trunc(i * s/t) arithmetic as the C++ side (audit A1/I4), with
    # the last target's block forced to the source edge.
    def _blocks(size: int, target: int) -> tuple[np.ndarray, np.ndarray]:
        step = np.float32(size) / np.float32(max(1, target))
        lo = (np.arange(target, dtype=np.float32) * step).astype(np.int64)
        nxt = np.empty(target, dtype=np.int64)
        nxt[:-1] = (np.arange(1, target, dtype=np.float32) * step).astype(np.int64) - 1
        nxt[-1] = size - 1
        hi = np.maximum(lo, nxt)  # upsampling: single-sample blocks
        return lo, hi

    lo0, hi0 = _blocks(s0, t0)
    lo1, hi1 = _blocks(s1, t1)
    lo2, hi2 = _blocks(s2, t2)

    out = np.empty((t0, t1, t2), dtype=np.float32)
    for i in range(t0):
        for j in range(t1):
            for k in range(t2):
                sub = vol[lo0[i] : hi0[i] + 1, lo1[j] : hi1[j] + 1, lo2[k] : hi2[k] + 1]
                if np.isnan(sub).any():
                    out[i, j, k] = np.nan
                    continue
                flat = sub.ravel()  # C order: same scan order as the C++ loops
                out[i, j, k] = flat[int(np.argmax(np.abs(flat)))]
    return out


def _py_compute_coherence_3d(
    volume: np.ndarray,
    inline_window: int = 3,
    crossline_window: int = 3,
    sample_window: int = 3,
) -> np.ndarray:
    for _name, _w in (
        ("inline_window", inline_window),
        ("crossline_window", crossline_window),
        ("sample_window", sample_window),
    ):
        if _w <= 0:
            raise ValueError(f"{_name} must be a positive odd integer (got {_w})")
        if _w % 2 == 0:
            raise ValueError(f"{_name} must be odd (got {_w}); even windows are not supported")

    vol = np.asarray(volume, dtype=np.float32)
    ni, nx, nt = vol.shape
    coh = np.ones_like(vol, dtype=np.float32)

    hi = inline_window // 2
    hx = crossline_window // 2
    ht = sample_window // 2
    n_spatial = float((2 * hi + 1) * (2 * hx + 1))

    for i in range(hi, ni - hi):
        for j in range(hx, nx - hx):
            sub = vol[i - hi : i + hi + 1, j - hx : j + hx + 1, :].astype(np.float64)
            trace_sum = np.sum(sub, axis=(0, 1))
            trace_sq_sum = np.sum(sub**2, axis=(0, 1))
            mean_sq = (trace_sum / n_spatial) ** 2
            sum_sq = trace_sq_sum

            for k in range(nt):
                k0 = max(0, k - ht)
                k1 = min(nt - 1, k + ht)
                vert_len = float(k1 - k0 + 1)
                run_num = np.sum(mean_sq[k0 : k1 + 1])
                run_den = np.sum(sum_sq[k0 : k1 + 1]) / vert_len + 1e-12
                value = run_num / run_den
                if isinstance(value, float) and math.isnan(value):
                    # C++ parity: NaN input propagates into the sums, and the
                    # std::min/std::max clamp chain maps NaN to 0.0 (never a
                    # NaN sample in the output volume).
                    coh[i, j, k] = 0.0
                else:
                    coh[i, j, k] = float(np.clip(value, 0.0, 1.0))

    return coh


def _py_marching_cubes_3d(
    volume: np.ndarray, isovalue: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    try:
        from skimage.measure import marching_cubes
    except ImportError:  # pragma: no cover
        raise RuntimeError(
            "marching_cubes_3d requires the seismic_3d_core C++ extension "
            "or scikit-image (pip install scikit-image)."
        )
    vol = np.asarray(volume, dtype=np.float32)
    level = float(isovalue)
    if vol.size == 0 or not (np.nanmin(vol) <= level <= np.nanmax(vol)):
        # Match the C++ contract: an out-of-range isovalue yields an EMPTY
        # mesh, not a ValueError (K-F2).
        return (
            np.zeros((0, 3), dtype=np.float32),
            np.zeros((0, 3), dtype=np.int32),
        )
    verts, faces, _normals, _values = marching_cubes(vol, level=level)
    return verts.astype(np.float32), faces.astype(np.int32)


def _py_minmax_downsample(
    depth: np.ndarray,
    values: np.ndarray,
    target_pixels: int = 1000,
) -> tuple[np.ndarray, np.ndarray]:
    d = np.asarray(depth, dtype=np.float32)
    v = np.asarray(values, dtype=np.float32)

    if d.ndim != 1 or v.ndim != 1:
        raise ValueError("depth and values must be 1-D arrays")
    if d.shape[0] != v.shape[0]:
        raise ValueError(
            f"depth and values must have the same length (got {d.shape[0]} and {v.shape[0]})"
        )
    if target_pixels <= 0:
        raise ValueError(f"target_pixels must be positive (got {target_pixels})")
    if target_pixels > (2**31 - 1) // 2:
        # Parity with well_log_core's C++ guard: a target_pixels this large
        # would overflow the int arithmetic in the native implementation.
        raise ValueError("target_pixels too large (would overflow)")

    n_pts = len(d)
    if n_pts <= target_pixels * 2:
        return d.copy(), v.copy()

    bin_size = max(1, math.ceil(n_pts / float(target_pixels)))
    out_d = []
    out_v = []

    for i in range(0, n_pts, bin_size):
        chunk_d = d[i : i + bin_size]
        chunk_v = v[i : i + bin_size]
        if len(chunk_v) == 0:
            continue

        finite_mask = np.isfinite(chunk_v)
        if not finite_mask.any():
            out_d.append(chunk_d[0])
            out_v.append(np.float32("nan"))
            continue
        fv = chunk_v[finite_mask]
        fd = chunk_d[finite_mask]
        min_idx = int(np.argmin(fv))
        max_idx = int(np.argmax(fv))

        if min_idx <= max_idx:
            out_d.append(fd[min_idx])
            out_v.append(fv[min_idx])
            if min_idx != max_idx:
                out_d.append(fd[max_idx])
                out_v.append(fv[max_idx])
        else:
            out_d.append(fd[max_idx])
            out_v.append(fv[max_idx])
            out_d.append(fd[min_idx])
            out_v.append(fv[min_idx])

    return np.array(out_d, dtype=np.float32), np.array(out_v, dtype=np.float32)


def _wl_token_value(tok: str, null_value: float) -> float:
    """Parse one whitespace-delimited LAS token with C++ from_chars semantics.

    ``float()`` handles the well-formed cases (including ``inf``/``nan``); when
    it rejects the token, the numeric prefix is parsed instead — the C++ side's
    std::from_chars stops at the first non-numeric character (``0x1p3`` -> 0.0,
    ``1.0<NBSP>2.5`` -> 1.0, ``123abc`` -> 123.0). Tokens with no numeric
    prefix are NaN. Inf is mapped to NaN like the C++ tokenizer.
    """
    if not tok:
        return np.nan
    if tok[0].isspace():
        # float() would silently skip leading Unicode whitespace (e.g. NBSP)
        # that the C++ from_chars treats as token content; parse the prefix.
        val = None
    else:
        try:
            val = float(tok)
        except ValueError:
            val = None
    if val is None:
        m = _NUM_PREFIX_RE.match(tok)
        if m is None:
            return np.nan
        val = float(m.group(0))
    if abs(val) < 1e-300:
        # std::from_chars reports result_out_of_range for values that round to
        # zero (|exact| < half of the smallest double subnormal, 2**-1075) and
        # the C++ side maps that to NaN, while Python float() silently
        # underflows to 0.0. Compare the exact decimal token so genuine
        # subnormals survive (``5e-324`` -> 5e-324) but true underflow is NaN
        # (``1e-324``, ``1e-999``).
        try:
            if Decimal(tok) and abs(Decimal(tok)) < _DOUBLE_MIN_SUBNORMAL:
                return np.nan
        except Exception:  # noqa: BLE001 — non-decimal token: nothing to do
            pass
    if math.isnan(val) or math.isinf(val) or val == null_value:
        return np.nan
    return val


# std::from_chars (general format) numeric-prefix pattern: optional sign,
# decimal mantissa with optional fraction, optional exponent. No hex floats.
_NUM_PREFIX_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")

# Half the smallest positive double subnormal (2**-1075): the exact
# underflow boundary where std::from_chars switches from returning the rounded
# subnormal to reporting result_out_of_range.
_DOUBLE_MIN_SUBNORMAL = Decimal(2) ** -1075


def _py_fast_las_parse_data(
    content: str, null_value: float = -999.0
) -> tuple[tuple[str, ...], np.ndarray]:
    """Pure-Python parity fallback for ``well_log_core.fast_las_parse_data``.

    Must mirror the C++ tokenizer exactly (issue #421): lines split on ``\\n``
    only (NOT on VT/FF like ``str.splitlines``), tokens split on the ASCII
    whitespace set used by the C++ side (``\\x0b``/``\\x0c`` are separators,
    U+00A0 NBSP is a regular token character), tokens parse with from_chars
    numeric-prefix semantics (``0x1p3`` -> ``0.0``, ``1.0<NBSP>2.5`` -> ``1.0``),
    no inline ``~A`` mnemonics yields an EMPTY header tuple (no fabricated
    ``COL_n``), and the long-row truncation warning fires only when headers
    were declared.
    """
    if isinstance(content, bytes):
        # pybind11's std::string caster accepts bytes verbatim; mirror it.
        content = content.decode("utf-8", errors="replace")
    elif not isinstance(content, str):
        raise TypeError("content must be a str or bytes LAS payload")

    in_data = False
    in_curve_info = False
    curve_mnemonics: list[str] = []
    headers: list[str] = []
    rows: list[list[float]] = []

    for line in content.split("\n"):
        # C++ skips leading wl_is_space chars only — ASCII whitespace, not the
        # full Unicode set (an NBSP-leading line must stay a NaN token).
        stripped = line.lstrip(" \t\r\v\f")
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("~"):
            section = stripped[1:2].lower()
            if section == "c":
                # ~CURVE block: the authoritative curve list (CWLS ~C section),
                # mirroring the C++ parser (workbench #433).
                in_curve_info = True
                in_data = False
                continue
            if section == "a":
                # Start of the data section. Inline tokens are only treated as
                # column headers when separated from `~A` by whitespace
                # (`~A DEPT GR DEN`); a directly-attached suffix is part of the
                # section name (`~Ascii` must not yield "scii"). Per CWLS the
                # trailing words of `~A` (e.g. "~A LOG DATA") are a title, not
                # headers, so the ~CURVE mnemonics win whenever the file
                # declares a ~CURVE block.
                in_data = True
                in_curve_info = False
                rest = stripped[2:]
                if rest and rest[0] in " \t":
                    inline_headers = [
                        t for t in re.split(r"[ \t\r\n\v\f]+", rest) if t
                    ]
                else:
                    inline_headers = []
                headers = list(curve_mnemonics) if curve_mnemonics else inline_headers
                continue
            in_curve_info = False
            continue
        if in_curve_info:
            # "MNEM.UNIT : DESCRIPTION" -> mnemonic up to the first dot. Token
            # splitting stays on the ASCII whitespace set the C++ istringstream
            # uses; str.split() would additionally split on NBSP.
            first = next(
                (t for t in re.split(r"[ \t\r\n\v\f]+", stripped) if t), None
            )
            if first is not None:
                curve_mnemonics.append(first.split(".", 1)[0])
            continue
        if in_data:
            row = []
            for tok in re.split(r"[ \t\r\n\v\f]+", stripped):
                if not tok:
                    continue
                row.append(_wl_token_value(tok, null_value))
            if row:
                rows.append(row)

    if not headers and rows:
        # Parity with C++: no inline mnemonics -> empty headers; the column
        # count is taken from the first data row instead of fabricated names.
        num_cols = len(rows[0])
    else:
        num_cols = len(headers)

    truncated = 0
    if num_cols and rows:
        norm_rows = []
        for row in rows:
            if len(row) > num_cols:
                truncated += 1
            r = row[:num_cols]
            if len(r) < num_cols:
                r = r + [np.nan] * (num_cols - len(r))
            norm_rows.append(r)
        rows = norm_rows
        # C++ emits the truncation warning only when headers were declared
        # (with empty headers, extra columns are dropped silently).
        if truncated and headers:
            warnings.warn(
                f"LAS data has {truncated} row(s) with more columns than the "
                f"{num_cols} declared header(s); extra columns were truncated",
                UserWarning,
                stacklevel=1,
            )

    arr = (
        np.array(rows, dtype=np.float64)
        if rows
        else np.zeros((0, num_cols), dtype=np.float64)
    )
    return tuple(headers), arr


def _py_hit_test(features: list, x: float, y: float, tol: float) -> str | None:
    from geoviz_plots.map_edit.api import _hit_test_python
    return _hit_test_python(features, x, y, tol)


def _py_snap_point(
    candidates: list[tuple[float, float]], x: float, y: float, tol: float
) -> tuple[float, float]:
    from geoviz_plots.map_edit.api import _snap_point_python
    return _snap_point_python(candidates, x, y, tol)


def _py_validate_ring(ring: list[list[float]]) -> list[dict[str, Any]]:
    from geoviz_plots.map_edit.api import _validate_ring_python
    return _validate_ring_python(ring)


# ---------------------------------------------------------------------------
# Deep NativeEngineBackend Class
# ---------------------------------------------------------------------------
class NativeEngineBackend:
    """Centralized manager for C++ pybind11 native extensions and fallbacks."""

    _FEATURE_MODULE_MAP = {
        "seismic_3d": ("_HAS_SEISMIC_3D_CPP", seismic_3d_core),
        "well_log": ("_HAS_WELL_LOG_CPP", well_log_core),
        "map_edit": ("_HAS_MAP_EDIT_CPP", map_edit_core),
        "grid_render": ("_HAS_GRID_RENDER_CPP", grid_render_core),
    }

    _FALLBACK_TABLE: dict[str, Callable] = {
        "fast_slice_extract": _py_fast_slice_extract,
        "fast_slice_to_indexed8": _py_fast_slice_to_indexed8,
        "fast_resample_volume_3d": _py_fast_resample_volume_3d,
        "compute_coherence_3d": _py_compute_coherence_3d,
        "marching_cubes_3d": _py_marching_cubes_3d,
        "minmax_downsample": _py_minmax_downsample,
        "fast_las_parse_data": _py_fast_las_parse_data,
        "hit_test": _py_hit_test,
        "snap_point": _py_snap_point,
        "validate_ring": _py_validate_ring,
        "render_grid_rgba": _py_render_grid_rgba,
    }

    _FUNCTION_MODULE_MAP = {
        "fast_slice_extract": ("seismic_3d", seismic_3d_core),
        "fast_slice_to_indexed8": ("seismic_3d", seismic_3d_core),
        "fast_resample_volume_3d": ("seismic_3d", seismic_3d_core),
        "compute_coherence_3d": ("seismic_3d", seismic_3d_core),
        "marching_cubes_3d": ("seismic_3d", seismic_3d_core),
        "minmax_downsample": ("well_log", well_log_core),
        "fast_las_parse_data": ("well_log", well_log_core),
        "hit_test": ("map_edit", map_edit_core),
        "snap_point": ("map_edit", map_edit_core),
        "validate_ring": ("map_edit", map_edit_core),
        "render_grid_rgba": ("grid_render", grid_render_core),
    }

    def __init__(self) -> None:
        self._force_python = False
        self._installed_hooks = False

    def has_cpp(self, feature: str) -> bool:
        """Check if native C++ extension for a feature is installed.

        Note: this reflects import success only. To distinguish a *stale*
        committed repo-root binary (which shadows fresh builds on
        ``sys.path[0]`` — packaging #435) from a genuinely missing module, use
        :func:`native_status` instead.
        """
        feature_map = {
            "seismic_3d": _HAS_SEISMIC_3D_CPP,
            "well_log": _HAS_WELL_LOG_CPP,
            "map_edit": _HAS_MAP_EDIT_CPP,
            "grid_render": _HAS_GRID_RENDER_CPP,
        }
        return feature_map.get(feature, False)

    def is_accelerated(self, feature: str) -> bool:
        """Check if C++ acceleration for feature is currently active."""
        if self._force_python:
            return False
        return self.has_cpp(feature)

    @contextmanager
    def disabled_acceleration(self) -> Generator[None, None, None]:
        """Context manager seam to temporarily force Pure-Python fallbacks."""
        prev = self._force_python
        self._force_python = True
        try:
            yield
        finally:
            self._force_python = prev

    def dispatch(self, func_name: str, *args: Any, **kwargs: Any) -> Any:
        """Dispatch algorithm execution to C++ native extension or Python fallback."""
        if func_name not in self._FUNCTION_MODULE_MAP:
            raise KeyError(f"Unknown native backend function: {func_name}")

        feature, cpp_mod = self._FUNCTION_MODULE_MAP[func_name]
        if self.is_accelerated(feature) and cpp_mod is not None and hasattr(cpp_mod, func_name):
            cpp_fn = getattr(cpp_mod, func_name)
            return cpp_fn(*args, **kwargs)

        fallback_fn = self._FALLBACK_TABLE[func_name]
        return fallback_fn(*args, **kwargs)

    def install_all_hooks(self) -> None:
        """Inject C++ acceleration hooks into the geoviz engine."""
        try:
            from geoviz import (
                set_downsample_provider,
                set_isosurface_extractor,
                set_las_parser_provider,
            )
        except ImportError:  # pragma: no cover
            return

        from paleo_workbench.viz.seismic_3d_api import marching_cubes_3d

        set_downsample_provider(_cpp_minmax_provider)
        set_isosurface_extractor(marching_cubes_3d)
        set_las_parser_provider(_cpp_las_parser_provider)
        self._installed_hooks = True


def _cpp_minmax_provider(
    depths: np.ndarray, values: np.ndarray, pixel_height: int
) -> tuple[np.ndarray, np.ndarray]:
    if len(depths) <= pixel_height * 2:
        return depths, values
    d = np.asarray(depths, dtype=np.float32)
    v = np.asarray(values, dtype=np.float32)
    out_d, out_v = native_backend.dispatch("minmax_downsample", d, v, int(pixel_height))
    return np.asarray(out_d, dtype=np.float64), np.asarray(out_v, dtype=np.float64)


def _cpp_las_parser_provider(
    content: str, null_value: float
) -> tuple[tuple[str, ...], np.ndarray]:
    return native_backend.dispatch("fast_las_parse_data", content, float(null_value))


# ---------------------------------------------------------------------------
# Global Singleton & Helper Shortcuts
# ---------------------------------------------------------------------------
native_backend = NativeEngineBackend()


def is_accelerated(feature: str) -> bool:
    return native_backend.is_accelerated(feature)


def disabled_acceleration():
    return native_backend.disabled_acceleration()


def install_all_hooks() -> None:
    native_backend.install_all_hooks()
