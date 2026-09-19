#!/usr/bin/env python3
"""VIZ-B — well-tie numeric kernel oracle fixtures (frozen from the real
Python reference).

Reference: geo-viz-engine submodule gitlink 08851951 (frozen behaviour
source), packages/geoviz_well_tie — the CANONICAL set exported by its
__init__ (wavelet/synthetic/calibration/auto_tie/sonic_units) plus the
legacy tie_evaluator kept for residual parity. The legacy
synthetic_generator.py / wavelet_engine.py variant is intentionally NOT
frozen (see docs/development/cpp-viz-b/scope.md §1).

Real well data: sonic (AC) + density (DEN) are read from the checkout's
project-area LAS wells via lasio (the same reader the Python product's
preview path uses), unit-normalized through the real
normalize_sonic_units, then frozen as inputs AND outputs of
synthetic_from_logs / WellTieCalibration.from_sonic so the C++ port is
validated against the real reference on real logs.

Run (venv with numpy+lasio):
  /path/to/venv/bin/python tools/oracle/generate_viz_b_well_tie_fixtures.py

Output: libs/visualization/src/well_tie/well_tie_tests/fixtures/
        viz_b_well_tie_oracle.json

Non-finite numbers are frozen as the tagged strings "inf"/"-inf"/"nan"
(repo oracle convention).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / "geo-viz-engine" / "packages"
# The engine repo installs each PROJECT dir (packages/<pkg>, which holds
# the real importable package inside) on sys.path — mirroring the venv's
# .pth entries, but pointing at THIS worktree's frozen gitlink.
for _project in ("geoviz_well_tie",):
    sys.path.insert(0, str(PACKAGES / _project))
# The shared venv carries setuptools editable-install meta-path finders
# (installed as CLASS objects, so type(f).__name__ == "type") that shadow
# any sys.path entry with the main worktree's checkout. Drop them so the
# frozen gitlink in THIS worktree is the reference actually executed
# (both checkouts sit at 08851951; this keeps the proof local).


def _is_editable_finder(finder: object) -> bool:
    name = getattr(finder, "__name__", "") or ""
    return "editable" in name.lower() or "editable" in repr(finder).lower()


sys.meta_path = [f for f in sys.meta_path if not _is_editable_finder(f)]

from geoviz_well_tie import (  # noqa: E402
    US_FT_TO_US_M,
    WellTieCalibration,
    canonical_sonic_unit,
    compute_reflectivity,
    correlate_synthetic_to_trace,
    generate_synthetic,
    generate_synthetic_twt,
    normalize_sonic_units,
    ormsby_wavelet,
    resample_to_seismic_grid,
    ricker_wavelet,
    shift_depths,
    synthetic_from_logs,
)
from geoviz_well_tie.tie_evaluator import evaluate_tie_quality  # noqa: E402

import geoviz_well_tie as _gvt  # noqa: E402

assert str(_gvt.__file__).startswith(
    str(PACKAGES)
), f"reference must be this checkout's submodule, got {_gvt.__file__}"

OUT = (
    REPO_ROOT
    / "libs/visualization/src/well_tie/well_tie_tests/fixtures/viz_b_well_tie_oracle.json"
)

LAS_DIR = Path(
    "/home/kevin/projects/paleo_project/data/project_area/井曲线"
)


def _num(value) -> object:
    """Tag non-finite floats; convert numpy scalars to JSON scalars."""
    v = float(value)
    if math.isnan(v):
        return "nan"
    if math.isinf(v):
        return "inf" if v > 0 else "-inf"
    return v


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values).ravel()]


def _load_real_wells() -> list[dict]:
    import lasio

    wells = []
    for name in ("A4", "A13", "A16"):
        las = lasio.read(LAS_DIR / f"{name}.Las")
        depth = las["DEPT"]
        sonic_unit = None
        for curve in las.curves:
            if curve.mnemonic == "AC":
                sonic_unit = curve.unit
        ac = np.asarray(las["AC"], dtype=float)
        den_curve = "DEN" if "DEN" in las.keys() else None
        den = (
            np.asarray(las[den_curve], dtype=float)
            if den_curve
            else np.full_like(ac, np.nan)
        )
        normalized, resolved, warning = normalize_sonic_units(ac, sonic_unit)
        wells.append(
            {
                "name": name,
                "sonic_unit_raw": sonic_unit,
                "sonic_unit_resolved": resolved,
                "unit_warning": warning,
                "depths": _nums(depth),
                "sonic_raw": _nums(ac),
                "sonic_us_per_m": _nums(normalized),
                "density": _nums(den),
            }
        )
    return wells


def build_cases() -> list[dict]:
    cases: list[dict] = []

    # --- wavelet ------------------------------------------------------
    for n, dt, freq in [
        (21, 0.002, 30.0),
        (41, 0.002, 30.0),
        (65, 0.002, 30.0),
        (81, 0.004, 25.0),
        (33, 0.001, 12.0),
        (22, 0.002, 30.0),  # even length — centre falls between samples
    ]:
        w = ricker_wavelet(n, dt=dt, peak_freq=freq)
        cases.append(
            {
                "id": f"ricker_{n}_{dt}_{freq}",
                "kind": "wavelet_ricker",
                "n_samples": n,
                "dt": dt,
                "peak_freq": freq,
                "output": _nums(w),
            }
        )
    for n, dt, f1, f2, f3, f4 in [
        (21, 0.002, 5.0, 10.0, 40.0, 50.0),
        (41, 0.004, 4.0, 9.0, 35.0, 55.0),
        (65, 0.002, 5.0, 10.0, 40.0, 50.0),
        (33, 0.001, 2.0, 8.0, 30.0, 48.0),
    ]:
        w = ormsby_wavelet(n, dt=dt, f1=f1, f2=f2, f3=f3, f4=f4)
        cases.append(
            {
                "id": f"ormsby_{n}_{dt}_{f1}_{f2}_{f3}_{f4}",
                "kind": "wavelet_ormsby",
                "n_samples": n,
                "dt": dt,
                "f1": f1,
                "f2": f2,
                "f3": f3,
                "f4": f4,
                "output": _nums(w),
            }
        )

    # --- reflectivity --------------------------------------------------
    sonic = [240.0, 250.0, 235.0, 260.0, 255.0, 270.0]
    density = [2.35, 2.42, 2.30, 2.50, 2.47, 2.55]
    rc = compute_reflectivity(sonic, density)
    cases.append(
        {
            "id": "rc_basic",
            "kind": "reflectivity",
            "sonic": sonic,
            "density": density,
            "output": _nums(rc),
        }
    )
    rc_nan = compute_reflectivity(
        [240.0, float("nan"), 235.0, 260.0], [2.3, 2.4, 2.35, 2.5]
    )
    cases.append(
        {
            "id": "rc_nan_propagates",
            "kind": "reflectivity",
            "sonic": [240.0, "nan", 235.0, 260.0],
            "density": [2.3, 2.4, 2.35, 2.5],
            "output": _nums(rc_nan),
        }
    )
    cases.append(
        {
            "id": "rc_single_sample_empty",
            "kind": "reflectivity",
            "sonic": [240.0],
            "density": [2.3],
            "output": [],
        }
    )
    # (2,) vs (3,) are INCOMPATIBLE for numpy broadcasting — this is the
    # pair that actually raises ((2,) vs (1,) would silently broadcast).
    try:
        compute_reflectivity([1.0, 2.0], [1.0, 2.0, 3.0])
        err = None
    except ValueError as exc:
        err = f"ValueError: {exc}"
    cases.append(
        {
            "id": "rc_length_mismatch_raises",
            "kind": "reflectivity_error",
            "sonic": [1.0, 2.0],
            "density": [1.0, 2.0, 3.0],
            "error": err,
        }
    )

    # --- synthetic convolution ----------------------------------------
    reflectivity = [0.01, -0.02, 0.03, 0.05, -0.01, 0.02, 0.0, 0.04, -0.03]
    wavelet = ricker_wavelet(21, dt=0.002, peak_freq=30.0)
    syn = generate_synthetic(np.asarray(reflectivity), wavelet)
    cases.append(
        {
            "id": "syn_wavelet_shorter",
            "kind": "synthetic",
            "reflectivity": reflectivity,
            "wavelet": _nums(wavelet),
            "output": _nums(syn),
        }
    )
    wavelet_long = ricker_wavelet(25, dt=0.002, peak_freq=30.0)
    syn_pad = generate_synthetic(np.asarray(reflectivity[:7]), wavelet_long)
    cases.append(
        {
            "id": "syn_wavelet_longer_pad",
            "kind": "synthetic",
            "reflectivity": reflectivity[:7],
            "wavelet": _nums(wavelet_long),
            "output": _nums(syn_pad),
        }
    )
    cases.append(
        {
            "id": "syn_empty_reflectivity",
            "kind": "synthetic",
            "reflectivity": [],
            "wavelet": _nums(wavelet),
            "output": [],
        }
    )

    # --- generate_synthetic_twt ---------------------------------------
    for wt, n_ref in [("ricker", 40), ("ricker", 41), ("ormsby", 40)]:
        rc_in = np.asarray(
            [0.01, -0.02, 0.03, 0.05, -0.01, 0.02] * (n_ref // 6 + 1)
        )[:n_ref]
        syn = generate_synthetic_twt(
            rc_in.astype(np.float32),
            wavelet_type=wt,
            dt_ms=4.0,
            peak_freq=25.0,
        )
        cases.append(
            {
                "id": f"syn_twt_{wt}_{n_ref}",
                "kind": "synthetic_twt",
                "wavelet_type": wt,
                "dt_ms": 4.0,
                "peak_freq": 25.0,
                "reflectivity": _nums(rc_in),
                "output": _nums(syn),
            }
        )

    # --- synthetic_from_logs (synthetic + NaN policy) ------------------
    logs_sonic = [240.0, 245.0, 250.0, 255.0, 260.0, 258.0, 262.0, 265.0]
    logs_density = [2.35, 2.38, 2.42, 2.45, 2.50, 2.48, 2.52, 2.55]
    syn = synthetic_from_logs(logs_sonic, logs_density)
    cases.append(
        {
            "id": "from_logs_defaults",
            "kind": "synthetic_from_logs",
            "sonic": logs_sonic,
            "density": logs_density,
            "output": _nums(syn),
        }
    )
    syn_nan = synthetic_from_logs(
        [240.0, float("nan"), 250.0, float("nan"), 260.0, 258.0],
        [2.35, 2.38, 2.42, 2.45, 2.50, 2.48],
    )
    cases.append(
        {
            "id": "from_logs_interior_nan",
            "kind": "synthetic_from_logs",
            "sonic": [240.0, "nan", 250.0, "nan", 260.0, 258.0],
            "density": [2.35, 2.38, 2.42, 2.45, 2.50, 2.48],
            "output": _nums(syn_nan),
        }
    )
    syn_edge = synthetic_from_logs(
        [float("nan"), float("nan"), 250.0, 260.0],
        [2.35, 2.42, 2.50, 2.55],
    )
    cases.append(
        {
            "id": "from_logs_leading_nan",
            "kind": "synthetic_from_logs",
            "sonic": ["nan", "nan", 250.0, 260.0],
            "density": [2.35, 2.42, 2.50, 2.55],
            "output": _nums(syn_edge),
        }
    )
    syn_all_nan = synthetic_from_logs(
        [float("nan")] * 4, [float("nan")] * 4
    )
    cases.append(
        {
            "id": "from_logs_all_nan_stays_nan",
            "kind": "synthetic_from_logs",
            "sonic": ["nan"] * 4,
            "density": ["nan"] * 4,
            "output": _nums(syn_all_nan),
        }
    )
    syn_clip_off = synthetic_from_logs(
        logs_sonic, logs_density, sonic_clip=None
    )
    cases.append(
        {
            "id": "from_logs_clip_off",
            "kind": "synthetic_from_logs",
            "sonic": logs_sonic,
            "density": logs_density,
            "sonic_clip": None,
            "output": _nums(syn_clip_off),
        }
    )
    cases.append(
        {
            "id": "from_logs_too_short_empty",
            "kind": "synthetic_from_logs",
            "sonic": [240.0],
            "density": [2.35],
            "output": [],
        }
    )
    # Even-aperture half length (round(2*0.065/0.002)+1 = 66 -> |1 = 67).
    syn_even = synthetic_from_logs(
        logs_sonic, logs_density, half_length_s=0.065
    )
    cases.append(
        {
            "id": "from_logs_even_aperture",
            "kind": "synthetic_from_logs",
            "sonic": logs_sonic,
            "density": logs_density,
            "half_length_s": 0.065,
            "output": _nums(syn_even),
        }
    )

    # --- calibration ---------------------------------------------------
    depths = [1000.0, 1100.0, 1200.0, 1300.0, 1400.0]
    twts = [520.0, 560.0, 605.0, 648.0, 695.0]
    cal = WellTieCalibration(depths, twts)
    probe_depths = [900.0, 1050.0, 1250.0, 1500.0]
    cases.append(
        {
            "id": "cal_depth_to_twt_clamped",
            "kind": "cal_depth_to_twt",
            "depths": depths,
            "twts": twts,
            "probe": probe_depths,
            "output": [_num(cal.depth_to_twt(d)) for d in probe_depths],
        }
    )
    cal_rev = WellTieCalibration(list(reversed(depths)), list(reversed(twts)))
    cases.append(
        {
            "id": "cal_descending_reversed",
            "kind": "cal_depth_to_twt",
            "depths": list(reversed(depths)),
            "twts": list(reversed(twts)),
            "probe": probe_depths,
            "output": [
                _num(cal_rev.depth_to_twt(d)) for d in probe_depths
            ],
        }
    )
    cases.append(
        {
            "id": "cal_twt_to_depth",
            "kind": "cal_twt_to_depth",
            "depths": depths,
            "twts": twts,
            "probe": [500.0, 540.0, 600.0, 700.0],
            "output": [
                _num(cal.twt_to_depth(t))
                for t in [500.0, 540.0, 600.0, 700.0]
            ],
        }
    )
    log_values = [10.0, 20.0, 30.0, 40.0, 50.0]
    resampled = cal.resample_to_twt(log_values, dt_ms=10.0, t0_ms=520.0)
    cases.append(
        {
            "id": "cal_resample_to_twt",
            "kind": "cal_resample_to_twt",
            "depths": depths,
            "twts": twts,
            "log_values": log_values,
            "dt_ms": 10.0,
            "t0_ms": 520.0,
            "output": _nums(resampled),
        }
    )
    sonic_int = [
        250.0,
        252.0,
        248.0,
        float("nan"),
        255.0,
        258.0,
        251.0,
    ]
    depths_int = [1000.0, 1010.0, 1020.0, 1030.0, 1040.0, 1050.0, 1060.0]
    cal_sonic = WellTieCalibration.from_sonic(depths_int, sonic_int)
    cases.append(
        {
            "id": "cal_from_sonic_nan_masked",
            "kind": "cal_from_sonic",
            "depths": depths_int,
            "sonic": ["nan" if v != v else v for v in sonic_int],
            "output_depths": _nums(cal_sonic.depths),
            "output_twt": _nums(cal_sonic.twt),
        }
    )
    cal_sonic_rev = WellTieCalibration.from_sonic(
        list(reversed(depths_int)), list(reversed(sonic_int))
    )
    cases.append(
        {
            "id": "cal_from_sonic_descending",
            "kind": "cal_from_sonic",
            "depths": list(reversed(depths_int)),
            "sonic": ["nan" if v != v else v for v in reversed(sonic_int)],
            "output_depths": _nums(cal_sonic_rev.depths),
            "output_twt": _nums(cal_sonic_rev.twt),
        }
    )
    try:
        WellTieCalibration.from_sonic([1.0], [250.0])
        err = None
    except ValueError as exc:
        err = f"ValueError: {exc}"
    cases.append(
        {
            "id": "cal_from_sonic_too_few_raises",
            "kind": "cal_from_sonic_error",
            "depths": [1.0],
            "sonic": [250.0],
            "error": err,
        }
    )
    try:
        WellTieCalibration([1.0, 2.0], [3.0])
        err = None
    except ValueError as exc:
        err = f"ValueError: {exc}"
    cases.append(
        {
            "id": "cal_length_mismatch_raises",
            "kind": "cal_error",
            "depths": [1.0, 2.0],
            "twts": [3.0],
            "error": err,
        }
    )
    grid = resample_to_seismic_grid(
        [0.0, 1.0, 2.0, 3.0], [100.0, 110.0, 120.0, 130.0],
        dt_ms=4.0, t0_ms=96.0, n_samples=12,
    )
    cases.append(
        {
            "id": "resample_seismic_grid_zero_fill",
            "kind": "resample_seismic_grid",
            "values": [0.0, 1.0, 2.0, 3.0],
            "src_twt": [100.0, 110.0, 120.0, 130.0],
            "dt_ms": 4.0,
            "t0_ms": 96.0,
            "n_samples": 12,
            "output": _nums(grid),
        }
    )
    shifted = shift_depths(depths, -12.5)
    cases.append(
        {
            "id": "shift_depths",
            "kind": "shift_depths",
            "depths": depths,
            "shift": -12.5,
            "output": _nums(shifted),
        }
    )

    # --- auto tie ------------------------------------------------------
    rng = np.random.default_rng(20260919)
    base = np.sin(np.linspace(0.0, 6.0, 120)) + 0.1 * rng.standard_normal(
        120
    )
    trace_long = np.concatenate(
        [np.zeros(20), base, np.zeros(60)]
    )  # synthetic embedded at offset 20
    syn_trace = base
    shift, r = correlate_synthetic_to_trace(syn_trace, trace_long)
    cases.append(
        {
            "id": "auto_tie_embedded_offset20",
            "kind": "auto_tie",
            "synthetic": _nums(syn_trace),
            "seismic": _nums(trace_long),
            "shift": int(shift),
            "r": _num(r),
        }
    )
    cases.append(
        {
            "id": "auto_tire_perfect_match",
            "kind": "auto_tie",
            "synthetic": _nums(base),
            "seismic": _nums(base.copy()),
            "shift": 0,
            "r": _num(correlate_synthetic_to_trace(base, base)[1]),
        }
    )
    neg = correlate_synthetic_to_trace(base, -base)
    cases.append(
        {
            "id": "auto_tie_negative_correlation",
            "kind": "auto_tie",
            "synthetic": _nums(base),
            "seismic": _nums(-base),
            "shift": int(neg[0]),
            "r": _num(neg[1]),
        }
    )
    cases.append(
        {
            "id": "auto_tie_constant_trace",
            "kind": "auto_tie",
            "synthetic": _nums(base),
            "seismic": [1.0] * 50,
            "shift": 0,
            "r": 0.0,
        }
    )
    cases.append(
        {
            "id": "auto_tie_empty",
            "kind": "auto_tie",
            "synthetic": [],
            "seismic": _nums(base),
            "shift": 0,
            "r": 0.0,
        }
    )
    tiny = correlate_synthetic_to_trace([1.0, 2.0], [1.0, 2.0, 3.0, 4.0])
    cases.append(
        {
            "id": "auto_tie_below_min_overlap",
            "kind": "auto_tie",
            "synthetic": [1.0, 2.0],
            "seismic": [1.0, 2.0, 3.0, 4.0],
            "shift": int(tiny[0]),
            "r": _num(tiny[1]),
        }
    )

    # --- legacy evaluator ----------------------------------------------
    rolled = np.roll(base, 10)
    quality = evaluate_tie_quality(base, rolled)
    cases.append(
        {
            "id": "legacy_quality_rolled10",
            "kind": "tie_quality",
            "synthetic": _nums(base),
            "seismic": _nums(rolled),
            "r": _num(quality[0]),
            "lag": int(quality[1]),
            "residual_head": _nums(quality[2][:8]),
            "residual_len": int(len(quality[2])),
        }
    )

    # --- sonic units ----------------------------------------------------
    unit_table = [
        ("US/M", None),
        ("us/m", None),
        ("µs/m", None),
        ("US/FT", None),
        ("us/ft", None),
        ("usf", None),
        ("USF", None),
        ("usft", None),
        ("usecft", None),
        ("", None),
        ("banana", None),
        (None, "unknown_and_heuristic"),
        (None, "unknown_below_150"),
    ]
    for idx, (unit, mode) in enumerate(unit_table):
        if mode == "unknown_and_heuristic":
            values = [60.0, 62.0, 61.0, 63.0]  # median |v| ~61.5 < 150
        elif mode == "unknown_below_150":
            values = [55.0, 58.0, 57.5]
        else:
            values = [240.0, 250.0, 235.0]
        normalized, resolved, warning = normalize_sonic_units(values, unit)
        cases.append(
            {
                "id": f"sonic_units_{idx}_{unit or 'none'}",
                "kind": "sonic_units",
                "unit": unit,
                "values": values,
                "output": _nums(normalized),
                "resolved": resolved,
                "warning": warning,
            }
        )
        canonical = canonical_sonic_unit(unit)
        cases.append(
            {
                "id": f"sonic_canonical_{idx}_{unit or 'none'}",
                "kind": "sonic_canonical",
                "unit": unit,
                "canonical": canonical,
            }
        )
    cases.append(
        {
            "id": "sonic_units_no_finite",
            "kind": "sonic_units",
            "unit": None,
            "values": ["nan", "nan"],
            "output": ["nan", "nan"],
            "resolved": "us/m",
            "warning": normalize_sonic_units(
                [float("nan"), float("nan")], None
            )[2],
        }
    )
    cases.append(
        {
            "id": "sonic_units_factor",
            "kind": "constant",
            "us_ft_to_us_m": US_FT_TO_US_M,
        }
    )

    # --- real well logs (lasio reference path) --------------------------
    wells = _load_real_wells()
    for well in wells:
        # Real synthetic seismogram on the normalized sonic + density.
        syn = synthetic_from_logs(
            np.asarray(well["sonic_us_per_m"]), np.asarray(well["density"])
        )
        well["synthetic_from_logs_head"] = _nums(syn[:64])
        well["synthetic_len"] = int(len(syn))
        # Real integrated time-depth on a finite sample of the logs.
        cal = WellTieCalibration.from_sonic(
            np.asarray(well["depths"]), np.asarray(well["sonic_us_per_m"])
        )
        well["from_sonic_twt_head"] = _nums(cal.twt[:16])
        well["from_sonic_twt_tail"] = _nums(cal.twt[-4:])
    case_wells = {
        "kind": "real_wells",
        "source": "lasio 0.32 + project_area LAS (A4/A13/A16), normalize_sonic_units",
        "wells": wells,
    }
    return cases, case_wells


def main() -> None:
    cases, real_wells = build_cases()
    payload = {
        "meta": {
            "generator": "tools/oracle/generate_viz_b_well_tie_fixtures.py",
            "reference": "geo-viz-engine@08851951 packages/geoviz_well_tie",
            "numpy": np.__version__,
            "python": sys.version.split()[0],
        },
        "cases": cases,
        "real_wells": real_wells,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"wrote {OUT} ({len(cases)} cases + {len(real_wells['wells'])} real wells)")


if __name__ == "__main__":
    main()
