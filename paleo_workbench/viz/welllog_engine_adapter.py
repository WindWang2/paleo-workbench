"""Revision-aware Workbench → retained WellLogEngine document adapter.

The Workbench project model remains authoritative.  This module only prepares
immutable typed buffers and maps them into the native session in one complete
document transaction.  It deliberately has no Python renderer, LOD pyramid, or
parallel scene model.

The native bridge owns accepted read-only buffers.  Typed, finite float64
arrays therefore reach C++ without a sample copy; mutable, non-contiguous, or
null-filtered inputs receive one safe normalized copy before submission.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

_ID_NS = uuid.UUID("a1690000-0000-4000-8000-000000000001")
_FALSEY = frozenset({"0", "false", "no", "off", "legacy"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_LOG_SCALE_CURVES = frozenset({"RT", "RXO"})
_CURVE_COLORS = {
    "AC": "#1d4ed8",
    "GR": "#15803d",
    "RT": "#b91c1c",
    "RXO": "#ea580c",
}
_FACIES_PALETTE = (
    "#d4e6f1",
    "#d5f5e3",
    "#fdebd0",
    "#e8daef",
    "#fcf3cf",
    "#fadbd8",
    "#d1f2eb",
    "#ebdef0",
)

# Sedimentary facies / lithology fill colors. Mirrors the canonical mapping in
# geo-viz-engine's geoviz_well_log.pattern_map.FACIES_COLORS: the geoviz facade
# deliberately does not export it, and workbench production code may import the
# facade only (test_geoviz_package_independence), so the table is vendored here.
_FACIES_COLORS = {
    # Rock Types & Lithologies
    "砂岩": "#f0d9b5",
    "泥岩": "#d4c5a9",
    "灰岩": "#b5d4c1",
    "白云岩": "#a8cdb8",
    "页岩": "#c9bfa0",
    "粉砂岩": "#e6c9a8",
    # Coastal & Flats
    "砂坪": "#f0d9b5",
    "泥坪": "#d4c5a9",
    "云质坪": "#c4d4c0",
    "混积潮坪": "#c4d4c0",
    "碎屑岩潮坪": "#d4c5a9",
    "潮坪": "#d4c5a9",
    "混合坪": "#e2d2b5",
    "潮汐水道": "#ebd2b0",
    "潮汐砂脊": "#ebd2b0",
    "潮沟": "#ebd2b0",
    "潮道": "#ebd2b0",
    "泥裂": "#c0dcc0",
    "藻席": "#c0dcc0",
    # Shelf
    "泥质陆棚": "#d4c5a9",
    "砂质陆棚": "#f0d9b5",
    "砂泥质陆棚": "#dccfb5",
    "碎屑岩浅水陆棚": "#d4c5a9",
    "混积浅水陆棚": "#c4d4c0",
    "陆棚": "#d9d4c8",
    "混积": "#c4d4c0",
    "陆棚泥": "#d4c5a9",
    "陆棚砂": "#f0d9b5",
    "风暴沉积": "#dccfb5",
    # Delta & Fluvial
    "三角洲": "#e6c9a8",
    "河流": "#f0d9b5",
    "河道": "#ebd2b0",
    "沼泽": "#c0dcc0",
    "三角洲前缘": "#ebd2b0",
    "三角洲平原": "#ebd2b0",
    "前三角洲": "#dccfb5",
    "分流河道": "#ebd2b0",
    "天然堤": "#e2d2b5",
    "辫状河道": "#ebd2b0",
    # Marine & Deep Water
    "深水盆地": "#9bb5cf",
    "深海": "#9bb5cf",
    "半深海": "#a8c0d8",
    "深海平原": "#9bb5cf",
    "海底扇": "#abc4d4",
    "深海泥": "#9bb5cf",
    "浊积岩": "#adc6d9",
    "等深积岩": "#9bb5cf",
    "碎屑流": "#abc4d4",
    # Lakes (湖泊)
    "湖": "#92d4f0",
    "深湖": "#53b3df",
    "半深湖": "#73c3ef",
    "浅湖": "#aae2f7",
    "湖底泥": "#73c3ef",
    # Carbonates & Reefs
    "碳酸盐台地": "#b5d4c1",
    "局限台地": "#b8d4cc",
    "开阔台地": "#b5d4c1",
    "台地边缘": "#94d6b5",
    "生物礁": "#b5d4c1",
    "礁": "#b5d4c1",
    "粒屑滩": "#bde3cf",
    # Transitional & Others
    "滨岸": "#f0d9b5",
    "前滨": "#f0d9b5",
    "临滨": "#f0d9b5",
    "后滨": "#f0d9b5",
    "沿岸坝": "#f0d9b5",
    "海滩砂": "#f0d9b5",
    "冲越扇": "#f0d9b5",
    "蒸发岩": "#e8dcc8",
    "蒸发盐": "#e8dcc8",
    "膏盐": "#e8dcc8",
    "冰川": "#c8d8e4",
    "冰碛": "#c8d8e4",
    "火山岩": "#c4a8a0",
    "熔岩": "#c4a8a0",
    "变质岩": "#bfb8b0",
    "冲积扇": "#e6c9a8",
    "洪积扇": "#e6c9a8",
    "扇中": "#e6c9a8",
    "扇根": "#e6c9a8",
    "扇缘": "#e6c9a8",
    "泥石流": "#e6c9a8",
    "片流沉积": "#e6c9a8",
    "潟湖": "#b8d4cc",
    "半咸水潟湖": "#b8d4cc",
    "超咸水潟湖": "#a0c7c0",
}


def welllog_engine_env_enabled() -> bool:
    """Return whether the product-default native backend is enabled."""
    raw = (os.environ.get("PALEO_USE_WELLLOG_ENGINE") or "").strip().lower()
    if raw == "":
        return True
    if raw in _FALSEY:
        return False
    if raw in _TRUTHY:
        return True
    return True


def try_import_welllog() -> tuple[Any, type | None, type | None]:
    """Return the optional native module and view class without raising."""
    try:
        import welllog  # type: ignore

        return welllog, getattr(welllog, "WellLogView", None), welllog
    except ImportError:
        # Only import failures mean "binding not installed": any other
        # exception is a real regression and must not silently degrade the
        # workbench to the legacy path (H13).
        return None, None, None


def stable_entity_id(*parts: str) -> str:
    """Make a deterministic UUID for a Workbench-owned business entity."""
    return str(uuid.uuid5(_ID_NS, "|".join(str(p).strip() for p in parts)))


@dataclass(frozen=True)
class EngineCurveSubmission:
    """One normalized curve and its stable native identifiers."""

    document_id: str
    axis_id: str
    curve_id: str
    mnemonic: str
    depth_unit: str
    value_unit: str
    depth: np.ndarray
    values: np.ndarray
    null_indices: tuple[int, ...] = ()
    display_range: tuple[float, float] = (0.0, 100.0)
    color: str = "#63b3ed"
    line_style: str = "solid"


@dataclass(frozen=True)
class EngineIntervalSubmission:
    """A business interval retained as a native document entity."""

    interval_id: str
    top: float
    bottom: float
    semantic: str
    label: str
    fill_color: str


@dataclass(frozen=True)
class EngineMarkerSubmission:
    """A Workbench marker exposed by the native document where supplied."""

    marker_id: str
    depth: float
    label: str
    semantic: str = "formation_top"


@dataclass
class EngineLoadPlan:
    """Complete native document payload prepared from one ``WellLogData``."""

    well_name: str
    top_depth: float
    bottom_depth: float
    curves: list[EngineCurveSubmission] = field(default_factory=list)
    intervals: list[EngineIntervalSubmission] = field(default_factory=list)
    markers: list[EngineMarkerSubmission] = field(default_factory=list)
    lithology_bounds: list[tuple[float, float, str]] = field(default_factory=list)
    facies_bounds: list[tuple[float, float, str]] = field(default_factory=list)
    primary_curve_id: str | None = None
    diagnostics: list[str] = field(default_factory=list)

    @property
    def primary(self) -> EngineCurveSubmission | None:
        if self.primary_curve_id is not None:
            for curve in self.curves:
                if curve.curve_id == self.primary_curve_id:
                    return curve
        return self.curves[0] if self.curves else None

    @property
    def document_id(self) -> str | None:
        primary = self.primary
        return primary.document_id if primary is not None else None


def _freeze_float64(value: Any) -> np.ndarray:
    """Return a 1-D read-only float64 buffer without mutating caller storage."""
    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.dtype == np.float64 and array.flags.c_contiguous and not array.flags.writeable:
        return array
    # Never flip writeability on a caller-owned mutable array: the engine relies
    # on immutability for its retained zero-copy lifetime contract.
    frozen = np.array(array, dtype=np.float64, order="C", copy=True)
    frozen.setflags(write=False)
    return frozen


def _finite_pairs(
    depth: Any, values: Any
) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """Align, safely normalize, and retain only finite depth/value pairs.

    ``np.isfinite`` replaces the previous Python sample loop.  Fully finite,
    read-only typed buffers remain zero-copy candidates for the native bridge.
    A null gap necessarily has a compact filtered copy because the native
    SamplingAxis cannot contain a non-finite coordinate.
    """
    d = _freeze_float64(depth)
    v = _freeze_float64(values)
    n = min(d.size, v.size)
    d = d[:n]
    v = v[:n]
    valid = np.isfinite(d) & np.isfinite(v)
    nulls = tuple(int(index) for index in np.flatnonzero(~valid))
    if not valid.any():
        empty = np.empty(0, dtype=np.float64)
        empty.setflags(write=False)
        return empty, empty, nulls
    if bool(valid.all()):
        return d, v, nulls
    depth_out = np.ascontiguousarray(d[valid], dtype=np.float64)
    values_out = np.ascontiguousarray(v[valid], dtype=np.float64)
    depth_out.setflags(write=False)
    values_out.setflags(write=False)
    return depth_out, values_out, nulls


_FT_UNITS = frozenset({"FT", "F", "FEET", "FOOT"})
_M_UNITS = frozenset({"M", "METER", "METERS", "MTR", "MTRS"})


def _normalize_depth_unit(value: Any) -> str:
    """Map a depth-axis unit string to the engine contract ("m"/"ft")."""
    unit = str(value or "").strip().upper()
    if unit in _FT_UNITS:
        return "ft"
    if unit in _M_UNITS:
        return "m"
    return "m"


def _pick_primary(curves: Iterable[Any]) -> tuple[int, str]:
    curves = list(curves)
    for index, curve in enumerate(curves):
        name = str(getattr(curve, "name", "") or "").upper()
        if name in ("GR", "GAM", "GAMMA", "预测概率") or "GR" in name:
            return index, name
    return 0, str(getattr(curves[0], "name", "") or "") if curves else ""


def _display_range(curve: Any) -> tuple[float, float]:
    value = getattr(curve, "display_range", None) or (0.0, 100.0)
    try:
        lower, upper = float(value[0]), float(value[1])
    except (IndexError, TypeError, ValueError):
        return (0.0, 100.0)
    return (lower, upper) if np.isfinite(lower) and np.isfinite(upper) else (0.0, 100.0)


def _interval_color(label: str, index: int, *, semantic: str) -> str:
    color = _FACIES_COLORS.get(label)
    if color is None:
        for key in sorted(_FACIES_COLORS, key=len, reverse=True):
            if key and key in label:
                color = _FACIES_COLORS[key]
                break
    if color:
        return str(color)
    if semantic == "lithology":
        return "#e0e0e0"
    return _FACIES_PALETTE[index % len(_FACIES_PALETTE)]


def _append_intervals(
    plan: EngineLoadPlan,
    source: Iterable[Any],
    *,
    semantic: str,
    label_attr: str,
) -> None:
    for index, item in enumerate(source):
        try:
            top = float(getattr(item, "top"))
            bottom = float(getattr(item, "bottom"))
        except (TypeError, ValueError, AttributeError):
            continue
        label = str(getattr(item, label_attr, "") or "")
        if not (np.isfinite(top) and np.isfinite(bottom) and bottom > top):
            plan.diagnostics.append(f"interval_invalid:{semantic}:{index}")
            continue
        interval = EngineIntervalSubmission(
            interval_id=stable_entity_id(
                "interval", plan.well_name, semantic, str(index), repr(top), repr(bottom), label
            ),
            top=top,
            bottom=bottom,
            semantic=semantic,
            label=label,
            fill_color=_interval_color(label, index, semantic=semantic),
        )
        plan.intervals.append(interval)
        bounds = (top, bottom, label)
        if semantic == "lithology":
            plan.lithology_bounds.append(bounds)
        else:
            plan.facies_bounds.append(bounds)


def _append_markers(plan: EngineLoadPlan, source: Iterable[Any]) -> None:
    """Map optional source markers without inventing a business marker model."""
    for index, item in enumerate(source):
        try:
            depth = float(
                getattr(item, "depth", getattr(item, "reference_depth", None))
            )
        except (TypeError, ValueError):
            continue
        if not np.isfinite(depth):
            plan.diagnostics.append(f"marker_invalid:{index}")
            continue
        label = str(getattr(item, "label", getattr(item, "name", "")) or "")
        semantic = str(getattr(item, "semantic", "formation_top") or "formation_top")
        identifier = str(getattr(item, "id", "") or "")
        plan.markers.append(
            EngineMarkerSubmission(
                marker_id=identifier
                or stable_entity_id("marker", plan.well_name, str(index), repr(depth), label),
                depth=depth,
                label=label,
                semantic=semantic,
            )
        )


def adapt_well_log_data(data: Any) -> EngineLoadPlan:
    """Create a complete typed engine document plan from Workbench data."""
    well_name = str(getattr(data, "well_name", "") or "well")
    top = float(getattr(data, "top_depth", 0.0) or 0.0)
    bottom = float(getattr(data, "bottom_depth", 0.0) or 0.0)
    plan = EngineLoadPlan(well_name=well_name, top_depth=top, bottom_depth=bottom)
    source_curves = list(getattr(data, "curves", None) or [])
    if not source_curves:
        plan.diagnostics.append("no_curves")
        return plan

    primary_index, _ = _pick_primary(source_curves)
    document_id = stable_entity_id("document", well_name)
    depth_unit = _normalize_depth_unit(getattr(data, "depth_unit", None))
    for index, curve in enumerate(source_curves):
        mnemonic = str(getattr(curve, "name", "") or f"CURVE_{index}")
        unit = str(getattr(curve, "unit", "") or "unit")
        raw_depth = getattr(curve, "depth", None)
        raw_values = getattr(curve, "values", None)
        depth, values, nulls = _finite_pairs(
            () if raw_depth is None else raw_depth,
            () if raw_values is None else raw_values,
        )
        if depth.size == 0:
            plan.diagnostics.append(f"curve_empty:{mnemonic}")
            continue
        curve_id = stable_entity_id("curve", well_name, mnemonic, str(index))
        submission = EngineCurveSubmission(
            document_id=document_id,
            axis_id=stable_entity_id("axis", well_name, mnemonic, str(index)),
            curve_id=curve_id,
            mnemonic=mnemonic,
            depth_unit=depth_unit,
            value_unit=unit,
            depth=depth,
            values=values,
            null_indices=nulls,
            display_range=_display_range(curve),
            color=str(getattr(curve, "color", "") or _CURVE_COLORS.get(mnemonic.upper(), "#63b3ed")),
        )
        plan.curves.append(submission)
        if index == primary_index:
            plan.primary_curve_id = curve_id

    lithology = list(getattr(data, "lithology", None) or [])
    facies = list(getattr(data, "facies", None) or [])
    grouped = getattr(data, "intervals", None)
    if not lithology and grouped is not None:
        lithology = list(getattr(grouped, "lithology", None) or [])
    if not facies and grouped is not None:
        facies_data = getattr(grouped, "facies", None)
        if facies_data is not None:
            facies = [
                *list(getattr(facies_data, "phase", None) or []),
                *list(getattr(facies_data, "sub_phase", None) or []),
                *list(getattr(facies_data, "micro_phase", None) or []),
            ]
    _append_intervals(plan, lithology, semantic="lithology", label_attr="lithology")
    # ``IntervalItem`` fallback uses ``name`` while FaciesInterval uses facies.
    if facies and not hasattr(facies[0], "facies"):
        _append_intervals(plan, facies, semantic="facies", label_attr="name")
    else:
        _append_intervals(plan, facies, semantic="facies", label_attr="facies")
    _append_markers(plan, getattr(data, "markers", None) or [])
    if not plan.curves:
        plan.diagnostics.append("all_curves_empty")
    return plan


def _track_payload(plan: EngineLoadPlan) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    semantics = {interval.semantic for interval in plan.intervals}
    for semantic in ("lithology", "facies"):
        if semantic in semantics:
            tracks.append(
                {"width_mm": 24.0, "layers": [], "interval_semantic": semantic}
            )
    for curve in plan.curves:
        lower, upper = curve.display_range
        if not upper > lower:
            upper = lower + 1.0
        tracks.append(
            {
                "width_mm": 40.0,
                "scale_min": lower,
                "scale_max": upper,
                "scale_mode": "log" if curve.mnemonic.upper() in _LOG_SCALE_CURVES else "linear",
                "layers": [
                    {
                        "curve_id": curve.curve_id,
                        "color": curve.color,
                    }
                ],
            }
        )
    return tracks


def plan_to_submit_payload(plan: EngineLoadPlan) -> dict[str, Any]:
    """Build the one-transaction ``submit_multi_track`` payload.

    Every curve carries a stable private sampling axis.  This keeps mixed-rate
    LAS curves valid and lets an append batch extend all changed curves without
    duplicating a shared axis tail.
    """
    primary = plan.primary
    if primary is None:
        raise ValueError("engine load plan has no submittable curves")
    top, bottom = min(plan.top_depth, plan.bottom_depth), max(plan.top_depth, plan.bottom_depth)
    if not bottom > top and primary.depth.size >= 2:
        top, bottom = float(primary.depth[0]), float(primary.depth[-1])
        top, bottom = min(top, bottom), max(top, bottom)
    return {
        "document_id": primary.document_id,
        "axis_id": stable_entity_id("document-axis", plan.well_name, "md"),
        "depth": primary.depth,
        "depth_unit": primary.depth_unit,
        "top": top,
        "bottom": bottom,
        "curves": [
            {
                "curve_id": curve.curve_id,
                "axis_id": curve.axis_id,
                "mnemonic": curve.mnemonic,
                "values": curve.values,
                "value_unit": curve.value_unit,
                "depth": curve.depth,
            }
            for curve in plan.curves
        ],
        "tracks": _track_payload(plan),
        "intervals": [
            {
                "id": interval.interval_id,
                "top_depth": interval.top,
                "bottom_depth": interval.bottom,
                "semantic": interval.semantic,
                "label": interval.label,
                "fill_color": interval.fill_color,
            }
            for interval in plan.intervals
        ],
        "markers": [
            {
                "id": marker.marker_id,
                "depth": marker.depth,
                "label": marker.label,
                "semantic": marker.semantic,
            }
            for marker in plan.markers
        ],
    }


def _load_report(plan: EngineLoadPlan, report: Any, *, update_kind: str) -> dict[str, Any]:
    primary = plan.primary
    native = report if isinstance(report, dict) else {}
    return {
        "report": report,
        "document_id": plan.document_id,
        "curve_id": primary.curve_id if primary else None,
        "mnemonic": primary.mnemonic if primary else None,
        "sample_count": int(primary.depth.size) if primary else 0,
        "total_samples": int(sum(curve.depth.size for curve in plan.curves)),
        "curve_count": len(plan.curves),
        "track_count": int(native.get("track_count", len(_track_payload(plan)))),
        "lithology_count": len(plan.lithology_bounds),
        "facies_count": len(plan.facies_bounds),
        "diagnostics": list(plan.diagnostics),
        "update_kind": update_kind,
    }


def submit_plan_to_view(view: Any, plan: EngineLoadPlan) -> dict[str, Any]:
    """Atomically submit all Workbench curves, tracks, and intervals."""
    payload = plan_to_submit_payload(plan)
    submit = getattr(view, "submit_multi_track", None)
    if not callable(submit):
        raise RuntimeError("WellLogEngine binding lacks submit_multi_track")
    return _load_report(plan, submit(payload), update_kind="full_replace")


def _same_structure(previous: EngineLoadPlan, current: EngineLoadPlan) -> bool:
    if previous.document_id != current.document_id or len(previous.curves) != len(current.curves):
        return False
    return all(
        (a.curve_id, a.axis_id, a.mnemonic, a.value_unit, a.depth_unit)
        == (b.curve_id, b.axis_id, b.mnemonic, b.value_unit, b.depth_unit)
        for a, b in zip(previous.curves, current.curves)
    )


def _curve_data_equal(previous: EngineLoadPlan, current: EngineLoadPlan) -> bool:
    return all(
        a.depth.shape == b.depth.shape
        and a.values.shape == b.values.shape
        and np.array_equal(a.depth, b.depth)
        and np.array_equal(a.values, b.values)
        for a, b in zip(previous.curves, current.curves)
    )


def _append_payload(previous: EngineLoadPlan, current: EngineLoadPlan) -> dict[str, Any] | None:
    if not _same_structure(previous, current):
        return None
    tails: list[dict[str, Any]] = []
    for old, new in zip(previous.curves, current.curves):
        old_count = old.depth.size
        if new.depth.size < old_count or new.values.size < old_count:
            return None
        if not np.array_equal(old.depth, new.depth[:old_count]) or not np.array_equal(
            old.values, new.values[:old_count]
        ):
            return None
        if new.depth.size > old_count:
            tails.append(
                {
                    "curve_id": new.curve_id,
                    "axis_id": new.axis_id,
                    "depth": new.depth[old_count:],
                    "values": new.values[old_count:],
                }
            )
    if not tails:
        return None
    return {"document_id": current.document_id, "viewport_mode": "fixed", "tails": tails}


def _style_signature(plan: EngineLoadPlan) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (curve.curve_id, curve.display_range, curve.color, curve.line_style)
        for curve in plan.curves
    )


def _interval_signature(plan: EngineLoadPlan) -> tuple[EngineIntervalSubmission, ...]:
    return tuple(plan.intervals)


def _marker_signature(plan: EngineLoadPlan) -> tuple[EngineMarkerSubmission, ...]:
    return tuple(plan.markers)


def update_plan_to_view(
    view: Any, current: EngineLoadPlan, previous: EngineLoadPlan | None
) -> dict[str, Any]:
    """Choose the smallest correctness-preserving native Session operation."""
    if previous is None or not _same_structure(previous, current):
        return submit_plan_to_view(view, current)

    # Markers can only be delivered through a full submit_multi_track payload
    # (the engine's patch_document accepts tracks/intervals only), so any
    # marker change forces a full replace instead of a silent no-op.
    if _marker_signature(previous) != _marker_signature(current):
        return submit_plan_to_view(view, current)

    styles_changed = _style_signature(previous) != _style_signature(current)
    intervals_changed = _interval_signature(previous) != _interval_signature(current)
    patch = getattr(view, "patch_document", None)
    append_payload = _append_payload(previous, current)
    append = getattr(view, "append_curves", None)

    # Test an extension before testing complete equality. This avoids a second
    # full-array pass for every streaming append while retaining the strict
    # prefix validation required when the host has no revision token.
    if append_payload is not None and callable(append):
        append_report = append(append_payload)
        if (styles_changed or intervals_changed) and callable(patch):
            patch_payload: dict[str, Any] = {"document_id": current.document_id}
            if styles_changed:
                patch_payload["axis_id"] = stable_entity_id("document-axis", current.well_name, "md")
                patch_payload["tracks"] = _track_payload(current)
            if intervals_changed:
                patch_payload["intervals"] = plan_to_submit_payload(current)["intervals"]
            patch_report = patch(patch_payload)
            append_report = {"append": append_report, "patch": patch_report}
        return _load_report(current, append_report, update_kind="append")

    data_equal = _curve_data_equal(previous, current)

    if data_equal:
        if not styles_changed and not intervals_changed:
            return _load_report(current, {"reused": True}, update_kind="unchanged")
        if callable(patch):
            payload: dict[str, Any] = {"document_id": current.document_id}
            if styles_changed:
                payload["axis_id"] = stable_entity_id("document-axis", current.well_name, "md")
                payload["tracks"] = _track_payload(current)
            if intervals_changed:
                payload["intervals"] = plan_to_submit_payload(current)["intervals"]
            return _load_report(current, patch(payload), update_kind="patch")
        return submit_plan_to_view(view, current)

    return submit_plan_to_view(view, current)


def parity_snapshot(data: Any) -> dict[str, Any]:
    """Host-comparable semantic snapshot for regression tests."""
    plan = adapt_well_log_data(data)
    return {
        "well_name": plan.well_name,
        "top_depth": plan.top_depth,
        "bottom_depth": plan.bottom_depth,
        "document_id": plan.document_id,
        "curves": [
            {
                "mnemonic": curve.mnemonic,
                "unit": curve.value_unit,
                "depth_unit": curve.depth_unit,
                "length": int(curve.depth.size),
                "depth_first": float(curve.depth[0]) if curve.depth.size else None,
                "depth_last": float(curve.depth[-1]) if curve.depth.size else None,
                "value_first": float(curve.values[0]) if curve.values.size else None,
                "value_last": float(curve.values[-1]) if curve.values.size else None,
                "null_indices": list(curve.null_indices),
                "curve_id": curve.curve_id,
                "axis_id": curve.axis_id,
            }
            for curve in plan.curves
        ],
        "lithology_bounds": list(plan.lithology_bounds),
        "facies_bounds": list(plan.facies_bounds),
        "markers": [
            {
                "depth": marker.depth,
                "label": marker.label,
                "semantic": marker.semantic,
            }
            for marker in plan.markers
        ],
        "diagnostics": list(plan.diagnostics),
    }


def clear_engine_view(view: Any) -> None:
    """Best-effort detach; callers should delete a switched native view."""
    if view is None:
        return
    clear = getattr(view, "clear_document", None) or getattr(view, "clear", None)
    if callable(clear):
        try:
            clear()
            return
        except Exception:
            pass
    try:
        view.hide()
    except Exception:
        pass
