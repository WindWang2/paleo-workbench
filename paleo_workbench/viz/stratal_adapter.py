"""Workbench glue: build stratal (proportional) slice grids from scene assets.

This is the thin adapter between the geo-viz-engine stratal core
(:mod:`geoviz_seismic.stratal`, reached via the ``geoviz`` facade) and the
well-seismic joint scene. It owns **no algorithm** — it reads the loaded survey
+ volume, parses two horizon ``.dat`` files into aligned sample-index grids,
and hands them to :func:`geoviz.build_proportional_surfaces` /
``Renderer3D.set_stratal_slices``.

Boundary rule (see ``docs/agents/geo-viz-boundary.md``): engine core stays in
``geo-viz-engine``; this module is page/host workflow glue only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from scipy.ndimage import map_coordinates

from geoviz import (
    HorizonAxes,
    HorizonParser,
    build_proportional_surfaces,
    stratal_slice_volume,
    validate_horizon_pair,
)

if TYPE_CHECKING:
    from geoviz_well_seismic_3d import WellSeismicScene

logger = logging.getLogger(__name__)

__all__ = [
    "build_stratal_grids",
    "build_stratal_surfaces",
    "make_demo_stratal_grids",
    "make_synthetic_demo_volume",
]


def build_stratal_grids(
    scene: "WellSeismicScene",
    volume: np.ndarray,
    top_path: str | Path,
    bottom_path: str | Path,
    *,
    fill: str = "nearest",
) -> tuple[np.ndarray, np.ndarray] | None:
    """Parse two horizon ``.dat`` files into preview-aligned sample-index grids.

    Args:
        scene: The joint scene — its ``survey`` and ``registration`` describe how
            the full-grid survey maps onto the (possibly downsampled) preview
            volume that the renderer actually holds.
        volume: The renderer's loaded volume, shape ``(nI_prev, nX_prev, nS_prev)``.
        top_path, bottom_path: ``.dat`` horizon files (inline, crossline, twt_ms).
        fill: Gap-fill strategy for sparse picks — ``"nearest"`` (fast, default)
            or ``"rbf"`` (smoother, slower).

    Returns:
        ``(top_sidx, bot_sidx)`` — two ``(nI_prev, nX_prev)`` float grids in
        **preview sample-index space**, NaN where a horizon is absent. Returns
        ``None`` if the survey/registration is unavailable or the volume shape
        is degenerate.
    """
    survey = getattr(scene, "survey", None)
    reg = getattr(scene, "registration", None)
    if survey is None or reg is None or volume.ndim != 3:
        return None
    n_i_prev, n_x_prev, n_s_prev = volume.shape
    if n_i_prev < 2 or n_x_prev < 2 or n_s_prev < 2:
        return None

    # Full-survey IL/XL *numbers* so HorizonParser can match the .dat rows.
    ilines_full = survey.iline_start + np.arange(survey.n_inlines) * survey.iline_step
    xlines_full = survey.xline_start + np.arange(survey.n_crosslines) * survey.xline_step
    axes: HorizonAxes = {
        "ilines": ilines_full,
        "xlines": xlines_full,
        "nI": survey.n_inlines,
        "nX": survey.n_crosslines,
    }

    def _ms_grid(path: str | Path) -> np.ndarray:
        parser = HorizonParser(str(path), unit="ms")
        grid = parser.parse(axes)
        if fill == "rbf":
            return parser.fill_rbf(grid)
        return parser.fill_nearest(grid)

    top_ms = _ms_grid(top_path)
    bot_ms = _ms_grid(bottom_path)

    # Resample the full (nI_full, nX_full) ms grid onto the preview shape using
    # bilinear interpolation in IL/XL index space, then map ms -> preview sample.
    ii_prev, xx_prev = np.meshgrid(
        np.arange(n_i_prev, dtype=float),
        np.arange(n_x_prev, dtype=float),
        indexing="ij",
    )
    # preview (i,x) fraction -> full-grid fractional index
    fi = ii_prev / max(n_i_prev - 1, 1) * max(survey.n_inlines - 1, 1)
    fx = xx_prev / max(n_x_prev - 1, 1) * max(survey.n_crosslines - 1, 1)

    def _to_preview_sample_index(grid_ms: np.ndarray) -> np.ndarray:
        coords = np.stack([fi, fx])
        ms = map_coordinates(
            grid_ms.astype(float), coords, order=1, mode="nearest", cval=np.nan
        )
        return ms_to_preview_sample_index(
            ms,
            dt_ms=survey.dt_ms,
            t0_ms=survey.t0_ms,
            n_samples=survey.n_samples,
            n_sample_preview=reg.n_sample,
        )

    return _to_preview_sample_index(top_ms), _to_preview_sample_index(bot_ms)


def ms_to_preview_sample_index(
    ms: np.ndarray,
    *,
    dt_ms: float,
    t0_ms: float,
    n_samples: int,
    n_sample_preview: int,
) -> np.ndarray:
    """Vectorized ms -> preview-sample-index transform.

    The registration's ``time_ms_to_sample_idx`` rescaled to the preview
    sampling: ``(twt - t0)/dt / (n_samples-1) * (n_sample_preview-1)``.
    Endpooints: ``t0`` maps to 0; ``t0 + (n_samples-1)*dt`` maps to
    ``n_sample_preview-1``. Non-positive ``dt_ms`` degrades to 1.0 (matching
    the legacy per-pixel loop).
    """
    dt = dt_ms if dt_ms and dt_ms > 0 else 1.0
    full_t = (np.asarray(ms, dtype=float) - t0_ms) / dt
    full_nt = max(n_samples - 1, 1)
    s_idx = full_t / full_nt * max(n_sample_preview - 1, 0)
    return np.asarray(s_idx, dtype=float)


def build_stratal_surfaces(
    top_sidx: np.ndarray,
    bot_sidx: np.ndarray,
    volume_shape: tuple[int, int, int],
    *,
    fractions: tuple[float, ...] = (0.25, 0.50, 0.75),
) -> tuple[list[np.ndarray], list[np.ndarray]] | None:
    """Build proportional surfaces + validate the horizon pair.

    Returns ``(surfaces, amp_maps)`` or ``None`` if the pair is unusable
    everywhere. Inverted cells (``top > bot``) and NaN picks are masked.
    """
    good = validate_horizon_pair(top_sidx, bot_sidx, volume_shape=volume_shape)
    if not good.any():
        return None
    top_c = top_sidx.copy()
    bot_c = bot_sidx.copy()
    top_c[~good] = np.nan
    bot_c[~good] = np.nan
    surfaces = list(
        np.asarray(
            build_proportional_surfaces(top_c, bot_c, list(fractions))
        )
    )
    return surfaces, [top_c, bot_c]


def make_synthetic_demo_volume(
    shape: tuple[int, int, int] = (16, 20, 32),
    n_reflectors: int = 3,
    seed: int = 7,
) -> np.ndarray:
    """A deterministic synthetic seismic cube for the stratal demo fallback.

    Produces gently-dipping reflectors so proportional slices between two
    synthetic horizons reveal structure that flat time slices would miss. Used
    only when no real SEGY volume is loaded (e.g. offscreen / CI), so the stratal
    feature has a visible result regardless of environment.
    """
    rng = np.random.default_rng(seed)
    ni, nx, nt = shape
    vol = np.zeros(shape, np.float32)
    # Embed a few dipping planar reflectors across the cube.
    for r in range(n_reflectors):
        t0 = (r + 1) * nt / (n_reflectors + 1)
        ii, xx = np.meshgrid(np.arange(ni), np.arange(nx), indexing="ij")
        dip = (ii - ni / 2.0) * 0.20 + (xx - nx / 2.0) * 0.15
        center = t0 + dip
        amp = np.exp(-((np.arange(nt)[None, None, :] - center[:, :, None]) ** 2) / 2.0)
        sign = 1.0 if r % 2 == 0 else -1.0
        vol += (sign * amp).astype(np.float32)
    vol += (rng.standard_normal(shape) * 0.05).astype(np.float32)
    return vol


def make_demo_stratal_grids(
    shape: tuple[int, int, int] = (16, 20, 32),
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Synthetic top/bottom horizon grids (sample-index) matching the demo volume.

    The horizons bracket the middle reflector so proportional slices reveal it.
    Returns ``(volume, top_sidx, bot_sidx)``.
    """
    vol = make_synthetic_demo_volume(shape)
    ni, nx, nt = shape
    ii, xx = np.meshgrid(np.arange(ni), np.arange(nx), indexing="ij")
    dip = (ii - ni / 2.0) * 0.20 + (xx - nx / 2.0) * 0.15
    # Top horizon above the middle reflector, bottom below it.
    mid = nt / 2.0 + dip
    top = np.clip(mid - 4.0, 0.5, nt - 1.5)
    bot = np.clip(mid + 4.0, 0.5, nt - 1.5)
    return vol, top.astype(float), bot.astype(float)
