"""HorizonSculpting: Interactive 3D horizon brush surface editing & smooth annealing engine."""

from __future__ import annotations

import numpy as np


class HorizonSculpting:
    """RBF and Gaussian brush surface sculptor for 3D horizon meshes."""

    def sculpt_surface(
        self,
        vertices: np.ndarray,
        center_xy: tuple[float, float],
        delta_z: float,
        radius: float = 5.0,
    ) -> np.ndarray:
        """Deform surface vertex elevations within a radial influence brush sphere."""
        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("Vertices array must have shape (N, 3)")

        res = vertices.copy()
        cx, cy = center_xy
        dx = res[:, 0] - cx
        dy = res[:, 1] - cy
        dist = np.hypot(dx, dy)

        # Gaussian RBF radial weighting: w = exp(-(d / radius)^2)
        within_mask = dist <= radius
        weights = np.exp(-((dist[within_mask] / (radius * 0.5)) ** 2))
        res[within_mask, 2] += delta_z * weights

        return res

    def smooth_anneal(self, z_grid: np.ndarray, iterations: int = 1) -> np.ndarray:
        """Apply laplacian smooth annealing to a 2D height grid."""
        if z_grid.ndim != 2:
            raise ValueError("z_grid must be a 2D array")

        grid = z_grid.copy()
        rows, cols = grid.shape

        for _ in range(iterations):
            padded = np.pad(grid, pad_width=1, mode="edge")
            # 3x3 box blur mean smoothing
            smoothed = (
                padded[:-2, 1:-1] + padded[2:, 1:-1] +
                padded[1:-1, :-2] + padded[1:-1, 2:] +
                padded[1:-1, 1:-1] * 4.0
            ) / 8.0
            grid = smoothed

        return grid
