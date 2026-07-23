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
