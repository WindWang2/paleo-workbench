#!/usr/bin/env python3
"""Oracle for the CONV-09 DTW well-log matcher kernel (M8 first slice).

Imports the REAL paleo_workbench.viz.dtw_log_matcher (no hand-written
expectations) and freezes input/output pairs for the C++ port in
libs/well_science. Run with the project venv interpreter (needs the
paleo_workbench package import chain):

    /home/kevin/projects/paleo_project/main/.venv/bin/python \
        tools/oracle/generate_dtw_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.viz.dtw_log_matcher import (  # noqa: E402
    _MAX_COST_CELLS,
    DTWLogMatcher,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "well_science"
    / "well_science_tests"
    / "fixtures"
)

_MATCHER = DTWLogMatcher()


def _num(value: float):
    """JSON-safe float: JSON has no NaN/Infinity, so non-finite values are
    frozen as tagged strings ("inf"/"-inf"/"nan") — keeping NaN and ±inf
    distinguishable instead of collapsing them into one null."""
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values, dtype=np.float64).reshape(-1)]


def _norm_case(case_id: str, curve) -> dict:
    out = _MATCHER._normalized(np.asarray(curve, dtype=np.float64))
    return {"id": case_id, "kind": "normalized", "input": _nums(curve),
            "output": _nums(out)}


def _ds_case(case_id: str, curve, bin_size: int) -> dict:
    values, indices = _MATCHER._min_max_downsample(
        np.asarray(curve, dtype=np.float64), bin_size)
    return {"id": case_id, "kind": "downsample", "input": _nums(curve),
            "bin_size": bin_size, "values": _nums(values),
            "indices": [int(i) for i in indices]}


def _match_case(case_id: str, ref, target, window=None) -> dict:
    result = _MATCHER.match_curves(
        np.asarray(ref, dtype=np.float64),
        np.asarray(target, dtype=np.float64),
        window=window,
    )
    return {
        "id": case_id,
        "kind": "match",
        "ref": _nums(ref),
        "target": _nums(target),
        "window": window,
        "cost": _num(result.cost),
        "path_ref": [int(i) for i in result.path_ref],
        "path_target": [int(i) for i in result.path_target],
    }


def _transfer_case(case_id: str, ref_top_idx, path_ref, path_target) -> dict:
    return {
        "id": case_id,
        "kind": "transfer",
        "ref_top_idx": int(ref_top_idx),
        "path_ref": [int(i) for i in path_ref],
        "path_target": [int(i) for i in path_target],
        "expected": int(_MATCHER.transfer_top_index(
            ref_top_idx, list(path_ref), list(path_target))),
    }


def _thin_bed_curve(n: int = 4000, seed: int = 1054) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.linspace(0.0, 40.0 * np.pi, n)
    curve = 0.3 * np.sin(x) + rng.normal(0.0, 0.02, n)
    curve[1234] = 6.0
    curve[2600] = -5.0
    curve[2601] = -5.0
    return curve


def _expected_stride(n_ref: int, n_target: int) -> int:
    if n_ref * n_target <= _MAX_COST_CELLS:
        return 1
    scale = math.sqrt(float(n_ref * n_target) / float(_MAX_COST_CELLS))
    return max(2, int(math.ceil(scale * 2.0)))


def build_cases() -> list[dict]:
    cases: list[dict] = []

    # --- normalized --------------------------------------------------------
    rng = np.random.default_rng(101)
    basic = np.sin(np.linspace(0.0, 6.0 * np.pi, 64)) + rng.normal(0.0, 0.1, 64)
    cases.append(_norm_case("norm_basic", basic))

    with_nan = basic.copy()
    with_nan[5:12] = np.nan
    with_nan[30] = np.nan
    cases.append(_norm_case("norm_with_nan", with_nan))

    with_inf = basic.copy()
    with_inf[3] = np.inf
    with_inf[40:43] = -np.inf
    cases.append(_norm_case("norm_with_inf", with_inf))

    cases.append(_norm_case("norm_all_nan", [np.nan] * 8))
    cases.append(_norm_case("norm_empty", []))
    cases.append(_norm_case("norm_single", [7.5]))
    cases.append(_norm_case("norm_constant", [42.0] * 8))
    cases.append(_norm_case("norm_sign_overflow",
                            [1e308, -1e308, 1e308, -1e308]))
    cases.append(_norm_case("norm_mean_overflow", [1e308, 1e308]))
    cases.append(_norm_case("norm_large_offset",
                            1.0e6 + np.sin(np.linspace(0.0, 8.0, 40))))

    # --- min_max_downsample -------------------------------------------------
    small = [3.0, 1.0, 4.0, 1.5, 5.0, -2.0, 0.0, 2.5, 9.0, 9.0]
    cases.append(_ds_case("ds_identity_bin1", small, 1))
    cases.append(_ds_case("ds_identity_bin0", small, 0))
    cases.append(_ds_case("ds_empty", [], 3))
    cases.append(_ds_case("ds_min_first", small, 3))
    cases.append(_ds_case("ds_max_first", [1.0, 5.0, 2.0, -7.0, 0.5], 2))
    cases.append(_ds_case("ds_flat", [4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0], 3))
    cases.append(_ds_case("ds_partial_tail", small, 4))
    cases.append(_ds_case("ds_ties", [2.0, 2.0, 2.0, 2.0, 1.0, 1.0], 3))
    nan_curve = basic.copy()
    nan_curve[4:8] = np.nan  # NaN inside the first bins (first-NaN contract)
    cases.append(_ds_case("ds_nan_chunk", nan_curve, 4))

    # --- match_curves -------------------------------------------------------
    z = np.linspace(1000.0, 1100.0, 100)
    sin100 = np.sin(z * 0.1) * 20.0 + 50.0
    cases.append(_match_case("match_shifted_sin100", sin100, np.roll(sin100, 5)))
    cases.append(_match_case("match_identical_100", sin100, sin100.copy()))
    cases.append(_match_case("match_constant_vs_constant", [3.0] * 4, [3.0] * 4))
    cases.append(_match_case("match_constant_vs_shape", [5.0, 5.0, 5.0],
                             [1.0, 2.0, 3.0]))

    # E3 audit: LAS nulls must not poison the cost matrix (seed 11, 400 pts).
    rng11 = np.random.default_rng(11)
    base11 = np.sin(np.linspace(0.0, 12.0, 400))
    ref11 = base11 + rng11.normal(0.0, 0.05, 400)
    shifted11 = np.roll(base11, 40) + rng11.normal(0.0, 0.05, 400)
    ref_nulls = ref11.copy()
    ref_nulls[180:220] = np.nan
    target_nulls = shifted11.copy()
    target_nulls[100:130] = np.nan
    cases.append(_match_case("match_e3_nulls", ref_nulls, target_nulls))
    cases.append(_match_case("match_e3_clean", ref11, shifted11))

    rng12 = np.random.default_rng(12)
    sig200 = np.sin(np.linspace(0.0, 20.0, 200)) + rng12.normal(0.0, 0.1, 200)
    sig260 = np.sin(np.linspace(0.0, 26.0, 260)) + rng12.normal(0.0, 0.1, 260)
    cases.append(_match_case("match_unequal_lengths", sig200, sig260))
    cases.append(_match_case("match_window_refuse", sig200, sig260, window=20))
    cases.append(_match_case("match_unequal_lengths_nw", sig200, sig260,
                             window=None))

    rng14 = np.random.default_rng(14)
    sig150 = np.sin(np.linspace(0.0, 15.0, 150)) + rng14.normal(0.0, 0.1, 150)
    sig150b = np.roll(sig150, 4) + rng14.normal(0.0, 0.02, 150)
    cases.append(_match_case("match_window_ok", sig150, sig150b, window=5))
    cases.append(_match_case("match_window_boundary", sig150,
                             np.concatenate([sig150, [0.5, 0.4, 0.3, 0.2,
                                                      0.1, 0.0, -0.1, -0.2]]),
                             window=8))
    cases.append(_match_case("match_window_zero", sig150,
                             np.roll(sig150, 2), window=0))

    thin = _thin_bed_curve(4000)
    cases.append(_match_case("match_thinbed_4000", thin, thin.copy()))
    assert _expected_stride(4000, 4000) == 8

    rng42 = np.random.default_rng(42)
    n4k = 4000
    base42 = 0.4 * np.sin(np.linspace(0.0, 30.0 * np.pi, n4k)) + rng42.normal(
        0.0, 0.05, n4k)
    ref42 = base42.copy()
    ref42[1500] = 8.0
    ref42[2600] = -7.0
    target42 = base42.copy()
    target42[1620] = 8.0
    target42[2720] = -7.0
    cases.append(_match_case("match_spike_shift_4000", ref42, target42))

    long_sin = np.sin(np.linspace(0.0, 50.0, 20_000))
    cases.append(_match_case("match_long_sin_20k", long_sin, long_sin.copy()))
    assert _expected_stride(20_000, 20_000) == 40

    cases.append(_match_case("match_empty_ref", [], [1.0, 2.0, 3.0]))
    cases.append(_match_case("match_empty_target", [1.0, 2.0, 3.0], []))
    cases.append(_match_case("match_single_vs_single", [4.2], [4.2]))
    cases.append(_match_case("match_all_nan_curves", [np.nan] * 10,
                             [np.nan] * 12))
    cases.append(_match_case("match_ref_all_nan", [np.nan] * 10,
                             np.sin(np.linspace(0.0, 3.0, 10))))
    cases.append(_match_case("match_sign_overflow",
                             [1e308, -1e308] * 4, [1e308, 1e308, -1e308]))

    f32 = np.sin(np.linspace(0.0, 4.0 * np.pi, 100)).astype(np.float32)
    cases.append(_match_case("match_float32_input", f32, np.roll(f32, 5)))

    rng13 = np.random.default_rng(13)
    quant = np.sin(np.linspace(0.0, 12.0, 120)) + rng13.normal(0.0, 0.3, 120)
    quant_a = np.round(quant * 2.0) / 2.0  # 0.5 grid: many exact dist ties
    quant_b = np.round((np.roll(quant, 3)) * 2.0) / 2.0
    cases.append(_match_case("match_quantized_ties", quant_a, quant_b))

    depths = np.linspace(-80.0, -20.0, 80) + 0.1 * np.sin(
        np.linspace(0.0, 9.0, 80))
    cases.append(_match_case("match_negative_domain", depths,
                             np.roll(depths, 6)))

    cases.append(_match_case("match_tiny_2v3", [1.0, 2.0], [1.0, 2.0, 3.0]))
    long_tgt = np.sin(np.linspace(0.0, 8.0, 40))
    cases.append(_match_case("match_left_edge", [0.5, -0.5, 0.25], long_tgt))

    rng15 = np.random.default_rng(15)
    walk = np.cumsum(rng15.normal(0.0, 1.0, 600))
    cases.append(_match_case("match_random_walk_600", walk,
                             np.roll(walk, 17) + rng15.normal(0.0, 0.1, 600)))

    # --- transfer_top_index --------------------------------------------------
    cases.append(_transfer_case("tr_shift5", 30, list(range(100)),
                                [i + 5 for i in range(100)]))
    cases.append(_transfer_case("tr_empty_paths", 30, [], []))
    cases.append(_transfer_case("tr_empty_target", 30, [1, 2, 3], []))
    cases.append(_transfer_case("tr_ties", 30, [5, 5, 5], [7, 8, 9]))
    cases.append(_transfer_case("tr_nearest_nonmonotone", 25,
                                [10, 20, 30, 20], [100, 200, 300, 999]))
    cases.append(_transfer_case("tr_out_of_range", -5, [0, 10], [50, 60]))
    cases.append(_transfer_case("tr_short_zip", 4, [1, 2, 3], [10, 20]))

    return cases


def main() -> None:
    cases = build_cases()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "dtw_oracle.json"
    payload = {
        "max_cost_cells": int(_MAX_COST_CELLS),
        "cases": cases,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False),
                      encoding="utf-8")
    kinds: dict[str, int] = {}
    for case in cases:
        kinds[case["kind"]] = kinds.get(case["kind"], 0) + 1
    print(f"wrote {target} ({len(cases)} cases: {kinds})")


if __name__ == "__main__":
    main()
