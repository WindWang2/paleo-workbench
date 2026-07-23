"""CrossWellFenceGenerator: 3D curtain/fence mesh generator and 2D/3D seismic slice extractor."""

from __future__ import annotations

import numpy as np


class CrossWellFenceGenerator:
    """Generates 3D curtain/fence surface meshes and extracts inter-well 2D seismic slices."""

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

            z_left = np.linspace(0.0, -d1, nz_samples, dtype=np.float32)
            z_right = np.linspace(0.0, -d2, nz_samples, dtype=np.float32)

            v_left = np.column_stack([np.full(nz_samples, x1), np.full(nz_samples, y1), z_left])
            v_right = np.column_stack([np.full(nz_samples, x2), np.full(nz_samples, y2), z_right])

            panel_verts = np.vstack([v_left, v_right])
            vertices.append(panel_verts)

            max_d = max(d1, d2)
            for k in range(nz_samples - 1):
                idx_l1 = vert_offset + k
                idx_l2 = vert_offset + k + 1
                idx_r1 = vert_offset + nz_samples + k
                idx_r2 = vert_offset + nz_samples + k + 1

                faces.append([idx_l1, idx_r1, idx_l2])
                faces.append([idx_r1, idx_r2, idx_l2])

                depth_ratio = abs(float(z_left[k])) / max(max_d, 1.0)
                c = [0.1, 0.4 + 0.5 * (1 - depth_ratio), 0.7 + 0.3 * depth_ratio, 0.75]
                face_colors.append(c)
                face_colors.append(c)

            vert_offset += 2 * nz_samples

        all_verts = np.vstack(vertices).astype(np.float32)
        all_faces = np.array(faces, dtype=np.int32)
        all_colors = np.array(face_colors, dtype=np.float32)

        return all_verts, all_faces, all_colors

    @staticmethod
    def extract_seismic_slice(
        seismic_data: np.ndarray,
        wells: list[dict],
        n_samples_per_segment: int = 50,
    ) -> np.ndarray:
        """Extract 2D seismic amplitude section along piecewise multi-well trajectory path."""
        if len(wells) < 2 or seismic_data.ndim != 3:
            return np.zeros((0, 0), dtype=np.float32)

        ni, nx, nz = seismic_data.shape
        path_x = []
        path_y = []

        for i in range(len(wells) - 1):
            w1 = wells[i]
            w2 = wells[i + 1]
            x1, y1 = float(w1.get("x", 0)), float(w1.get("y", 0))
            x2, y2 = float(w2.get("x", 0)), float(w2.get("y", 0))

            xs = np.linspace(x1, x2, n_samples_per_segment)
            ys = np.linspace(y1, y2, n_samples_per_segment)

            if i > 0:
                xs = xs[1:]
                ys = ys[1:]

            path_x.extend(xs)
            path_y.extend(ys)

        n_pts = len(path_x)
        slice_2d = np.zeros((nz, n_pts), dtype=np.float32)

        for p in range(n_pts):
            ix = int(np.clip(path_x[p], 0, ni - 1))
            iy = int(np.clip(path_y[p], 0, nx - 1))
            slice_2d[:, p] = seismic_data[ix, iy, :]

        return slice_2d
