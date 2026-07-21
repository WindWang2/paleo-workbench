"""Fault cutting and dislocation engine for geological surfaces."""

from __future__ import annotations
import numpy as np


class FaultCuttingEngine:
    """Engine for simulating fault cutting and block dislocation on geological surfaces."""

    @staticmethod
    def apply_dislocation(
        surface_points: np.ndarray,
        fault_plane: tuple,
        throw_vector: np.ndarray,
        split_throw: bool = False,
        decay_distance: float | None = None,
        decay_style: str = "linear",
    ) -> np.ndarray:
        """Applies geological fault dislocation to a set of 3D surface points.

        Parameters
        ----------
        surface_points : np.ndarray
            Array of shape (N, 3) or (H, W, 3) representing 3D coordinates of the surface.
        fault_plane : tuple
            A tuple representing the fault plane. Can be:
            - (point, normal): Where point is (3,) array/list and normal is (3,) array/list.
            - (a, b, c, d): Coefficients of the plane equation a*x + b*y + c*z + d = 0.
        throw_vector : np.ndarray
            Array of shape (3,) or (N, 3) representing the displacement vector.
        split_throw : bool, optional
            If True, displaces the positive side by +0.5 * throw_vector and the negative side
            by -0.5 * throw_vector. If False (default), displaces the positive side by throw_vector
            and keeps the negative side stationary.
        decay_distance : float, optional
            If specified, the dislocation decays to zero over this distance from the fault plane
            to simulate fault drag/folding.
        decay_style : str, optional
            Type of decay function to use: "linear", "exponential", or "gaussian".
            Default is "linear".

        Returns
        -------
        np.ndarray
            The displaced surface points with the same shape as `surface_points`.
        """
        if not isinstance(fault_plane, tuple):
            raise TypeError("fault_plane must be a tuple")

        # Unpack fault plane representation
        if len(fault_plane) == 2:
            plane_pt = np.asarray(fault_plane[0], dtype=float)
            plane_normal = np.asarray(fault_plane[1], dtype=float)
            if plane_pt.shape != (3,) or plane_normal.shape != (3,):
                raise ValueError("For (point, normal) representation, both must have shape (3,)")
        elif len(fault_plane) == 4:
            a, b, c, d = map(float, fault_plane)
            plane_normal = np.array([a, b, c], dtype=float)
            norm_sq = np.dot(plane_normal, plane_normal)
            if norm_sq < 1e-12:
                raise ValueError("Fault plane normal vector cannot be zero (a, b, c cannot all be 0)")
            # Point on plane: project origin onto plane
            plane_pt = -d * plane_normal / norm_sq
        else:
            raise ValueError(
                "fault_plane tuple must have length 2 (point, normal) or 4 (a, b, c, d)"
            )

        # Normalize normal vector
        norm_len = np.linalg.norm(plane_normal)
        if norm_len < 1e-12:
            raise ValueError("Fault plane normal vector length cannot be zero")
        unit_normal = plane_normal / norm_len

        # Coerce surface points to float and determine original shape
        pts = np.asarray(surface_points, dtype=float)
        orig_shape = pts.shape
        if len(orig_shape) < 1 or orig_shape[-1] != 3:
            raise ValueError("surface_points must have last dimension of size 3")

        # Flatten to (N, 3) for unified processing
        pts_flat = pts.reshape(-1, 3)
        N = pts_flat.shape[0]

        # Parse throw vector
        throw = np.asarray(throw_vector, dtype=float)
        if throw.shape == (3,):
            pass
        elif throw.shape == (N, 3):
            pass
        elif len(throw.shape) == 2 and throw.shape[0] == 1 and throw.shape[1] == 3:
            throw = throw.squeeze(0)
        else:
            raise ValueError(
                f"throw_vector shape {throw.shape} must be (3,) or match the number of surface points ({N}, 3)"
            )

        # Calculate signed distance to the plane for each point
        # d = (P - P0) . n_unit
        vectors = pts_flat - plane_pt
        signed_dist = np.dot(vectors, unit_normal)

        displaced_flat = pts_flat.copy()
        pos_mask = signed_dist >= 0.0
        neg_mask = ~pos_mask

        if decay_distance is not None:
            if decay_distance <= 0:
                raise ValueError("decay_distance must be positive")

            abs_dist = np.abs(signed_dist)
            factors = np.zeros(N)
            in_range = abs_dist < decay_distance

            # Normalize distances inside the decay zone to [0, 1]
            normalized_dist = abs_dist[in_range] / decay_distance

            if decay_style == "linear":
                factors[in_range] = 1.0 - normalized_dist
            elif decay_style == "exponential":
                # Decays from 1 to 0 over normalized_dist [0, 1]
                factors[in_range] = (np.exp(3.0 * (1.0 - normalized_dist)) - 1.0) / (np.exp(3.0) - 1.0)
            elif decay_style == "gaussian":
                # Decays smoothly from 1 to 0
                factors[in_range] = (np.exp(-4.0 * normalized_dist**2) - np.exp(-4.0)) / (1.0 - np.exp(-4.0))
            else:
                raise ValueError(f"Unknown decay_style: {decay_style}")

            # Apply displacement using the decay factors
            if split_throw:
                pos_factors = factors * pos_mask
                neg_factors = factors * neg_mask
                if throw.shape == (3,):
                    displaced_flat += 0.5 * pos_factors[:, np.newaxis] * throw
                    displaced_flat -= 0.5 * neg_factors[:, np.newaxis] * throw
                else:
                    displaced_flat += 0.5 * pos_factors[:, np.newaxis] * throw
                    displaced_flat -= 0.5 * neg_factors[:, np.newaxis] * throw
            else:
                pos_factors = factors * pos_mask
                if throw.shape == (3,):
                    displaced_flat += pos_factors[:, np.newaxis] * throw
                else:
                    displaced_flat += pos_factors[:, np.newaxis] * throw
        else:
            # Rigid dislocation (sharp offset)
            if split_throw:
                if throw.shape == (3,):
                    displaced_flat[pos_mask] += 0.5 * throw
                    displaced_flat[neg_mask] -= 0.5 * throw
                else:
                    displaced_flat[pos_mask] += 0.5 * throw[pos_mask]
                    displaced_flat[neg_mask] -= 0.5 * throw[neg_mask]
            else:
                if throw.shape == (3,):
                    displaced_flat[pos_mask] += throw
                else:
                    displaced_flat[pos_mask] += throw[pos_mask]

        return displaced_flat.reshape(orig_shape)
