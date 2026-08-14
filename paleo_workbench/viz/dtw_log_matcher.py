"""DTW matcher for automated well-to-well curve correlation."""

from dataclasses import dataclass
import math

import numpy as np

# Upper bound on cost-matrix cells before the curves are decimated. DTW is
# quadratic; two 100k-sample LAS preview curves would otherwise need ~75 GiB
# and freeze the host for minutes.
_MAX_COST_CELLS = 1_000_000


@dataclass
class AlignmentResult:
    """Typed alignment result from DTWLogMatcher."""

    cost: float
    path_ref: list[int]
    path_target: list[int]


class DTWLogMatcher:
    """Dynamic Time Warping (DTW) matcher for automated well-to-well curve correlation."""

    @staticmethod
    def _normalized(curve: np.ndarray) -> np.ndarray:
        """Z-normalize a curve, imputing LAS nulls (NaN/±inf) with the finite mean.

        Raw NaN samples poison ``std``/``mean`` (NaN is truthy, so the ``or 1.0``
        guard never engaged) and turn every DTW cost into NaN, which degrades
        the backtracked path to a degenerate transfer result. Imputation keeps
        every original sample index addressable; null intervals simply stop
        contributing shape information.
        """
        values = np.asarray(curve, dtype=np.float64).reshape(-1)
        finite = values[np.isfinite(values)]
        fill = float(finite.mean()) if finite.size else 0.0
        values = np.where(np.isfinite(values), values, fill)
        std = float(np.std(values))
        if not np.isfinite(std) or std <= 0.0:
            std = 1.0
        return (values - float(np.mean(values))) / std

    def match_curves(
        self,
        curve_ref: np.ndarray,
        curve_target: np.ndarray,
        window: int | None = None,
    ) -> AlignmentResult:
        """Compute optimal non-linear DTW alignment path between two log curves."""
        c_ref = self._normalized(curve_ref)
        c_target = self._normalized(curve_target)
        n_ref = c_ref.size
        n_target = c_target.size

        # Decimate over-long curves so the cost matrix stays bounded; path
        # indices are mapped back to original sample space below.
        stride = 1
        if n_ref * n_target > _MAX_COST_CELLS:
            stride = int(math.ceil(math.sqrt(n_ref * n_target / _MAX_COST_CELLS)))
        d_ref = c_ref[::stride]
        d_target = c_target[::stride]
        d_n_ref = d_ref.size
        d_n_target = d_target.size

        # Construct pairwise distance matrix
        cost_matrix = np.full((d_n_ref + 1, d_n_target + 1), fill_value=np.inf)
        cost_matrix[0, 0] = 0.0

        for i in range(1, d_n_ref + 1):
            for j in range(1, d_n_target + 1):
                if window is not None and abs(i - j) > window:
                    continue
                dist = (d_ref[i - 1] - d_target[j - 1]) ** 2
                cost_matrix[i, j] = dist + min(
                    cost_matrix[i - 1, j],      # Insertion
                    cost_matrix[i, j - 1],      # Deletion
                    cost_matrix[i - 1, j - 1],  # Match
                )

        # Backtrack optimal alignment path to (0, 0)
        i, j = d_n_ref, d_n_target
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

        if stride > 1:
            path_ref = [min(idx * stride, n_ref - 1) for idx in path_ref]
            path_target = [min(idx * stride, n_target - 1) for idx in path_target]

        return AlignmentResult(
            cost=float(cost_matrix[d_n_ref, d_n_target]),
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
