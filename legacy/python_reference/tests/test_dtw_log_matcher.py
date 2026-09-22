"""Unit tests for DTWLogMatcher automated curve correlation engine (Ticket 03)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher


def test_dtw_log_matcher_aligns_shifted_curves():
    # Generate reference synthetic curve (e.g. GR)
    z = np.linspace(1000.0, 1100.0, 100)
    curve_ref = np.sin(z * 0.1) * 20.0 + 50.0

    # Target curve shifted downwards by 5 samples
    curve_target = np.roll(curve_ref, 5)

    matcher = DTWLogMatcher()
    alignment = matcher.match_curves(curve_ref, curve_target)

    assert alignment.cost >= 0.0
    assert len(alignment.path_ref) == len(alignment.path_target)
    assert len(alignment.path_ref) > 0


def test_dtw_log_matcher_suggests_top_pick():
    matcher = DTWLogMatcher()
    # Reference well top at depth index 30
    ref_top_idx = 30
    path_ref = list(range(100))
    path_target = [idx + 5 for idx in range(100)]  # 5 index shift

    target_top_idx = matcher.transfer_top_index(ref_top_idx, path_ref, path_target)
    assert target_top_idx == 35


def test_dtw_survives_null_samples_and_transfers_meaningful_top():
    """Audit E3: LAS nulls (NaN) must not poison the DTW cost matrix.

    Previously NaN propagated through std/mean into every cost; the backtrack
    degraded to a degenerate path and transfer_top_index returned index 0
    (recommended top at curve start) regardless of the true shift.
    """
    from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher

    rng = np.random.default_rng(11)
    base = np.sin(np.linspace(0.0, 12.0, 400))
    ref = base + rng.normal(0.0, 0.05, 400)
    shifted = np.roll(base, 40) + rng.normal(0.0, 0.05, 400)
    # Inject LAS nulls into the middle of both curves.
    ref_nulls = ref.copy()
    ref_nulls[180:220] = np.nan
    target_nulls = shifted.copy()
    target_nulls[100:130] = np.nan

    matcher = DTWLogMatcher()
    result = matcher.match_curves(ref_nulls, target_nulls)
    assert np.isfinite(result.cost)
    assert result.path_ref and result.path_target

    clean = matcher.match_curves(ref, shifted)
    transferred_with_nulls = matcher.transfer_top_index(
        200, result.path_ref, result.path_target
    )
    transferred_clean = matcher.transfer_top_index(
        200, clean.path_ref, clean.path_target
    )
    # With nulls imputed, the recommended transfer must stay near the clean
    # alignment instead of collapsing to index 0.
    assert abs(transferred_with_nulls - transferred_clean) <= 12
    assert transferred_with_nulls > 0


def test_dtw_bounds_cost_matrix_for_long_curves():
    """Audit E8: very long curves are decimated instead of allocating GBs."""
    from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher, _MAX_COST_CELLS

    n = 20_000  # naive matrix = 400M cells (~3 GiB float64)
    x = np.linspace(0.0, 50.0, n)
    curve = np.sin(x)

    matcher = DTWLogMatcher()
    result = matcher.match_curves(curve, curve.copy())

    assert np.isfinite(result.cost)
    assert max(result.path_ref) <= n - 1
    assert max(result.path_target) <= n - 1
    # Identical curves align near the diagonal.
    assert all(
        abs(r - t) <= 40 for r, t in zip(result.path_ref, result.path_target)
    )
    assert _MAX_COST_CELLS == 1_000_000
