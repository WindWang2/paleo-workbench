"""Mutable horizon interpretation draft with sparse undo and dirty detection.

Baseline is immutable scientific state. Working Z lives on a
:class:`SculptableHorizonMesh` with :class:`SparseDeltaPatch` undo/redo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from paleo_workbench.viz.horizon_sculpting import SculptableHorizonMesh
from paleo_workbench.viz.interpretation_artifact import scientific_fingerprint


@dataclass
class InterpretationSaveSnapshot:
    """Narrow save payload — never a deep-copied ProjectDocument."""

    interpretation_id: str
    horizon_key: str
    name: str
    z: np.ndarray
    shape: tuple[int, int]
    vertical_domain: str
    crs: str | None
    parent_version_id: str | None
    source_version_ids: tuple[str, ...]
    scientific_fingerprint: str
    generation: int
    scheduled_fingerprint: str
    grid_xy: tuple[np.ndarray, np.ndarray] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HorizonInterpretationDraft:
    """Working draft based on an immutable baseline Z grid."""

    def __init__(
        self,
        *,
        interpretation_id: str,
        horizon_key: str,
        name: str,
        baseline_z: np.ndarray,
        vertical_domain: str = "time",
        crs: str | None = None,
        parent_version_id: str | None = None,
        source_version_ids: list[str] | tuple[str, ...] | None = None,
        generation: int = 0,
        x_coords: np.ndarray | None = None,
        y_coords: np.ndarray | None = None,
    ) -> None:
        z = np.ascontiguousarray(baseline_z, dtype=np.float32)
        if z.ndim != 2:
            raise ValueError("baseline_z must be 2-D")
        self.interpretation_id = interpretation_id
        self.horizon_key = horizon_key
        self.name = name
        self.vertical_domain = vertical_domain
        self.crs = crs
        self.parent_version_id = parent_version_id
        self.source_version_ids = tuple(source_version_ids or ())
        self.generation = int(generation)
        self._baseline_z = z.copy()
        rows, cols = z.shape
        if x_coords is None:
            x_coords = np.arange(cols, dtype=np.float32)
        if y_coords is None:
            y_coords = np.arange(rows, dtype=np.float32)
        xx, yy = np.meshgrid(x_coords.astype(np.float32), y_coords.astype(np.float32))
        verts = np.column_stack([xx.ravel(), yy.ravel(), z.ravel()])
        self._mesh = SculptableHorizonMesh(verts, grid_shape=(rows, cols))
        self._x = np.asarray(x_coords, dtype=np.float32)
        self._y = np.asarray(y_coords, dtype=np.float32)
        self._baseline_fp = scientific_fingerprint(
            self._baseline_z,
            shape=z.shape,
            vertical_domain=vertical_domain,
            crs=crs,
            horizon_key=horizon_key,
        )
        self.status = "clean"  # clean|dirty|stale|invalid
        self.save_generation = 0

    # ------------------------------------------------------------------ views
    @property
    def shape(self) -> tuple[int, int]:
        return (int(self._baseline_z.shape[0]), int(self._baseline_z.shape[1]))

    @property
    def baseline_fingerprint(self) -> str:
        return self._baseline_fp

    def working_z(self) -> np.ndarray:
        rows, cols = self.shape
        return self._mesh.vertices[:, 2].reshape((rows, cols)).astype(np.float32, copy=False)

    def scientific_fingerprint_now(self) -> str:
        return scientific_fingerprint(
            self.working_z(),
            shape=self.shape,
            vertical_domain=self.vertical_domain,
            crs=self.crs,
            horizon_key=self.horizon_key,
        )

    def is_dirty(self) -> bool:
        """Scientific dirty: working Z differs from baseline fingerprint."""
        if self.status == "stale":
            return True
        return self.scientific_fingerprint_now() != self._baseline_fp

    def refresh_status(self) -> str:
        if self.status == "stale":
            return self.status
        self.status = "dirty" if self.is_dirty() else "clean"
        return self.status

    # ------------------------------------------------------------------ edit
    def sculpt(
        self,
        center_xy: tuple[float, float],
        delta_z: float,
        radius: float = 5.0,
    ) -> np.ndarray:
        self._mesh.sculpt_surface(center_xy, delta_z, radius)
        self.generation += 1
        self.refresh_status()
        return self.working_z()

    def smooth(self, iterations: int = 1) -> np.ndarray:
        self._mesh.smooth_anneal(iterations=iterations)
        self.generation += 1
        self.refresh_status()
        return self.working_z()

    def undo(self) -> bool:
        ok = self._mesh.undo()
        if ok:
            self.generation += 1
            self.refresh_status()
        return ok

    def redo(self) -> bool:
        ok = self._mesh.redo()
        if ok:
            self.generation += 1
            self.refresh_status()
        return ok

    def can_undo(self) -> bool:
        return self._mesh.can_undo()

    def can_redo(self) -> bool:
        return self._mesh.can_redo()

    def reset_to_baseline(self) -> None:
        """Discard draft edits; restore baseline Z (not version switch)."""
        rows, cols = self.shape
        self._mesh.vertices[:, 2] = self._baseline_z.ravel()
        self._mesh._undo_stack.clear()
        self._mesh._redo_stack.clear()
        self.generation += 1
        self.status = "clean"

    def mark_stale(self, reason: str = "") -> None:
        self.status = "stale"
        self._stale_reason = reason

    # ------------------------------------------------------------------ save snapshot
    def to_save_snapshot(self) -> InterpretationSaveSnapshot:
        z = np.ascontiguousarray(self.working_z(), dtype=np.float32)
        fp = scientific_fingerprint(
            z,
            shape=self.shape,
            vertical_domain=self.vertical_domain,
            crs=self.crs,
            horizon_key=self.horizon_key,
        )
        self.save_generation += 1
        return InterpretationSaveSnapshot(
            interpretation_id=self.interpretation_id,
            horizon_key=self.horizon_key,
            name=self.name,
            z=z,
            shape=self.shape,
            vertical_domain=self.vertical_domain,
            crs=self.crs,
            parent_version_id=self.parent_version_id,
            source_version_ids=self.source_version_ids,
            scientific_fingerprint=fp,
            generation=self.generation,
            scheduled_fingerprint=fp,
            grid_xy=(self._x.copy(), self._y.copy()),
            metadata={
                "save_generation": self.save_generation,
                "scheduled_at": time.time(),
            },
        )

    def adopt_saved_version(
        self,
        *,
        version_id: str,
        fingerprint: str,
        z: np.ndarray | None = None,
    ) -> None:
        """After successful save of *current* draft fingerprint, promote to baseline."""
        if z is not None:
            arr = np.ascontiguousarray(z, dtype=np.float32)
            self._baseline_z = arr.copy()
            self._mesh.vertices[:, 2] = arr.ravel()
        else:
            self._baseline_z = self.working_z().copy()
        self._baseline_fp = fingerprint
        self.parent_version_id = version_id
        self._mesh._undo_stack.clear()
        self._mesh._redo_stack.clear()
        self.status = "clean"
