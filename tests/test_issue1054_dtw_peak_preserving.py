"""#1054: DTW decimation must preserve thin-bed extrema (min-max downsampling).

The previous uniform ``curve[::stride]`` decimation deleted 1-2 sample spikes
and mapped warping indices back with ``idx * stride`` quantization.  These
tests pin the peak-preserving contract:

- every significant local extremum of the original curve survives
  downsampling within one stride window;
- DTW alignment of a spike shifted by ``δ`` (< 10% of curve length) maps it
  back with error < stride, through the full ``match_curves`` pipeline;
- the cost-matrix bound (``_MAX_COST_CELLS``) semantics still hold;
- long curves still complete in seconds.

All tests run the real production path (``DTWLogMatcher.match_curves`` /
``_min_max_downsample``) on synthetic thin-bed fixtures — no mocks.
"""

from __future__ import annotations

import math
import time

import numpy as np

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.dtw_log_matcher import (
    _MAX_COST_CELLS,
    AlignmentResult,
    DTWLogMatcher,
)


def _expected_stride(n_ref: int, n_target: int) -> int:
    """Mirror of the module's decimation choice (kept explicit in tests)."""
    if n_ref * n_target <= _MAX_COST_CELLS:
        return 1
    scale = math.sqrt(float(n_ref * n_target) / float(_MAX_COST_CELLS))
    return max(2, int(math.ceil(scale * 2.0)))


def _thin_bed_curve(n: int = 4000, seed: int = 1054) -> np.ndarray:
    """Long synthetic log with 1-2 sample wide thin-bed spikes.

    Spikes (all interior):
        index 1234      - single-sample high spike (+6 sigma baseline)
        index 2600/2601 - two-sample low spike   (-5)
    """
    rng = np.random.default_rng(seed)
    x = np.linspace(0.0, 40.0 * np.pi, n)
    curve = 0.3 * np.sin(x) + rng.normal(0.0, 0.02, n)
    curve[1234] = 6.0
    curve[2600] = -5.0
    curve[2601] = -5.0
    return curve


def _significant_local_extrema(curve: np.ndarray, factor: float = 1.5):
    """Indices of local maxima/minima standing out by ``factor`` sigma."""
    mean, std = float(curve.mean()), float(curve.std())
    highs, lows = [], []
    for i in range(1, curve.size - 1):
        if curve[i] >= curve[i - 1] and curve[i] >= curve[i + 1]:
            if curve[i] > mean + factor * std:
                highs.append(i)
        if curve[i] <= curve[i - 1] and curve[i] <= curve[i + 1]:
            if curve[i] < mean - factor * std:
                lows.append(i)
    return highs, lows


# --- peak preservation of the downsampler ---------------------------------


def test_min_max_downsample_keeps_thin_bed_spikes():
    curve = _thin_bed_curve(4000)
    stride = _expected_stride(4000, 4000)
    assert stride > 1, "fixture must be long enough to trigger decimation"

    values, indices = DTWLogMatcher._min_max_downsample(curve, stride)

    # Contract: kept samples are exact original samples, index-ordered.
    assert indices.dtype == np.int64
    assert np.all(np.diff(indices) > 0), "indices must be strictly increasing"
    assert values.size == indices.size
    assert np.array_equal(values, curve[indices])
    # At most two representatives per stride segment.
    assert values.size <= 2 * math.ceil(curve.size / stride)

    # The 1-sample high spike and 2-sample low spike both survive verbatim.
    assert 1234 in set(indices.tolist())
    assert 2600 in set(indices.tolist())
    assert float(curve[1234]) == float(values.max())
    assert float(curve[2600]) == float(values.min())


def test_min_max_downsample_preserves_significant_extrema_set():
    """Every significant local extremum of the original curve must have a
    kept sample at least as extreme within one stride window."""
    curve = _thin_bed_curve(4000)
    stride = _expected_stride(4000, 4000)
    _values, indices = DTWLogMatcher._min_max_downsample(curve, stride)
    kept = indices.astype(np.int64)

    highs, lows = _significant_local_extrema(curve)
    assert highs and lows, "fixture must contain significant extrema"

    for i in highs:
        window = kept[np.abs(kept - i) < stride]
        assert window.size > 0, f"high extremum at {i} lost its window"
        assert curve[window].max() >= curve[i] - 1e-12

    for i in lows:
        window = kept[np.abs(kept - i) < stride]
        assert window.size > 0, f"low extremum at {i} lost its window"
        assert curve[window].min() <= curve[i] + 1e-12


# --- full-pipeline alignment quality ---------------------------------------


def test_shifted_thin_bed_spike_aligns_within_stride():
    """Reference spike at p, target spike at p+δ (δ < 10% length): the DTW
    path (in ORIGINAL index space) must align them within one stride."""
    n = 4000
    stride = _expected_stride(n, n)
    delta = 120  # 3% of curve length, well below the 10% budget
    p = 1500

    rng = np.random.default_rng(42)
    base = 0.4 * np.sin(np.linspace(0.0, 30.0 * np.pi, n)) + rng.normal(
        0.0, 0.05, n
    )
    ref = base.copy()
    ref[p] = 8.0  # single-sample spike
    ref[2600] = -7.0  # second (single-sample, low) thin bed
    target = base.copy()
    target[p + delta] = 8.0
    target[2600 + delta] = -7.0

    matcher = DTWLogMatcher()
    result = matcher.match_curves(ref, target)

    assert isinstance(result, AlignmentResult)
    assert np.isfinite(result.cost)
    assert len(result.path_ref) == len(result.path_target) > 0
    # Paths live in original index space and stay monotone.
    assert 0 <= min(result.path_ref) and max(result.path_ref) <= n - 1
    assert 0 <= min(result.path_target) and max(result.path_target) <= n - 1
    assert all(
        a <= b for a, b in zip(result.path_ref, result.path_ref[1:])
    )

    # Nearest path pair to the reference spike maps onto the target spike.
    pair = min(
        range(len(result.path_ref)),
        key=lambda k: abs(result.path_ref[k] - p),
    )
    error = abs(result.path_target[pair] - (p + delta))
    assert error < stride, f"spike alignment error {error} >= stride {stride}"

    pair2 = min(
        range(len(result.path_ref)),
        key=lambda k: abs(result.path_ref[k] - 2600),
    )
    error2 = abs(result.path_target[pair2] - (2600 + delta))
    assert error2 < stride, f"second spike alignment error {error2} >= stride"

    # transfer_top_index (public API) transfers through the mapped path.
    transferred = matcher.transfer_top_index(
        p, result.path_ref, result.path_target
    )
    assert abs(transferred - (p + delta)) < stride


def test_identical_long_curves_align_on_diagonal_in_original_space():
    n = 4000
    curve = _thin_bed_curve(n)
    result = DTWLogMatcher().match_curves(curve, curve.copy())
    assert np.isfinite(result.cost)
    assert result.path_ref and result.path_target
    # Identical curves downsample identically: exact diagonal mapping.
    assert result.path_ref == result.path_target


# --- cost bound + runtime sanity -------------------------------------------


def test_decimated_cost_matrix_stays_bounded_and_fast():
    n = 20_000  # naive matrix would be 400M cells (~3 GiB)
    x = np.linspace(0.0, 50.0, n)
    curve = np.sin(x)
    stride = _expected_stride(n, n)

    values, _indices = DTWLogMatcher._min_max_downsample(curve, stride)
    assert values.size * values.size <= _MAX_COST_CELLS

    start = time.perf_counter()
    result = DTWLogMatcher().match_curves(curve, curve.copy())
    elapsed = time.perf_counter() - start

    assert np.isfinite(result.cost)
    assert elapsed < 10.0, f"long-curve match took {elapsed:.1f}s"
    assert max(result.path_ref) <= n - 1
    assert max(result.path_target) <= n - 1
    assert all(
        abs(r - t) <= stride for r, t in zip(result.path_ref, result.path_target)
    )


def test_short_curves_bypass_decimation_unchanged():
    """Below the cost bound the previous behaviour (identity path space)
    must be preserved: public API contract unchanged."""
    z = np.linspace(1000.0, 1100.0, 100)
    curve_ref = np.sin(z * 0.1) * 20.0 + 50.0
    curve_target = np.roll(curve_ref, 5)

    result = DTWLogMatcher().match_curves(curve_ref, curve_target)

    assert result.cost >= 0.0
    assert len(result.path_ref) == len(result.path_target) > 0
    assert max(result.path_ref) <= curve_ref.size - 1
    assert max(result.path_target) <= curve_target.size - 1
