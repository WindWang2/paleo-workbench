"""Well-Seismic Tie, 3D Curve overlay, and Advanced Seismic Analysis algorithms."""
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


class RGBAttributeFusion:
    """Fuses 3 scalar seismic attribute arrays (R, G, B) into RGBA mesh color array."""

    @staticmethod
    def blend_rgb(r_channel: np.ndarray, g_channel: np.ndarray, b_channel: np.ndarray, alpha: float = 0.85) -> np.ndarray:
        """Normalize and blend 3 attribute channels into an RGBA color matrix."""
        def norm(arr: np.ndarray) -> np.ndarray:
            min_val, max_val = np.min(arr), np.max(arr)
            if max_val - min_val < 1e-8:
                return np.zeros_like(arr, dtype=np.float32)
            return (arr - min_val) / (max_val - min_val)

        r_norm = norm(r_channel).astype(np.float32)
        g_norm = norm(g_channel).astype(np.float32)
        b_norm = norm(b_channel).astype(np.float32)
        a_norm = np.full_like(r_norm, fill_value=alpha, dtype=np.float32)

        return np.stack([r_norm, g_norm, b_norm, a_norm], axis=-1)


class LithologyCrossplotEngine:
    """Computes 2D/3D crossplot statistics and cluster centroids for reservoir lithology discrimination."""

    @staticmethod
    def analyze(gr: np.ndarray, ai: np.ndarray, lithology: list[str]) -> dict:
        """Analyze GR vs Acoustic Impedance (AI) arrays grouped by lithology."""
        points = []
        clusters: dict[str, dict] = {}

        for i in range(len(gr)):
            lith = lithology[i] if i < len(lithology) else "Unknown"
            g_val = float(gr[i])
            a_val = float(ai[i])
            points.append({"gr": g_val, "ai": a_val, "lithology": lith})

            if lith not in clusters:
                clusters[lith] = {"gr_list": [], "ai_list": []}
            clusters[lith]["gr_list"].append(g_val)
            clusters[lith]["ai_list"].append(a_val)

        summary_clusters = {}
        for lith, data in clusters.items():
            g_arr = np.array(data["gr_list"])
            a_arr = np.array(data["ai_list"])
            summary_clusters[lith] = {
                "count": len(g_arr),
                "mean_gr": float(np.mean(g_arr)),
                "mean_ai": float(np.mean(a_arr)),
                "std_gr": float(np.std(g_arr)),
                "std_ai": float(np.std(a_arr)),
            }

        return {
            "points": points,
            "clusters": summary_clusters,
        }


class CrossWellFenceGenerator:
    """Generates 3D curtain/fence surface meshes connecting adjacent borehole paths."""

    @staticmethod
    def generate_fence_mesh(wells: list[dict], nz_samples: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate 3D triangulated quad strip mesh curtain connecting consecutive wells.

        Each well dict should contain: 'name', 'x', 'y', 'depth'.
        Returns:
            (vertices, faces, face_colors)
        """
        if len(wells) < 2:
            return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.int32), np.empty((0, 4), dtype=np.float32)

        vertices = []
        faces = []
        face_colors = []

        vert_offset = 0
        for w_idx in range(len(wells) - 1):
            w1 = wells[w_idx]
            w2 = wells[w_idx + 1]

            x1, y1, d1 = w1["x"], w1["y"], w1["depth"]
            x2, y2, d2 = w2["x"], w2["y"], w2["depth"]

            max_depth = max(d1, d2)
            z_levels = np.linspace(0.0, -max_depth, nz_samples, dtype=np.float32)

            # Left side (well 1) and Right side (well 2) vertices
            v_left = np.column_stack([np.full(nz_samples, x1), np.full(nz_samples, y1), z_levels])
            v_right = np.column_stack([np.full(nz_samples, x2), np.full(nz_samples, y2), z_levels])

            # Add to vertex list
            panel_verts = np.vstack([v_left, v_right])
            vertices.append(panel_verts)

            # Generate quad triangles
            for k in range(nz_samples - 1):
                idx_l1 = vert_offset + k
                idx_l2 = vert_offset + k + 1
                idx_r1 = vert_offset + nz_samples + k
                idx_r2 = vert_offset + nz_samples + k + 1

                # Quad triangle 1
                faces.append([idx_l1, idx_r1, idx_l2])
                # Quad triangle 2
                faces.append([idx_r1, idx_r2, idx_l2])

                # Depth-gradient color (light cyan/teal to dark blue)
                depth_ratio = abs(float(z_levels[k])) / max_depth
                c1 = [0.1, 0.4 + 0.5 * (1 - depth_ratio), 0.7 + 0.3 * depth_ratio, 0.75]
                c2 = [0.1, 0.4 + 0.5 * (1 - depth_ratio), 0.7 + 0.3 * depth_ratio, 0.75]
                face_colors.append(c1)
                face_colors.append(c2)

            vert_offset += 2 * nz_samples

        all_verts = np.vstack(vertices).astype(np.float32)
        all_faces = np.array(faces, dtype=np.int32)
        all_colors = np.array(face_colors, dtype=np.float32)

        return all_verts, all_faces, all_colors
