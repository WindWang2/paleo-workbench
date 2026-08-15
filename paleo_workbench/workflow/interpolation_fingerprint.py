"""Deterministic scientific dependency fingerprints for factor interpolation.

Stage-4: decide *whether* a FactorMapTask must be recomputed without relying on
UI state, wall-clock timestamps, or incomplete legacy hashes.

Fingerprints are SHA-256 of canonical JSON (sorted keys).  Python's built-in
``hash()`` is never used for persisted identity.

Component digests:

* **geometry** — sample XY (order preserved), grid_n, fault polyline geometry
* **values** — sample Z (same order as geometry samples)
* **algorithm** — resolved backend, power / anisotropy, generator version
* **constraints** — direction corridors and other non-fault constraint params
* **result** — combination of the above + CRS (output identity)

Dirty classification prefers false DIRTY over false CLEAN.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from geoviz import resolve_anisotropy_params

from paleo_workbench.workflow.constrained_idw_adapter import CONSTRAINED_IDW_ENGINE_LABEL
from paleo_workbench.workflow.constraints import (
    break_polylines_for_idw,
    constraint_layers_for_project,
    direction_line_params,
)

FINGERPRINT_SCHEMA_VERSION = 1

# Keep in sync with factor_interpolation.GENERATOR_VERSION when calling builders.
DEFAULT_GENERATOR_VERSION = "factor-interp-v1"

METHOD_TO_BACKEND = {
    "克里金": "kriging",
    "克里金(MVP·线性)": "kriging",
    "IDW": "idw",
    "idw": "idw",
    "样条": "cubic",
    "方向趋势": "directional",
    "约束IDW": CONSTRAINED_IDW_ENGINE_LABEL,
    "mock": "idw",
    "kriging": "kriging",
    "directional": "directional",
    CONSTRAINED_IDW_ENGINE_LABEL: CONSTRAINED_IDW_ENGINE_LABEL,
}


class FactorDirtyState(str, Enum):
    CLEAN = "CLEAN"
    DIRTY_VALUES = "DIRTY_VALUES"
    DIRTY_GEOMETRY = "DIRTY_GEOMETRY"
    DIRTY_ALGORITHM = "DIRTY_ALGORITHM"
    DIRTY_CONSTRAINTS = "DIRTY_CONSTRAINTS"
    MISSING_OUTPUT = "MISSING_OUTPUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FactorFingerprints:
    geometry: str
    values: str
    algorithm: str
    constraints: str
    result: str
    schema_version: int = FINGERPRINT_SCHEMA_VERSION
    backend: str = "idw"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "geometry_fingerprint": self.geometry,
            "values_fingerprint": self.values,
            "algorithm_fingerprint": self.algorithm,
            "constraints_fingerprint": self.constraints,
            "result_fingerprint": self.result,
            "backend": self.backend,
        }


def stable_sha256(payload: Any) -> str:
    """SHA-256 of canonical JSON (sorted keys, compact separators)."""
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    # Normalize -0.0 → 0.0 so the fingerprint is insensitive to sign-of-zero
    # (identical science, identical hash).
    return number + 0.0


def extract_sample_records(
    sample_points: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Pull ordered (x, y, z) samples with the same validity rules as extract_xy_values.

    Order is preserved: algorithms may depend on sample order for ties/duplicates.
    Directional-engine extras (``q``/``b_i``/``qc_flag``) ride along so the
    fingerprint can cover them for that backend (H11).
    """
    out: list[dict[str, Any]] = []
    for pt in sample_points or []:
        if not isinstance(pt, dict):
            continue
        x = y = z = None
        try:
            if "x" in pt and "y" in pt:
                x = _finite_float(pt["x"])
                y = _finite_float(pt["y"])
            elif "lng" in pt and "lat" in pt:
                x = _finite_float(pt["lng"])
                y = _finite_float(pt["lat"])
            else:
                continue
            z = _finite_float(pt.get("value", pt.get("z", pt.get("v"))))
        except (TypeError, ValueError):
            continue
        if x is None or y is None or z is None:
            continue
        record: dict[str, Any] = {"x": x, "y": y, "z": z}
        for key in ("q", "b_i"):
            if key in pt and pt[key] is not None:
                try:
                    record[key] = float(pt[key])
                except (TypeError, ValueError):
                    pass
        if "qc_flag" in pt and pt["qc_flag"] is not None:
            record["qc_flag"] = str(pt["qc_flag"])
        out.append(record)
    return out


def resolve_backend(method: str) -> str:
    return METHOD_TO_BACKEND.get(method, "idw")


def backend_uses_breaks(backend: str) -> bool:
    return backend in {"idw", CONSTRAINED_IDW_ENGINE_LABEL}


def backend_uses_directions(backend: str) -> bool:
    return backend in {"directional", CONSTRAINED_IDW_ENGINE_LABEL}


def backend_uses_power(backend: str) -> bool:
    return backend in {"idw", CONSTRAINED_IDW_ENGINE_LABEL}


def backend_uses_anisotropy(backend: str) -> bool:
    return backend in {"directional"}


def _normalize_polylines(
    polylines: Sequence[Sequence[tuple[float, float] | list[float]]] | None,
) -> list[list[list[float]]]:
    """Normalize polylines without reordering vertices or polylines."""
    out: list[list[list[float]]] = []
    for poly in polylines or []:
        pts: list[list[float]] = []
        for p in poly:
            try:
                pts.append([float(p[0]), float(p[1])])
            except (TypeError, ValueError, IndexError):
                continue
        if len(pts) >= 2:
            out.append(pts)
    return out


def _normalize_direction_params(params: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in params or []:
        if not isinstance(raw, dict):
            continue
        coords = raw.get("coordinates") or []
        pts: list[list[float]] = []
        for p in coords:
            try:
                pts.append([float(p[0]), float(p[1])])
            except (TypeError, ValueError, IndexError):
                continue
        if len(pts) < 2:
            continue
        entry: dict[str, Any] = {
            "id": str(raw.get("id") or ""),
            "coordinates": pts,
        }
        for key in ("semi_major", "semi_minor", "azimuth_deg"):
            if raw.get(key) is not None:
                try:
                    entry[key] = float(raw[key])
                except (TypeError, ValueError):
                    pass
        out.append(entry)
    return out


def build_factor_fingerprints(
    *,
    sample_points: Sequence[dict[str, Any]] | None,
    method: str,
    grid_n: int,
    power: float = 2.0,
    azimuth_deg: float = 0.0,
    semi_major: float = 1.0,
    semi_minor: float = 0.4,
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None = None,
    direction_params: Sequence[dict[str, Any]] | None = None,
    crs: str | None = None,
    generator_version: str = DEFAULT_GENERATOR_VERSION,
    target_horizon: str | None = None,
) -> FactorFingerprints:
    """Build component + result fingerprints for a resolved interpolation input set."""
    backend = resolve_backend(method)
    samples = extract_sample_records(sample_points)
    xy = [[s["x"], s["y"]] for s in samples]
    zz = [s["z"] for s in samples]

    breaks = (
        _normalize_polylines(fault_polylines) if backend_uses_breaks(backend) else []
    )
    dirs = (
        _normalize_direction_params(direction_params)
        if backend_uses_directions(backend)
        else []
    )

    geometry_payload = {
        "schema": FINGERPRINT_SCHEMA_VERSION,
        "xy": xy,
        "grid_n": int(grid_n),
        "breaks": breaks,
        "target_horizon": (target_horizon or "").strip(),
    }
    values_payload: dict[str, Any] = {
        "schema": FINGERPRINT_SCHEMA_VERSION,
        "z": zz,
    }
    if backend == "directional":
        # The directional engine multiplies each sample's weight by q and b_i
        # and DROPS samples whose qc_flag is not ok/"" (H11): those per-sample
        # scientific inputs must be part of the fingerprint or a QC weight
        # change would be classified CLEAN while the surface changes.
        values_payload["q"] = [s.get("q") for s in samples]
        values_payload["b_i"] = [s.get("b_i") for s in samples]
        values_payload["qc_flag"] = [s.get("qc_flag") for s in samples]
    algorithm_payload: dict[str, Any] = {
        "schema": FINGERPRINT_SCHEMA_VERSION,
        "method": str(method),
        "backend": backend,
        "generator_version": str(generator_version),
    }
    if backend_uses_power(backend):
        algorithm_payload["power"] = float(power)
    if backend_uses_anisotropy(backend):
        algorithm_payload["azimuth_deg"] = float(azimuth_deg)
        algorithm_payload["semi_major"] = float(semi_major)
        algorithm_payload["semi_minor"] = float(semi_minor)

    constraints_payload = {
        "schema": FINGERPRINT_SCHEMA_VERSION,
        "directions": dirs,
        # Break geometry is geometry-fingerprint for IDW; constrained also uses
        # direction corridors here.
        "constrained": backend == CONSTRAINED_IDW_ENGINE_LABEL,
    }

    geometry = stable_sha256(geometry_payload)
    values = stable_sha256(values_payload)
    algorithm = stable_sha256(algorithm_payload)
    constraints = stable_sha256(constraints_payload)
    result = stable_sha256(
        {
            "schema": FINGERPRINT_SCHEMA_VERSION,
            "geometry": geometry,
            "values": values,
            "algorithm": algorithm,
            "constraints": constraints,
            "crs": crs or "",
        }
    )
    return FactorFingerprints(
        geometry=geometry,
        values=values,
        algorithm=algorithm,
        constraints=constraints,
        result=result,
        backend=backend,
    )


def _fingerprint_memo_key(
    task: Any,
    *,
    method: str | None,
    grid_n: int | None,
    power: float,
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None,
    generator_version: str,
) -> tuple:
    """Identity of a fingerprint derivation within one prepare request.

    A request-scoped memo (see ``fingerprints_for_task(memo=...)``) reuses the
    derivation for the same task + resolved inputs instead of re-serializing
    and re-hashing every sample 3-4x per prepare generation.  The commit-time
    stale-input guard intentionally does NOT use the memo: it must re-derive
    from live project inputs.
    """
    params = dict(getattr(task, "parameters", None) or {})
    points = params.get("sample_points") or []
    breaks_key: Any = None
    if fault_polylines is not None:
        breaks_key = tuple(
            tuple((float(x), float(y)) for x, y in poly)
            for poly in fault_polylines
        )
    return (
        str(getattr(task, "id", "") or ""),
        str(method if method is not None else getattr(task, "method", "IDW")),
        int(grid_n if grid_n is not None else int(params.get("grid_n") or 50)),
        float(power),
        str(generator_version),
        str(getattr(task, "target_horizon", "") or ""),
        int(len(points)),
        breaks_key,
    )


def fingerprints_for_task(
    task: Any,
    *,
    project: Any | None = None,
    method: str | None = None,
    grid_n: int | None = None,
    power: float = 2.0,
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None = None,
    generator_version: str = DEFAULT_GENERATOR_VERSION,
    memo: dict | None = None,
) -> FactorFingerprints:
    """Resolve project constraints and build fingerprints for *task*.

    When *memo* (a plain dict, scoped to one prepare request) is supplied,
    derivations are cached per (task id, resolved inputs) so a task's
    fingerprint is computed once per request instead of once per call site.
    """
    if memo is not None:
        key = _fingerprint_memo_key(
            task,
            method=method,
            grid_n=grid_n,
            power=power,
            fault_polylines=fault_polylines,
            generator_version=generator_version,
        )
        cached = memo.get(key)
        if cached is not None:
            return cached
        fps = _fingerprints_for_task_uncached(
            task,
            project=project,
            method=method,
            grid_n=grid_n,
            power=power,
            fault_polylines=fault_polylines,
            generator_version=generator_version,
        )
        memo[key] = fps
        return fps
    return _fingerprints_for_task_uncached(
        task,
        project=project,
        method=method,
        grid_n=grid_n,
        power=power,
        fault_polylines=fault_polylines,
        generator_version=generator_version,
    )


def _fingerprints_for_task_uncached(
    task: Any,
    *,
    project: Any | None = None,
    method: str | None = None,
    grid_n: int | None = None,
    power: float = 2.0,
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None = None,
    generator_version: str = DEFAULT_GENERATOR_VERSION,
) -> FactorFingerprints:
    """Uncached derivation (see :func:`fingerprints_for_task`)."""
    params = dict(getattr(task, "parameters", None) or {})
    points = params.get("sample_points") or []
    # Prepare-time overrides (method/grid_n/power) win over stored task params so
    # batch_prepare(power=3) correctly invalidates results computed with power=2.
    use_method = method if method is not None else str(getattr(task, "method", "IDW"))
    use_grid_n = (
        int(grid_n)
        if grid_n is not None
        else int(params.get("grid_n") or 50)
    )
    use_power = float(power)
    az = float(params.get("azimuth_deg") or 0.0)
    a_axis = float(params.get("semi_major") or 1.0)
    b_axis = float(params.get("semi_minor") or 0.4)
    horizon = str(getattr(task, "target_horizon", "") or "")

    breaks = fault_polylines
    directions = None
    crs = None
    if project is not None:
        layers = constraint_layers_for_project(project, target_horizon=horizon or None)
        if breaks is None:
            breaks = break_polylines_for_idw(layers, target_horizon=horizon or None)
        directions = direction_line_params(layers, target_horizon=horizon or None)
        az, a_axis, b_axis = resolve_anisotropy_params(directions)
        if params.get("azimuth_deg") is not None:
            try:
                az = float(params["azimuth_deg"])
            except (TypeError, ValueError):
                pass
        if params.get("semi_major") is not None:
            try:
                a_axis = float(params["semi_major"])
            except (TypeError, ValueError):
                pass
        if params.get("semi_minor") is not None:
            try:
                b_axis = float(params["semi_minor"])
            except (TypeError, ValueError):
                pass
        crs = getattr(getattr(project, "coordinate", None), "project_crs", None)

    return build_factor_fingerprints(
        sample_points=points,
        method=use_method,
        grid_n=use_grid_n,
        power=use_power,
        azimuth_deg=az,
        semi_major=a_axis,
        semi_minor=b_axis,
        fault_polylines=breaks,
        direction_params=directions,
        crs=crs,
        generator_version=generator_version,
        target_horizon=horizon,
    )


def stored_fingerprints_from_task(task: Any) -> FactorFingerprints | None:
    """Recover previously stored component fingerprints, if present."""
    params = dict(getattr(task, "parameters", None) or {})
    meta = dict(getattr(task, "grid_metadata", None) or {})
    algo = dict(meta.get("algorithm_parameters") or {})

    def _get(key: str) -> str | None:
        for bag in (params, meta, algo):
            value = bag.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    result = _get("result_fingerprint") or (
        getattr(task, "input_snapshot_hash", None) or None
    )
    geometry = _get("geometry_fingerprint")
    values = _get("values_fingerprint")
    algorithm = _get("algorithm_fingerprint")
    constraints = _get("constraints_fingerprint")
    if not result:
        return None
    # Legacy: only monolithic input_snapshot_hash without components.
    if not (geometry and values and algorithm and constraints):
        return None
    return FactorFingerprints(
        geometry=geometry,
        values=values,
        algorithm=algorithm,
        constraints=constraints,
        result=result,
        backend=str(_get("backend") or params.get("interp_backend") or "idw"),
    )


def task_has_numerical_output(task: Any) -> bool:
    """True if the task has live cache, artifact path, or legacy inline grid."""
    from paleo_workbench.project import factor_grid_artifacts as fga

    task_id = str(getattr(task, "id", "") or "")
    with fga._LIVE_FACTOR_GRIDS_LOCK:
        if task_id and task_id in fga._LIVE_FACTOR_GRIDS:
            return True
    path = getattr(task, "grid_artifact_path", None)
    if path:
        try:
            return Path(path).is_file()
        except OSError:
            return False
    params = getattr(task, "parameters", None) or {}
    return params.get("grid_z") is not None


def classify_factor_recompute(
    task: Any,
    current: FactorFingerprints,
    *,
    force: bool = False,
) -> FactorDirtyState:
    """Classify whether *task* must be recomputed for *current* fingerprints.

    Hard rules:
    * force → UNKNOWN (full recompute path)
    * missing output → MISSING_OUTPUT
    * no stored component fingerprints → UNKNOWN (legacy one-shot recompute)
    * result match + has output → CLEAN
    * else the most specific dirty component
    """
    if force:
        return FactorDirtyState.UNKNOWN
    if not task_has_numerical_output(task):
        # Pending / wiped output.
        status = str(getattr(task, "status", "") or "")
        if status != "complete" and not (getattr(task, "parameters", None) or {}).get(
            "grid_z"
        ):
            return FactorDirtyState.MISSING_OUTPUT
        # Complete but missing file → repair on explicit prepare.
        if getattr(task, "grid_artifact_path", None):
            return FactorDirtyState.MISSING_OUTPUT
        if status != "complete":
            return FactorDirtyState.MISSING_OUTPUT

    stored = stored_fingerprints_from_task(task)
    if stored is None:
        # May still match old monolithic hash if we recompute result the same way —
        # but old hash schema differs, so treat as UNKNOWN (conservative recompute).
        old = str(getattr(task, "input_snapshot_hash", "") or "")
        if old and old == current.result and task_has_numerical_output(task):
            # Extremely unlikely with new schema; keep as clean only on exact match.
            return FactorDirtyState.CLEAN
        if task_has_numerical_output(task) and str(getattr(task, "status", "")) == "complete":
            return FactorDirtyState.UNKNOWN
        return FactorDirtyState.MISSING_OUTPUT

    if stored.result == current.result and task_has_numerical_output(task):
        return FactorDirtyState.CLEAN

    if stored.geometry != current.geometry:
        return FactorDirtyState.DIRTY_GEOMETRY
    if stored.values != current.values:
        return FactorDirtyState.DIRTY_VALUES
    if stored.algorithm != current.algorithm:
        return FactorDirtyState.DIRTY_ALGORITHM
    if stored.constraints != current.constraints:
        return FactorDirtyState.DIRTY_CONSTRAINTS
    # Result differs only by CRS or schema drift.
    return FactorDirtyState.DIRTY_ALGORITHM


def stamp_fingerprints_on_task(task: Any, fps: FactorFingerprints) -> None:
    """Persist component fingerprints on task metadata (small, no grid arrays)."""
    params = dict(getattr(task, "parameters", None) or {})
    for key, value in fps.to_dict().items():
        params[key] = value
    task.parameters = params
    task.input_snapshot_hash = fps.result
    meta = dict(getattr(task, "grid_metadata", None) or {})
    meta["result_fingerprint"] = fps.result
    meta["geometry_fingerprint"] = fps.geometry
    meta["values_fingerprint"] = fps.values
    meta["algorithm_fingerprint"] = fps.algorithm
    meta["constraints_fingerprint"] = fps.constraints
    task.grid_metadata = meta


# ---------------------------------------------------------------------------
# Optional in-session plan cache (geometry fingerprint → InterpolationPlan)
# ---------------------------------------------------------------------------

from collections import OrderedDict
import threading

_PLAN_CACHE: OrderedDict[str, Any] = OrderedDict()
_PLAN_CACHE_LOCK = threading.RLock()
_PLAN_CACHE_MAX = 32


def plan_cache_get(geometry_key: str) -> Any | None:
    with _PLAN_CACHE_LOCK:
        plan = _PLAN_CACHE.get(geometry_key)
        if plan is not None:
            _PLAN_CACHE.move_to_end(geometry_key)
        return plan


def plan_cache_put(geometry_key: str, plan: Any) -> None:
    with _PLAN_CACHE_LOCK:
        _PLAN_CACHE[geometry_key] = plan
        _PLAN_CACHE.move_to_end(geometry_key)
        while len(_PLAN_CACHE) > _PLAN_CACHE_MAX:
            _PLAN_CACHE.popitem(last=False)


def plan_cache_clear() -> None:
    with _PLAN_CACHE_LOCK:
        _PLAN_CACHE.clear()


def plan_cache_stats() -> dict[str, int]:
    with _PLAN_CACHE_LOCK:
        return {"entries": len(_PLAN_CACHE), "max_entries": _PLAN_CACHE_MAX}
