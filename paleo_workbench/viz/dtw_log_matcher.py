from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class AlignmentResult:
    """Typed alignment result from DTWLogMatcher."""

    cost: float
    path_ref: list[int]
    path_target: list[int]


class DTWLogMatcher:
    """Dynamic Time Warping (DTW) matcher for automated well-to-well curve correlation."""

    def match_curves(
        self,
        curve_ref: np.ndarray,
        curve_target: np.ndarray,
        window: int | None = None,
    ) -> AlignmentResult:
        """Compute optimal non-linear DTW alignment path between two log curves."""
        n_ref = len(curve_ref)
        n_target = len(curve_target)

        # Normalize input curves to zero mean unit variance for robust matching
        std_ref = float(np.std(curve_ref)) or 1.0
        std_target = float(np.std(curve_target)) or 1.0

        c_ref = (curve_ref - np.mean(curve_ref)) / std_ref
        c_target = (curve_target - np.mean(curve_target)) / std_target

        # Construct pairwise distance matrix
        cost_matrix = np.full((n_ref + 1, n_target + 1), fill_value=np.inf)
        cost_matrix[0, 0] = 0.0

        for i in range(1, n_ref + 1):
            for j in range(1, n_target + 1):
                if window is not None and abs(i - j) > window:
                    continue
                dist = (c_ref[i - 1] - c_target[j - 1]) ** 2
                cost_matrix[i, j] = dist + min(
                    cost_matrix[i - 1, j],      # Insertion
                    cost_matrix[i, j - 1],      # Deletion
                    cost_matrix[i - 1, j - 1],  # Match
                )

        # Backtrack optimal alignment path to (0, 0)
        i, j = n_ref, n_target
        path_ref: list[int] = []
        path_target: list[int] = []

        while i > 0 or j > 0:
            if i > 0 and j > 0:
                path_ref.append(i - 1)
                path_target.append(j - 1)
                min_val = min(cost_matrix[i - 1, j], cost_matrix[i, j - 1], cost_matrix[i - 1, j - 1])
                if min_val == cost_matrix[i - 1, j - 1]:
                    i -= 1
                    j -= 1
                elif min_val == cost_matrix[i - 1, j]:
                    i -= 1
                else:
                    j -= 1
            elif i > 0:
                path_ref.append(i - 1)
                path_target.append(0)
                i -= 1
            else:
                path_ref.append(0)
                path_target.append(j - 1)
                j -= 1

        path_ref.reverse()
        path_target.reverse()

        return AlignmentResult(
            cost=float(cost_matrix[n_ref, n_target]),
            path_ref=path_ref,
            path_target=path_target,
        )

    def transfer_top_index(
        self,
        ref_top_idx: int,
        path_ref: list[int],
        path_target: list[int],
    ) -> int:
        """Transfer a formation top depth index from reference well to target well using DTW path."""
        if not path_ref or not path_target:
            return ref_top_idx

        best_idx = 0
        min_dist = float("inf")

        for idx, (r, t) in enumerate(zip(path_ref, path_target)):
            dist = abs(r - ref_top_idx)
            if dist < min_dist:
                min_dist = dist
                best_idx = t

        return best_idx
