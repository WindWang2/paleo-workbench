"""HorizonSculpting: Interactive 3D horizon brush surface editing & smooth annealing engine."""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np


@dataclass
class SparseDeltaPatch:
    """Sparse vertex height delta patch for memory-efficient undo/redo."""
    indices: np.ndarray
    old_z: np.ndarray
    new_z: np.ndarray


class SculptableHorizonMesh:
    """Stateful 3D horizon surface mesh with Gaussian brush sculpting and sparse undo/redo."""

    def __init__(
        self,
        vertices: np.ndarray,
        faces: np.ndarray | None = None,
        grid_shape: tuple[int, int] | None = None,
    ):
        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("Vertices array must have shape (N, 3)")

        self.vertices = vertices.astype(np.float32, copy=True)
        self.faces = faces if faces is not None else np.zeros((0, 3), dtype=np.int32)
        self.grid_shape = grid_shape
        self._undo_stack: list[SparseDeltaPatch] = []
        self._redo_stack: list[SparseDeltaPatch] = []

    def sculpt_surface(
        self,
        center_xy: tuple[float, float],
        delta_z: float,
        radius: float = 5.0,
    ) -> np.ndarray:
        """Deform surface vertex elevations with a radial Gaussian brush.

        The brush is a fixed Gaussian kernel (not a fitted RBF solve):
        weights fall to EXACTLY zero at ``radius`` — the plain
        exp(-(d/(r/2))²) profile still applied 1.83% of the delta at the
        rim, leaving a visible step at the brush boundary (#846).
        """
        cx, cy = center_xy
        dx = self.vertices[:, 0] - cx
        dy = self.vertices[:, 1] - cy
        dist = np.hypot(dx, dy)

        within_mask = dist <= radius
        indices = np.where(within_mask)[0]

        if len(indices) > 0:
            sigma = radius * 0.5
            tail = math.exp(-((radius / sigma) ** 2))
            denom = 1.0 - tail
            if denom <= 0.0:  # pragma: no cover - radius > 0 keeps tail < 1
                weights = np.ones(len(indices))
            else:
                weights = (np.exp(-((dist[within_mask] / sigma) ** 2)) - tail) / denom
            old_z = self.vertices[indices, 2].copy()
            new_z = old_z + delta_z * weights
            self.vertices[indices, 2] = new_z

            patch = SparseDeltaPatch(indices=indices, old_z=old_z, new_z=new_z)
            self._undo_stack.append(patch)
            self._redo_stack.clear()

        return self.vertices

    def smooth_anneal(self, iterations: int = 1) -> np.ndarray:
        """Apply laplacian smooth annealing to mesh height values.

        The undo patch records only the vertices that actually moved
        (#846): the previous all-indices patch pushed three full float32
        grids per smoothing step onto the undo stack on a 1000x1000
        horizon, violating SparseDeltaPatch's own memory contract.
        """
        if self.grid_shape is None:
            raise ValueError(
                "grid_shape is required for smooth_anneal: vertex count alone "
                "cannot identify the (rows, cols) topology (N=36 is both 4x9 "
                "and 6x6)"
            )

        rows, cols = self.grid_shape
        grid = self.vertices[:, 2].reshape((rows, cols)).copy()

        for _ in range(iterations):
            padded = np.pad(grid, pad_width=1, mode="edge")
            smoothed = (
                padded[:-2, 1:-1] + padded[2:, 1:-1] +
                padded[1:-1, :-2] + padded[1:-1, 2:] +
                padded[1:-1, 1:-1] * 4.0
            ) / 8.0
            grid = smoothed

        new_z = grid.ravel()
        changed = np.nonzero(new_z != self.vertices[:, 2])[0]
        if len(changed) > 0:
            patch = SparseDeltaPatch(
                indices=changed,
                old_z=self.vertices[changed, 2].copy(),
                new_z=new_z[changed],
            )
            self._undo_stack.append(patch)
            self._redo_stack.clear()
        self.vertices[:, 2] = new_z
        return self.vertices

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        patch = self._undo_stack.pop()
        self.vertices[patch.indices, 2] = patch.old_z
        self._redo_stack.append(patch)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        patch = self._redo_stack.pop()
        self.vertices[patch.indices, 2] = patch.new_z
        self._undo_stack.append(patch)
        return True


class HorizonSculpting:
    """Gaussian brush surface sculptor for 3D horizon meshes."""

    def sculpt_surface(
        self,
        vertices: np.ndarray,
        center_xy: tuple[float, float],
        delta_z: float,
        radius: float = 5.0,
    ) -> np.ndarray:
        """Deform surface vertex elevations within a radial influence brush sphere."""
        mesh = SculptableHorizonMesh(vertices)
        mesh.sculpt_surface(center_xy, delta_z, radius)
        return mesh.vertices

    def smooth_anneal(self, z_grid: np.ndarray, iterations: int = 1) -> np.ndarray:
        """Apply laplacian smooth annealing to a 2D height grid."""
        rows, cols = z_grid.shape
        x, y = np.meshgrid(np.arange(cols, dtype=np.float32), np.arange(rows, dtype=np.float32))
        verts = np.column_stack([x.ravel(), y.ravel(), z_grid.ravel()])
        mesh = SculptableHorizonMesh(verts, grid_shape=(rows, cols))
        mesh.smooth_anneal(iterations)
        return mesh.vertices[:, 2].reshape((rows, cols))
