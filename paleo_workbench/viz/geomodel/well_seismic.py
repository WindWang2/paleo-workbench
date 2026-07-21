"""Well-Seismic Tie and 3D Curve overlay generation algorithms."""
from __future__ import annotations

import numpy as np


class WellSeismicTieCalibration:
    """Core mathematical algorithms for synthetic trace generation and calibration."""

    @staticmethod
    def compute_synthetic(sonic: np.ndarray, density: np.ndarray, wavelet_freq: float = 30.0, dt_s: float = 0.002) -> np.ndarray:
        """Compute Ricker synthetic seismogram from Sonic DT and Density logs."""
        if len(sonic) <= 1:
            return np.array([], dtype=np.float32)

        # 1. Compute Acoustic Impedance (AI)
        sonic_clipped = np.clip(sonic, 10.0, 1000.0)
        velocity = 1e6 / sonic_clipped  # convert us/m to m/s
        ai = velocity * density

        # 2. Compute reflection coefficients (RC)
        rc = (ai[1:] - ai[:-1]) / (ai[1:] + ai[:-1] + 1e-8)

        # 3. Create Ricker wavelet
        t_half = 0.064  # wavelet length window
        t = np.arange(-t_half, t_half + dt_s, dt_s, dtype=np.float32)
        pi2_f2 = (np.pi * wavelet_freq) ** 2
        wavelet = (1.0 - 2.0 * pi2_f2 * (t**2)) * np.exp(-pi2_f2 * (t**2))

        # 4. Convolve RC with wavelet
        synthetic = np.convolve(rc, wavelet, mode="same")
        return synthetic

    @staticmethod
    def auto_correlate(synthetic: np.ndarray, seismic_trace: np.ndarray) -> tuple[int, float]:
        """Cross-correlate synthetic with a seismic trace to find optimal shift.

        Returns:
            (shift_samples, correlation_coefficient)
        """
        if len(synthetic) == 0 or len(seismic_trace) == 0:
            return 0, 0.0

        # Normalize both traces
        s_std = np.std(synthetic)
        t_std = np.std(seismic_trace)
        if s_std < 1e-10 or t_std < 1e-10:
            return 0, 0.0

        s_norm = (synthetic - np.mean(synthetic)) / s_std
        t_norm = (seismic_trace - np.mean(seismic_trace)) / t_std

        # Cross-correlate
        corr = np.correlate(t_norm, s_norm, mode="full")
        corr /= max(len(s_norm), len(t_norm))

        best_idx = int(np.argmax(corr))
        shift = best_idx - (len(s_norm) - 1)
        cc = float(corr[best_idx])

        return shift, min(cc, 1.0)

    @staticmethod
    def align_twt_depth(depths: np.ndarray, depth_shift: float) -> np.ndarray:
        """Align depth index coordinates using a physical calibration offset shift."""
        return depths + depth_shift


class WellCurve3DGenerator:
    """Generates 3D coordinates for displaying curve tracks offset along well paths."""

    @staticmethod
    def generate_curve_mesh(well_path: np.ndarray, curve_values: np.ndarray, scale: float = 0.1) -> np.ndarray:
        """Offset curve data along the horizontal plane perpendicular to well trajectory."""
        n_pts = len(well_path)
        if n_pts == 0:
            return np.empty((0, 3), dtype=np.float32)

        offset_pts = np.copy(well_path)
        for i in range(n_pts):
            # Compute tangent direction
            if i < n_pts - 1:
                tangent = well_path[i + 1] - well_path[i]
            else:
                tangent = well_path[i] - well_path[i - 1]

            norm = np.linalg.norm(tangent)
            if norm > 1e-5:
                tangent /= norm

            # Perpendicular vector in the horizontal plane (X-Y plane)
            perp = np.array([-tangent[1], tangent[0], 0.0], dtype=np.float32)
            perp_norm = np.linalg.norm(perp)
            if perp_norm < 1e-5:
                # If well is perfectly vertical, offset directly along the X-axis
                perp = np.array([1.0, 0.0, 0.0], dtype=np.float32)
            else:
                perp /= perp_norm

            # Shift the coordinate by scaled curve amplitude value
            offset_pts[i] += perp * curve_values[i] * scale

        return offset_pts
