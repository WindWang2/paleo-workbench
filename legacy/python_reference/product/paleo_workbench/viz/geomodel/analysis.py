"""Pure analysis services for the 3D geological modeling page.

The scientific/algorithm methods extracted from ``GeologicalModeling3DPage``
(``_generate_well_curve_overlays``, ``_generate_seismic_slice_overlay``,
``_run_auto_tie``, ``_generate_rgb_fusion_slice``,
``_generate_cross_well_fence``, ``_run_lithology_crossplot``) live here as
pure functions: they take borehole data + parameters and return numpy data /
results, so they run without Qt or GL. The page keeps thin delegating calls
and owns only the GL item wiring and user-facing messages.

The explicitly-synthetic sub-pieces (noise, synthetic slice patterns, the
synthetic "field" trace, crossplot sampling) come from
:mod:`~paleo_workbench.viz.geomodel.demo` — see its docstring: demo providers
are NOT production code.
"""
from __future__ import annotations

import numpy as np

from geoviz import (
    analyze_lithology_crossplot,
    correlate_synthetic_to_trace,
    generate_fence_mesh,
    offset_curve_along_trajectory,
    shift_depths,
    synthetic_from_logs,
)

from . import demo
from .lithology import (
    DEFAULT_DENSITY,
    DEFAULT_GR,
    DEFAULT_SONIC,
    LITHO_DENSITY,
    LITHO_GR,
    LITHO_SONIC,
    sample_log_values,
)


def _well_depth_axis(layers: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Build the (depths, well_path) arrays for a borehole's layer stack.

    ``well_path`` is (n,3) float32 with Z pointing upward (depths negated),
    spanning surface to total depth.
    """
    max_depth = max(layer["bottom"] for layer in layers)
    n_samples = max(int(max_depth), 50)
    depths = np.linspace(0, max_depth, n_samples, dtype=np.float32)
    return depths, n_samples


def generate_well_curve_overlays(
    bh_raw_data: list[dict], freq: float, td_shift: float
) -> list[dict]:
    """Compute GR curve + synthetic seismogram data for every borehole.

    Returns one dict per borehole with layers:
      - ``well_path`` (n,3) float32 — vertical well path surface→TD
      - ``curve_pts`` (n,3) float32 — GR log offset sideways off the trajectory
      - ``synthetic`` (k,) — synthetic seismogram from sonic/density logs
      - ``syn_path`` (k,3) float32 or ``None`` — aligned synthetic path
      - ``syn_curve_pts`` (k,3) float32 or ``None`` — offset synthetic trace
    """
    overlays: list[dict] = []
    for bh in bh_raw_data:
        bx, by = bh["x"], bh["y"]
        layers = bh["layers"]
        if not layers:
            continue

        depths, n_samples = _well_depth_axis(layers)
        well_path = np.column_stack([
            np.full(n_samples, bx, dtype=np.float32),
            np.full(n_samples, by, dtype=np.float32),
            -depths,  # Z is upward, depth is downward
        ])

        # GR-like curve from per-lithology table values, plus demo noise.
        gr_values = sample_log_values(layers, depths, LITHO_GR, DEFAULT_GR)
        gr_values = gr_values + demo.gr_noise(n_samples)

        # Offset the GR log sideways off the trajectory (engine: geoviz_well_seismic_3d)
        curve_pts = offset_curve_along_trajectory(well_path, gr_values, scale=0.15)

        # Sonic and density logs for the synthetic seismogram.
        sonic = sample_log_values(layers, depths, LITHO_SONIC, DEFAULT_SONIC)
        density = sample_log_values(layers, depths, LITHO_DENSITY, DEFAULT_DENSITY)
        synthetic = synthetic_from_logs(sonic, density, wavelet_freq=freq)

        syn_path = None
        syn_curve_pts = None
        if len(synthetic) > 0:
            # Align synthetic length to well path subset
            syn_len = min(len(synthetic), n_samples - 1)
            syn_path = well_path[1:syn_len + 1].copy()

            # Apply T-D shift
            aligned_depths = shift_depths(-syn_path[:, 2], td_shift)
            syn_path[:, 2] = -aligned_depths

            # Offset synthetic trace in the opposite direction from GR
            syn_curve_pts = offset_curve_along_trajectory(
                syn_path, synthetic[:syn_len], scale=5.0
            )

        overlays.append({
            "well_path": well_path,
            "curve_pts": curve_pts,
            "synthetic": synthetic,
            "syn_path": syn_path,
            "syn_curve_pts": syn_curve_pts,
        })
    return overlays


def generate_seismic_slice_overlay(nx_pts: int = 30, ny_pts: int = 30):
    """Synthetic horizontal seismic amplitude slice (verts, faces, colors).

    Demo provider; see :func:`paleo_workbench.viz.geomodel.demo.seismic_slice_geometry`.
    """
    return demo.seismic_slice_geometry(nx_pts=nx_pts, ny_pts=ny_pts)


def run_auto_tie(bh_raw_data: list[dict], freq: float) -> dict | None:
    """Real cross-correlation auto-tie via ``geoviz.correlate_synthetic_to_trace``.

    Uses the first borehole with layers for calibration: build a synthetic seismogram from
    its lithology-derived sonic/density logs, synthesize a demo "field" trace,
    and return ``{"shift_samples": int, "cc": float}``. ``None`` when no
    borehole data or no synthetic can be built.
    """
    if not bh_raw_data:
        return None

    # Calibration needs a borehole with layers; boreholes whose layer stack
    # is empty cannot build logs (max() over layers would fail) — skip them.
    bh = next((b for b in bh_raw_data if b.get("layers")), None)
    if bh is None:
        return None
    layers = bh["layers"]
    depths, n_samples = _well_depth_axis(layers)

    sonic = sample_log_values(layers, depths, LITHO_SONIC, DEFAULT_SONIC)
    density = sample_log_values(layers, depths, LITHO_DENSITY, DEFAULT_DENSITY)
    synthetic = synthetic_from_logs(sonic, density, wavelet_freq=freq)

    if len(synthetic) == 0:
        return None

    # Generate a synthetic "field seismic trace" (shifted synthetic + noise)
    seismic_trace = demo.synthetic_field_trace(synthetic)
    shift_samples, cc = correlate_synthetic_to_trace(synthetic, seismic_trace)
    return {"shift_samples": int(shift_samples), "cc": float(cc)}


def generate_rgb_fusion_slice(nx_pts: int = 40, ny_pts: int = 40):
    """Synthetic RGB frequency-attribute fusion slice (verts, faces, colors).

    Demo provider; see :func:`paleo_workbench.viz.geomodel.demo.rgb_fusion_geometry`.
    """
    return demo.rgb_fusion_geometry(nx_pts=nx_pts, ny_pts=ny_pts)


def generate_cross_well_fence(bh_raw_data: list[dict], nz_samples: int = 25):
    """3D curtain/fence slice connecting all loaded boreholes.

    Returns ``(verts, faces, colors)`` from ``geoviz.generate_fence_mesh``,
    or ``None`` when there are no boreholes or the mesh is empty.
    """
    if not bh_raw_data:
        return None

    wells = [
        {"name": bh["name"], "x": bh["x"], "y": bh["y"], "depth": bh["total_depth"]}
        for bh in bh_raw_data
    ]

    verts, faces, colors = generate_fence_mesh(wells, nz_samples=nz_samples)
    if len(verts) == 0:
        return None
    return verts, faces, colors


def run_lithology_crossplot(
    bh_raw_data: list[dict], *, seed: int = 42, samples_per_layer: int = 10
) -> dict:
    """Run ``geoviz.analyze_lithology_crossplot`` over demo-sampled (GR, AI) pairs.

    The sampling itself is a demo provider (per-lithology table values +
    Gaussian jitter); the statistics are the real engine.
    """
    gr_list, ai_list, lith_list = demo.crossplot_samples(
        bh_raw_data, seed=seed, samples_per_layer=samples_per_layer
    )
    return analyze_lithology_crossplot(
        np.array(gr_list, dtype=np.float32),
        np.array(ai_list, dtype=np.float32),
        lith_list,
    )
