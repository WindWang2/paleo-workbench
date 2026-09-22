#!/usr/bin/env python3
"""Oracle fixture generator for the C++ factor_host kernel (CONV-08).

Imports the REAL implementations — paleo_workbench.workflow
.interpolation_fingerprint / interpolation_evaluation / interpolation_plan /
factor_interpolation / sample_normalization — and freezes their outputs to
JSON so the C++ port in libs/factor_host can be verified byte-for-byte.

The host environment has no PySide6, so ``import geoviz`` (and the
``geoviz_plots`` package ``__init__``) fails. This generator loads the two
real geoviz leaf modules (factor/directional.py, factor/interpolation.py —
pure numpy) from their source files via importlib and injects them as the
``geoviz`` facade. No expectation value is hand-written: every frozen number,
hash and error text comes from the real modules running in this interpreter.

Regenerate with:

    python3 tools/oracle/generate_factor_host_fixtures.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

def _geoplot_root() -> Path:
    """geo-viz-engine is git-ignored and lives only in the main checkout."""
    candidates = [
        REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_plots" / "geoviz_plots",
        Path("/home/kevin/projects/paleo_project/main/geo-viz-engine/packages"
             "/geoviz_plots/geoviz_plots"),
    ]
    for candidate in candidates:
        if (candidate / "factor" / "interpolation.py").is_file():
            return candidate
    raise SystemExit("geo-viz-engine leaf modules not found; looked in: "
                     + ", ".join(str(c) for c in candidates))


GEOPLOT_ROOT = _geoplot_root()


def _bootstrap_geoviz_leaf_modules() -> None:
    """Load the real geoviz leaf modules without the PySide6-dependent
    package __init__ chain and register them as the ``geoviz`` facade."""
    pkg = types.ModuleType("geoviz_plots")
    pkg.__path__ = [str(GEOPLOT_ROOT)]
    sys.modules["geoviz_plots"] = pkg
    sub = types.ModuleType("geoviz_plots.factor")
    sub.__path__ = [str(GEOPLOT_ROOT / "factor")]
    sys.modules["geoviz_plots.factor"] = sub

    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    directional = _load(
        "geoviz_plots.factor.directional", GEOPLOT_ROOT / "factor" / "directional.py"
    )
    interpolation = _load(
        "geoviz_plots.factor.interpolation", GEOPLOT_ROOT / "factor" / "interpolation.py"
    )
    facade = types.ModuleType("geoviz")
    facade.extract_xy_values = interpolation.extract_xy_values
    facade.interpolate_factor_grid = interpolation.interpolate_factor_grid
    facade.resolve_anisotropy_params = directional.resolve_anisotropy_params
    facade.synthetic_sample_points = interpolation.synthetic_sample_points
    facade.JobCancelled = type("JobCancelled", (Exception,), {})
    sys.modules["geoviz"] = facade


_bootstrap_geoviz_leaf_modules()

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.workflow import factor_interpolation as fi  # noqa: E402
from paleo_workbench.workflow import interpolation_fingerprint as ifp  # noqa: E402
from paleo_workbench.workflow import interpolation_plan as iplan  # noqa: E402
from paleo_workbench.workflow.interpolation_evaluation import (  # noqa: E402
    EvaluationMetrics,
    adjudicate_recommendation,
    bilinear_sample_grid,
    cross_validate_surface,
    leave_one_well_out_folds,
    residual_features,
    signed_r_squared,
    spatial_fold_assignment,
    surface_residuals,
    _validate_recommendation_context,
)
from paleo_workbench.workflow.sample_normalization import (  # noqa: E402
    normalize_factor_samples,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "factor_host"
    / "factor_host_tests"
    / "fixtures"
)


def canonical(payload) -> str:
    """The exact bytes stable_sha256 hashes (Python json canonical form)."""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )


def _num(v):
    """JSON-safe float: non-finite values become string sentinels."""
    if isinstance(v, float) and not math.isfinite(v):
        if math.isnan(v):
            return "NaN"
        return "Infinity" if v > 0 else "-Infinity"
    return v


def clean(obj):
    """Recursively make obj strict-JSON-safe (non-finite floats → sentinels)."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, float):
        return _num(obj)
    if isinstance(obj, (np.floating,)):
        return _num(float(obj))
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    return obj


def fps_dict(fps) -> dict:
    return {
        "geometry": fps.geometry,
        "values": fps.values,
        "algorithm": fps.algorithm,
        "constraints": fps.constraints,
        "result": fps.result,
        "backend": fps.backend,
        "schema_version": fps.schema_version,
        "to_dict": fps.to_dict(),
    }


BASE_XY = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)]


def pts(values, shift=0.0, **extra):
    return [
        {"x": x + shift, "y": y + shift, "value": float(v), **extra}
        for (x, y), v in zip(BASE_XY, values)
    ]


# ---------------------------------------------------------------------------
# fingerprint component cases
# ---------------------------------------------------------------------------

fault_a = [[(10.0, -5.0), (10.0, 6.0)]]
fault_two = [
    [(0.0, 0.5), (1.0, 0.5)],
    [(0.5, 0.0), (0.5, 1.0)],
]
directions_a = [
    {
        "id": "d1",
        "coordinates": [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]],
        "semi_major": 4.0,
        "semi_minor": 1.0,
        "azimuth_deg": 45.0,
    }
]
directions_bad = [
    {"id": "d2", "coordinates": [[0.0, 0.0]]},  # single point → dropped
    "not-a-dict",
    {"coordinates": [[0.0, 0.0], [1.0, 1.0]], "semi_major": "x"},  # bad float
]

fingerprint_cases = []


def fp_case(cid, *, method, grid_n, points, power=2.0, azimuth_deg=0.0,
            semi_major=1.0, semi_minor=0.4, fault_polylines=None,
            direction_params=None, crs=None, generator_version=None,
            target_horizon=None, duplicate_policy=None):
    kwargs = dict(
        sample_points=points,
        method=method,
        grid_n=grid_n,
        power=power,
        azimuth_deg=azimuth_deg,
        semi_major=semi_major,
        semi_minor=semi_minor,
        fault_polylines=fault_polylines,
        direction_params=direction_params,
        crs=crs,
        generator_version=generator_version or ifp.DEFAULT_GENERATOR_VERSION,
        target_horizon=target_horizon,
        duplicate_policy=duplicate_policy,
    )
    fps = ifp.build_factor_fingerprints(**kwargs)
    backend = ifp.resolve_backend(method)
    samples = ifp.extract_sample_records(points)
    xy = [[s["x"], s["y"]] for s in samples]
    zz = [s["z"] for s in samples]
    breaks = (
        ifp._normalize_polylines(fault_polylines)
        if ifp.backend_uses_breaks(backend)
        else []
    )
    dirs = (
        ifp._normalize_direction_params(direction_params)
        if ifp.backend_uses_directions(backend)
        else []
    )
    geometry_payload = {
        "schema": ifp.FINGERPRINT_SCHEMA_VERSION,
        "xy": xy,
        "grid_n": int(grid_n),
        "breaks": breaks,
        "target_horizon": (target_horizon or "").strip(),
    }
    values_payload = {"schema": ifp.FINGERPRINT_SCHEMA_VERSION, "z": zz}
    if backend == "directional":
        values_payload["q"] = [s.get("q") for s in samples]
        values_payload["b_i"] = [s.get("b_i") for s in samples]
        values_payload["qc_flag"] = [s.get("qc_flag") for s in samples]
    algorithm_payload = {
        "schema": ifp.FINGERPRINT_SCHEMA_VERSION,
        "method": str(method),
        "backend": backend,
        "generator_version": str(generator_version or ifp.DEFAULT_GENERATOR_VERSION),
    }
    if duplicate_policy is not None:
        algorithm_payload["duplicate_policy"] = str(duplicate_policy)
    if ifp.backend_uses_power(backend):
        algorithm_payload["power"] = float(power)
    if ifp.backend_uses_anisotropy(backend):
        algorithm_payload["azimuth_deg"] = float(azimuth_deg)
        algorithm_payload["semi_major"] = float(semi_major)
        algorithm_payload["semi_minor"] = float(semi_minor)
    constraints_payload = {
        "schema": ifp.FINGERPRINT_SCHEMA_VERSION,
        "directions": dirs,
        "constrained": backend == "constrained_idw",
    }
    fingerprint_cases.append(
        clean(
            {
                "id": cid,
                "inputs": {
                    "sample_points": points,
                    "method": method,
                    "grid_n": grid_n,
                    "power": power,
                    "azimuth_deg": azimuth_deg,
                    "semi_major": semi_major,
                    "semi_minor": semi_minor,
                    "fault_polylines": fault_polylines,
                    "direction_params": direction_params,
                    "crs": crs,
                    "generator_version": generator_version,
                    "target_horizon": target_horizon,
                    "duplicate_policy": duplicate_policy,
                },
                "payloads": {
                    "geometry": canonical(geometry_payload),
                    "values": canonical(values_payload),
                    "algorithm": canonical(algorithm_payload),
                    "constraints": canonical(constraints_payload),
                },
                "fingerprints": fps_dict(fps),
                "records": samples,
            }
        )
    )


fp_case("idw_basic", method="IDW", grid_n=32, points=pts([1, 2, 3, 4, 5]))
fp_case("idw_swapped_values", method="IDW", grid_n=32, points=pts([2, 1, 3, 4, 5]))
fp_case("idw_shifted_xy", method="IDW", grid_n=32, points=pts([1, 2, 3, 4, 5], shift=0.1))
fp_case("idw_negzero", method="IDW", grid_n=20,
        points=[{"x": 0.0, "y": -0.0, "value": 1.0}])
fp_case("idw_negzero_swapped", method="IDW", grid_n=20,
        points=[{"x": -0.0, "y": 0.0, "value": 1.0}])
fp_case("idw_faults", method="IDW", grid_n=16, points=pts([1, 2, 3, 4, 5]),
        fault_polylines=fault_two)
fp_case("idw_directions_ignored", method="idw", grid_n=16,
        points=pts([1, 2, 3, 4, 5]), direction_params=directions_a)
fp_case("idw_string_numbers", method="mock", grid_n=50.0,
        points=[{"x": "2.5", "y": 3, "value": "4.25"}, {"lng": 1.0, "lat": 2.0, "v": 9.0}])
fp_case("idw_invalid_filtered", method="IDW", grid_n=8,
        points=[
            {"x": 1.0, "y": 2.0, "value": 3.0},
            "not-a-dict",
            {"x": float("nan"), "y": 0.0, "value": 1.0},
            {"x": 0.0, "y": float("inf"), "value": 1.0},
            {"lng": 5.0, "lat": 6.0, "value": 7.5},
            {"x": 1.0, "y": 2.0, "value": None, "z": 3.0},  # value=None wins, no fallback
            {"x": 1.0, "y": 2.0},  # no z at all
            {"a": 1},
            {"x": 4.0, "y": 5.0, "z": 6.0},
        ])
fp_case("kriging_cn", method="克里金", grid_n=40, points=pts([5, 6, 7, 8, 9]))
fp_case("kriging_alias", method="克里金(MVP·线性)", grid_n=40, points=pts([5, 6, 7, 8, 9]))
fp_case("cubic", method="样条", grid_n=24, points=pts([1, 2, 3, 4, 5]))
fp_case("unknown_method", method="mystic", grid_n=24, points=pts([1, 2, 3, 4, 5]))
fp_case("directional_full", method="方向趋势", grid_n=40,
        points=pts([1, 2, 3, 4, 5], q=1.0, b_i=1.0, qc_flag="ok"),
        azimuth_deg=45.0, semi_major=4.0, semi_minor=1.0,
        fault_polylines=fault_a, direction_params=directions_a, crs="EPSG:32650")
fp_case("directional_b_i_changed", method="方向趋势", grid_n=40,
        points=pts([1, 2, 3, 4, 5], q=1.0, b_i=0.1, qc_flag="ok"),
        azimuth_deg=45.0, semi_major=4.0, semi_minor=1.0,
        fault_polylines=fault_a, direction_params=directions_a, crs="EPSG:32650")
fp_case("directional_qc_flagged", method="方向趋势", grid_n=40,
        points=pts([1, 2, 3, 4, 5], q=1.0, b_i=1.0, qc_flag="outlier"),
        azimuth_deg=45.0, semi_major=4.0, semi_minor=1.0,
        fault_polylines=fault_a, direction_params=directions_a, crs="EPSG:32650")
fp_case("directional_nan_weights", method="directional", grid_n=40,
        points=pts([1, 2, 3, 4, 5], q=float("nan"), b_i=float("inf"), qc_flag=None),
        azimuth_deg=0.0, semi_major=1.0, semi_minor=0.4)
fp_case("constrained_full", method="约束IDW", grid_n=24,
        points=pts([2, 4, 6, 8, 10]), power=3.0,
        fault_polylines=fault_a, direction_params=directions_bad, crs=None)
fp_case("idw_duplicate_policy", method="IDW", grid_n=20,
        points=pts([1, 2, 3, 4, 5]), duplicate_policy="mean")
fp_case("idw_dup_policy_keep", method="IDW", grid_n=20,
        points=pts([1, 2, 3, 4, 5]), duplicate_policy="keep")
fp_case("idw_horizon", method="IDW", grid_n=20, points=pts([1, 2, 3, 4, 5]),
        target_horizon="  T1  ")
fp_case("idw_horizon_padded_same", method="IDW", grid_n=20,
        points=pts([1, 2, 3, 4, 5]), target_horizon="T1")
fp_case("idw_gen_version", method="IDW", grid_n=20, points=pts([1, 2, 3, 4, 5]),
        generator_version="factor-interp-v9")
fp_case("idw_grid_n_float", method="IDW", grid_n=32.0, points=pts([1, 2, 3, 4, 5]))
fp_case("idw_empty", method="IDW", grid_n=10, points=[])
# float("0x1p3") raises in Python → sample dropped; "  2.5  " is accepted
# (float strips whitespace). Both are part of the validity contract.
fp_case("idw_hexfloat_string_dropped", method="IDW", grid_n=12,
        points=[
            {"x": "0x1p3", "y": 1.0, "value": 5.0},
            {"x": "  2.5  ", "y": 3.5, "value": 7.0},
        ])
# nan(payload) is a Python ValueError; \x1c is NOT number-strip whitespace.
fp_case("idw_nan_payload_dropped", method="IDW", grid_n=12,
        points=[
            {"x": "nan(1)", "y": 1.0, "value": 5.0},
            {"x": 0.5, "y": 0.5, "value": 1.0},
            {"x": "\x1c5", "y": 2.0, "value": 6.0},
        ])
# Falsy direction ids fall back to "" (str(raw.get("id") or "")); polyline /
# direction coordinates keep -0.0, inf and nan (no _finite_float there).
fp_case("idw_fault_negzero_inf", method="IDW", grid_n=16,
        points=pts([1, 2, 3, 4, 5]),
        fault_polylines=[[(-0.0, 1.0), (2.0, float("inf"))]])
fp_case("constrained_falsy_ids", method="约束IDW", grid_n=24,
        points=pts([2, 4, 6, 8, 10]), power=3.0,
        direction_params=[
            {"id": 0, "coordinates": [[-0.0, -0.0], [1.0, 1.0]]},
            {"id": False, "coordinates": [[0.0, 0.0], [2.0, 2.0]],
             "semi_major": True, "semi_minor": 0.5, "azimuth_deg": "30"},
        ])
fp_case("idw_unicode_horizon", method="IDW", grid_n=20,
        points=pts([1, 2, 3, 4, 5]), target_horizon=" T1　")

# ---------------------------------------------------------------------------
# classify cases — each entry: task fields + resolved current fingerprints +
# force flag → expected FactorDirtyState value.
# ---------------------------------------------------------------------------

classify_cases = []


def _task_fps(points, **kwargs):
    return ifp.build_factor_fingerprints(sample_points=points, **kwargs)


CLASSIFY_BASE = pts([1, 2, 3, 4, 5])


def classify_case(cid, *, parameters, grid_metadata=None, status="complete",
                  input_snapshot_hash=None, grid_artifact_path=None,
                  grid_z_inline=None, current=None, force=False,
                  method="IDW", grid_n=20):
    task = types.SimpleNamespace(
        id="task-1",
        status=status,
        parameters=parameters,
        grid_metadata=grid_metadata or {},
        input_snapshot_hash=input_snapshot_hash,
        grid_artifact_path=grid_artifact_path,
    )
    if current is None:
        # The CURRENT derivation is built from the task's own (possibly
        # edited) sample set — exactly what fingerprints_for_task does.
        current = _task_fps(parameters.get("sample_points") or [],
                            method=method, grid_n=grid_n)
    state = ifp.classify_factor_recompute(task, current, force=force)
    entry = {
        "id": cid,
        "task": {
            "parameters": parameters,
            "grid_metadata": grid_metadata or {},
            "status": status,
            "input_snapshot_hash": input_snapshot_hash,
            "grid_artifact_path": grid_artifact_path,
        },
        "current": fps_dict(current),
        "force": force,
        "expected": state.value if hasattr(state, "value") else str(state),
    }
    classify_cases.append(clean(entry))


_fresh = _task_fps(CLASSIFY_BASE, method="IDW", grid_n=20)
_stored = _fresh.to_dict()
_constrained_stored = _task_fps(
    CLASSIFY_BASE, method="约束IDW", grid_n=20,
    direction_params=directions_a).to_dict()

classify_case("force", parameters={"sample_points": CLASSIFY_BASE}, force=True)
classify_case("clean", parameters={
    "sample_points": CLASSIFY_BASE, **_stored, "grid_z": [[1.0, 2.0]]})
# grid_z is `is not None` for has-output purposes: [] / 0 count as output
# even though they are falsy.
classify_case("clean_grid_z_empty_list", parameters={
    "sample_points": CLASSIFY_BASE, **_stored, "grid_z": []})
classify_case("clean_grid_z_zero", parameters={
    "sample_points": CLASSIFY_BASE, **_stored, "grid_z": 0})
classify_case("unknown_legacy_empty_grid_z", parameters={
    "sample_points": CLASSIFY_BASE, "grid_z": []},
    input_snapshot_hash="deadbeef")
classify_case("missing_output_pending", parameters={"sample_points": CLASSIFY_BASE},
              status="pending")
classify_case("missing_output_complete_with_path", parameters={
    "sample_points": CLASSIFY_BASE, **_stored},
    grid_artifact_path="/nonexistent/path/factor.factor_grid.npz")
classify_case("missing_output_no_stored_pending", parameters={
    "sample_points": CLASSIFY_BASE}, status="pending")
classify_case("unknown_legacy_complete", parameters={
    "sample_points": CLASSIFY_BASE, "grid_z": [[1.0, 2.0]]},
    input_snapshot_hash="deadbeef")
classify_case("legacy_monolithic_match", parameters={
    "sample_points": CLASSIFY_BASE, "grid_z": [[1.0, 2.0]]},
    input_snapshot_hash=_fresh.result)
classify_case("dirty_values", parameters={
    "sample_points": pts([9, 2, 3, 4, 5]), **_stored, "grid_z": [[1.0]]})
classify_case("dirty_geometry", parameters={
    "sample_points": pts([1, 2, 3, 4, 5], shift=0.2), **_stored,
    "grid_z": [[1.0]]})
# Algorithm-only drift: method label changes the algorithm payload while the
# resolved backend (idw) keeps geometry / values / constraints identical.
classify_case("dirty_algorithm_method_label", parameters={
    "sample_points": CLASSIFY_BASE, **_stored, "grid_z": [[1.0]]},
    method="idw")
classify_case("dirty_algorithm_crs_drift", parameters={
    "sample_points": CLASSIFY_BASE, **_stored, "grid_z": [[1.0]]},
    current=_task_fps(CLASSIFY_BASE, method="IDW", grid_n=20,
                      crs="EPSG:4326"))
# Constraints-only drift: constrained backend, different direction lines,
# no faults (breaks stay empty on both sides so geometry is untouched).
classify_case("dirty_constraints", parameters={
    "sample_points": CLASSIFY_BASE, **_constrained_stored, "grid_z": [[1.0]]},
    method="约束IDW",
    current=_task_fps(CLASSIFY_BASE, method="约束IDW", grid_n=20,
                      direction_params=directions_bad))
classify_case("no_output_complete_no_stored", parameters={
    "sample_points": CLASSIFY_BASE}, status="complete")

# ---------------------------------------------------------------------------
# plan cases
# ---------------------------------------------------------------------------

plan_cases = {"xy_signature": [], "fault_signature": [], "plan_key": [],
              "build_idw_plan": [], "extract_values_aligned": []}

rng = np.random.default_rng(7)
_xy40x = [float(v) for v in rng.uniform(-1e6, 1e6, 40)]
_xy40y = [float(v) for v in rng.uniform(-1e6, 1e6, 40)]
for cid, x, y in [
    ("empty", [], []),
    ("single", [1.5], [2.5]),
    ("pair", [1.0, 2.0], [3.0, 4.0]),
    ("negzero", [0.0, -0.0], [-0.0, 0.0]),
    ("big", [5e15, 1.23456789e-5], [-7.5e-7, 42.0]),
    ("forty", _xy40x, _xy40y),
    ("with_nan", [1.0, float("nan")], [2.0, 3.0]),
]:
    plan_cases["xy_signature"].append(
        {"id": cid, "x": clean(x), "y": clean(y),
         "sig": iplan.xy_signature(np.asarray(x, dtype=np.float64),
                                   np.asarray(y, dtype=np.float64))})

for cid, poly in [
    ("none", None),
    ("empty_list", []),
    ("one", fault_a),
    ("two", fault_two),
    ("bad_points", [[(0.0, 0.0)], [(1.0, 1.0), (2.0, 2.0)]]),
]:
    plan_cases["fault_signature"].append(
        {"id": cid, "polylines": clean(poly),
         "sig": iplan._fault_signature(poly)})

for cid, kwargs in [
    ("plain", dict(method="idw", x=[1.0, 2.0], y=[3.0, 4.0], grid_n=50)),
    ("power", dict(method="idw", x=[1.0, 2.0], y=[3.0, 4.0], grid_n=50,
                   power=3.0)),
    ("faults", dict(method="idw", x=[1.0, 2.0], y=[3.0, 4.0], grid_n=50,
                    fault_polylines=fault_a)),
    ("aniso", dict(method="idw", x=[1.0, 2.0], y=[3.0, 4.0], grid_n=50,
                   azimuth_deg=30.0, semi_major=2.0, semi_minor=0.5)),
    ("tiny_grid", dict(method="idw", x=[0.0], y=[0.0], grid_n=1)),
]:
    kwargs = {
        **{"power": 2.0, "fault_polylines": None, "azimuth_deg": 0.0,
           "semi_major": 1.0, "semi_minor": 0.4},
        **kwargs,
    }
    key = iplan.plan_key_from_arrays(**kwargs)
    plan_cases["plan_key"].append(
        {"id": cid, "kwargs": clean(
            {**kwargs, "x": list(kwargs["x"]), "y": list(kwargs["y"])}),
         "fields": {"method": key.method, "xy_sig": key.xy_sig,
                    "grid_n": key.grid_n, "power": key.power,
                    "fault_sig": key.fault_sig,
                    "azimuth_deg": key.azimuth_deg,
                    "semi_major": key.semi_major,
                    "semi_minor": key.semi_minor},
         "digest": key.digest()})

plan_pts = pts([1.0, 2.0, 3.0, 4.0, 2.5])
plan_pts_lnglat = [
    {"lng": 10.0, "lat": 20.0, "value": 5.0},
    {"x": 30.0, "y": 40.0, "value": 6.0},
    {"lng": 50.0, "lat": 60.0, "z": 7.0},
]
plan_pts_faulted = pts([9.0, 8.0, 7.0, 6.0, 5.0])
for cid, sample_points, grid_n, power, fault in [
    ("basic", plan_pts, 16, 2.0, None),
    ("faulted", plan_pts_faulted, 12, 3.0, fault_two),
    ("lnglat", plan_pts_lnglat, 8, 2.0, None),
    ("grid_n_one", plan_pts, 1, 2.0, None),
]:
    plan = iplan.build_idw_plan(sample_points, grid_n=grid_n, power=power,
                                fault_polylines=fault)
    plan_cases["build_idw_plan"].append(clean({
        "id": cid,
        "inputs": {"sample_points": sample_points, "grid_n": grid_n,
                   "power": power, "fault_polylines": fault},
        "source_x": plan.source_x.tolist(),
        "source_y": plan.source_y.tolist(),
        "grid_x": plan.grid_x.tolist(),
        "grid_y": plan.grid_y.tolist(),
        "fault_polylines": plan.fault_polylines,
        "geometry_id": plan.geometry_id,
        "key": {"method": plan.key.method, "xy_sig": plan.key.xy_sig,
                "grid_n": plan.key.grid_n, "power": plan.key.power,
                "fault_sig": plan.key.fault_sig,
                "azimuth_deg": plan.key.azimuth_deg,
                "semi_major": plan.key.semi_major,
                "semi_minor": plan.key.semi_minor,
                "digest": plan.key.digest()},
    }))

plan_cases["build_idw_plan_errors"] = [
    {"id": "single_point", "sample_points": [{"x": 0.0, "y": 0.0, "value": 1.0}],
     "error": None},
    {"id": "empty", "sample_points": [], "error": None},
    {"id": "all_nonfinite",
     "sample_points": [{"x": float("nan"), "y": 0.0, "value": 1.0}], "error": None},
]
for entry in plan_cases["build_idw_plan_errors"]:
    try:
        iplan.build_idw_plan(entry["sample_points"], grid_n=10)
    except ValueError as exc:
        entry["error"] = str(exc)

aligned_pts = plan_pts
aligned_plan = iplan.build_idw_plan(aligned_pts, grid_n=16)
values = [p["value"] for p in aligned_pts]
plan_cases["extract_values_aligned"].append(clean({
    "id": "ok", "sample_points": aligned_pts, "values": values}))
bad_pts = [dict(p) for p in aligned_pts]
bad_pts[0] = {**bad_pts[0], "x": 9.0}
try:
    iplan.extract_values_aligned(bad_pts, aligned_plan)
    plan_cases["extract_values_aligned"].append(
        {"id": "mismatch", "sample_points": clean(bad_pts), "error": None})
except ValueError as exc:
    plan_cases["extract_values_aligned"].append(
        clean({"id": "mismatch", "plan_points": aligned_pts,
               "sample_points": bad_pts, "error": str(exc)}))

# ---------------------------------------------------------------------------
# evaluation cases
# ---------------------------------------------------------------------------

eval_cases = {"metrics": [], "signed_r2": [], "bilinear": [], "folds": [],
              "lowo": [], "cross_validate": [], "surface_residuals": [],
              "residual_features": [], "context": [], "adjudicate": []}

for cid, observed, predicted in [
    ("perfect", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
    ("poor", [1.0, 2.0, 3.0], [3.0, 2.0, 1.0]),
    ("skipped", [1.0, 2.0, float("nan"), 4.0], [1.5, float("nan"), 9.0, 4.5]),
    ("all_skipped", [float("nan"), 1.0], [1.0, float("nan")]),
    ("constant_observed", [2.0, 2.0], [2.0, 1.0]),
    ("single", [5.0], [4.0]),
    ("empty", [], []),
    ("bias", [10.0, 20.0, 30.0], [11.0, 21.0, 31.0]),
]:
    m = EvaluationMetrics.from_arrays(observed, predicted)
    eval_cases["metrics"].append(clean({
        "id": cid, "observed": observed, "predicted": predicted,
        "metrics": m.to_dict(), "n_samples": m.n_samples,
        "n_skipped": m.n_skipped}))
try:
    EvaluationMetrics.from_arrays([1.0, 2.0, 3.0], [1.0, 2.0])
    eval_cases["metrics"].append(
        {"id": "shape_mismatch", "observed": [1.0, 2.0, 3.0],
         "predicted": [1.0, 2.0], "error": None})
except ValueError as exc:
    eval_cases["metrics"].append({
        "id": "shape_mismatch", "observed": [1.0, 2.0, 3.0],
        "predicted": [1.0, 2.0], "error": str(exc)})

for cid, observed, predicted in [
    ("perfect", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
    ("terrible", [1.0, 2.0, 3.0], [10.0, -10.0, 30.0]),
    ("constant", [2.0, 2.0], [2.0, 1.0]),
    ("negative", [1.0, 2.0, 3.0], [3.0, 2.0, 1.0]),
]:
    eval_cases["signed_r2"].append({
        "id": cid, "observed": observed, "predicted": predicted,
        "r2": signed_r_squared(np.asarray(observed), np.asarray(predicted))})

gx = [0.0, 1.0, 2.0]
gy = [0.0, 1.0]
gz = [[0.0, 10.0, 20.0], [0.0, 10.0, 20.0]]
hole = [row[:] for row in gz]
hole[0][1] = float("nan")
gy_three = [0.0, 1.0, 2.0]
gz_three = [[0.0, 10.0, 20.0], [1.0, 11.0, 21.0], [2.0, 12.0, 22.0]]
for cid, grid_z, grid_x, grid_y, px, py in [
    ("midpoint", gz, gx, gy, 0.5, 0.5),
    ("corner", gz, gx, gy, 2.0, 0.0),
    ("hole", hole, gx, gy, 0.5, 0.0),
    ("off_grid_x", gz, gx, gy, 3.0, 0.0),
    ("off_grid_neg", gz, gx, gy, -0.1, 0.0),
    ("interior", gz_three, gx, gy_three, 1.5, 1.25),
    ("nonfinite_query", gz, gx, gy, float("nan"), 0.0),
    ("single_column", [[5.0], [7.0]], [1.0], [0.0, 2.0], 1.0, 1.0),
    ("single_row", [[3.0, 9.0]], [0.0, 4.0], [7.0], 2.0, 7.0),
    ("single_cell", [[4.0]], [1.0], [1.0], 1.0, 1.0),
    ("single_col_far_x", [[5.0], [7.0]], [1.0], [0.0, 2.0], 5000.0, 1.0),
    ("single_row_far_y", [[3.0, 9.0]], [0.0, 4.0], [7.0], 2.0, -99.0),
]:
    sampled = bilinear_sample_grid(
        np.asarray(grid_z, dtype=float), np.asarray(grid_x),
        np.asarray(grid_y), px, py)
    eval_cases["bilinear"].append(clean({
        "id": cid, "grid_z": grid_z, "grid_x": grid_x, "grid_y": grid_y,
        "px": px, "py": py, "sampled": sampled}))

fold_xs = [0.0, 10.0, 20.0, 30.0, 5.0, 15.0, 25.0, 35.0, 12.0, 22.0,
           32.0, 2.0]
fold_ys = [0.0, 5.0, 0.0, 5.0, 10.0, 15.0, 10.0, 15.0, 5.0, 5.0, 5.0, 0.0]
rng_f = np.random.default_rng(7)
fold_rand_x = [float(v) for v in rng_f.uniform(0, 100, 40)]
fold_rand_y = [float(v) for v in rng_f.uniform(0, 100, 40)]
for cid, x, y, k in [
    ("k4", fold_xs, fold_ys, 4),
    ("k3_rand", fold_rand_x, fold_rand_y, 3),
    ("k2", fold_xs[:6], fold_ys[:6], 2),
    ("tied_angles", [1.0, 1.0, 1.0, 2.0], [1.0, 1.0, 1.0, 1.0], 2),
    ("k_too_many", fold_xs[:5], fold_ys[:5], 7),
    # NaN coordinate → mean NaN → every angle NaN → numpy keeps input order.
    ("nan_angles", [0.0, 1.0, float("nan")], [0.0, 1.0, 0.0], 2),
]:
    folds = spatial_fold_assignment(x, y, k)
    eval_cases["folds"].append({
        "id": cid, "x": x, "y": y, "k": k,
        "folds": [[int(i) for i in f] for f in folds]})
eval_cases["folds"].append({
    "id": "empty", "x": [], "y": [], "k": 4, "folds": []})
for cid, x, y, k, error in [
    ("k1", [0.0], [0.0], 1, "k must be >= 2, got 1"),
    ("size_mismatch", [0.0, 1.0], [0.0], 2, "x/y size mismatch"),
]:
    try:
        spatial_fold_assignment(x, y, k)
        eval_cases["folds"].append(
            {"id": cid, "x": x, "y": y, "k": k, "error": None})
    except ValueError as exc:
        eval_cases["folds"].append(
            {"id": cid, "x": x, "y": y, "k": k, "error": str(exc)})

lowo_pts = [
    {"well_id": "w1", "x": 0.0, "y": 0.0, "value": 1.0},
    {"x": 1.0, "y": 1.0, "value": 2.0},
    {"well_id": "w2", "x": 2.0, "y": 2.0, "value": 3.0},
    {"name": "W3", "x": 3.0, "y": 3.0, "value": 4.0},
    {"name": "W3", "x": 3.5, "y": 3.5, "value": 5.0},
    {"well_id": "  ", "x": 4.0, "y": 4.0, "value": 6.0},
    {"well_id": "w1", "x": 0.5, "y": 0.5, "value": 1.5},
]
eval_cases["lowo"].append({
    "id": "mixed", "points": lowo_pts,
    "folds": [[int(i) for i in f]
              for f in leave_one_well_out_folds(lowo_pts)]})


def _linear_points(n, seed):
    r = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        x = float(r.uniform(0, 100))
        y = float(r.uniform(0, 100))
        out.append({"x": x, "y": y, "value": 0.5 * x + 2.0 * y + 10.0})
    return out


def _crude_idw_fold(train):
    xs = np.array([p["x"] for p in train])
    ys = np.array([p["y"] for p in train])
    zs = np.array([p["value"] for p in train])
    gx_, gy_ = np.meshgrid(
        np.linspace(xs.min() - 50, xs.max() + 50, 40),
        np.linspace(ys.min() - 50, ys.max() + 50, 40),
    )
    d = np.sqrt(
        (gx_[:, :, None] - xs[None, None, :]) ** 2
        + (gy_[:, :, None] - ys[None, None, :]) ** 2
    ) + 1e-9
    gz_ = (zs[None, None, :] / d**2).sum(-1) / (1.0 / d**2).sum(-1)
    return gx_[0], gy_[:, 0], gz_


def _flat_fold(train):
    xs = np.array([p["x"] for p in train])
    ys = np.array([p["y"] for p in train])
    gx_ = np.linspace(xs.min() - 50, xs.max() + 50, 8)
    gy_ = np.linspace(ys.min() - 50, ys.max() + 50, 6)
    return gx_, gy_, np.zeros((6, 8))


def _boom_fold(train):
    raise ValueError("engine exploded")


def _hole_fold(train):
    gx_, gy_, _ = _crude_idw_fold(train)
    return gx_, gy_, np.full((len(gy_), len(gx_)), np.nan)


cv_points24 = _linear_points(24, 11)
cv_points4 = _linear_points(4, 11)
twins = [dict(p) for p in cv_points24[:20]]
with_twins = cv_points24 + twins
nonfinite_pts = cv_points24 + [{"x": float("nan"), "y": 0.0, "value": 1.0}]
for cid, points, k, engine_fn, label in [
    ("idw_k4", cv_points24, 4, _crude_idw_fold, "IDW"),
    ("too_few", cv_points4, 4, _crude_idw_fold, "IDW"),
    ("boom", cv_points24, 4, _boom_fold, "X"),
    ("hole", _linear_points(12, 11), 4, _hole_fold, "IDW"),
    ("twins", with_twins, 4, _crude_idw_fold, "IDW"),
    ("nonfinite", nonfinite_pts, 4, _crude_idw_fold, "IDW"),
    ("flat", cv_points24, 3, _flat_fold, "flat"),
]:
    report = cross_validate_surface(points, run_fold=engine_fn, k=k,
                                    method_label=label, engine="test")
    eval_cases["cross_validate"].append(clean({
        "id": cid, "points": points, "k": k,
        "report": report.to_dict() if report is not None else None,
        # to_dict() intentionally omits residuals; freeze them separately.
        "residuals": report.residuals if report is not None else None}))

sr_points = _linear_points(12, 5)
sr_plan_grid = _crude_idw_fold(sr_points)
records, sr_metrics = surface_residuals(
    sr_points, sr_plan_grid[0], sr_plan_grid[1], sr_plan_grid[2])
eval_cases["surface_residuals"].append(clean({
    "id": "linear", "points": sr_points,
    "grid_x": sr_plan_grid[0].tolist(), "grid_y": sr_plan_grid[1].tolist(),
    "grid_z": sr_plan_grid[2].tolist(),
    "records": records, "metrics": sr_metrics.to_dict()}))

eval_cases["residual_features"].append(clean({
    "id": "basic",
    "residuals": [{"x": 1.0, "y": 2.0, "value": 3.0, "predicted": 2.5,
                   "residual": 0.5}],
    "features": residual_features(
        [{"x": 1.0, "y": 2.0, "value": 3.0, "predicted": 2.5,
          "residual": 0.5}])}))

HAS_PYPROJ = True
try:
    import pyproj  # noqa: F401
except ImportError:
    HAS_PYPROJ = False

for cid, unit, crs in [
    ("unit_none", None, None),
    ("unit_blank", "   ", None),
    ("unit_m", "m", None),
    ("unit_cn", "米", None),
    ("unit_percent", "%", None),
    ("unit_ratio", "ratio", None),
    ("unit_md", "mD", None),
    ("unit_one", "1", None),
    ("unit_upper_ft", "FT", None),
    ("unit_unknown", "furlongs", None),
    ("unit_quote", "fur'longs", None),
    ("unit_nbsp", "\u00a0", None),
    ("unit_gcm3", "g/cm3", None),
    ("unit_uscm", "us/cm", None),
    ("unit_vv", "v/v", None),
    ("unit_api", "api", None),
    ("unit_dimensionless", "dimensionless", None),
    ("crs_valid", "m", "EPSG:4326"),
    ("crs_garbage", "m", "NOT::A::CRS"),
    ("crs_blank", "m", "  "),
    ("crs_none", "m", None),
    ("crs_epsg_32650", "m", "EPSG:32650"),
]:
    warnings_, gate = _validate_recommendation_context(unit, crs)
    eval_cases["context"].append({
        "id": cid, "unit": unit, "crs": crs,
        "warnings": warnings_, "gate": gate})

for cid, entries, gate, unknown, caveat in [
    ("open_best", [
        {"method": "IDW", "metrics": {"rmse": 3.0}, "capability_warnings": []},
        {"method": "克里金", "metrics": {"rmse": 1.5}, "capability_warnings": []},
    ], None, None, ""),
    ("gate_unit", [
        {"method": "IDW", "metrics": {"rmse": 3.0}, "capability_warnings": []},
    ], "unit_unknown", None, ""),
    ("unknown_constraint", [
        {"method": "IDW", "metrics": {"rmse": 3.0}, "capability_warnings": []},
        {"method": "样条", "metrics": {"rmse": 1.0}, "capability_warnings": []},
    ], None, ["unicorn_barrier"], ""),
    ("unknown_constraint_quote", [
        {"method": "IDW", "metrics": {"rmse": 3.0}, "capability_warnings": []},
    ], None, ["unicorn'_barrier"], ""),
    ("unsupported_disqualified", [
        {"method": "IDW", "metrics": {"rmse": 0.5},
         "capability_warnings": ["barrier: :unsupported: by this method"]},
        {"method": "约束IDW", "metrics": {"rmse": 4.0}, "capability_warnings": []},
    ], None, None, ""),
    ("null_metrics_skipped", [
        {"method": "IDW", "metrics": None, "capability_warnings": []},
        {"method": "克里金", "metrics": {"rmse": 2.0}, "capability_warnings": []},
    ], None, None, ""),
    ("caveat", [
        {"method": "IDW", "metrics": {"rmse": 3.0}, "capability_warnings": []},
        {"method": "克里金", "metrics": {"rmse": 1.5}, "capability_warnings": []},
    ], None, None, "schemes differ across methods"),
    ("all_none_metrics", [
        {"method": "IDW", "metrics": None, "capability_warnings": []},
    ], None, None, ""),
    ("missing_rmse_is_inf", [
        {"method": "IDW", "metrics": {"rmse": None}, "capability_warnings": []},
        {"method": "克里金", "metrics": {"rmse": 9.0}, "capability_warnings": []},
    ], None, None, ""),
]:
    mutated, recommended = adjudicate_recommendation(
        json.loads(json.dumps(entries)), gate=gate,
        unknown_constraints=unknown, scheme_caveat=caveat)
    eval_cases["adjudicate"].append({
        "id": cid, "entries": entries, "gate": gate,
        "unknown_constraints": unknown, "scheme_caveat": caveat,
        "mutated": mutated, "recommended_method": recommended})

# ---------------------------------------------------------------------------
# factor_interop cases (resolve_engine_method / variogram / task params)
# ---------------------------------------------------------------------------

interop_cases = {"resolve_engine_method": [], "variogram": [],
                 "interp_params": []}

for label in ["克里金", "克里金(MVP·线性)", "IDW", "idw", "样条", "spline",
              "cubic", "方向趋势", "directional", "kriging", "约束IDW",
              "constrained_idw", "mock", "not-a-real-method", "", "a'b"]:
    try:
        mapped = fi.resolve_engine_method(label)
        interop_cases["resolve_engine_method"].append(
            {"id": label or "empty", "input": label, "engine": mapped,
             "error": None})
    except ValueError as exc:
        interop_cases["resolve_engine_method"].append(
            {"id": label or "empty", "input": label, "engine": None,
             "error": str(exc)})

for cid, params in [
    ("full", {"variogram_model": "gaussian", "variogram_range": 25.0,
              "variogram_nugget": 0.5}),
    ("aliases", {"range_m": 30.0, "nugget": 1.0}),
    ("mixed", {"variogram_model": "spherical", "range_m": 12.0,
               "variogram_range": 99.0}),
    ("none_values", {"variogram_model": None, "variogram_range": None}),
    ("empty", {}),
]:
    interop_cases["variogram"].append({
        "id": cid, "params": params,
        "settings": fi.variogram_settings_from_params(params)})

for cid, params, task_method in [
    ("recorded", {"sample_points": [], "grid_n": 24, "power": 3.0}, "克里金"),
    ("defaults", {"sample_points": []}, "IDW"),
    ("zero_grid_n", {"grid_n": 0, "power": 0.0}, "idw"),
    ("float_truncation", {"grid_n": 24.9, "power": 2.9}, "IDW"),
    ("string_float_grid_n", {"grid_n": "24.7"}, "IDW"),
    ("string_int_grid_n", {"grid_n": "24"}, "IDW"),
    ("bad_types", {"grid_n": [], "power": {}}, "样条"),
    ("empty_string_method", {"method": ""}, ""),
    ("method_in_params", {"method": "克里金"}, "IDW"),
    ("negative", {"grid_n": -5, "power": -1.5}, "IDW"),
    ("method_number", {"method": 5, "grid_n": 10}, 5),
    ("method_bool", {"method": True}, "IDW"),
    ("grid_n_filesep", {"grid_n": "\x1c24", "power": 2.0}, "IDW"),
]:
    method, grid_n, power = fi.interpolation_params_from_task(
        types.SimpleNamespace(parameters=params, method=task_method))
    interop_cases["interp_params"].append({
        "id": cid, "params": clean(params), "task_method": task_method,
        "method": method, "grid_n": grid_n, "power": power})

# ---------------------------------------------------------------------------
# normalization-fed fingerprint parity (V8 M3 contract, real normalize call)
# ---------------------------------------------------------------------------

norm_raw = pts([50.0, 60.0]) + [
    {"x": 5.0, "y": 5.0, "value": 20.0, "well_id": "t1"},
    {"x": 5.0, "y": 5.0, "value": 30.0, "well_id": "t2"},
]
normalized, report = normalize_factor_samples(norm_raw, policy="mean")
parity = {
    "raw": clean(norm_raw),
    "normalized": clean(normalized),
    "report": report.to_dict(),
    "fps_on_raw": fps_dict(ifp.build_factor_fingerprints(
        sample_points=norm_raw, method="IDW", grid_n=20,
        target_horizon="H1")),
    "fps_on_normalized": fps_dict(ifp.build_factor_fingerprints(
        sample_points=normalized, method="IDW", grid_n=20,
        target_horizon="H1", duplicate_policy=(
            report.policy if report.duplicates_present else None))),
}

fixture = {
    "meta": {
        "generator": "tools/oracle/generate_factor_host_fixtures.py",
        "baseline_commit": "35987e13",
        "pyproj_used": HAS_PYPROJ,
        "schema_version": ifp.FINGERPRINT_SCHEMA_VERSION,
        "default_generator_version": ifp.DEFAULT_GENERATOR_VERSION,
        "default_cv_folds": 4,
        "constrained_idw_label": "constrained_idw",
        "default_grid_n": fi.DEFAULT_GRID_N,
        "generator_version": fi.GENERATOR_VERSION,
        "max_loo_samples": fi.MAX_LOO_SAMPLES,
        "method_to_backend": ifp.METHOD_TO_BACKEND,
        "method_label_to_engine": fi.METHOD_LABEL_TO_ENGINE,
        "default_factor_types": list(fi.DEFAULT_FACTOR_TYPES),
        "known_units": sorted([
            "m", "米", "ft", "feet", "英尺", "%", "percent", "ratio",
            "dimensionless", "v/v", "g/cm3", "api", "us/cm", "md", "1",
        ]),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
    },
    "fingerprint": fingerprint_cases,
    "classify": classify_cases,
    "plan": plan_cases,
    "evaluation": eval_cases,
    "interop": interop_cases,
    "normalization_parity": parity,
}

OUT.mkdir(parents=True, exist_ok=True)
text = json.dumps(clean(fixture), ensure_ascii=False, indent=1, allow_nan=False)
out_path = OUT / "factor_host_oracle.json"
out_path.write_text(text + "\n", encoding="utf-8")
n_cases = (
    len(fingerprint_cases)
    + len(classify_cases)
    + sum(len(v) for v in plan_cases.values())
    + sum(len(v) for v in eval_cases.values())
    + sum(len(v) for v in interop_cases.values())
    + 1
)
print(f"froze {n_cases} cases → {out_path.relative_to(REPO_ROOT)} "
      f"({len(text)} bytes)")
