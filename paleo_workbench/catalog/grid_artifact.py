"""Managed factor-grid artifact persistence (§21 grid persistence upgrade).

Moves large single-factor grids *out* of inline ``.paleo.json`` (where they bloat the
project file and serialize as non-standard JSON ``NaN``) into a managed sidecar
``.factor_grid.npz`` plus a JSON descriptor. The artifact is the canonical payload a
catalog INTERMEDIATE/DERIVED version points at; the project stores only the descriptor
reference.

Format (versioned, backward-compatible by version bump):

* **V1** — ``np.savez_compressed`` with ``grid_z``, ``grid_x``, ``grid_y``,
  optional ``variance_grid``, optional ``mask``, and ``__descriptor__``.
* **V2** — ``np.savez`` (uncompressed; benchmarked faster for local interactive
  save/reopen) with the same arrays **except** ``mask`` (derived as
  ``np.isfinite(grid_z)``). Descriptor embeds statistics so loads can skip a
  full-grid scan when trusted.

Pure numpy + stdlib + the FactorGridResult contract, so it is unit-testable without
PySide6.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from paleo_workbench.workflow.factor_grid_result import FactorGridResult, GridStatistics

__all__ = [
    "FACTOR_GRID_ARTIFACT_VERSION",
    "GRID_ARTIFACT_SUFFIX",
    "write_grid_artifact",
    "read_grid_artifact",
    "artifact_file_identity",
]

# Current writer version.  Readers accept V1 and V2.
FACTOR_GRID_ARTIFACT_VERSION = 2
GRID_ARTIFACT_SUFFIX = ".factor_grid.npz"


def artifact_file_identity(path: Path | str) -> tuple[str, int, int]:
    """Cheap identity for cache keys: (resolved path, mtime_ns, size)."""
    p = Path(path).resolve()
    st = p.stat()
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    return (str(p), int(mtime_ns), int(st.st_size))


def write_grid_artifact(
    result: FactorGridResult,
    dest_dir: Path | str,
    name: str,
) -> Path:
    """Persist ``result`` as a managed ``.factor_grid.npz`` artifact in ``dest_dir``.

    Returns the absolute artifact path. Atomic write (temp file + ``os.replace``).
    V2 uses uncompressed NPZ for interactive save latency (see module docstring).
    """
    if not isinstance(result, FactorGridResult):
        raise TypeError("result must be a FactorGridResult")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    safe_name = name.strip().replace("/", "_").replace("\\", "_") or "factor_grid"
    target = dest / f"{safe_name}{GRID_ARTIFACT_SUFFIX}"

    descriptor = result.to_descriptor()
    descriptor["artifact_version"] = FACTOR_GRID_ARTIFACT_VERSION
    if result.boundary is not None:
        descriptor["boundary_ring"] = [[float(x), float(y)] for x, y in result.boundary]

    # Prefer views of already-contiguous producer buffers; do not force a second
    # full-grid allocation when the sealed result is already C-contiguous.
    grid_z = result.grid_z
    if grid_z.dtype != np.float32 or not grid_z.flags["C_CONTIGUOUS"]:
        grid_z = np.ascontiguousarray(grid_z, dtype=np.float32)
    grid_x = result.grid_x
    if grid_x.dtype != np.float64 or not grid_x.flags["C_CONTIGUOUS"]:
        grid_x = np.ascontiguousarray(grid_x, dtype=np.float64)
    grid_y = result.grid_y
    if grid_y.dtype != np.float64 or not grid_y.flags["C_CONTIGUOUS"]:
        grid_y = np.ascontiguousarray(grid_y, dtype=np.float64)

    arrays: dict[str, np.ndarray] = {
        "grid_z": grid_z,
        "grid_x": grid_x,
        "grid_y": grid_y,
        # V2: no redundant mask member (derive from finite(grid_z)).
        "__descriptor__": np.array(
            json.dumps(descriptor, ensure_ascii=False, allow_nan=False)
        ),
    }
    if result.variance_grid is not None:
        var = result.variance_grid
        if var.dtype != np.float32 or not var.flags["C_CONTIGUOUS"]:
            var = np.ascontiguousarray(var, dtype=np.float32)
        arrays["variance_grid"] = var

    tmp = target.with_name(target.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            # Uncompressed: interactive save/reopen is CPU-bound on compress for
            # smooth float32 grids; size trade-off measured in Stage-3 bench.
            np.savez(fh, **arrays)
        tmp.replace(target)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return target


def _stats_from_descriptor(descriptor: dict[str, Any], grid_z: np.ndarray) -> GridStatistics | None:
    """Reuse writer-embedded statistics when present and shape-consistent."""
    raw = descriptor.get("statistics")
    if not isinstance(raw, dict):
        return None
    total = int(grid_z.size)
    try:
        total_count = int(raw.get("total_count", total))
        valid_count = int(raw["valid_count"])
    except (KeyError, TypeError, ValueError):
        return None
    if total_count != total:
        return None

    def _num(key: str) -> float:
        value = raw.get(key)
        if value is None:
            return math.nan
        return float(value)

    return GridStatistics(
        min=_num("min"),
        max=_num("max"),
        mean=_num("mean"),
        std=_num("std"),
        valid_count=valid_count,
        total_count=total_count,
    )


def read_grid_artifact(path: Path | str) -> FactorGridResult:
    """Reconstruct a :class:`FactorGridResult` from a managed grid artifact (V1 or V2)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"factor grid artifact not found: {p}")
    with np.load(p, allow_pickle=False) as data:
        # Must copy out of the load context; one owned allocation per array.
        grid_z = np.array(data["grid_z"], dtype=np.float32, copy=True, order="C")
        grid_x = np.array(data["grid_x"], dtype=np.float64, copy=True, order="C")
        grid_y = np.array(data["grid_y"], dtype=np.float64, copy=True, order="C")
        variance_grid = (
            np.array(data["variance_grid"], dtype=np.float32, copy=True, order="C")
            if "variance_grid" in data.files
            else None
        )
        # V1 may include mask; ignored (derived from grid_z).
        descriptor_raw = str(data["__descriptor__"])
    descriptor: dict[str, Any] = json.loads(descriptor_raw)

    raw_ring = descriptor.get("boundary_ring")
    boundary = (
        [(float(x), float(y)) for x, y in raw_ring] if raw_ring else None
    )

    # Seal buffers before construction so _finalise can share them.
    grid_z.setflags(write=False)
    grid_x.setflags(write=False)
    grid_y.setflags(write=False)
    if variance_grid is not None:
        variance_grid.setflags(write=False)

    result = FactorGridResult(
        grid_z=grid_z,
        grid_x=grid_x,
        grid_y=grid_y,
        factor_name=descriptor.get("factor_name", ""),
        algorithm_id=descriptor.get("algorithm_id", ""),
        algorithm_parameters=dict(descriptor.get("algorithm_parameters") or {}),
        crs=descriptor.get("crs"),
        unit=descriptor.get("unit"),
        generator_version=descriptor.get("generator_version"),
        source_refs=list(descriptor.get("source_refs") or []),
        run_ref=descriptor.get("run_ref"),
        created_at=descriptor.get("created_at"),
        variance_grid=variance_grid,
        boundary=boundary,
        contours=descriptor.get("contours") or None,
    )
    # Prefer writer-produced statistics for immutable artifacts (avoids O(grid) scan).
    version = int(descriptor.get("artifact_version") or 1)
    if version >= 2:
        trusted = _stats_from_descriptor(descriptor, result.grid_z)
        if trusted is not None:
            result.statistics = trusted
    return result
