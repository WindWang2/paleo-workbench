"""WellSectionDatum: Multi-mode vertical datum alignment policy engine."""

from __future__ import annotations

from typing import Any
import numpy as np


class WellSectionDatum:
    """Computes vertical depth coordinate shifts across multi-well cross sections."""

    VALID_MODES = ("md", "tvdss", "horizon")

    @staticmethod
    def shift_key_for(well: dict[str, Any]) -> str:
        """The key a well's shift is stored under (well_id, else name)."""
        return str(well.get("well_id", "") or "") or well.get("name", "Unknown")

    def compute_shifts(
        self,
        wells: list[dict[str, Any]],
        mode: str = "md",
        target_horizon: str | None = None,
        kb_elevations: dict[str, float] | None = None,
        diagnostics: list[str] | None = None,
    ) -> dict[str, float]:
        """Calculate vertical depth shifts (z_aligned = z_true + shift) for each well.

        Shifts are keyed by ``well_id`` when a well dict carries one (stable
        identity — duplicate display names each keep their own shift, V6
        P0-2) and by display name otherwise. When *diagnostics* is provided,
        wells that cannot be corrected (missing target horizon or KB) append
        a notice instead of silently sitting at shift 0.0 beside corrected
        wells; duplicate NAME keys without ids are reported too — last-wins
        collapse is unavoidable there, and that is exactly what the caller
        must see instead of trusting the number.
        """
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of {self.VALID_MODES}")

        shifts: dict[str, float] = {}
        seen_name_keys: dict[str, str] = {}

        for bh in wells:
            wname = bh.get("name", "Unknown")
            key = str(bh.get("well_id", "") or "") or wname
            keyed_by_id = bool(bh.get("well_id"))
            if not keyed_by_id:
                previous = seen_name_keys.get(wname)
                if previous is not None and diagnostics is not None:
                    diagnostics.append(
                        f"well '{wname}': 重复井名且无 well_id；同名井位移不可区分（后值覆盖前值）"
                    )
                seen_name_keys[wname] = key
            if mode == "md":
                shifts[key] = 0.0
            elif mode == "tvdss":
                # KB lookup uses the same key the shift is stored under —
                # name-keyed lookups made duplicate-named wells share one KB
                # (review R2-P2).
                kb = (kb_elevations or {}).get(WellSectionDatum.shift_key_for(bh))
                if kb is None:
                    kb = (kb_elevations or {}).get(wname)
                if kb is None and diagnostics is not None:
                    diagnostics.append(
                        f"well '{wname}': KB elevation missing; tvdss shift left at 0.0"
                    )
                shifts[key] = -float(kb or 0.0)
            elif mode == "horizon":
                if not target_horizon:
                    shifts[key] = 0.0
                    continue
                tops = bh.get("tops") or bh.get("layers") or []
                h_depth = None
                for t in tops:
                    tname = t.get("name") or t.get("lithology")
                    if tname == target_horizon:
                        h_depth = float(t.get("depth", t.get("top", 0.0)))
                        break

                if h_depth is not None:
                    shifts[key] = -h_depth
                else:
                    if diagnostics is not None:
                        diagnostics.append(
                            f"well '{wname}': target horizon '{target_horizon}' missing; shift left at 0.0"
                        )
                    shifts[key] = 0.0

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
