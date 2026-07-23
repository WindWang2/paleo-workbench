"""NativeEngineBackend: Deep module for C++ native extension management and fallback dispatch.

Centralizes C++ pybind11 extension discovery (`seismic_3d_core`, `well_log_core`,
`map_edit_core`), pure-Python fallback implementations, GIL-release policies, and
geoviz visualization engine hook injections.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
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


# ---------------------------------------------------------------------------
# Pure-Python Fallback Implementations
# ---------------------------------------------------------------------------
def _py_fast_slice_extract(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    vol = np.asarray(volume)
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
    volume: np.ndarray, axis: int, index: int
) -> tuple[np.ndarray, float, float]:
    slice_data = _py_fast_slice_extract(volume, axis, index)
    slice_clean = np.nan_to_num(slice_data, nan=0.0, posinf=0.0, neginf=0.0)
    v_min = float(slice_clean.min()) if slice_clean.size > 0 else 0.0
    v_max = float(slice_clean.max()) if slice_clean.size > 0 else 0.0
    if v_max > v_min:
        norm = ((slice_clean - v_min) / (v_max - v_min) * 255.0).astype(np.uint8)
    else:
        norm = np.zeros(slice_clean.shape, dtype=np.uint8)
    return norm, v_min, v_max


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
    idx0 = np.linspace(0, s0 - 1, t0, dtype=np.int32)
    idx1 = np.linspace(0, s1 - 1, t1, dtype=np.int32)
    idx2 = np.linspace(0, s2 - 1, t2, dtype=np.int32)
    return vol[np.ix_(idx0, idx1, idx2)]


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
                coh[i, j, k] = float(np.clip(run_num / run_den, 0.0, 1.0))

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
    verts, faces, _normals, _values = marching_cubes(vol, level=float(isovalue))
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


def _py_fast_las_parse_data(
    content: str, null_value: float = -999.0
) -> tuple[tuple[str, ...], np.ndarray]:
    lines = content.splitlines()
    in_data = False
    headers: list[str] = []
    rows: list[list[float]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("~A") or stripped.startswith("~a"):
            in_data = True
            rest = stripped[2:]
            if rest and rest[0] in " \t":
                headers = rest.split()
            else:
                headers = []
            continue
        if in_data:
            tokens = stripped.split()
            row = []
            for tok in tokens:
                try:
                    val = float(tok)
                    if math.isnan(val) or math.isinf(val) or val == null_value:
                        row.append(np.nan)
                    else:
                        row.append(val)
                except ValueError:
                    row.append(np.nan)
            if row:
                rows.append(row)

    if not headers and rows:
        headers = [f"COL_{i}" for i in range(len(rows[0]))]

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
        if truncated:
            warnings.warn(
                f"LAS data has {truncated} row(s) with more columns than the "
                f"{num_cols} declared header(s); extra columns were truncated",
                UserWarning,
                stacklevel=2,
            )

    arr = (
        np.array(rows, dtype=np.float64)
        if rows
        else np.zeros((0, len(headers)), dtype=np.float64)
    )
    return tuple(headers), arr


def _py_hit_test(features: list, x: float, y: float, tol: float) -> str | None:
    from paleo_workbench.mapping.map_edit_api import _hit_test_python
    return _hit_test_python(features, x, y, tol)


def _py_snap_point(
    candidates: list[tuple[float, float]], x: float, y: float, tol: float
) -> tuple[float, float]:
    from paleo_workbench.mapping.map_edit_api import _snap_point_python
    return _snap_point_python(candidates, x, y, tol)


def _py_validate_ring(ring: list[list[float]]) -> list[dict[str, Any]]:
    from paleo_workbench.mapping.map_edit_api import _validate_ring_python
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
    }

    def __init__(self) -> None:
        self._force_python = False
        self._installed_hooks = False

    def has_cpp(self, feature: str) -> bool:
        """Check if native C++ extension for a feature is installed."""
        feature_map = {
            "seismic_3d": _HAS_SEISMIC_3D_CPP,
            "well_log": _HAS_WELL_LOG_CPP,
            "map_edit": _HAS_MAP_EDIT_CPP,
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
