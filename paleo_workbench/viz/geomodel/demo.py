"""Explicit synthetic/demo data providers for the 3D geological modeling page.

**NOT production code.** Every function here synthesizes demo data so the
well-seismic overlay, auto-tie, RGB-fusion, and crossplot features remain
visible without real surveys. Production mode with no real data must show the
empty/unavailable state instead of calling these (the page owns that guard).

Extracted from ``GeologicalModeling3DPage`` so the synthetic bits live apart
from the pure analysis services in :mod:`~paleo_workbench.viz.geomodel.analysis`.
"""
from __future__ import annotations

import numpy as np

from geoviz import blend_rgba

from .lithology import DEFAULT_AI, DEFAULT_GR, LITHO_AI, LITHO_GR


def gr_noise(n_samples: int, *, seed: int = 42) -> np.ndarray:
    """Deterministic Gaussian noise added to synthetic GR curves (float32)."""
    return np.random.default_rng(seed).normal(0, 8.0, n_samples).astype(np.float32)


def seismic_slice_geometry(nx_pts: int = 30, ny_pts: int = 30):
    """Synthetic horizontal seismic amplitude slice (verts, faces, colors).

    Returns an (N,3) float32 vertex array, (M,3) int32 face index array, and
    an (M,4) float32 face-color array with a blue-white-red colormap.
    """
    x = np.linspace(-80, 80, nx_pts)
    y = np.linspace(-80, 80, ny_pts)
    xx, yy = np.meshgrid(x, y)
    # Synthetic seismic amplitude pattern
    zz = -60.0 + 3.0 * np.sin(xx / 15.0) * np.cos(yy / 15.0)

    verts = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).astype(np.float32)

    # Build face indices for grid quads (as triangles)
    faces = []
    for j in range(ny_pts - 1):
        for i in range(nx_pts - 1):
            idx = j * nx_pts + i
            faces.append([idx, idx + 1, idx + nx_pts])
            faces.append([idx + 1, idx + nx_pts + 1, idx + nx_pts])
    faces = np.array(faces, dtype=np.int32)

    # Color by amplitude
    amp = (zz.ravel() + 63.0) / 6.0  # normalize 0-1
    amp = np.clip(amp, 0, 1)
    colors = np.zeros((len(faces), 4), dtype=np.float32)
    for fi, face in enumerate(faces):
        a = float(np.mean(amp[face]))
        # Blue-white-red colormap
        if a < 0.5:
            colors[fi] = [0.2, 0.2 + 0.6 * (a * 2), 0.9, 0.55]
        else:
            colors[fi] = [0.9, 0.2 + 0.6 * (2 - a * 2), 0.2, 0.55]
    return verts, faces, colors


def rgb_fusion_geometry(nx_pts: int = 40, ny_pts: int = 40):
    """Synthetic RGB frequency-attribute fusion slice (verts, faces, colors).

    Three synthetic frequency channels (15/35/55 Hz proxies) blended via
    ``geoviz.blend_rgba`` into per-face RGBA colors.
    """
    x = np.linspace(-80, 80, nx_pts)
    y = np.linspace(-80, 80, ny_pts)
    xx, yy = np.meshgrid(x, y)
    zz = -40.0 + 2.0 * np.sin(xx / 10.0) * np.cos(yy / 10.0)

    # Synthetic frequency channels
    ch_r = np.sin(xx / 12.0) * np.cos(yy / 12.0) + 1.0  # Low frequency (15Hz)
    ch_g = np.cos(xx / 8.0) * np.sin(yy / 8.0) + 1.0   # Mid frequency (35Hz)
    ch_b = np.sin(xx / 5.0 + yy / 5.0) + 1.0          # High frequency (55Hz)

    rgba_grid = blend_rgba(ch_r, ch_g, ch_b, alpha=0.85)

    verts = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).astype(np.float32)

    faces = []
    face_colors = []
    for j in range(ny_pts - 1):
        for i in range(nx_pts - 1):
            idx = j * nx_pts + i
            faces.append([idx, idx + 1, idx + nx_pts])
            faces.append([idx + 1, idx + nx_pts + 1, idx + nx_pts])

            c = rgba_grid[j, i]
            face_colors.append(c)
            face_colors.append(c)

    faces = np.array(faces, dtype=np.int32)
    face_colors = np.array(face_colors, dtype=np.float32)
    return verts, faces, face_colors


def synthetic_field_trace(synthetic: np.ndarray, *, seed: int = 123, true_shift: int = 12) -> np.ndarray:
    """A synthetic "field" seismic trace: the synthetic shifted + noise.

    Deterministic (fixed seed) so the auto-tie cross-correlation is
    reproducible in tests and demos.
    """
    rng = np.random.default_rng(seed)
    return np.roll(synthetic, true_shift) + rng.normal(0, 0.05, len(synthetic))


def crossplot_samples(
    bh_raw_data: list[dict],
    *,
    seed: int = 42,
    samples_per_layer: int = 10,
) -> tuple[list[float], list[float], list[str]]:
    """Sample (GR, AI, lithology) tuples around the per-lithology table values.

    Returns parallel Python lists; the caller feeds them to
    ``geoviz.analyze_lithology_crossplot``.
    """
    rng = np.random.default_rng(seed)
    gr_list: list[float] = []
    ai_list: list[float] = []
    lith_list: list[str] = []
    for bh in bh_raw_data:
        for layer in bh["layers"]:
            lith = layer["lithology"]
            base_g = LITHO_GR.get(lith, DEFAULT_GR)
            base_a = LITHO_AI.get(lith, DEFAULT_AI)

            # Sample ``samples_per_layer`` points per layer
            for _ in range(samples_per_layer):
                gr_list.append(base_g + float(rng.normal(0, 6.0)))
                ai_list.append(base_a + float(rng.normal(0, 400.0)))
                lith_list.append(lith)
    return gr_list, ai_list, lith_list
