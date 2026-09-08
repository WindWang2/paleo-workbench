"""V8 M3 — unified factor sample normalization (duplicate policy authority)."""

from __future__ import annotations

import math

import pytest

from paleo_workbench.workflow.sample_normalization import (
    DEFAULT_DUPLICATE_POLICY,
    DUPLICATE_POLICIES,
    duplicate_policy_from_params,
    normalize_factor_samples,
)


TWIN_A = {"x": 1.0, "y": 2.0, "value": 10.0, "well_id": "w1"}
TWIN_B = {"x": 1.0, "y": 2.0, "value": 20.0, "well_id": "w2"}
OTHER = {"x": 3.0, "y": 4.0, "value": 30.0, "well_id": "w3"}


def test_mean_policy_merges_duplicates_to_mean():
    points, report = normalize_factor_samples([TWIN_A, TWIN_B, OTHER])
    assert len(points) == 2
    merged = next(p for p in points if (p["x"], p["y"]) == (1.0, 2.0))
    assert merged["z"] == pytest.approx(15.0)
    assert report.policy == "mean"
    assert report.n_duplicate_groups == 1
    assert report.n_duplicates_merged == 1
    assert report.duplicates_present


def test_first_policy_keeps_first_occurrence():
    points, report = normalize_factor_samples(
        [TWIN_A, TWIN_B, OTHER], policy="first"
    )
    merged = next(p for p in points if (p["x"], p["y"]) == (1.0, 2.0))
    assert merged["z"] == 10.0
    assert report.n_duplicates_merged == 1


def test_error_policy_refuses_duplicates():
    with pytest.raises(ValueError, match="duplicate sample locations"):
        normalize_factor_samples([TWIN_A, TWIN_B], policy="error")
    # no duplicates → error policy passes through untouched
    points, report = normalize_factor_samples([TWIN_A, OTHER], policy="error")
    assert len(points) == 2
    assert report.n_duplicate_groups == 0


def test_keep_policy_is_a_documented_noop():
    points, report = normalize_factor_samples([TWIN_A, TWIN_B], policy="keep")
    assert len(points) == 2
    assert report.n_duplicate_groups == 0
    assert report.n_duplicates_merged == 0


def test_nonfinite_samples_dropped_and_counted():
    bad = {"x": math.inf, "y": 0.0, "value": 1.0}
    nan_val = {"x": 0.0, "y": 0.0, "value": math.nan}
    points, report = normalize_factor_samples([bad, nan_val, OTHER])
    assert len(points) == 1
    assert report.n_nonfinite_dropped == 2


def test_qc_flag_visibility_and_worst_flag_wins():
    flagged = {**TWIN_A, "qc_flag": "suspect"}
    points, report = normalize_factor_samples([flagged, TWIN_B, OTHER])
    assert report.n_qc_flagged == 1
    merged = next(p for p in points if (p["x"], p["y"]) == (1.0, 2.0))
    assert merged.get("qc_flag") == "suspect"


def test_merged_well_identity_lists_members():
    points, _ = normalize_factor_samples([TWIN_A, TWIN_B, OTHER])
    merged = next(p for p in points if (p["x"], p["y"]) == (1.0, 2.0))
    assert merged.get("well_id") == "w1+w2"


def test_lng_lat_coordinates_supported():
    points, _ = normalize_factor_samples([{"lng": 5.0, "lat": 6.0, "z": 7.0}])
    assert points and points[0]["x"] == 5.0 and points[0]["z"] == 7.0


def test_unknown_policy_rejected():
    with pytest.raises(ValueError, match="unknown duplicate policy"):
        normalize_factor_samples([OTHER], policy="median")


def test_policy_from_params_defaults_honestly():
    assert duplicate_policy_from_params(None) == DEFAULT_DUPLICATE_POLICY
    assert duplicate_policy_from_params({}) == DEFAULT_DUPLICATE_POLICY
    assert duplicate_policy_from_params({"duplicate_policy": "error"}) == "error"
    # unknown value falls back to default rather than guessing
    assert duplicate_policy_from_params({"duplicate_policy": "median"}) == (
        DEFAULT_DUPLICATE_POLICY
    )
    assert DEFAULT_DUPLICATE_POLICY in DUPLICATE_POLICIES


def test_numeric_extras_averaged_for_directional_backends():
    a = {**TWIN_A, "q": 2.0, "b_i": 4.0}
    b = {**TWIN_B, "q": 4.0, "b_i": 8.0}
    points, _ = normalize_factor_samples([a, b, OTHER])
    merged = next(p for p in points if (p["x"], p["y"]) == (1.0, 2.0))
    assert merged["q"] == pytest.approx(3.0)
    assert merged["b_i"] == pytest.approx(6.0)
