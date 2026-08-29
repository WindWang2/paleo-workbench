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
        """Z-normalize a curve, imputing LAS nulls (NaN/±inf) with the finite mean."""
        values = np.asarray(curve, dtype=np.float64).reshape(-1)
        if values.size == 0:
            return values
        finite = values[np.isfinite(values)]
        fill = float(finite.mean()) if finite.size else 0.0
        values = np.where(np.isfinite(values), values, fill)
        std = float(np.std(values))
        if not np.isfinite(std) or std <= 0.0:
            std = 1.0
        return (values - float(np.mean(values))) / std

    @staticmethod
    def _min_max_downsample(
        curve: np.ndarray, bin_size: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Min-max peak-preserving downsampling of a 1-D curve (#1054).

        Each ``bin_size``-sample segment contributes its minimum sample and
        its maximum sample, ordered by original index, so the segment's global
        extrema can never be dropped.  Uniform striding (``curve[::stride]``)
        silently deleted 1-2 sample thin-bed spikes and left DTW correlating
        decimated curves without their most distinctive markers.

        Returns:
            (downsampled_values, original_indices) where ``original_indices``
            is strictly increasing and maps each kept sample back to its
            position in the input curve.
        """
        n = curve.size
        if n == 0 or bin_size <= 1:
            return curve, np.arange(n, dtype=np.int64)

        downsampled_vals: list[float] = []
        orig_indices: list[int] = []

        for start in range(0, n, bin_size):
            end = min(start + bin_size, n)
            chunk = curve[start:end]
            min_rel = int(np.argmin(chunk))
            max_rel = int(np.argmax(chunk))
            min_idx = start + min_rel
            max_idx = start + max_rel

            if min_idx < max_idx:
                downsampled_vals.append(float(chunk[min_rel]))
                orig_indices.append(min_idx)
                downsampled_vals.append(float(chunk[max_rel]))
                orig_indices.append(max_idx)
            elif max_idx < min_idx:
                downsampled_vals.append(float(chunk[max_rel]))
                orig_indices.append(max_idx)
                downsampled_vals.append(float(chunk[min_rel]))
                orig_indices.append(min_idx)
            else:
                # Flat segment: minimum and maximum coincide.
                downsampled_vals.append(float(chunk[min_rel]))
                orig_indices.append(min_idx)

        return (
            np.asarray(downsampled_vals, dtype=np.float64),
            np.asarray(orig_indices, dtype=np.int64),
        )

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

        # Guard against empty / degenerate curves
        if n_ref == 0 or n_target == 0:
            return AlignmentResult(cost=float("inf"), path_ref=[], path_target=[])

        # Decimate over-long curves with min-max peak-preserving downsampling
        # so the cost matrix stays bounded while thin-bed extrema survive;
        # path indices are mapped back to original sample space below (#1054).
        # Each segment keeps up to two samples, hence the 2x scale factor.
        stride = 1
        if _MAX_COST_CELLS > 0 and n_ref * n_target > _MAX_COST_CELLS:
            scale = math.sqrt(float(n_ref * n_target) / float(_MAX_COST_CELLS))
            stride = max(2, int(math.ceil(scale * 2.0)))
        if stride > 1:
            d_ref, ref_indices = self._min_max_downsample(c_ref, stride)
            d_target, target_indices = self._min_max_downsample(c_target, stride)
            # The kept extrema redistribute the value statistics; renormalize
            # so both decimated sequences stay comparable.
            d_ref = self._normalized(d_ref)
            d_target = self._normalized(d_target)
        else:
            d_ref, ref_indices = c_ref, np.arange(n_ref, dtype=np.int64)
            d_target, target_indices = c_target, np.arange(n_target, dtype=np.int64)
        d_n_ref = d_ref.size
        d_n_target = d_target.size

        if d_n_ref == 0 or d_n_target == 0:
            return AlignmentResult(cost=float("inf"), path_ref=[], path_target=[])

        # Construct pairwise distance matrix
        cost_matrix = np.full((d_n_ref + 1, d_n_target + 1), fill_value=np.inf)
        cost_matrix[0, 0] = 0.0

        # A Sakoe-Chiba band of width `window` makes the DP endpoint
        # unreachable when the length difference exceeds the band; the old
        # backtracker then walked through inf cells and fabricated a
        # monotone path (transfer_top_index returned meaningless indices).
        # Return an empty alignment instead (#897).
        if window is not None and abs(d_n_ref - d_n_target) > window:
            return AlignmentResult(cost=float("inf"), path_ref=[], path_target=[])

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

        # Map the warping path from decimated sample space back to original
        # curve indices. ``ref_indices``/``target_indices`` are strictly
        # increasing, so the mapped path stays monotone in original space.
        if stride > 1:
            path_ref = [int(ref_indices[idx]) for idx in path_ref]
            path_target = [int(target_indices[idx]) for idx in path_target]

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
