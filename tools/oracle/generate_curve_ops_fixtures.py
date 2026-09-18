#!/usr/bin/env python3
"""Oracle fixture generator for the C++ well curve-ops kernels (CONV-11).

Imports the REAL implementations (paleo_workbench.workflow.curve_operations,
.well_science and the pure kernels of .curve_interpretation) and freezes
their outputs to JSON so the C++ port in libs/well_science can be verified
value-exactly. Every expected value is computed from the live modules —
nothing is hand-written. Regenerate with:

    /home/kevin/project/oracle-venvs/conv11/bin/python \
        tools/oracle/generate_curve_ops_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.workflow import curve_operations as co  # noqa: E402
from paleo_workbench.workflow import curve_interpretation as ci  # noqa: E402
from paleo_workbench.workflow import well_science as ws  # noqa: E402

OUT = REPO_ROOT / "libs" / "well_science" / "well_science_tests" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

NAN = float("nan")
INF = float("inf")


def jarr(a) -> list:
    """numpy array → JSON list with NaN/inf → null / strings."""
    out = []
    for v in np.asarray(a, dtype=float).ravel().tolist():
        if math.isnan(v):
            out.append(None)
        elif math.isinf(v):
            out.append("Infinity" if v > 0 else "-Infinity")
        else:
            out.append(v)
    return out


def jval(v) -> object:
    if v is None:
        return None
    v = float(v)
    if math.isnan(v):
        return None
    if math.isinf(v):
        return "Infinity" if v > 0 else "-Infinity"
    return v


def err(exc: BaseException, mode: str = "exact") -> dict:
    return {"raises": True, "message": str(exc), "match_mode": mode}


rng = np.random.default_rng(20260917)

fixtures: dict = {"meta": {
    "task": "CONV-11 well curve ops",
    "python": sys.version.split()[0],
    "numpy": np.__version__,
}}

# ---------------------------------------------------------------------------
# moving_average
# ---------------------------------------------------------------------------
cases = []
cases.append({"name": "pytest:test_moving_average_is_nan_aware",
              "values": [1, 2, 3, None, 5, 6], "window": 3})
cases.append({"name": "window5_default_smooth", "values": [1, 2, 3, 4, 5, 6, 7], "window": 5})
cases.append({"name": "even_window4", "values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], "window": 4})
cases.append({"name": "pytest:test_moving_average_window_wider_than_curve",
              "values": list(range(10)), "window": 101})
cases.append({"name": "window1_identity", "values": [1, None, 3], "window": 1})
cases.append({"name": "window0_clamped_to_1", "values": [1, 2, 3], "window": 0})
cases.append({"name": "negative_window_clamped", "values": [1, 2, 3], "window": -5})
cases.append({"name": "empty", "values": [], "window": 3})
cases.append({"name": "all_nan", "values": [None, None, None], "window": 3})
cases.append({"name": "inf_rides_as_nonfinite",
              "values": [1, 2, "Infinity", 4, 5], "window": 3})
cases.append({"name": "single_sample", "values": [7], "window": 5})
for c in cases:
    arr = np.array([NAN if v is None else (INF if v == "Infinity" else float(v))
                    for v in c["values"]], dtype=float)
    c["expected"] = jarr(co.moving_average(arr, window=c["window"]))
fixtures["moving_average"] = cases

# ---------------------------------------------------------------------------
# median_filter_curve
# ---------------------------------------------------------------------------
cases = [
    {"name": "pytest:test_median_filter_preserves_nan_positions",
     "values": [10, 10, 10, 500, 10, None, 10], "window": 3},
    {"name": "window5_spike", "values": [1, 1, 9, 1, 1, 1, 1], "window": 5},
    {"name": "even_window_becomes_5", "values": [1, 2, 3, 900, 5], "window": 4},
    {"name": "window1_identity", "values": [3, 1, 2], "window": 1},
    {"name": "negative_window", "values": [3, 1, 2], "window": -7},
    {"name": "empty", "values": [], "window": 3},
    {"name": "all_nan", "values": [None, None], "window": 3},
    {"name": "nan_gap_neighbors_medians", "values": [1, 2, None, 4, 900], "window": 3},
    {"name": "single_sample", "values": [42], "window": 5},
]
for c in cases:
    arr = np.array([NAN if v is None else float(v) for v in c["values"]], dtype=float)
    c["expected"] = jarr(co.median_filter_curve(arr, window=c["window"]))
fixtures["median_filter"] = cases

# ---------------------------------------------------------------------------
# normalize_curve
# ---------------------------------------------------------------------------
v = np.array([1.0, 2.0, 3.0, 4.0, NAN])
cases = [
    {"name": "pytest:test_normalize_zscore_z", "values": jarr(v), "method": "zscore"},
    {"name": "pytest:test_normalize_zscore_m", "values": jarr(v), "method": "minmax"},
    {"name": "constant_zscore_zeros", "values": [5, 5, 5, None], "method": "zscore"},
    {"name": "constant_minmax_half", "values": [5, 5, 5, None], "method": "minmax"},
    {"name": "single_finite_zscore", "values": [None, 7], "method": "zscore"},
    {"name": "single_finite_minmax", "values": [None, 7], "method": "minmax"},
    {"name": "all_nan", "values": [None, None], "method": "zscore"},
    {"name": "empty", "values": [], "method": "zscore"},
    {"name": "with_inf_excluded_from_stats", "values": [1, 2, "Infinity", 4], "method": "minmax"},
]
for c in cases:
    arr = np.array([NAN if x is None else (INF if x == "Infinity" else float(x))
                    for x in c["values"]], dtype=float)
    c["expected"] = jarr(co.normalize_curve(arr, method=c["method"]))
try:
    co.normalize_curve(v, method="magic")
    raise AssertionError("expected ValueError")
except ValueError as exc:
    fixtures["normalize_curve"] = cases + [
        {"name": "pytest:unknown_method", "values": jarr(v), "method": "magic",
         **err(exc)}]

# ---------------------------------------------------------------------------
# clip_outliers
# ---------------------------------------------------------------------------
cases = []
base = np.arange(100, dtype=float)
base[50] = 1e6
cases.append({"name": "pytest:percentile5", "values": jarr(base), "percentile": 5.0})
cases.append({"name": "pytest:bounds", "values": [-5, 0, 5], "lower": 0.0, "upper": 1.0})
cases.append({"name": "lower_only", "values": [-5, 0, 5], "lower": 0.0})
cases.append({"name": "upper_only", "values": [-5, 0, 5], "upper": 0.0})
cases.append({"name": "nan_survives", "values": [-5, None, 5], "lower": 0.0, "upper": 3.0})
cases.append({"name": "percentile_with_nan", "values": jarr(base[:30]) + [None], "percentile": 10.0})
cases.append({"name": "all_nan_returns_unchanged", "values": [None, None], "lower": None, "upper": None})
cases.append({"name": "small_array_percentile", "values": [1.0], "percentile": 25.0})
cases.append({"name": "percentile_extremes", "values": [3, 1, 4, 1, 5, 9, 2, 6], "percentile": 49.999})
for c in cases:
    arr = np.array([NAN if x is None else float(x) for x in c["values"]], dtype=float)
    out = co.clip_outliers(
        arr,
        lower=c.get("lower"), upper=c.get("upper"), percentile=c.get("percentile"))
    c["expected"] = jarr(out)

error_cases = []
for name, kwargs, values in [
    ("pytest:no_bounds", {}, [1.0]),
    ("percentile_zero", {"percentile": 0.0}, base),
    ("percentile_fifty", {"percentile": 50.0}, base),
    ("percentile_negative", {"percentile": -5.0}, base),
    ("percentile_over_fifty", {"percentile": 50.5}, base),
]:
    try:
        co.clip_outliers(np.asarray(values, dtype=float), **kwargs)
        raise AssertionError(f"expected ValueError for {name}")
    except ValueError as exc:
        error_cases.append({"name": name, "values": jarr(np.asarray(values, dtype=float)),
                            **{k: w for k, w in kwargs.items()}, **err(exc)})
fixtures["clip_outliers"] = cases + error_cases

# ---------------------------------------------------------------------------
# units: normalize_unit_name / conversion_factor / convert_values
# ---------------------------------------------------------------------------
unit_cases = []
probe_tokens = [
    "m", "M", "meter", "METER", "meters", "metre", "METRES", "ft", "FT", "feet",
    "FOOT", "f", "F", "g/cc", "G/CC", "g/cm3", "g/cm³", "gm/cc", "kg/m3", "KG/M3",
    "kg/m³", "us/m", "µs/m", "US/FT", "µs/ft", "mm", "MM", "in", "inch", "INCHES",
    "mv", "MV", "millivolt", "v", "VOLT", "ohmm", "ohm.m", "ohmm.m", "ohm-m",
    "%", "pct", "v/v", "api", "API", "  m  ", "FURLONGS", "blorts", "",
]
for token in probe_tokens:
    unit_cases.append({"name": f"token:{token!r}", "token": token,
                       "expected": co.normalize_unit_name(token)})
unit_cases.append({"name": "token:None", "token": None,
                   "expected": co.normalize_unit_name(None)})
fixtures["normalize_unit_name"] = unit_cases

factor_cases = []
pairs = [
    ("m", "ft"), ("ft", "m"), ("g/cc", "kg/m3"), ("kg/m3", "g/cc"),
    ("us/m", "us/ft"), ("us/ft", "us/m"), ("mm", "in"), ("in", "mm"),
    ("mv", "v"), ("v", "mv"), ("%", "v/v"), ("pct", "v/v"),
    ("m", "m"), ("METER", "m"), ("g/cm3", "g/cc"), ("f", "ft"), ("%", "pct"),
    ("ohm-m", "ohm.m"), ("m", "M"), ("us/m", "us/m"),
]
for src, dst in pairs:
    factor_cases.append({"name": f"{src}->{dst}", "from": src, "to": dst,
                         "expected": co.conversion_factor(src, dst)})
for src, dst in [("api", "m"), ("m", "g/cc"), ("mm", "mv"), ("percent", "api"),
                 ("g/cc", "us/m")]:
    try:
        co.conversion_factor(src, dst)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        factor_cases.append({"name": f"no-pair:{src}->{dst}", "from": src, "to": dst,
                             **err(exc)})
for src, dst in [("blorts", "m"), ("m", "blorts"), (None, "m"), ("api", None),
                 ("percent", "v/v")]:  # canonical name itself is NOT an alias key
    try:
        co.conversion_factor(src, dst)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        factor_cases.append({"name": f"unknown-unit:{src}->{dst}", "from": src, "to": dst,
                             **err(exc)})
fixtures["conversion_factor"] = factor_cases

conv_cases = []
for name, values, src, dst in [
    ("pytest:m_to_ft", [1000.0], "m", "ft"),
    ("pytest:g/cc_to_kg/m3", [2.0], "g/cm3", "kg/m3"),
    ("pytest:us/m_to_us/ft", [100.0], "us/m", "us/ft"),
    ("with_nan_and_inf", [1.0, None, "Infinity", -2.5], "mv", "v"),
    ("identity_passthrough", [1.5, None], "M", "meter"),
    ("empty", [], "m", "ft"),
]:
    arr = np.array([NAN if x is None else (INF if x == "Infinity" else float(x))
                    for x in values], dtype=float)
    conv_cases.append({"name": name, "values": jarr(arr), "from": src, "to": dst,
                       "expected": jarr(co.convert_values(arr, src, dst))})
try:
    co.convert_values(np.array([1.0]), "api", "m")
    raise AssertionError("expected ValueError")
except ValueError as exc:
    conv_cases.append({"name": "bad_pair_even_empty", "values": [], "from": "api", "to": "m",
                       **err(exc)})
fixtures["convert_values"] = conv_cases

# ---------------------------------------------------------------------------
# resample_axis
# ---------------------------------------------------------------------------
cases = [
    {"name": "pytest:regular", "depth": [1000.0, 1000.5, 1001.0, 1001.5], "step": 1.0},
    {"name": "exact_fit_guard", "depth": [0.0, 0.3, 0.6, 0.9], "step": 0.3},
    {"name": "trailing_partial_dropped", "depth": [0.0, 1.0, 2.0, 2.5], "step": 1.0},
    {"name": "single_span", "depth": [5.0, 7.0], "step": 3.0},
    {"name": "tiny_step", "depth": [10.0, 10.05], "step": 0.01},
]
for c in cases:
    c["expected"] = jarr(co.resample_axis(np.asarray(c["depth"], dtype=float), c["step"]))
empty_cases = [
    {"name": "short_axis_passthrough", "depth": [3.0], "step": 1.0},
    {"name": "empty_passthrough", "depth": [], "step": 1.0},
]
for c in empty_cases:
    c["expected"] = jarr(co.resample_axis(np.asarray(c["depth"], dtype=float), c["step"]))
resample_errors = []
for name, depth, step in [
    ("pytest:zero_step", [1000.0, 1000.5, 1001.0, 1001.5], 0.0),
    ("negative_step", [1000.0, 1001.0], -0.5),
    ("nan_step", [1000.0, 1001.0], NAN),
    ("pytest:descending", [2000.0, 1990.0, 1980.0], 1.0),
]:
    try:
        co.resample_axis(np.asarray(depth, dtype=float), step)
        raise AssertionError(f"expected ValueError for {name}")
    except ValueError as exc:
        resample_errors.append({"name": name, "depth": depth, "step": jval(step), **err(exc)})
fixtures["resample_axis"] = cases + empty_cases + resample_errors

# ---------------------------------------------------------------------------
# interp_nan_aware (deprecated bridging semantics) / interp_gap_preserving
# ---------------------------------------------------------------------------
cases = []
xa = np.array([0.0, 1.0, 2.0, 3.0])
ya = np.array([0.0, NAN, 2.0, 3.0])
for c in [
    {"name": "pytest:bridges_interior_nan",
     "new_x": [0.5, 1.5, 2.5], "x": jarr(xa), "y": jarr(ya)},
    {"name": "pytest:outside_hull_nan", "new_x": [-1.0, 4.0], "x": jarr(xa), "y": jarr(ya)},
    {"name": "unsorted_x_sorted_internally",
     "new_x": [1.5, 0.5], "x": [3.0, 1.0, 2.0], "y": [30.0, 10.0, 20.0]},
    {"name": "duplicate_depth_keeps_first",
     "new_x": [1.5], "x": [1.0, 1.0, 2.0], "y": [10.0, 99.0, 20.0]},
    {"name": "endpoint_clamp", "new_x": [0.0, 3.0], "x": jarr(xa), "y": jarr(ya)},
    {"name": "nan_query", "new_x": [None], "x": jarr(xa), "y": jarr(ya)},
    {"name": "all_nan_y", "new_x": [0.5], "x": [0.0, 1.0], "y": [None, None]},
    {"name": "nan_x_dropped", "new_x": [1.5], "x": [0.0, None, 2.0], "y": [0.0, 5.0, 2.0]},
    {"name": "single_finite_sample", "new_x": [0.0, 5.0, 10.0], "x": [7.0], "y": [42.0]},
]:
    cases.append({**c, "expected": jarr(co.interp_nan_aware(
        np.array([NAN if q is None else q for q in c["new_x"]], dtype=float),
        np.array([NAN if q is None else q for q in c["x"]], dtype=float),
        np.array([NAN if q is None else q for q in c["y"]], dtype=float)))})
fixtures["interp_nan_aware"] = cases

cases = []
xg = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
yg = np.array([1.0, 2.0, NAN, NAN, 5.0])
nx = np.arange(0.0, 4.01, 0.25)
cases.append({"name": "pytest:interior_gap_not_bridged", "new_x": jarr(nx),
              "x": jarr(xg), "y": jarr(yg)})
cases.append({"name": "pytest:outside_hull_stays_nan", "new_x": [0.0, 1.5, 3.5],
              "x": [1.0, 2.0, 3.0], "y": [10.0, 20.0, 30.0]})
cases.append({"name": "pytest:two_runs", "new_x": [0.5, 2.5, 4.5],
              "x": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
              "y": [0.0, 1.0, None, 3.0, 4.0, 5.0]})
cases.append({"name": "pytest:all_nan", "new_x": [0.0, 1.0],
              "x": [0.0, 1.0], "y": [None, None]})
cases.append({"name": "duplicate_depth_in_run_keeps_first", "new_x": [0.5, 1.0],
              "x": [0.0, 0.0, 1.0], "y": [10.0, 99.0, 20.0]})
cases.append({"name": "single_sample_run_exact_hit", "new_x": [2.0, 2.5],
              "x": [0.0, 1.0, 2.0, 3.0], "y": [0.0, None, 7.0, 1.0]})
cases.append({"name": "leading_trailing_nan", "new_x": [0.5, 1.5, 2.5, 3.5],
              "x": [0.0, 1.0, 2.0, 3.0, 4.0], "y": [None, 1.0, 2.0, 3.0, None]})
cases.append({"name": "nan_query_nan_result", "new_x": [None, 1.5],
              "x": [1.0, 2.0], "y": [1.0, 2.0]})
cases.append({"name": "no_finite_x_at_all", "new_x": [0.5],
              "x": [None, None], "y": [1.0, 2.0]})
cases.append({"name": "nan_depth_in_x_rides", "new_x": [1.5],
              "x": [0.0, None, 3.0], "y": [0.0, 9.0, 3.0]})
gap_cases = []
for c in cases:
    arrs = (
        np.array([NAN if q is None else q for q in c["new_x"]], dtype=float),
        np.array([NAN if q is None else q for q in c["x"]], dtype=float),
        np.array([NAN if q is None else q for q in c["y"]], dtype=float),
    )
    c["expected"] = jarr(co.interp_gap_preserving(*arrs))
fixtures["interp_gap_preserving"] = cases

gap_errors = []
try:
    co.interp_gap_preserving(np.array([0.5]), np.array([3.0, 2.0, 1.0]),
                             np.array([3.0, 2.0, 1.0]))
    raise AssertionError("expected ValueError")
except ValueError as exc:
    gap_errors.append({"name": "descending_finite_x", "new_x": [0.5],
                       "x": [3.0, 2.0, 1.0], "y": [3.0, 2.0, 1.0], **err(exc)})
try:
    co.interp_gap_preserving(np.array([0.5]), np.array([3.0, NAN, 1.0]),
                             np.array([3.0, 2.0, 1.0]))
    raise AssertionError("expected ValueError")
except ValueError as exc:
    gap_errors.append({"name": "descending_with_nan_x", "new_x": [0.5],
                       "x": [3.0, None, 1.0], "y": [3.0, 2.0, 1.0], **err(exc)})
fixtures["interp_gap_preserving"] = fixtures["interp_gap_preserving"] + gap_errors

# ---------------------------------------------------------------------------
# missing_interval_report
# ---------------------------------------------------------------------------
cases = []
depth = np.arange(1000.0, 1010.0, 0.5)
values = np.ones_like(depth)
values[4:8] = NAN
cases.append({"name": "pytest:basic", "depth": jarr(depth), "values": jarr(values),
              "expect_fraction": 0.2, "expect_largest": 1.5})
cases.append({"name": "pytest:report_fields", "depth": jarr(depth), "values": jarr(values),
              "expect_fraction": 0.2, "expect_largest": 1.5})
d2 = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
v2 = np.array([NAN, 1.0, 2.0, 3.0, NAN])
cases.append({"name": "edge_missing_not_a_gap", "depth": jarr(d2), "values": jarr(v2),
              "expect_fraction": 0.4, "expect_largest": 0.0})
v3 = np.array([1.0, NAN, NAN, NAN, 5.0])
cases.append({"name": "one_full_hole", "depth": jarr(d2), "values": jarr(v3),
              "expect_fraction": 0.6, "expect_largest": 2.0})
cases.append({"name": "all_finite", "depth": jarr(d2), "values": [1, 2, 3, 4, 5],
              "expect_fraction": 0.0, "expect_largest": 0.0})
cases.append({"name": "all_nan_no_intervals", "depth": jarr(d2), "values": [None] * 5,
              "expect_fraction": 1.0, "expect_largest": 0.0})
cases.append({"name": "nan_depth_inside_hole", "depth": [0.0, None, None, None, 4.0],
              "values": [1.0, None, None, None, 5.0], "expect_fraction": 0.6})
cases.append({"name": "two_holes", "depth": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
              "values": [1, None, None, 4, 5, 6, None, None, 9, 10],
              "expect_fraction": 0.4, "expect_largest": 1.0})
cases.append({"name": "short_curves_no_intervals", "depth": [0.0, 1.0],
              "values": [1.0, None], "expect_fraction": 0.5, "expect_largest": 0.0})
cases.append({"name": "empty", "depth": [], "values": [],
              "expect_fraction": 0.0, "expect_largest": 0.0})
for c in cases:
    d = np.array([NAN if q is None else q for q in c["depth"]], dtype=float)
    vv = np.array([NAN if q is None else q for q in c["values"]], dtype=float)
    rep = co.missing_interval_report(d, vv)
    c["total_samples"] = rep.total_samples
    c["missing_samples"] = rep.missing_samples
    c["intervals"] = [[jval(a), jval(b)] for a, b in rep.intervals]
    # frozen from the live properties (max() over spans is order-dependent
    # with NaN endpoints — never hand-write these)
    c["expect_fraction"] = jval(rep.missing_fraction)
    c["expect_largest"] = jval(rep.largest_gap)
fixtures["missing_interval_report"] = cases

# ---------------------------------------------------------------------------
# evaluate_curve_expression
# ---------------------------------------------------------------------------
expr_cases = []
GR = [10.0, 50.0]
RT = [1.0, 4.0]
HOLE = [1.0, None, 3.0, 4.0]


def run_expr(expr, variables):
    return jarr(co.evaluate_curve_expression(
        expr, {k: np.asarray(v, dtype=float) for k, v in variables.items()}))


for name, expr, variables in [
    ("pytest:arithmetic_and_functions", "GR / max(RT, 2.0) + 1", {"GR": GR, "RT": RT}),
    ("pytest:where_and_clip", "where(GR > 100, 100, GR)", {"GR": [5.0, 200.0]}),
    ("powers", "GR ** 2 + RT ** -1", {"GR": GR, "RT": RT}),
    ("power_right_assoc", "2 ** 3 ** 2", {"GR": GR}),
    ("unary_minus_binds_looser_than_pow", "-2 ** 2", {"GR": GR}),
    ("unary_on_exponent", "2 ** -2", {"GR": GR}),
    ("modulo_python_sign", "GR % 3 - RT % -2", {"GR": GR, "RT": RT}),
    ("floordiv_python_floor", "GR // 3 + -7 // 2", {"GR": GR}),
    ("chain_compare", "1 < GR < 40", {"GR": GR}),
    ("chain_compare_three", "0 <= GR <= 10 <= RT + 10", {"GR": GR, "RT": RT}),
    ("bool_and_or_nan_truthy", "(G4 > 5) and (R4 < 100) or (HOLE != 1)",
     {"G4": [10.0, 50.0, 1.0, 60.0], "R4": [1.0, 4.0, 2.0, 8.0], "HOLE": HOLE}),
    ("bool_scalar_operand", "GR and 2", {"GR": GR}),
    ("nan_compare_false", "HOLE > 2", {"HOLE": HOLE}),
    ("nan_bool_truthy", "HOLE and 1", {"HOLE": HOLE}),
    ("min_nan_propagates", "min(GR, RT)", {"GR": GR, "RT": [1.0, None]}),
    ("max_nan_propagates", "max(GR, RT)", {"GR": GR, "RT": [1.0, None]}),
    ("abs_min_max_funcs", "abs(min(GR, 0)) - max(RT, 2)", {"GR": GR, "RT": RT}),
    ("log_family", "log(GR) + log10(GR) + log2(RT)", {"GR": GR, "RT": RT}),
    ("log_negative_nan", "log(-GR)", {"GR": GR}),
    ("log_zero_minus_inf", "log(GR - GR)", {"GR": GR}),
    ("exp_sqrt", "exp(RT / 10) + sqrt(GR)", {"GR": GR, "RT": RT}),
    ("trig", "sin(GR) + cos(GR) + tan(RT)", {"GR": GR, "RT": RT}),
    ("clip_nan_passthrough", "clip(HOLE, 2, 3)", {"HOLE": HOLE}),
    ("where_with_nan_condition", "where(HOLE > 2, 1, 0)", {"HOLE": HOLE}),
    ("scalar_folding", "1 + 2", {"GR": GR}),
    ("scalar_broadcast_from_vars", "GR * 0 + 3", {"GR": GR}),
    ("division_by_zero_inf", "GR / (RT - RT)", {"GR": GR, "RT": RT}),
    ("compare_result_as_value", "(GR > 20) * 10", {"GR": GR}),
    ("nested_calls", "where(clip(GR, 0, 20) > 10, sqrt(GR), 0)", {"GR": GR}),
    ("nan_rides_through_arithmetic", "HOLE * 2 + 1", {"HOLE": HOLE}),
]:
    expr_cases.append({"name": name, "expr": expr, "variables": variables,
                       "expected": run_expr(expr, variables)})

# error branches — freeze exact module text
def expect_error(name, expr, variables, mode="exact"):
    try:
        co.evaluate_curve_expression(expr, {k: np.asarray(v, dtype=float)
                                            for k, v in variables.items()})
    except ValueError as exc:
        expr_cases.append({"name": name, "expr": expr, "variables": variables,
                           **err(exc, mode)})
        return
    raise AssertionError(f"expected ValueError for {name}")

expect_error("pytest:unknown_name", "DT + 1", {"GR": [1.0]})
expect_error("unknown_name_sorted_available", "DT + 1", {"ZZ": [1.0], "AA": [2.0], "MM": [3.0]})
expect_error("pytest:attribute_access", "GR.__class__", {"GR": [1.0]}, "prefix")
expect_error("pytest:subscript", "GR[0]", {"GR": [1.0]}, "prefix")
expect_error("pytest:disallowed_function", "open('x')", {"GR": [1.0]})
expect_error("pytest:keywords", "clip(GR, a_min=0)", {"GR": [1.0]})
expect_error("pytest:no_variables", "1.5", {})
expect_error("empty_expression", "", {"GR": [1.0]})
expect_error("whitespace_expression", "   ", {"GR": [1.0]})
expect_error("string_constant", "'a' + GR", {"GR": [1.0]})
expect_error("bool_constant", "GR and True", {"GR": [1.0]})
expect_error("disallowed_bitand", "GR & RT", {"GR": [1.0], "RT": [1.0]}, "prefix")
expect_error("disallowed_not", "not GR", {"GR": [1.0]}, "prefix")
expect_error("list_node", "[1, 2]", {"GR": [1.0]}, "prefix")
expect_error("min_three_args", "min(GR, RT, 1)", {"GR": GR, "RT": RT})
expect_error("sample_aligned_mismatch", "BB * BB", {"AA": [1.0, 2.0, 3.0, 4.0],
                                                    "BB": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
# numpy broadcast error for same-rank different-length operands
try:
    co.evaluate_curve_expression(
        "AA + BB", {"AA": np.asarray([1.0, 2.0, 3.0, 4.0]),
                    "BB": np.asarray([1.0, 2.0])})
    raise AssertionError("expected broadcast ValueError")
except ValueError as exc:
    expr_cases.append({"name": "broadcast_error_text", "expr": "AA + BB",
                       "variables": {"AA": [1.0, 2.0, 3.0, 4.0], "BB": [1.0, 2.0]},
                       **err(exc)})
# syntax error → prefix match only (CPython SyntaxError text is not our contract)
expr_cases.append({"name": "syntax_error", "expr": "GR +* 2", "variables": {"GR": [1.0]},
                   "raises": True, "message": "invalid expression:", "match_mode": "prefix"})
fixtures["evaluate_curve_expression"] = expr_cases

# ---------------------------------------------------------------------------
# well_science: classify_depth_unit / require_depth_unit / depth_unit_of
# ---------------------------------------------------------------------------
cls_cases = []
for token in ["M", "m", "METER", "Meters", "MTR", "MTRS", "metre", "METRES", " m ",
              "FT", "ft", "F", "FEET", "Foot", "  FT", "FURLONGS", "g/cc", "", "  ",
              "us/ft"]:
    info = ws.classify_depth_unit(token)
    cls_cases.append({"name": f"token:{token!r}", "token": token, "unit": info.unit,
                      "declared": info.declared, "raw": info.raw,
                      "known": info.known})
info = ws.classify_depth_unit(None)
cls_cases.append({"name": "token:None", "token": None, "unit": info.unit,
                  "declared": info.declared, "raw": info.raw, "known": info.known})
fixtures["classify_depth_unit"] = cls_cases

def token_case(token):
    """Encode a require_depth_unit input (raw token | None | pre-classified)."""
    if token is None:
        return {"token_kind": "none"}
    if isinstance(token, str):
        return {"token_kind": "string", "token": token}
    return {"token_kind": "info", "token": token.raw}  # C++: classify(raw)


req_cases = []
for token, op in [("m", "depth_shift"), ("ft", "depth_shift"), ("MTR", "x"),
                  (ws.classify_depth_unit("FT"), "resample_display")]:
    req_cases.append({"name": f"ok:{token!r}:{op}", **token_case(token),
                      "operation": op,
                      "expected": ws.require_depth_unit(token, operation=op)})
for token, op in [(None, "depth_shift"), (ws.classify_depth_unit("FURLONGS"), "resample_display"),
                  ("g/cc", "unit_gate"), ("", "depth_shift")]:
    try:
        ws.require_depth_unit(token, operation=op)
        raise AssertionError("expected UnknownDepthUnitError")
    except ws.UnknownDepthUnitError as exc:
        req_cases.append({"name": f"raise:{token!r}:{op}", **token_case(token),
                          "operation": op, **err(exc)})
fixtures["require_depth_unit"] = req_cases

# depth_unit_of reads the `depth_unit` ATTRIBUTE off a loaded document
# (duck-typed): a bare document without the attribute is UNKNOWN, never
# meters. The C++ core receives the envelope value directly (decisions D9),
# so cases are simulated documents with/without the attribute.
import types  # noqa: E402
duo_cases = []
for name, doc in [
    ("bare_document", types.SimpleNamespace()),
    ("wrapper_ft", types.SimpleNamespace(depth_unit="ft")),
    ("wrapper_none", types.SimpleNamespace(depth_unit=None)),
    ("envelope_empty", types.SimpleNamespace(depth_unit="")),
    ("envelope_furlongs", types.SimpleNamespace(depth_unit="FURLONGS")),
]:
    info = ws.depth_unit_of(doc)
    duo_cases.append({"name": name, "envelope": getattr(doc, "depth_unit", "__ABSENT__"),
                      "unit": info.unit, "declared": info.declared, "raw": info.raw,
                      "known": info.known})
fixtures["depth_unit_of"] = duo_cases

# ---------------------------------------------------------------------------
# well_science: NullPolicy
# ---------------------------------------------------------------------------
np_cases = []
policy = ws.NullPolicy(source="declared", sentinel=-999.25)
vals = [-999.25, -999.2500005, -999.250002, 0.0, None, 42.0]
np_cases.append({"name": "declared_mask", "policy": policy.as_dict(),
                 "values": jarr(np.array(vals, dtype=float)),
                 "expected_mask": [int(b) for b in policy.matches(np.asarray(vals, dtype=float))]})
policy2 = ws.NullPolicy(source="declared", sentinel=-999.0,
                        inferred_sentinels=(-9999.0, -99999.0))
vals2 = [-999.0, -9999.0, -99999.0 + 5e-7, -999.25, None, 1.0]
np_cases.append({"name": "declared_plus_inferred_mask", "policy": policy2.as_dict(),
                 "values": jarr(np.array(vals2, dtype=float)),
                 "expected_mask": [int(b) for b in policy2.matches(np.asarray(vals2, dtype=float))]})
policy3 = ws.NullPolicy(source="none")
np_cases.append({"name": "none_policy_never_matches", "policy": policy3.as_dict(),
                 "values": jarr(np.array([-999.25, 0.0], dtype=float)),
                 "expected_mask": [0, 0]})
np_cases.append({"name": "nan_never_matches_sentinel", "policy": policy.as_dict(),
                 "values": jarr(np.array([NAN, -999.25], dtype=float)),
                 "expected_mask": [0, 1]})
for name, p in [
    ("declared", ws.NullPolicy(source="declared", sentinel=-999.25)),
    ("inferred", ws.NullPolicy(source="inferred", sentinel=-999.25,
                               inferred_sentinels=(-999.0,))),
    ("derived_injected", ws.NullPolicy(source="derived_injected",
                                       sentinel=ws.DERIVED_NULL_SENTINEL)),
    ("none_empty", ws.NullPolicy(source="none")),
]:
    np_cases.append({"name": f"as_dict:{name}", "policy": p.as_dict(),
                     "expected": p.as_dict(),
                     "declared_flag": p.declared})
fixtures["null_policy"] = np_cases

nfd_cases = []
for name, kind, raw_text in [("none", "none", None), ("empty_string", "empty", ""),
                             ("valid_number", "number", "-999.25"),
                             ("valid_string", "string", "-9999.0"),
                             ("text", "string", "abc"), ("garbage", "string", "1e")]:
    p = ws.null_policy_from_declared(raw_text if kind != "none" else None)
    nfd_cases.append({"name": name, "kind": kind, "raw": raw_text,
                      "source": p.source,
                      "sentinel": jval(p.sentinel) if p.sentinel is not None else None})
fixtures["null_policy_from_declared"] = nfd_cases

# ---------------------------------------------------------------------------
# curve_interpretation kernels: depth_shift / despike / baseline_shift
# ---------------------------------------------------------------------------
ds_cases = []
for name, depths, delta, unit in [
    ("pytest:meters_default", [1000.0, 1000.5], -1.5, "m"),
    ("pytest:foot_axis", [3000.0, 3001.0], 3.048, "ft"),
    ("pytest:moves_axis", [1000.0, 1000.5, 1001.0], -1.5, "m"),
    ("nan_rides", [1000.0, None], 2.0, "m"),
    ("ft_token_f", [1000.0], 0.3048, "F"),
    ("info_object", [500.0], 1.0, {"info_of": "METER"}),
]:
    unit_arg = ws.classify_depth_unit("METER") if unit == {"info_of": "METER"} else unit
    arr = np.array([NAN if q is None else q for q in depths], dtype=float)
    ds_cases.append({"name": name, "depths": jarr(arr), "delta_m": delta,
                     "axis_unit": unit if not isinstance(unit, dict) else "METER",
                     "expected": jarr(ci.depth_shift(arr, delta, axis_unit=unit_arg))})
for name, depths, delta, unit in [("pytest:unknown_unit", [1000.0, 1000.5], 1.0, None),
                                  ("declared_unknown", [1000.0], 1.0, "FURLONGS")]:
    try:
        ci.depth_shift(np.asarray(depths, dtype=float), delta, axis_unit=unit)
        raise AssertionError("expected UnknownDepthUnitError")
    except ws.UnknownDepthUnitError as exc:
        ds_cases.append({"name": name, "depths": depths, "delta_m": delta,
                         "axis_unit": unit, **err(exc)})
fixtures["depth_shift"] = ds_cases

despike_cases = []
for name, values, sigma, window in [
    ("pytest:sentinel_spike", [60.0, 61.0, 999.25, 60.5, 59.5, 60.0], 3.0, 3),
    ("quiet_curve_floor", [10.0] * 8 + [10.4, 10.0], 3.0, 3),
    ("nan_neighbors", [1.0, 2.0, None, 4.0, 900.0, 1.0, 1.5], 3.0, 3),
    ("all_nan", [None, None, None], 3.0, 3),
    ("empty", [], 3.0, 3),
    ("single_sample", [5.0], 3.0, 3),
    ("two_finite_ptp_floor", [0.0, 100.0], 3.0, 3),
    ("wide_window5", [5, 5, 5, 5, 999.0, 5, 5, 5, 5], 3.0, 5),
    ("even_window_oddified", [5, 5, 5, 999.0, 5], 3.0, 4),
    ("no_spike_untouched", [1.0, 2.0, 3.0, 4.0, 5.0], 3.0, 3),
    ("negative_spike", [60.0, 61.0, -500.0, 60.5, 59.5, 60.0], 3.0, 3),
    ("rng_field", jarr(rng.normal(50.0, 2.0, 64)), 3.0, 3),
]:
    arr = np.array([NAN if q is None else q for q in values], dtype=float)
    despike_cases.append({"name": name, "values": jarr(arr), "threshold_sigma": sigma,
                          "window": window,
                          "expected": jarr(ci.despike(arr, threshold_sigma=sigma, window=window))})
fixtures["despike"] = despike_cases

bs_cases = []
for name, values, delta in [("pytest:adds_offset", [60.0, 61.0], 5.0),
                            ("nan_rides", [1.0, None], 2.5),
                            ("empty", [], 1.0)]:
    arr = np.array([NAN if q is None else q for q in values], dtype=float)
    bs_cases.append({"name": name, "values": jarr(arr), "delta": delta,
                     "expected": jarr(ci.baseline_shift(arr, delta))})
fixtures["baseline_shift"] = bs_cases

# ---------------------------------------------------------------------------
# operation registry metadata
# ---------------------------------------------------------------------------
fixtures["operation_registry"] = {
    "operations": {k: {"required_params": list(v[1]),
                       "scope": ci.OPERATION_SCOPE[k]}
                   for k, v in ci.CURVE_OPERATIONS.items()},
    "generator_id": ci.GENERATOR_ID,
}

# ---------------------------------------------------------------------------
# geoviz analytics (well_qc math) is deliberately NOT ported (decisions D4:
# different user flow, formulas owned by the geo-viz-engine contract) — the
# behavior analysis lives in ledgers/11-findings.md, no frozen C++ cases.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
out_path = OUT / "curve_ops_oracle.json"
out_path.write_text(
    json.dumps(fixtures, ensure_ascii=False, indent=1, allow_nan=False),
    encoding="utf-8")

n_cases = sum(len(v) for k, v in fixtures.items() if isinstance(v, list))
print(f"frozen {n_cases} cases -> {out_path.relative_to(REPO_ROOT)}")
for key, val in fixtures.items():
    if isinstance(val, list):
        print(f"  {key}: {len(val)}")
    else:
        print(f"  {key}: registry ({len(val.get('operations', {}))} operations)")
