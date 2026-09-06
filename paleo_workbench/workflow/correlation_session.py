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
        # New rows carry their creation source on the canvas model
        # (``manual`` / ``dtw`` / import paths); map it to the scientific
        # method so DTW-assisted picks survive a save instead of relabeling
        # as IMPORTED (L4).
        row_source = str(getattr(t, "source", "") or "").strip().lower()
        if prev is not None:
            row_method = prev.method
        elif row_source == "dtw":
            row_method = CorrelationMethod.DTW_ASSISTED
        elif row_source == "manual":
            row_method = CorrelationMethod.MANUAL
        else:
            row_method = method
        out.append(
            FormationTop(
                id=tid,
                well_id=well_id,
                well_name=well,
                marker=marker,
                depth=depth,
                depth_domain=domain,
                method=row_method,
                # Interpreter metadata is as scientific as the depth: carry
                # it across save cycles instead of blanking it (L4).
                confidence=prev.confidence if prev is not None else "",
                status=prev.status if prev is not None else "active",
                notes=prev.notes if prev is not None else "",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Manual link editing (L4) — copy-on-edit through the draft
# ---------------------------------------------------------------------------


def stable_link_id(top_a_id: str, top_b_id: str) -> str:
    """Deterministic CorrelationLink id from its two endpoints (order-free)."""
    pair = sorted((str(top_a_id), str(top_b_id)))
    digest = hashlib.sha256("|".join(pair).encode("utf-8")).hexdigest()[:12]
    return f"clink_{digest}"


def add_manual_link(
    draft,
    top_a_id: str,
    top_b_id: str,
    *,
    method: CorrelationMethod = CorrelationMethod.MANUAL,
    notes: str = "",
) -> CorrelationLink:
    """Add a user-asserted link between two tops on *draft* (copy-on-edit).

    Refuses (ValueError) unknown tops, self-links and duplicates in either
    direction. Manual links may skip wells, so ``adjacent_only`` is False.
    Re-adding a previously suppressed pair resurrects it (the suppression
    is dropped).
    """
    tops = {t.id: t for t in draft.payload.tops}
    a, b = str(top_a_id), str(top_b_id)
    if a not in tops or b not in tops:
        raise ValueError("both link endpoints must be tops of the draft")
    if a == b:
        raise ValueError("a link needs two different tops")
    existing = {stable_link_id(x.top_a_id, x.top_b_id) for x in draft.payload.links}
    link = CorrelationLink(
        id=stable_link_id(a, b),
        top_a_id=a,
        top_b_id=b,
        well_a_id=tops[a].well_id,
        well_b_id=tops[b].well_id,
        method=method,
        adjacent_only=False,
        notes=notes,
    )
    if link.id in existing:
        raise ValueError("link already exists between these tops")
    draft.payload.links.append(link)
    # A manual re-add of a suppressed adjacency pair must resurrect it.
    if link.id in draft.payload.suppressed_link_ids:
        draft.payload.suppressed_link_ids = [
            sid for sid in draft.payload.suppressed_link_ids if sid != link.id
        ]
    draft.bump()
    return link


def remove_link(draft, link_id: str) -> bool:
    """Remove one link by id; True when the draft changed (copy-on-edit).

    Removing an ADJACENCY-derived pair also records the suppression —
    otherwise the next save would regenerate the link and silently undo
    the interpreter's "these tops are NOT correlated" statement.
    """
    target = next(
        (ln for ln in draft.payload.links if ln.id == str(link_id)), None
    )
    if target is None:
        return False
    draft.payload.links = [
        ln for ln in draft.payload.links if ln.id != str(link_id)
    ]
    if target.adjacent_only:
        canonical = stable_link_id(target.top_a_id, target.top_b_id)
        if canonical not in draft.payload.suppressed_link_ids:
            draft.payload.suppressed_link_ids = [
                *draft.payload.suppressed_link_ids, canonical
            ]
    draft.bump()
    return True


def edit_link(
    draft,
    link_id: str,
    *,
    method: CorrelationMethod | None = None,
    notes: str | None = None,
) -> bool:
    """Edit a link's method/notes in place; True when something changed."""
    changed = False
    for ln in draft.payload.links:
        if ln.id != str(link_id):
            continue
        if method is not None and ln.method != method:
            ln.method = method
            changed = True
        if notes is not None and ln.notes != notes:
            ln.notes = notes
            changed = True
    if changed:
        draft.bump()
    return changed


def merge_session_links(
    derived: Sequence[CorrelationLink],
    draft_links: Sequence[CorrelationLink] | None,
    suppressed_link_ids: Sequence[str] | None = None,
) -> list[CorrelationLink]:
    """Union of derived adjacency links with the draft's edited/manual links.

    Save-time link regeneration used to discard manual edits wholesale.
    Rules (deterministic, fingerprint-stable ordering):

    * a DERIVED pair whose canonical id is suppressed stays OUT — removal of
      an adjacency link is a scientific statement that must survive saves;
    * a draft link whose id matches a DERIVED link REPLACES it — the draft
      carries the user's method/notes edits on the same pair;
    * a draft link between tops that adjacency never generated SURVIVES
      (cross-well / cross-marker interpretation statements).
    """
    suppressed = set(suppressed_link_ids or ())
    merged: dict[str, CorrelationLink] = {}
    for ln in derived:
        canonical = stable_link_id(ln.top_a_id, ln.top_b_id)
        if canonical in suppressed:
            continue
        merged[canonical] = ln.model_copy(update={"id": canonical})
    for ln in draft_links or ():
        canonical = stable_link_id(ln.top_a_id, ln.top_b_id)
        if canonical in suppressed and canonical not in merged:
            continue
        merged[canonical] = ln.model_copy(update={"id": canonical})
    return sorted(
        merged.values(), key=lambda x: (x.top_a_id, x.top_b_id, x.id)
    )


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
            well_id_adjacent = bool(
                a.well_id
                and b.well_id
                and abs(
                    order_index.get(a.well_id, -99) - order_index.get(b.well_id, -99)
                )
                == 1
            )
            adjacent = (ib - ia == 1) or well_id_adjacent
            # Canonical (order-free) pair id: the SAME link keeps its id when
            # the section well order changes, so removals/edits track it.
            lid = stable_link_id(a.id, b.id)
            links.append(
                CorrelationLink(
                    id=lid,
                    top_a_id=a.id,
                    top_b_id=b.id,
                    well_a_id=a.well_id,
                    well_b_id=b.well_id,
                    method=method,
                    adjacent_only=adjacent,
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
