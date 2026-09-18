#!/usr/bin/env python3
"""mapping_bind.smoke — the built pwb_mapping_kernel module vs the frozen
Python oracle (fixtures/bind_oracle.json, generated from the REAL Python
implementations by libs/mapping_bind/oracle/generate_fixtures.py).

Exercises every interpolated / extracted / classified case plus every frozen
error branch (exact ValueError text). Exits non-zero on any mismatch.

Tolerances follow libs/mapping_kernel/mapping_kernel_tests: grid_z/variance
1e-6 (IDW) / 1e-4 (kriging) as the frozen bridge-inclusive bound, axes
1e-12, variogram scalars 1e-9, statistics 1e-9 relative (float64 reduction
order differs between numpy and the kernel).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pwb_mapping_kernel as kernel

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bind_oracle.json"

GRID_TOL_IDW = 1e-6
GRID_TOL_KRIGE = 1e-4
AXIS_TOL = 1e-12
SCALAR_TOL = 1e-9

g_failures = 0
g_checks = 0


def check(ok: bool, what: str) -> None:
    global g_checks, g_failures
    g_checks += 1
    if not ok:
        g_failures += 1
        print(f"FAIL {what}", flush=True)


def max_abs_flat(got, want) -> float:
    """Max |got-want| with None/NaN = nodata; inf on pattern/shape mismatch."""
    if len(got) != len(want):
        return math.inf
    worst = 0.0
    for a, b in zip(got, want):
        a_fin = math.isfinite(a)
        b_fin = b is not None and math.isfinite(b)
        if not a_fin and not b_fin:
            continue
        if a_fin != b_fin:
            return math.inf
        worst = max(worst, abs(a - float(b)))
    return worst


def close(a: float, b, tol: float) -> bool:
    if isinstance(b, bool) or b is None:
        return False
    if not math.isfinite(a) or not math.isfinite(float(b)):
        return a == b
    return abs(a - float(b)) <= tol * max(1.0, abs(float(b)))


def points_from(case: dict) -> list[dict]:
    out = []
    for p in case["points"]:
        value = p["value"]
        out.append({
            "x": p["x"],
            "y": p["y"],
            "value": math.nan if value is None else value,
            "qc_flag": p["qc_flag"],
        })
    return out


def run_interp_case(case: dict) -> None:
    cid = case["id"]
    expected = case["expected"]
    if "error" in expected:
        try:
            kernel.interpolate_factor(points_from(case), case["options"])
        except ValueError as exc:
            check(str(exc) == expected["error"],
                  f"{cid}: error text {str(exc)!r} != {expected['error']!r}")
        else:
            check(False, f"{cid}: expected ValueError, got a result")
        return

    got = kernel.interpolate_factor(points_from(case), case["options"])
    ztol = GRID_TOL_KRIGE if cid.startswith("krige") else GRID_TOL_IDW
    check(max_abs_flat(got["grid_x"], expected["grid_x"]) <= AXIS_TOL,
          f"{cid}: grid_x")
    check(max_abs_flat(got["grid_y"], expected["grid_y"]) <= AXIS_TOL,
          f"{cid}: grid_y")
    dz = max_abs_flat(got["grid_z"], expected["grid_z"])
    check(dz <= ztol, f"{cid}: grid_z max_diff={dz}")
    if expected["variance"] is None:
        check(got["variance_grid"] is None, f"{cid}: variance absent")
    else:
        dv = max_abs_flat(got["variance_grid"], expected["variance"])
        check(dv <= ztol, f"{cid}: variance max_diff={dv}")
    check(got["algorithm_id"] == expected["algorithm_id"],
          f"{cid}: algorithm_id")
    for key in ("method", "model", "variogram_fit"):
        if key in expected:
            check(got[key] == expected[key], f"{cid}: {key}")
    for key in ("power", "range", "sill", "nugget"):
        if key in expected:
            check(close(got[key], expected[key], SCALAR_TOL),
                  f"{cid}: {key} {got[key]} vs {expected[key]}")
    for key in ("n_samples", "duplicates_merged", "variogram_bins",
                "domain_masked_cells"):
        if key in expected:
            check(got[key] == expected[key], f"{cid}: {key}")
    check(got["distance_policy"] == expected["distance_policy"],
          f"{cid}: distance_policy")
    check(got["distance_policy_annotation"]
          == expected["distance_policy_annotation"],
          f"{cid}: distance_policy_annotation")
    stats = got["statistics"]
    want_stats = expected["statistics"]
    for key in ("min", "max", "mean", "std"):
        check(close(stats[key], want_stats[key], SCALAR_TOL),
              f"{cid}: statistics.{key}")
    for key in ("valid_count", "total_count"):
        check(stats[key] == want_stats[key], f"{cid}: statistics.{key}")


def deep_equal(got, want, path: str) -> None:
    if isinstance(want, dict):
        check(isinstance(got, dict), f"{path}: dict")
        if not isinstance(got, dict):
            return
        check(set(got.keys()) == set(want.keys()),
              f"{path}: keys {sorted(got.keys())} vs {sorted(want.keys())}")
        for key in want:
            if key in got:
                deep_equal(got[key], want[key], f"{path}.{key}")
    elif isinstance(want, list):
        check(isinstance(got, list), f"{path}: list")
        if not isinstance(got, list):
            return
        check(len(got) == len(want), f"{path}: len {len(got)} vs {len(want)}")
        for i, item in enumerate(want):
            if i < len(got):
                deep_equal(got[i], item, f"{path}[{i}]")
    elif want is None or isinstance(want, (str, bool, int)):
        check(got == want, f"{path}: {got!r} vs {want!r}")
    else:
        check(isinstance(got, float) and got == float(want),
              f"{path}: {got!r} vs {want!r}")


def run_extract_case(case: dict) -> None:
    got = kernel.extract_factors(
        case["records"], case["factor_name"], case["target_horizon"],
        case["unit"], case["crs"])
    deep_equal(got, case["expected"], case["id"])


def run_class_case(case: dict) -> None:
    got = kernel.nearest_neighbor_class_grid(
        case["points"], case["extent"], case["grid_n"], case["clip_ring"])
    expected = case["expected"]
    check(max_abs_flat(got["grid_x"], expected["grid_x"]) <= AXIS_TOL,
          f"{case['id']}: grid_x")
    check(max_abs_flat(got["grid_y"], expected["grid_y"]) <= AXIS_TOL,
          f"{case['id']}: grid_y")
    dz = max_abs_flat(got["grid_z"], expected["grid_z"])
    check(dz == 0.0, f"{case['id']}: grid_z exact, max_diff={dz}")
    check(list(got["facies_names"]) == expected["facies_names"],
          f"{case['id']}: facies_names")


def main() -> int:
    oracle = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for case in oracle["interp"]["cases"]:
        run_interp_case(case)
    for case in oracle["extract"]["cases"]:
        run_extract_case(case)
    for case in oracle["class_grid"]["cases"]:
        run_class_case(case)

    try:
        kernel.nearest_neighbor_class_grid(
            [], [0.0, 0.0, 1.0, 1.0], 80, None)
    except ValueError as exc:
        check(str(exc) == oracle["class_grid"]["empty_error"],
              "class_grid empty error text")
    else:
        check(False, "class_grid empty: expected ValueError")

    # Build metadata must match the package version (stale-module contract,
    # tests/test_native_backend.py pins the same equality for other modules).
    pyproject = FIXTURE.parents[4] / "pyproject.toml"
    want_version = ""
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            want_version = line.split("=", 1)[1].strip().strip('"')
            break
    check(kernel.__version__ == want_version,
          f"__version__ {kernel.__version__!r} == pyproject {want_version!r}")

    status = "PASS" if g_failures == 0 else "FAIL"
    print(f"{status} mapping_bind.smoke: {g_checks} checks, "
          f"{g_failures} failures, module __version__={kernel.__version__!r}")
    return 0 if g_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
