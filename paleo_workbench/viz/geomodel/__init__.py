"""3D geological modelling — thin adapter over the geo-viz-engine facade.

The visualization engine core (GL clipping items, borehole/tunnel/fault geometry,
well-tie algorithms, RGB attribute blending, cross-well fences, lithology crossplot
statistics) lives in ``geo-viz-engine`` and is reached through the ``geoviz`` facade.
See ``docs/agents/geo-viz-boundary.md`` for the boundary rules and the migration map.

What genuinely stays in the workbench:

- :mod:`~paleo_workbench.viz.geomodel.models` — domain dataclasses
- :mod:`~paleo_workbench.viz.geomodel.advisor` — business-rule data-consistency checks
- :mod:`~paleo_workbench.viz.geomodel.exporters` — FLAC3D / Abaqus numerical-simulation export

Everything else re-exported below is a pass-through to ``geoviz``, kept so existing
callers and tests need no churn. **New code should import from ``geoviz`` directly.**
The compatibility classes at the bottom are parameter-forwarding shims with no
algorithm of their own.
"""

from __future__ import annotations

import numpy as np
from geoviz import (
    BoreholeTraceGenerator,
    ClippedGLMeshItem,
    ClippedGLVolumeItem,
    CrossWellFenceGenerator,
    FaultCuttingEngine,
    TunnelMeshGenerator,
    analyze_lithology_crossplot,
    blend_rgba,
    correlate_synthetic_to_trace,
    generate_cylinder_geometry,
    generate_fault_geometry,
    generate_fence_mesh,
    generate_tube_geometry,
    get_seam_boundaries,
    offset_curve_along_trajectory,
    shift_depths,
    synthetic_from_logs,
)

from .advisor import check_boreholes, check_coplanar_faults
from .exporters import export_to_abaqus, export_to_flac3d
from .models import (
    BoreholeRecord,
    FaultRecord,
    GridSpec,
    Layer,
    TunnelRecord,
)


class WellSeismicTieCalibration:
    """Deprecated shim for the well-tie functions now in ``geoviz_well_tie``.

    Prefer ``from geoviz import synthetic_from_logs, correlate_synthetic_to_trace,
    shift_depths``.
    """

    @staticmethod
    def compute_synthetic(
        sonic: np.ndarray,
        density: np.ndarray,
        wavelet_freq: float = 30.0,
        dt_s: float = 0.002,
    ) -> np.ndarray:
        """See :func:`geoviz.synthetic_from_logs`."""
        return synthetic_from_logs(
            sonic, density, wavelet_freq=wavelet_freq, dt_s=dt_s
        )

    @staticmethod
    def auto_correlate(
        synthetic: np.ndarray, seismic_trace: np.ndarray
    ) -> tuple[int, float]:
        """See :func:`geoviz.correlate_synthetic_to_trace`."""
        return correlate_synthetic_to_trace(synthetic, seismic_trace)

    @staticmethod
    def align_twt_depth(depths: np.ndarray, depth_shift: float) -> np.ndarray:
        """See :func:`geoviz.shift_depths`."""
        return shift_depths(depths, depth_shift)


class WellCurve3DGenerator:
    """Deprecated shim. Prefer ``from geoviz import offset_curve_along_trajectory``."""

    @staticmethod
    def generate_curve_mesh(
        well_path: np.ndarray, curve_values: np.ndarray, scale: float = 0.1
    ) -> np.ndarray:
        """See :func:`geoviz.offset_curve_along_trajectory`."""
        return offset_curve_along_trajectory(well_path, curve_values, scale=scale)


class RGBAttributeFusion:
    """Deprecated shim. Prefer ``from geoviz import blend_rgba``."""

    @staticmethod
    def blend_rgb(
        r_channel: np.ndarray,
        g_channel: np.ndarray,
        b_channel: np.ndarray,
        alpha: float = 0.85,
    ) -> np.ndarray:
        """See :func:`geoviz.blend_rgba`."""
        return blend_rgba(r_channel, g_channel, b_channel, alpha=alpha)


class LithologyCrossplotEngine:
    """Deprecated shim. Prefer ``from geoviz import analyze_lithology_crossplot``."""

    @staticmethod
    def analyze(gr: np.ndarray, ai: np.ndarray, lithology: list[str]) -> dict:
        """See :func:`geoviz.analyze_lithology_crossplot`."""
        return analyze_lithology_crossplot(gr, ai, lithology)


__all__ = [
    # Workbench-owned: domain models
    "Layer",
    "BoreholeRecord",
    "FaultRecord",
    "TunnelRecord",
    "GridSpec",
    # Workbench-owned: business AI advisor
    "check_boreholes",
    "check_coplanar_faults",
    # Workbench-owned: numerical-simulation export
    "export_to_flac3d",
    "export_to_abaqus",
    # Engine pass-throughs: GL rendering primitives
    "ClippedGLMeshItem",
    "ClippedGLVolumeItem",
    # Engine pass-throughs: headless geometry
    "generate_cylinder_geometry",
    "generate_tube_geometry",
    "generate_fault_geometry",
    "get_seam_boundaries",
    "BoreholeTraceGenerator",
    "TunnelMeshGenerator",
    "FaultCuttingEngine",
    "CrossWellFenceGenerator",
    "generate_fence_mesh",
    # Engine pass-throughs: well-tie + attribute analysis
    "synthetic_from_logs",
    "correlate_synthetic_to_trace",
    "shift_depths",
    "offset_curve_along_trajectory",
    "blend_rgba",
    "analyze_lithology_crossplot",
    # Deprecated compatibility shims
    "WellSeismicTieCalibration",
    "WellCurve3DGenerator",
    "RGBAttributeFusion",
    "LithologyCrossplotEngine",
]
