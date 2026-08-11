"""Managed factor-grid artifact persistence (§21 grid persistence upgrade).

Moves large single-factor grids *out* of inline ``.paleo.json`` (where they bloat the
project file and serialize as non-standard JSON ``NaN``) into a managed sidecar
``.factor_grid.npz`` plus a JSON descriptor. The artifact is the canonical payload a
catalog INTERMEDIATE/DERIVED version points at; the project stores only the descriptor
reference.

Format (versioned, backward-compatible by version bump):
  ``{name}.factor_grid.npz`` — arrays: ``grid_z`` (float32 H×W), ``grid_x`` (float64 W),
  ``grid_y`` (float64 H), optional ``variance_grid`` (float32 H×W), ``mask`` (bool H×W),
  and a ``__descriptor__`` JSON string carrying every non-array field.

Pure numpy + stdlib + the FactorGridResult contract, so it is unit-testable without
PySide6. The catalog write entry point (``DataCatalogService.register_intermediate`` with
``intermediate_path``) consumes the path returned by :func:`write_grid_artifact`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = [
    "FACTOR_GRID_ARTIFACT_VERSION",
    "GRID_ARTIFACT_SUFFIX",
    "write_grid_artifact",
    "read_grid_artifact",
]

FACTOR_GRID_ARTIFACT_VERSION = 1
GRID_ARTIFACT_SUFFIX = ".factor_grid.npz"


def write_grid_artifact(
    result: FactorGridResult,
    dest_dir: Path | str,
    name: str,
) -> Path:
    """Persist ``result`` as a managed ``.factor_grid.npz`` artifact in ``dest_dir``.

    Returns the absolute artifact path. Atomic write (temp file + ``os.replace``). The
    descriptor (CRS, extent, statistics, algorithm, provenance — no arrays) is embedded
    so the artifact is fully self-describing.
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
        # Small domain ring; travels with the descriptor so the artifact is lossless.
        descriptor["boundary_ring"] = [[float(x), float(y)] for x, y in result.boundary]
    arrays: dict[str, np.ndarray] = {
        "grid_z": np.ascontiguousarray(result.grid_z, dtype=np.float32),
        "grid_x": np.ascontiguousarray(result.grid_x, dtype=np.float64),
        "grid_y": np.ascontiguousarray(result.grid_y, dtype=np.float64),
        "mask": result.mask,
        "__descriptor__": np.array(
            json.dumps(descriptor, ensure_ascii=False, allow_nan=False)
        ),
    }
    if result.variance_grid is not None:
        arrays["variance_grid"] = np.ascontiguousarray(
            result.variance_grid, dtype=np.float32
        )

    # Atomic placement so a partial write can never corrupt a project's canonical grid.
    # Write through a file handle: np.savez* otherwise auto-appends ".npz" to the path.
    tmp = target.with_name(target.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, **arrays)
        tmp.replace(target)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return target


def read_grid_artifact(path: Path | str) -> FactorGridResult:
    """Reconstruct a :class:`FactorGridResult` from a managed grid artifact."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"factor grid artifact not found: {p}")
    with np.load(p, allow_pickle=False) as data:
        grid_z = np.ascontiguousarray(data["grid_z"], dtype=np.float32)
        grid_x = np.ascontiguousarray(data["grid_x"], dtype=np.float64)
        grid_y = np.ascontiguousarray(data["grid_y"], dtype=np.float64)
        variance_grid = (
            np.ascontiguousarray(data["variance_grid"], dtype=np.float32)
            if "variance_grid" in data.files
            else None
        )
        descriptor_raw = str(data["__descriptor__"])
    descriptor: dict[str, Any] = json.loads(descriptor_raw)

    # Rebuild the optional boundary ring if it was embedded in the descriptor.
    raw_ring = descriptor.get("boundary_ring")
    boundary = (
        [(float(x), float(y)) for x, y in raw_ring] if raw_ring else None
    )
    return FactorGridResult(
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
    )
