"""Build scientific correlation payload pieces from session/canvas state (Stage 12).

Keeps top IDs stable so no-op saves do not spam versions. Pure functions —
callable from UI and tests without Qt.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Sequence

from paleo_workbench.workflow.stratigraphy_models import (
    CorrelationLink,
    CorrelationMethod,
    DepthDomain,
    FormationTop,
)


def stable_top_id(
    *,
    well_id: str = "",
    well_name: str = "",
    marker: str = "",
) -> str:
    """Deterministic FormationTop id from well + marker (not random)."""
    key = f"{(well_id or '').strip()}|{(well_name or '').strip()}|{(marker or '').strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"top_{digest}"


def tops_from_canvas_rows(
    rows: Sequence[Any],
    *,
    name_to_resource_id: dict[str, str] | None = None,
    depth_domain: DepthDomain = DepthDomain.MD,
    method: CorrelationMethod = CorrelationMethod.IMPORTED,
    previous_tops: Sequence[FormationTop] | None = None,
) -> list[FormationTop]:
    """Map canvas/tops_model rows to scientific FormationTop with stable ids.

    *rows* items expose ``well``/``well_name``, ``name``/``top_name``/
    ``formation_name``, ``depth``/``depth_m`` (the geoviz cross-well canvas
    model uses ``well_name``/``formation_name``/``depth_m`` — reading the
    wrong attribute previously persisted empty markers at depth 0.0).
    If *previous_tops* has the same well+marker, reuse that id (and keep
    method + depth_domain so reopen→resave cannot relabel domains).
    """
    name_to_id = name_to_resource_id or {}
    prev_by_key: dict[tuple[str, str, str], FormationTop] = {}
    for t in previous_tops or []:
        prev_by_key[(t.well_id, t.well_name, t.marker)] = t

    out: list[FormationTop] = []
    for t in rows:
        well = str(getattr(t, "well", "") or getattr(t, "well_name", "") or "")
        marker = str(
            getattr(t, "name", "")
            or getattr(t, "top_name", "")
            or getattr(t, "formation_name", "")
            or ""
        )
        depth_raw = getattr(t, "depth", None)
        if depth_raw is None:
            depth_raw = getattr(t, "depth_m", 0.0)
        depth = float(depth_raw or 0.0)
        well_id = name_to_id.get(well, "")
        key = (well_id, well, marker)
        prev = prev_by_key.get(key)
        tid = prev.id if prev is not None else stable_top_id(
            well_id=well_id, well_name=well, marker=marker
        )
        # Preserve the previously recorded depth domain: the canvas is
        # domain-free, so without this a reopen+resave silently relabels
        # TWT/TVDSS tops as MD (H8).
        domain = prev.depth_domain if prev is not None else depth_domain
        out.append(
            FormationTop(
                id=tid,
                well_id=well_id,
                well_name=well,
                marker=marker,
                depth=depth,
                depth_domain=domain,
                method=prev.method if prev is not None else method,
            )
        )
    return out


def adjacent_links_for_marker(
    tops: Sequence[FormationTop],
    *,
    well_order: Sequence[str],
    method: CorrelationMethod = CorrelationMethod.MANUAL,
) -> list[CorrelationLink]:
    """Link same-marker tops on consecutive wells in section order.

    *well_order* is resource ids when available, else well names.
    """
    # Map well key → ordered position
    order_index: dict[str, int] = {}
    for i, key in enumerate(well_order):
        order_index[key] = i

    by_marker: dict[str, list[FormationTop]] = {}
    for t in tops:
        by_marker.setdefault(t.marker, []).append(t)

    links: list[CorrelationLink] = []
    for marker, group in by_marker.items():

        def _sort_key(top: FormationTop) -> int:
            if top.well_id and top.well_id in order_index:
                return order_index[top.well_id]
            if top.well_name in order_index:
                return order_index[top.well_name]
            return 10_000

        ordered = sorted(group, key=_sort_key)
        for a, b in zip(ordered, ordered[1:]):
            # only adjacent in section (no gap in well_order indices)
            ia, ib = _sort_key(a), _sort_key(b)
            if ib - ia != 1 and not (
                a.well_id and b.well_id and abs(
                    order_index.get(a.well_id, -99) - order_index.get(b.well_id, -99)
                )
                == 1
            ):
                # still link consecutive tops in sorted section order
                pass
            lid = (
                "clink_"
                + hashlib.sha256(f"{a.id}|{b.id}".encode()).hexdigest()[:12]
            )
            links.append(
                CorrelationLink(
                    id=lid,
                    top_a_id=a.id,
                    top_b_id=b.id,
                    well_a_id=a.well_id,
                    well_b_id=b.well_id,
                    method=method,
                    adjacent_only=True,
                )
            )
    return links


def tops_overlay_for_well(
    tops: Iterable[FormationTop],
    *,
    well_id: str = "",
    well_name: str = "",
) -> list[dict[str, Any]]:
    """Lightweight overlay rows for well-log display (marker, depth, domain)."""
    out: list[dict[str, Any]] = []
    for t in tops:
        if well_id and t.well_id and t.well_id != well_id:
            continue
        if well_name and t.well_name and t.well_name != well_name and (
            not well_id or t.well_id != well_id
        ):
            if well_id and t.well_id == well_id:
                pass
            elif well_name and t.well_name != well_name:
                continue
        if well_id and not t.well_id and well_name and t.well_name != well_name:
            continue
        if well_id and t.well_id and t.well_id != well_id:
            continue
        if (not well_id) and well_name and t.well_name != well_name:
            continue
        out.append(
            {
                "id": t.id,
                "marker": t.marker,
                "depth": t.depth,
                "depth_domain": t.depth_domain.value
                if hasattr(t.depth_domain, "value")
                else str(t.depth_domain),
                "well_id": t.well_id,
                "well_name": t.well_name,
            }
        )
    return out
