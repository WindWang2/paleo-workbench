"""Multi-well stratigraphy correlation → WellLogEngine plan (#170).

Maps Workbench well lists, Track/marker tops, spacing, and datum mode onto
stable multi-well Entity IDs, Depth Transform control points, and Cross-Well
Overlay descriptors. Pure mapping — no Session/LOD decisions (mirrors
``welllog_engine_adapter`` for single-well #169).

Legacy CrossWell path remains available; this module is the engine dual-path
seam for StratigraphyCorrelationPage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from paleo_workbench.viz import welllog_engine_adapter as single
from paleo_workbench.viz.well_section_datum import WellSectionDatum

DatumMode = Literal["md", "tvdss", "horizon"]


@dataclass(frozen=True)
class EngineMarker:
    marker_id: str
    reference_depth: float
    label: str


@dataclass(frozen=True)
class EngineWellSlot:
    """One well column on the multi-well surface."""

    well_name: str
    resource_id: str  # stable source identity (resource id or name)
    order_index: int
    document_id: str
    axis_id: str
    curve_id: str
    mnemonic: str
    depth_unit: str
    value_unit: str
    depth: np.ndarray
    values: np.ndarray
    markers: tuple[EngineMarker, ...] = ()
    # Display Depth = reference + shift under MD/TVDSS/horizon (parity with Legacy).
    depth_shift: float = 0.0
    # Piecewise control points for SetDepthTransform (empty = identity after shift).
    transform_points: tuple[tuple[float, float], ...] = ()
    left_mm: float = 0.0
    width_mm: float = 30.0


@dataclass(frozen=True)
class EngineOverlay:
    overlay_id: str
    kind: str  # "horizon_line" | "correlation_band"
    left_document_id: str
    right_document_id: str
    left_marker_id: str
    right_marker_id: str
    left_bottom_marker_id: str = ""
    right_bottom_marker_id: str = ""
    formation: str = ""
    z_order: int = 50


@dataclass
class MultiWellEnginePlan:
    wells: list[EngineWellSlot] = field(default_factory=list)
    overlays: list[EngineOverlay] = field(default_factory=list)
    gap_mm: float = 5.0
    well_spacing_px: int = 150  # Legacy slider parity (UI pixels)
    shared_display_top: float = 0.0
    shared_display_bottom: float = 1.0
    datum_mode: str = "md"
    target_horizon: str = ""
    target_document_id: str = ""
    align_marker_labels: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def document_ids(self) -> list[str]:
        return [w.document_id for w in self.wells]

    @property
    def well_names(self) -> list[str]:
        return [w.well_name for w in self.wells]


def _tops_for_well(
    well_name: str,
    tops_by_well: dict[str, list[tuple[str, float]]] | None,
) -> list[tuple[str, float]]:
    if not tops_by_well:
        return []
    if well_name in tops_by_well:
        return list(tops_by_well[well_name])
    # Case-insensitive fallback
    lower = {k.lower(): v for k, v in tops_by_well.items()}
    return list(lower.get(well_name.lower(), []))


def _shift_for_well(
    well_name: str,
    tops: list[tuple[str, float]],
    *,
    mode: DatumMode,
    target_horizon: str,
    kb: float,
) -> float:
    datum = WellSectionDatum()
    well_dict = {
        "name": well_name,
        "tops": [{"name": n, "depth": d} for n, d in tops],
    }
    shifts = datum.compute_shifts(
        [well_dict],
        mode=mode,
        target_horizon=target_horizon or None,
        kb_elevations={well_name: kb},
    )
    return float(shifts.get(well_name, 0.0))


def _transform_for_shift(
    depth: np.ndarray, shift: float
) -> tuple[tuple[float, float], ...]:
    """Identity when shift≈0; otherwise two-point baseline shift map."""
    if depth.size == 0 or abs(shift) < 1e-12:
        return ()
    top = float(depth[0])
    bot = float(depth[-1])
    if abs(bot - top) < 1e-12:
        bot = top + 1.0
    # reference → display = reference + shift
    return ((top, top + shift), (bot, bot + shift))


def adapt_multi_well_section(
    well_logs: list[Any],
    well_names: list[str] | None = None,
    *,
    resource_ids: list[str] | None = None,
    tops_by_well: dict[str, list[tuple[str, float]]] | None = None,
    spacing_px: int = 150,
    gap_mm: float = 5.0,
    track_width_mm: float = 30.0,
    datum_mode: DatumMode = "md",
    target_horizon: str = "",
    kb_elevations: dict[str, float] | None = None,
    target_well_index: int = 0,
) -> MultiWellEnginePlan:
    """Build a multi-well engine plan from Legacy-compatible well log objects.

    *well_logs* are geoviz ``WellLogData`` (or duck types). Order is the
    left-to-right surface order. Re-running with the same resource_ids yields
    the same document/marker UUIDs (stable identity across reload/reorder when
    resource_ids stay attached to wells).
    """
    names = list(well_names or [])
    rids = list(resource_ids or [])
    plan = MultiWellEnginePlan(
        gap_mm=float(gap_mm),
        well_spacing_px=int(spacing_px),
        datum_mode=datum_mode,
        target_horizon=str(target_horizon or ""),
    )
    if not well_logs:
        plan.diagnostics.append("no_wells")
        return plan

    left = 0.0
    display_tops: list[float] = []
    display_bots: list[float] = []
    slots: list[EngineWellSlot] = []

    for index, data in enumerate(well_logs):
        name = (
            names[index]
            if index < len(names)
            else str(getattr(data, "well_name", "") or f"Well-{index + 1}")
        )
        rid = rids[index] if index < len(rids) else name
        single_plan = single.adapt_well_log_data(data)
        primary = single_plan.primary
        if primary is None:
            plan.diagnostics.append(f"well_empty:{name}")
            continue
        tops = _tops_for_well(name, tops_by_well)
        # Also harvest tops from lithology/facies labels if no external tops.
        if not tops:
            for top, _bot, label in single_plan.lithology_bounds:
                if label:
                    tops.append((label, top))
        kb = float((kb_elevations or {}).get(name, 0.0))
        shift = _shift_for_well(
            name,
            tops,
            mode=datum_mode,
            target_horizon=target_horizon,
            kb=kb,
        )
        xform = _transform_for_shift(primary.depth, shift)
        markers: list[EngineMarker] = []
        for mi, (label, depth) in enumerate(tops):
            markers.append(
                EngineMarker(
                    marker_id=single.stable_entity_id(
                        "marker", rid, label, f"{depth:.6f}", str(mi)
                    ),
                    reference_depth=float(depth),
                    label=str(label),
                )
            )
        # Document id keyed by resource_id so rename of display label is safe.
        document_id = single.stable_entity_id("document", rid)
        axis_id = single.stable_entity_id("axis", rid, "md")
        curve_id = single.stable_entity_id(
            "curve", rid, primary.mnemonic, "primary"
        )
        slot = EngineWellSlot(
            well_name=name,
            resource_id=rid,
            order_index=index,
            document_id=document_id,
            axis_id=axis_id,
            curve_id=curve_id,
            mnemonic=primary.mnemonic,
            depth_unit=primary.depth_unit,
            value_unit=primary.value_unit,
            depth=primary.depth,
            values=primary.values,
            markers=tuple(markers),
            depth_shift=shift,
            transform_points=xform,
            left_mm=left,
            width_mm=float(track_width_mm),
        )
        slots.append(slot)
        left += track_width_mm + gap_mm
        # Shared display window from shifted extents
        if primary.depth.size:
            d0 = float(primary.depth[0]) + shift
            d1 = float(primary.depth[-1]) + shift
            display_tops.append(min(d0, d1))
            display_bots.append(max(d0, d1))

    plan.wells = slots
    if not slots:
        plan.diagnostics.append("all_wells_empty")
        return plan

    plan.shared_display_top = min(display_tops) if display_tops else 0.0
    plan.shared_display_bottom = max(display_bots) if display_bots else 1.0
    if plan.shared_display_bottom <= plan.shared_display_top:
        plan.shared_display_bottom = plan.shared_display_top + 1.0

    t_idx = min(max(target_well_index, 0), len(slots) - 1)
    plan.target_document_id = slots[t_idx].document_id

    # Align labels: formation names present on the target well with ≥2 markers
    # shared across at least one other well.
    target_labels = {m.label for m in slots[t_idx].markers}
    shared_labels: list[str] = []
    for label in sorted(target_labels):
        count = sum(1 for s in slots if any(m.label == label for m in s.markers))
        if count >= 2:
            shared_labels.append(label)
    plan.align_marker_labels = shared_labels[:8]

    # Overlays: horizon lines + correlation bands between adjacent wells.
    plan.overlays = _build_overlays(slots, shared_labels)
    return plan


def _marker_by_label(slot: EngineWellSlot, label: str) -> EngineMarker | None:
    for m in slot.markers:
        if m.label == label:
            return m
    return None


def _build_overlays(
    slots: list[EngineWellSlot], shared_labels: list[str]
) -> list[EngineOverlay]:
    overlays: list[EngineOverlay] = []
    if len(slots) < 2:
        return overlays
    for i in range(len(slots) - 1):
        left, right = slots[i], slots[i + 1]
        for label in shared_labels:
            lm = _marker_by_label(left, label)
            rm = _marker_by_label(right, label)
            if lm is None or rm is None:
                continue
            overlays.append(
                EngineOverlay(
                    overlay_id=single.stable_entity_id(
                        "overlay-horizon", left.resource_id, right.resource_id, label
                    ),
                    kind="horizon_line",
                    left_document_id=left.document_id,
                    right_document_id=right.document_id,
                    left_marker_id=lm.marker_id,
                    right_marker_id=rm.marker_id,
                    formation=label,
                    z_order=80,
                )
            )
        # Correlation bands between consecutive shared tops on adjacent wells.
        ordered = [
            lab
            for lab in shared_labels
            if _marker_by_label(left, lab) and _marker_by_label(right, lab)
        ]
        for j in range(len(ordered) - 1):
            top_lab, bot_lab = ordered[j], ordered[j + 1]
            lt = _marker_by_label(left, top_lab)
            rt = _marker_by_label(right, top_lab)
            lb = _marker_by_label(left, bot_lab)
            rb = _marker_by_label(right, bot_lab)
            if not all((lt, rt, lb, rb)):
                continue
            overlays.append(
                EngineOverlay(
                    overlay_id=single.stable_entity_id(
                        "overlay-band",
                        left.resource_id,
                        right.resource_id,
                        top_lab,
                        bot_lab,
                    ),
                    kind="correlation_band",
                    left_document_id=left.document_id,
                    right_document_id=right.document_id,
                    left_marker_id=lt.marker_id,  # type: ignore[union-attr]
                    right_marker_id=rt.marker_id,  # type: ignore[union-attr]
                    left_bottom_marker_id=lb.marker_id,  # type: ignore[union-attr]
                    right_bottom_marker_id=rb.marker_id,  # type: ignore[union-attr]
                    formation=f"{top_lab}-{bot_lab}",
                    z_order=40,
                )
            )
    return overlays


def multi_well_parity_snapshot(plan: MultiWellEnginePlan) -> dict[str, Any]:
    """Host-comparable snapshot for Legacy ↔ Engine dual-path tests."""
    return {
        "well_count": len(plan.wells),
        "well_names": plan.well_names,
        "document_ids": plan.document_ids,
        "resource_ids": [w.resource_id for w in plan.wells],
        "order": [w.order_index for w in plan.wells],
        "gap_mm": plan.gap_mm,
        "well_spacing_px": plan.well_spacing_px,
        "lefts_mm": [w.left_mm for w in plan.wells],
        "widths_mm": [w.width_mm for w in plan.wells],
        "depth_shifts": {w.well_name: w.depth_shift for w in plan.wells},
        "transform_points": {
            w.well_name: list(w.transform_points) for w in plan.wells
        },
        "markers": {
            w.well_name: [
                {
                    "id": m.marker_id,
                    "label": m.label,
                    "reference_depth": m.reference_depth,
                }
                for m in w.markers
            ]
            for w in plan.wells
        },
        "overlays": [
            {
                "id": o.overlay_id,
                "kind": o.kind,
                "formation": o.formation,
                "left_document_id": o.left_document_id,
                "right_document_id": o.right_document_id,
                "left_marker_id": o.left_marker_id,
                "right_marker_id": o.right_marker_id,
                "left_bottom_marker_id": o.left_bottom_marker_id,
                "right_bottom_marker_id": o.right_bottom_marker_id,
            }
            for o in plan.overlays
        ],
        "shared_display_top": plan.shared_display_top,
        "shared_display_bottom": plan.shared_display_bottom,
        "datum_mode": plan.datum_mode,
        "target_horizon": plan.target_horizon,
        "target_document_id": plan.target_document_id,
        "align_marker_labels": list(plan.align_marker_labels),
        "diagnostics": list(plan.diagnostics),
    }


def plan_to_submit_payload(plan: MultiWellEnginePlan) -> dict[str, Any]:
    """Serialize a plan for ``WellLogView.submit_multi_well_section`` (or FakeView)."""
    wells = []
    for w in plan.wells:
        wells.append(
            {
                "depth": w.depth,
                "values": w.values,
                "document_id": w.document_id,
                "axis_id": w.axis_id,
                "curve_id": w.curve_id,
                "mnemonic": w.mnemonic,
                "depth_unit": w.depth_unit,
                "value_unit": w.value_unit,
                "markers": [
                    {
                        "id": m.marker_id,
                        "depth": m.reference_depth,
                        "label": m.label,
                    }
                    for m in w.markers
                ],
                "transform_points": [
                    {"reference": a, "display": b} for a, b in w.transform_points
                ],
                "left_mm": w.left_mm,
                "width_mm": w.width_mm,
            }
        )
    overlays = [
        {
            "id": o.overlay_id,
            "kind": o.kind,
            "left_document_id": o.left_document_id,
            "right_document_id": o.right_document_id,
            "left_marker_id": o.left_marker_id,
            "right_marker_id": o.right_marker_id,
            "left_bottom_marker_id": o.left_bottom_marker_id or None,
            "right_bottom_marker_id": o.right_bottom_marker_id or None,
        }
        for o in plan.overlays
    ]
    return {
        "wells": wells,
        "gap_mm": plan.gap_mm,
        "shared_top": plan.shared_display_top,
        "shared_bottom": plan.shared_display_bottom,
        "overlays": overlays,
        "pack_left_to_right": True,
    }


def submit_multi_well_plan(view: Any, plan: MultiWellEnginePlan) -> dict[str, Any]:
    """Submit multi-well plan to a live WellLogView (requires native bridge).

    Falls back to raising if the binding lacks ``submit_multi_well_section``.
    """
    if not plan.wells:
        raise ValueError("multi-well plan has no wells")
    payload = plan_to_submit_payload(plan)
    fn = getattr(view, "submit_multi_well_section", None)
    if not callable(fn):
        raise RuntimeError(
            "WellLogView.submit_multi_well_section is unavailable; "
            "rebuild welllog bindings with multi-well support (#170)"
        )
    report = fn(payload)
    return {
        "report": report,
        "well_count": len(plan.wells),
        "document_ids": plan.document_ids,
        "overlay_count": len(plan.overlays),
        "shared_display_top": plan.shared_display_top,
        "shared_display_bottom": plan.shared_display_bottom,
        "diagnostics": list(plan.diagnostics),
    }
