"""FormationVolumeIntegrator: Closed formation volume integration engine via Gauss Divergence Theorem."""

from __future__ import annotations

import numpy as np


class FormationVolumeIntegrator:
    """Computes exact 3D closed rock formation volume between top and bottom horizons using Gauss Divergence Theorem."""

    def compute_closed_volume(
        self,
        top_vertices: np.ndarray,
        bot_vertices: np.ndarray,
        grid_shape: tuple[int, int] | None = None,
    ) -> float:
        """Calculate watertight closed polyhedron volume via Gauss Divergence Theorem surface integrals.

        Constructs top mesh, bottom mesh, and vertical side-wall boundary strips to form a
        watertight 3D polyhedron, evaluating:
            V = 1/6 * sum( p0 . (p1 x p2) ) over all oriented surface triangles.

        Args:
            top_vertices: (N, 3) float32 array of top horizon vertex positions.
            bot_vertices: (N, 3) float32 array of bottom horizon vertex positions.
            grid_shape: (rows, cols) grid dimensions. Required for side-wall strip construction.

        Returns:
            Total enclosed 3D volume (cubic units).
        """
        if top_vertices.shape != bot_vertices.shape or top_vertices.shape[1] != 3:
            raise ValueError("top_vertices and bot_vertices must have matching (N, 3) shape")

        n_pts = top_vertices.shape[0]
        if grid_shape is None:
            side = int(np.round(np.sqrt(n_pts)))
            if side * side == n_pts:
                grid_shape = (side, side)
            else:
                raise ValueError("grid_shape is required for non-square vertex counts")

        rows, cols = grid_shape
        if rows * cols != n_pts:
            raise ValueError(f"grid_shape {grid_shape} does not match total vertices {n_pts}")

        return self._divergence_theorem_mesh_volume(top_vertices, bot_vertices, rows, cols)

    def _divergence_theorem_mesh_volume(
        self,
        top_verts: np.ndarray,
        bot_verts: np.ndarray,
        rows: int,
        cols: int,
    ) -> float:
        """Construct watertight closed 3D polyhedron and compute surface integral via Gauss Divergence Theorem."""
        # Build 3D mesh vertices: top vertices [0..N-1], bot vertices [N..2N-1]
        n = rows * cols
        # Accumulate in float64: float32 cross products cancel catastrophically
        # at UTM-scale coordinates (verified >2000% volume error).
        v_total = np.vstack([top_verts, bot_verts]).astype(np.float64)

        faces = []

        # 1. Top surface triangles (oriented CCW, normal pointing UP)
        for r in range(rows - 1):
            for c in range(cols - 1):
                i0 = r * cols + c
                i1 = r * cols + (c + 1)
                i2 = (r + 1) * cols + c
                i3 = (r + 1) * cols + (c + 1)
                faces.append([i0, i1, i2])
                faces.append([i1, i3, i2])

        # 2. Bottom surface triangles (oriented CW, normal pointing DOWN)
        for r in range(rows - 1):
            for c in range(cols - 1):
                i0 = n + (r * cols + c)
                i1 = n + (r * cols + (c + 1))
                i2 = n + ((r + 1) * cols + c)
                i3 = n + ((r + 1) * cols + (c + 1))
                faces.append([i0, i2, i1])
                faces.append([i1, i2, i3])

        # 3. Side-wall quadrilateral boundary strips (top_edge connected to bot_edge)
        # Top boundary (r = 0)
        for c in range(cols - 1):
            t0, t1 = c, c + 1
            b0, b1 = n + c, n + c + 1
            faces.append([t0, b0, t1])
            faces.append([t1, b0, b1])

        # Bottom boundary (r = rows - 1)
        for c in range(cols - 1):
            t0, t1 = (rows - 1) * cols + c, (rows - 1) * cols + c + 1
            b0, b1 = n + t0, n + t1
            faces.append([t0, t1, b0])
            faces.append([t1, b1, b0])

        # Left boundary (c = 0)
        for r in range(rows - 1):
            t0, t1 = r * cols, (r + 1) * cols
            b0, b1 = n + t0, n + t1
            faces.append([t0, t1, b0])
            faces.append([t1, b1, b0])

        # Right boundary (c = cols - 1)
        for r in range(rows - 1):
            t0, t1 = r * cols + (cols - 1), (r + 1) * cols + (cols - 1)
            b0, b1 = n + t0, n + t1
            faces.append([t0, b0, t1])
            faces.append([t1, b0, b1])

        faces_arr = np.array(faces, dtype=np.int32)

        # Gauss Divergence Theorem surface integral: V = 1/6 * sum( p0 . (p1 x p2) )
        p0 = v_total[faces_arr[:, 0]]
        p1 = v_total[faces_arr[:, 1]]
        p2 = v_total[faces_arr[:, 2]]

        cross = np.cross(p1, p2)
        signed_vols = np.sum(p0 * cross, axis=1) / 6.0

        total_volume = float(np.abs(np.sum(signed_vols)))
        return total_volume
