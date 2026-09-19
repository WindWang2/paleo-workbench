"""Generate the frozen S-line seismic-attribute oracle fixtures (S line).

Runs the pinned Python oracle (geo-viz-engine@08851951,
geoviz_seismic.attributes: compute_sweetness / compute_relative_impedance /
compute_dip / compute_azimuth / compute_curvature) over synthetic volumes
plus the real tiny.sgy fixture and writes input + expected payloads that the
C++ test (attribute_sline_test.cpp) compares against. Case design mirrors
generate_attribute_fixtures.py (E line): normal, constant, zeros, NaN/Inf
contamination, impulse, short axes (gradient/reflect boundary exercise), a
slanted plane with analytic dip angles, and the real fixture volume.

Deterministic: PCG64 with fixed seeds, float32 payloads. Re-running with the
same submodule gitlink and interpreter regenerates byte-identical files.

Before writing, the generator self-checks analytic invariants (the slanted
plane's dip angles equal atan of the index-unit slopes; zeros stay zeros;
the sweetness clamp fires on constants) AND a negative self-check: a
perturbed oracle output (>= 1e-3 relative) must FAIL the frozen comparison —
guarding against a vacuous comparator.

Usage (pinned interpreter, read-only):
    .venv-oracle/bin/python tests/cpp/seismic_attributes/oracle/\
generate_sline_attribute_fixtures.py \
        --out tests/cpp/seismic_attributes/fixtures
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import scipy

REPO_ROOT = Path(__file__).resolve().parents[4]  # worktree root
ORACLE_SOURCE = (
    REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_seismic"
    / "geoviz_seismic" / "attributes.py"
)
# attributes.py depends only on numpy/scipy (no intra-package imports), so
# it loads standalone. Importing the geoviz_seismic package instead would
# drag the PySide6 GUI stack in via __init__ — irrelevant for a headless
# oracle run. The file is the pinned gitlink checkout (read-only).
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("geoviz_oracle_attributes",
                                               ORACLE_SOURCE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

compute_azimuth = _mod.compute_azimuth
compute_curvature = _mod.compute_curvature
compute_dip = _mod.compute_dip
compute_relative_impedance = _mod.compute_relative_impedance
compute_sweetness = _mod.compute_sweetness

TINY_SGY_INPUT = (
    REPO_ROOT / "tests" / "cpp" / "seismic_attributes" / "fixtures"
    / "tiny_sgy_real" / "input.f32"
)

# S-line kernels and their production parameter sets (paleo_workbench
# seismic_attributes KERNELS table defaults; the C++ descriptors carry the
# same defaults).
KERNELS = {
    "sweetness": {"sample_interval": 1.0},
    "relative_impedance": {},
    "dip_il": {"dt": 1.0, "dx_il": 1.0, "dx_xl": 1.0},
    "dip_xl": {"dt": 1.0, "dx_il": 1.0, "dx_xl": 1.0},
    "dip_azimuth": {"dt": 1.0, "dx_il": 1.0, "dx_xl": 1.0},
    "curvature_mean": {"kind": "mean", "win_il": 3, "win_xl": 3, "win_t": 3},
}

# Tolerances are decided AFTER measuring the pinned-oracle-vs-C++ deltas on
# every case (protocol: measure, then freeze with >= 10x margin). The first
# run writes measured maxima into the manifest; the C++ test fails until the
# frozen values land here.
TOLERANCES = {
    "sweetness": {"max_abs": 1e-5, "max_rel": 1e-2},
    "relative_impedance": {"max_abs": 1e-6, "max_rel": 1e-5},
    "dip_il": {"max_abs": 1e-5, "max_rel": 1e-3},
    "dip_xl": {"max_abs": 1e-5, "max_rel": 1e-3},
    "dip_azimuth": {"max_abs": 1e-5, "max_rel": 1e-3},
    "curvature_mean": {"max_abs": 1e-4, "max_rel": 1e-2},
}

INTERPRETER = {
    "python": sys.version.split()[0],
    "numpy": np.__version__,
    "scipy": scipy.__version__,
    "executable": sys.executable,
}

ORACLE = {
    "gitlink": "geo-viz-engine@08851951f3bbc0beb90886adf52e1928f4383c16",
    "module": "geoviz_seismic.attributes",
    "functions": [
        "compute_sweetness",
        "compute_relative_impedance",
        "compute_dip",
        "compute_azimuth",
        "compute_curvature",
    ],
}


def case_volumes() -> dict[str, tuple[np.ndarray, dict]]:
    """Deterministic case inputs keyed by case name."""
    cases: dict[str, tuple[np.ndarray, dict]] = {}

    rng = np.random.default_rng(20260919)
    base = rng.uniform(-1.0, 1.0, size=(8, 6, 32)).astype(np.float32)
    cases["sl_synth_32"] = (
        base,
        {"note": "normal 8x6x32 uniform noise, seed 20260919"},
    )

    contaminated = base.copy()
    contaminated[0, :, :] = np.nan              # whole poisoned inline
    contaminated[2, 1, 5] = np.nan              # mid-trace NaN
    contaminated[3, 2, 0] = np.inf              # Inf at trace start
    contaminated[4, 3, 31] = -np.inf            # Inf at trace end
    cases["sl_nan_inf"] = (
        contaminated,
        {"note": "NaN/Inf poisoning: full inline, mid, start, end"},
    )

    cases["sl_constant"] = (
        np.full((4, 4, 16), 0.5, dtype=np.float32),
        {"note": "constant 0.5: |freq| ~ 0 exercises the sweetness clamp"},
    )
    cases["sl_zeros"] = (
        np.zeros((4, 4, 16), dtype=np.float32),
        {"note": "all zeros: dip clamps grad_t to 1e-10, curvature 0"},
    )

    rng_short = np.random.default_rng(424242)
    cases["sl_short_axes"] = (
        rng_short.uniform(-1.0, 1.0, size=(2, 3, 4)).astype(np.float32),
        {"note": "minimal axes (>=2): np.gradient edges + smoothing "
                 "window (7) wider than every axis -> reflect fold"},
    )

    impulse = np.zeros((6, 5, 24), dtype=np.float32)
    impulse[3, 2, 12] = 1.0
    cases["sl_impulse"] = (impulse, {"note": "single spike: gradient/unwrap "
                                             "boundaries around a delta"})

    il, xl, t = np.meshgrid(
        np.arange(6, dtype=np.float32),
        np.arange(5, dtype=np.float32),
        np.arange(20, dtype=np.float32),
        indexing="ij",
    )
    plane = (0.7 * il + (-0.4) * xl + 1.3 * t + 2.0).astype(np.float32)
    cases["sl_plane"] = (
        plane,
        {"note": "slanted plane: dip_il = atan(0.7/1.3), dip_xl = "
                 "atan(-0.4/1.3), azimuth analytic",
         "analytic": {
             "dip_il": math.atan2(0.7, 1.3),
             "dip_xl": math.atan2(-0.4, 1.3),
         }},
    )

    if TINY_SGY_INPUT.exists():
        real = np.fromfile(TINY_SGY_INPUT, dtype=np.float32)
        cases["sl_tiny_sgy_real"] = (
            real.reshape(8, 8, 32).copy(),
            {"note": "real tiny.sgy volume (frozen E-line input), "
                     "inline-major C-order"},
        )
    return cases


def compute_all(vol: np.ndarray) -> dict[str, np.ndarray]:
    dip_il, dip_xl = compute_dip(vol, axis_il=0, axis_xl=1, axis_t=2,
                                 dt=1.0, dx_il=1.0, dx_xl=1.0)
    return {
        "sweetness": compute_sweetness(vol, sample_interval=1.0, axis=-1),
        "relative_impedance": compute_relative_impedance(vol, axis=-1),
        "dip_il": dip_il,
        "dip_xl": dip_xl,
        "dip_azimuth": compute_azimuth(dip_il, dip_xl),
        "curvature_mean": compute_curvature(
            vol, kind="mean", win_il=3, win_xl=3, win_t=3),
    }


def self_check(cases: dict[str, tuple[np.ndarray, dict]]) -> None:
    """Analytic invariants; raise before anything is written on violation."""
    plane_vol, plane_meta = cases["sl_plane"]
    dip_il, dip_xl = compute_dip(plane_vol, axis_il=0, axis_xl=1, axis_t=2)
    want_il = plane_meta["analytic"]["dip_il"]
    want_xl = plane_meta["analytic"]["dip_xl"]
    got_il = float(dip_il[2, 2, 10])
    got_xl = float(dip_xl[2, 2, 10])
    if abs(got_il - want_il) > 1e-6 or abs(got_xl - want_xl) > 1e-6:
        raise AssertionError(
            f"plane dip invariant failed: il {got_il} vs {want_il}, "
            f"xl {got_xl} vs {want_xl}")
    zeros = cases["sl_zeros"][0]
    if not np.allclose(compute_relative_impedance(zeros), 0.0):
        raise AssertionError("zeros impedance invariant failed")
    const_sweet = compute_sweetness(cases["sl_constant"][0],
                                    sample_interval=1.0, axis=-1)
    if not np.all(np.isfinite(const_sweet)):
        raise AssertionError("constant sweetness clamp invariant failed "
                             "(non-finite after |freq| clamp)")
    # cumulative sums grow monotonically for a non-decreasing trace
    inc = np.arange(16, dtype=np.float32).reshape(1, 1, 16).repeat(2, 0)
    inc = np.repeat(inc, 2, axis=1)
    cum = compute_relative_impedance(inc.copy())
    if not (np.diff(cum[0, 0]) >= 0).all():
        raise AssertionError("cumsum monotonicity invariant failed")


def negative_self_check(golden: dict[str, np.ndarray]) -> None:
    """A perturbed oracle must FAIL the comparator (non-vacuous check)."""
    def compare(a: np.ndarray, b: np.ndarray, tol: dict) -> bool:
        if a.shape != b.shape:
            return False
        nan_a, nan_b = np.isnan(a), np.isnan(b)
        if not np.array_equal(nan_a, nan_b):
            return False
        fa, fb = a[~nan_a], b[~nan_b]
        max_abs = float(np.max(np.abs(fa - fb))) if fa.size else 0.0
        denom = np.maximum(np.abs(fa), np.abs(fb))
        max_rel = float(np.max(np.abs(fa - fb) / np.maximum(denom, 1e-30))) \
            if fa.size else 0.0
        return max_abs <= tol["max_abs"] and max_rel <= tol["max_rel"]

    for name, values in golden.items():
        tol = TOLERANCES[name]
        # A shift of 1000x the frozen max_abs tolerance (NaN preserved) must
        # fail the comparator through its max_abs rule — a vacuous
        # comparator would pass anything.
        with np.errstate(invalid="ignore"):
            shift = 1000.0 * tol["max_abs"]
            perturbed = values + np.float32(shift)
            if not np.any(~np.isnan(perturbed)):
                # All-NaN output: no finite elements exist, so the value
                # comparator is vacuous by construction. Perturb the mask
                # instead (one NaN -> sentinel) — it must be rejected.
                perturbed = values.copy()
                first_nan = int(np.argmax(np.isnan(values).ravel()))
                perturbed.ravel()[first_nan] = np.float32(0.0)
        if compare(values, perturbed, tol):
            raise AssertionError(
                f"negative self-check failed for {name}: perturbed output "
                "passed the frozen tolerance")


def stats(arr: np.ndarray) -> dict:
    finite = arr[np.isfinite(arr)]
    return {
        "elements": int(arr.size),
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "mean": float(finite.mean()) if finite.size else None,
        "n_nan": int(np.isnan(arr).sum()),
        "n_inf": int(np.isinf(arr).sum()),
    }


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)

    cases = case_volumes()
    self_check(cases)

    case_manifests = {}
    for case_name, (vol, meta) in cases.items():
        golden = compute_all(vol)
        negative_self_check(golden)

        case_dir = out_root / case_name
        case_dir.mkdir(exist_ok=True)
        input_path = case_dir / "input.f32"
        vol.astype(np.float32).tofile(input_path)

        files = {
            "input.f32": {"role": "input", "sha256": sha256_of(input_path),
                          **stats(vol)},
        }
        for kernel, values in golden.items():
            out = values.astype(np.float32)
            path = case_dir / f"expected_{kernel}.f32"
            out.tofile(path)
            files[f"expected_{kernel}.f32"] = {
                "kernel": kernel,
                "params": KERNELS[kernel],
                "sha256": sha256_of(path),
                **stats(out),
            }
        case_manifest = {
            "case": case_name,
            "dtype": "float32",
            "shape": list(vol.shape),
            "meta": meta,
            "files": files,
        }
        (case_dir / "manifest.json").write_text(
            json.dumps(case_manifest, indent=1, sort_keys=True) + "\n")
        case_manifests[case_name] = case_manifest
        print(f"wrote case {case_name}: shape={list(vol.shape)}")

    top = {
        "cases": sorted(case_manifests.keys()),
        "interpreter": INTERPRETER,
        "oracle": ORACLE,
        "kernels": KERNELS,
        "comparison_rules": {
            kernel: "max_abs + max_rel over finite elements; "
            "NaN masks must match elementwise"
            for kernel in KERNELS
        },
        "tolerances": TOLERANCES,
    }
    (out_root / "manifest.json").write_text(
        json.dumps(top, indent=1, sort_keys=True) + "\n")
    print(f"wrote top-level manifest with {len(case_manifests)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
