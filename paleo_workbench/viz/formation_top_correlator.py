"""FormationTopCorrelator: Interactive multi-well formation top correlation and DTW recommendation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import warnings

import numpy as np

from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher


@dataclass
class TopRecommendation:
    """DTW automated formation top recommendation."""
    suggested_depth: float
    confidence: float
    dtw_cost: float


class FormationTopCorrelator:
    """Inter-well formation top correlation geometry generator and DTW auto-recommender."""

    def __init__(self, dtw_matcher: DTWLogMatcher | None = None):
        self.dtw_matcher = dtw_matcher or DTWLogMatcher()

    def compute_correlation_polygons(
        self,
        well_a: dict[str, Any],
        well_b: dict[str, Any],
        x_a: float,
        x_b: float,
        top_names: list[str],
        shifts: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Compute polygon quad coordinates for matching top intervals between two adjacent wells.

        Args:
            well_a: Dict containing well 'name' and 'tops'.
            well_b: Dict containing well 'name' and 'tops'.
            x_a: Horizontal X layout position of well A.
            x_b: Horizontal X layout position of well B.
            top_names: Ordered list of marker top names (e.g. ["H1", "H2", "H3"]).
            shifts: Optional dict mapping well name to vertical depth shift value.

        Returns:
            List of dicts with 'name', 'polygon' array (4, 2), and 'color'.
        """
        shift_a = (shifts or {}).get(well_a.get("name", ""), 0.0)
        shift_b = (shifts or {}).get(well_b.get("name", ""), 0.0)

        tops_a = {t.get("name"): float(t.get("depth", 0.0)) + shift_a for t in well_a.get("tops", [])}
        tops_b = {t.get("name"): float(t.get("depth", 0.0)) + shift_b for t in well_b.get("tops", [])}

        polygons: list[dict[str, Any]] = []

        for i in range(len(top_names) - 1):
            t_curr = top_names[i]
            t_next = top_names[i + 1]

            if t_curr in tops_a and t_next in tops_a and t_curr in tops_b and t_next in tops_b:
                y1_a = tops_a[t_curr]
                y2_a = tops_a[t_next]
                y1_b = tops_b[t_curr]
                y2_b = tops_b[t_next]

                quad = np.array([
                    [x_a, y1_a],
                    [x_b, y1_b],
                    [x_b, y2_b],
                    [x_a, y2_a],
                ], dtype=np.float32)

                polygons.append({
                    "name": f"{t_curr}-{t_next}",
                    "polygon": quad,
                    "color": (0.3, 0.6, 0.9, 0.4),
                })

        return polygons

    def recommend_top_depth(
        self,
        ref_curve: np.ndarray,
        target_curve: np.ndarray,
        ref_top_depth: float,
        start_depth: float | None = None,
        depth_step: float | None = None,
        ref_depths: np.ndarray | None = None,
        target_depths: np.ndarray | None = None,
    ) -> TopRecommendation:
        """Use DTW curve alignment to recommend corresponding marker top depth in target well.

        The depth mapping comes from the curves' own depth axes when
        ``ref_depths``/``target_depths`` are provided; explicit
        ``start_depth``/``depth_step`` override them. Only when no depth
        information is given does the legacy uniform 0.0/0.5 grid apply.
        """
        if len(ref_curve) == 0 or len(target_curve) == 0:
            return TopRecommendation(suggested_depth=ref_top_depth, confidence=0.0, dtw_cost=999.0)

        ref_is_descending = False
        if start_depth is None and ref_depths is not None and len(ref_depths) == len(ref_curve):
            depths = np.asarray(ref_depths, dtype=float)
            if len(ref_depths) > 1:
                step = float(np.median(np.diff(depths)))
                if step > 0.0:
                    if depth_step is None:
                        depth_step = step
                    start_depth = float(depths[0])
                elif step < 0.0:
                    # Descending depth axis (deepest-first LAS files): index
                    # the reference grid from the shallowest sample and flip
                    # the computed index back into file order below.
                    if depth_step is None:
                        depth_step = -step
                    start_depth = float(depths[-1])
                    ref_is_descending = True
        if start_depth is None:
            start_depth = 0.0
        if depth_step is None or depth_step <= 0.0:
            depth_step = 0.5
            if ref_depths is not None:
                warnings.warn(
                    "ref_depths 无法用于单调深度网格（非单调或长度与曲线不一致），"
                    "已回退到均匀 0.5 网格",
                    UserWarning,
                    stacklevel=2,
                )

        # Convert ref_top_depth to index
        ref_idx = int(np.clip((ref_top_depth - start_depth) / depth_step, 0, len(ref_curve) - 1))
        if ref_is_descending:
            ref_idx = len(ref_curve) - 1 - ref_idx

        alignment = self.dtw_matcher.match_curves(ref_curve, target_curve)
        target_idx = self.dtw_matcher.transfer_top_index(ref_idx, alignment.path_ref, alignment.path_target)

        if target_depths is not None and len(target_depths) == len(target_curve):
            # Real LAS depth axis: map the warped index back to measured depth.
            target_idx = int(np.clip(target_idx, 0, len(target_depths) - 1))
            suggested_depth = float(np.asarray(target_depths, dtype=float)[target_idx])
        else:
            suggested_depth = start_depth + target_idx * depth_step
        # Normalize by the number of cost cells actually accumulated: the
        # matcher decimates over-long curves, and the returned cost is summed
        # over the decimated path — normalizing by the full input length
        # inflated confidence on decimated inputs (C40).
        cell_count = max(1, len(alignment.path_ref))
        confidence = float(np.exp(-alignment.cost / (cell_count * 2.0)))

        return TopRecommendation(
            suggested_depth=float(suggested_depth),
            confidence=min(1.0, max(0.0, confidence)),
            dtw_cost=alignment.cost,
        )
