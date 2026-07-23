"""WellSectionDatum: Multi-mode vertical datum alignment policy engine."""

from __future__ import annotations

from typing import Any
import numpy as np


class WellSectionDatum:
    """Computes vertical depth coordinate shifts across multi-well cross sections."""

    VALID_MODES = ("md", "tvdss", "horizon")

    def compute_shifts(
        self,
        wells: list[dict[str, Any]],
        mode: str = "md",
        target_horizon: str | None = None,
        kb_elevations: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Calculate vertical depth shifts (z_aligned = z_true + shift) for each well."""
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of {self.VALID_MODES}")

        shifts: dict[str, float] = {}

        for bh in wells:
            wname = bh.get("name", "Unknown")
            if mode == "md":
                shifts[wname] = 0.0
            elif mode == "tvdss":
                kb = (kb_elevations or {}).get(wname, 0.0)
                shifts[wname] = -float(kb)
            elif mode == "horizon":
                if not target_horizon:
                    shifts[wname] = 0.0
                    continue
                tops = bh.get("tops") or bh.get("layers") or []
                h_depth = None
                for t in tops:
                    tname = t.get("name") or t.get("lithology")
                    if tname == target_horizon:
                        h_depth = float(t.get("depth", t.get("top", 0.0)))
                        break

                if h_depth is not None:
                    shifts[wname] = -h_depth
                else:
                    shifts[wname] = 0.0

        return shifts

    def align_depths(
        self,
        wells: list[dict[str, Any]],
        mode: str = "horizon",
        target_marker: str = "H1",
        target_horizon: str | None = None,
        kb_elevations: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Spec-compliant alias for compute_shifts."""
        target = target_horizon or target_marker
        return self.compute_shifts(wells, mode=mode, target_horizon=target, kb_elevations=kb_elevations)

    def transform_well_depths(
        self,
        depths: np.ndarray,
        shift: float,
    ) -> np.ndarray:
        """Apply datum depth shift to depth array."""
        return depths + shift
