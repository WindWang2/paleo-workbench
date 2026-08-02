"""Thin adapter: Workbench WellLogData → WellLogEngine submission (no Session/LOD).

Feature flag: ``PALEO_USE_WELLLOG_ENGINE`` (#174).

- **Default ON** when the env var is unset (WellLogEngine is the product default).
- Explicit disable: ``0`` / ``false`` / ``no`` / ``off`` / ``legacy`` → Legacy.
- Explicit enable: ``1`` / ``true`` / ``yes`` / ``on`` → Engine.

Pages keep an explicit Legacy ↔ Engine combo; Legacy is never deleted (#169/#174).

This module does **not** reimplement LOD, layout, or session logic — it only
maps Pydantic/NumPy well-log data into the public ``WellLogView.submit_curve``
surface (and pure parity snapshots for tests).
"""

from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Stable namespace so the same well+curve identity reloads with the same UUIDs.
_ID_NS = uuid.UUID("a1690000-0000-4000-8000-000000000001")

_FALSEY = frozenset({"0", "false", "no", "off", "legacy"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def welllog_engine_env_enabled() -> bool:
    """Return True when WellLogEngine should be the default backend.

    Unset → True (default enable, #174). Explicit falsey tokens → False.
    """
    raw = (os.environ.get("PALEO_USE_WELLLOG_ENGINE") or "").strip().lower()
    if raw == "":
        return True
    if raw in _FALSEY:
        return False
    if raw in _TRUTHY:
        return True
    # Unknown values: prefer engine (product default) but stay predictable.
    return True


def try_import_welllog() -> tuple[Any, type | None, type | None]:
    """Import welllog bindings if the package is installed.

    Returns ``(module_or_None, WellLogView_or_None, ErrorTypes_tuple)``.
    """
    try:
        import welllog  # type: ignore

        return welllog, getattr(welllog, "WellLogView", None), welllog
    except Exception:
        return None, None, None


def stable_entity_id(*parts: str) -> str:
    """Deterministic UUID string from stable source parts (document/axis/curve)."""
    key = "|".join(p.strip() for p in parts if p is not None)
    return str(uuid.uuid5(_ID_NS, key))


@dataclass(frozen=True)
class EngineCurveSubmission:
    """One curve ready for ``WellLogView.submit_curve`` (zero-copy when possible)."""

    document_id: str
    axis_id: str
    curve_id: str
    mnemonic: str
    depth_unit: str
    value_unit: str
    depth: np.ndarray  # float64, read-only flag set by builder
    values: np.ndarray  # float64, read-only
    # Parity metadata (not sent to the engine).
    null_indices: tuple[int, ...] = ()
    display_range: tuple[float, float] = (0.0, 100.0)


@dataclass
class EngineLoadPlan:
    """Result of adapting a WellLogData for the engine path."""

    well_name: str
    top_depth: float
    bottom_depth: float
    curves: list[EngineCurveSubmission] = field(default_factory=list)
    # Interval boundaries for parity tests / future interval submit API.
    lithology_bounds: list[tuple[float, float, str]] = field(default_factory=list)
    facies_bounds: list[tuple[float, float, str]] = field(default_factory=list)
    primary_curve_index: int = 0
    diagnostics: list[str] = field(default_factory=list)

    @property
    def primary(self) -> EngineCurveSubmission | None:
        if not self.curves:
            return None
        idx = min(max(self.primary_curve_index, 0), len(self.curves) - 1)
        return self.curves[idx]


def _finite_pairs(
    depth: list[float] | np.ndarray, values: list[float] | np.ndarray
) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """Align depth/values; drop non-finite pairs; record dropped source indices."""
    d = np.asarray(depth, dtype=np.float64).reshape(-1)
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    n = min(d.size, v.size)
    d = d[:n]
    v = v[:n]
    nulls: list[int] = []
    keep: list[int] = []
    for i in range(n):
        if not (math.isfinite(float(d[i])) and math.isfinite(float(v[i]))):
            nulls.append(i)
        else:
            keep.append(i)
    if not keep:
        empty = np.asarray([], dtype=np.float64)
        empty.setflags(write=False)
        return empty, empty, tuple(nulls)
    depth_out = np.ascontiguousarray(d[keep], dtype=np.float64)
    values_out = np.ascontiguousarray(v[keep], dtype=np.float64)
    depth_out.setflags(write=False)
    values_out.setflags(write=False)
    return depth_out, values_out, tuple(nulls)


def _pick_primary_index(curves: list[Any]) -> int:
    for i, curve in enumerate(curves):
        name = str(getattr(curve, "name", "") or "").upper()
        if name in ("GR", "GAM", "GAMMA", "预测概率") or "GR" in name:
            return i
    return 0


def adapt_well_log_data(data: Any) -> EngineLoadPlan:
    """Convert geoviz ``WellLogData`` (or duck-type) into an engine load plan.

    Pure mapping — no Session, LOD, or layout decisions.
    """
    well_name = str(getattr(data, "well_name", "") or "well")
    top = float(getattr(data, "top_depth", 0.0) or 0.0)
    bottom = float(getattr(data, "bottom_depth", 0.0) or 0.0)
    plan = EngineLoadPlan(well_name=well_name, top_depth=top, bottom_depth=bottom)
    source_curves = list(getattr(data, "curves", None) or [])
    if not source_curves:
        plan.diagnostics.append("no_curves")
        return plan

    plan.primary_curve_index = _pick_primary_index(source_curves)
    document_id = stable_entity_id("document", well_name)
    axis_id = stable_entity_id("axis", well_name, "md")

    for index, curve in enumerate(source_curves):
        mnemonic = str(getattr(curve, "name", "") or f"CURVE_{index}")
        unit = str(getattr(curve, "unit", "") or "unit")
        depth_list = list(getattr(curve, "depth", None) or [])
        value_list = list(getattr(curve, "values", None) or [])
        depth_arr, value_arr, nulls = _finite_pairs(depth_list, value_list)
        if depth_arr.size == 0:
            plan.diagnostics.append(f"curve_empty:{mnemonic}")
            continue
        dr = getattr(curve, "display_range", (0.0, 100.0)) or (0.0, 100.0)
        try:
            display_range = (float(dr[0]), float(dr[1]))
        except Exception:
            display_range = (0.0, 100.0)
        plan.curves.append(
            EngineCurveSubmission(
                document_id=document_id,
                axis_id=axis_id,
                curve_id=stable_entity_id("curve", well_name, mnemonic, str(index)),
                mnemonic=mnemonic,
                depth_unit="m",
                value_unit=unit or "unit",
                depth=depth_arr,
                values=value_arr,
                null_indices=nulls,
                display_range=display_range,
            )
        )

    for item in list(getattr(data, "lithology", None) or []):
        plan.lithology_bounds.append(
            (
                float(getattr(item, "top", 0.0)),
                float(getattr(item, "bottom", 0.0)),
                str(getattr(item, "lithology", "") or ""),
            )
        )
    for item in list(getattr(data, "facies", None) or []):
        plan.facies_bounds.append(
            (
                float(getattr(item, "top", 0.0)),
                float(getattr(item, "bottom", 0.0)),
                str(getattr(item, "facies", "") or ""),
            )
        )
    if not plan.curves:
        plan.diagnostics.append("all_curves_empty")
    return plan


def parity_snapshot(data: Any) -> dict[str, Any]:
    """Host-comparable snapshot of depth/units/nulls/values/interval bounds."""
    plan = adapt_well_log_data(data)
    curves = []
    for c in plan.curves:
        curves.append(
            {
                "mnemonic": c.mnemonic,
                "unit": c.value_unit,
                "depth_unit": c.depth_unit,
                "length": int(c.depth.size),
                "depth_first": float(c.depth[0]) if c.depth.size else None,
                "depth_last": float(c.depth[-1]) if c.depth.size else None,
                "value_first": float(c.values[0]) if c.values.size else None,
                "value_last": float(c.values[-1]) if c.values.size else None,
                "null_indices": list(c.null_indices),
                "curve_id": c.curve_id,
            }
        )
    return {
        "well_name": plan.well_name,
        "top_depth": plan.top_depth,
        "bottom_depth": plan.bottom_depth,
        "document_id": plan.primary.document_id if plan.primary else None,
        "curves": curves,
        "lithology_bounds": list(plan.lithology_bounds),
        "facies_bounds": list(plan.facies_bounds),
        "diagnostics": list(plan.diagnostics),
    }


def submit_plan_to_view(view: Any, plan: EngineLoadPlan) -> dict[str, Any]:
    """Submit the primary curve of *plan* to a live WellLogView.

    The current Python binding replaces the document per ``submit_curve`` call,
    so only the primary (GR / first) curve is submitted. Multi-curve and
    interval tracks remain Legacy-path responsibilities until the binding grows.
    """
    primary = plan.primary
    if primary is None:
        raise ValueError("engine load plan has no submittable curves")
    report = view.submit_curve(
        primary.depth,
        primary.values,
        primary.document_id,
        primary.axis_id,
        primary.curve_id,
        primary.mnemonic,
        primary.depth_unit,
        primary.value_unit,
    )
    return {
        "report": report,
        "document_id": primary.document_id,
        "curve_id": primary.curve_id,
        "mnemonic": primary.mnemonic,
        "sample_count": int(primary.depth.size),
        "well_name": plan.well_name,
        "lithology_count": len(plan.lithology_bounds),
        "facies_count": len(plan.facies_bounds),
        "diagnostics": list(plan.diagnostics),
    }


def clear_engine_view(view: Any) -> None:
    """Release engine view document ownership for project/resource switches."""
    if view is None:
        return
    # Prefer a dedicated clear API when present; otherwise replace with empty.
    clear = getattr(view, "clear_document", None) or getattr(view, "clear", None)
    if callable(clear):
        try:
            clear()
            return
        except Exception:
            pass
    # Best-effort: hide and let panel drop the reference so GC can free buffers.
    try:
        view.hide()
    except Exception:
        pass
