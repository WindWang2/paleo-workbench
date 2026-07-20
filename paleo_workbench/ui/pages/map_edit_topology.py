from __future__ import annotations

from typing import Any

from paleo_workbench.mapping import map_edit_api as api
from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.ui.pages.map_edit_commands import (
    BatchVertexEditCommand,
    CompositeCommand,
    CreateFeatureCommand,
    DeleteFeatureCommand,
)
from paleo_workbench.ui.pages.map_edit_items import FaciesPolygonItem, LineItem


def facies_geometry_issues(item: FaciesPolygonItem) -> list[dict[str, object]]:
    """Return geometry issues for a single facies polygon item."""
    issues: list[dict[str, object]] = []
    for part_index, ring_index, ring in item.iter_ring_addresses():
        for issue in api.validate_ring(ring):
            issues.append({
                "feature_id": item.feature_id,
                "part_index": part_index,
                "ring_index": ring_index,
                "code": str(issue.get("code", "invalid_geometry")),
                "message": str(issue.get("message", "几何无效")),
                "severity": "error",
            })
    try:
        from geoviz import validate_polygon_geometry

        shape_issues = validate_polygon_geometry(
            item.to_record()["geometry_type"], item.geometry_coordinates()
        )
    except (ImportError, AttributeError):
        shape_issues = []
    for issue in shape_issues:
        issues.append({
            "feature_id": item.feature_id,
            "code": str(issue.get("code", "invalid_shape")),
            "message": str(issue.get("message", "Shape 几何无效")),
            "severity": "error",
        })
    return issues


def apply_adjacency_warnings(items: list[FaciesPolygonItem], gap_tol: float) -> None:
    """Apply warning status to adjacent facies polygons with gaps."""
    if len(items) < 2:
        return
    rings = [item.coordinates() for item in items]
    issues = api.validate_adjacency(rings, gap_tol=gap_tol)
    flagged: set[int] = set()
    for issue in issues:
        pair = issue.get("pair")
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            flagged.add(int(pair[0]))
            flagged.add(int(pair[1]))
    for idx in flagged:
        if 0 <= idx < len(items) and items[idx].topology_status == "ok":
            items[idx].set_topology_status("warning")


def plan_topology_rebuild(
    facies_items: list[FaciesPolygonItem],
    tol: float,
    apply_coords_fn,
) -> tuple[dict[str, Any], BatchVertexEditCommand | None]:
    """Calculate forced topology rebuild report and command."""
    if not facies_items:
        return (
            {
                "snapped_count": 0,
                "ring_warnings": 0,
                "adjacency_issues": 0,
                "changed": False,
            },
            None,
        )
    rings = [item.coordinates() for item in facies_items]
    report = api.rebuild_topology(rings, snap_tol=tol, gap_tol=tol)
    snapped_rings = report["rings"]
    changes: list[tuple[str, list, list]] = []
    for item, old_ring, new_ring in zip(facies_items, rings, snapped_rings):
        if old_ring != new_ring:
            changes.append((item.feature_id, old_ring, new_ring))
    cmd = BatchVertexEditCommand(changes, apply_coordinates=apply_coords_fn) if changes else None
    res_report = {
        "snapped_count": len(changes),
        "ring_warnings": len(report.get("ring_issues") or []),
        "adjacency_issues": len(report.get("adjacency_issues") or []),
        "changed": bool(changes or report.get("changed")),
        "ring_issues": report.get("ring_issues") or [],
        "adjacency_issue_list": report.get("adjacency_issues") or [],
    }
    return res_report, cmd


def plan_merge_facies(
    a: FaciesPolygonItem,
    b: FaciesPolygonItem,
    add_feature_fn,
    remove_feature_fn,
    item_from_record_fn,
) -> tuple[str | None, CompositeCommand | None]:
    """Plan merger of two facies polygons into one composite command."""
    if a.has_complex_geometry() or b.has_complex_geometry():
        return None, None
    merged = api.merge_rings(a.coordinates(), b.coordinates())
    if not merged:
        return None, None
    name = (
        str(a.get_property("name") or "")
        or str(b.get_property("name") or "")
        or "合并相带"
    )
    new_id = new_feature_id("facies")
    style = dict(a.to_record().get("style") or {})
    new_rec = {
        "id": new_id,
        "kind": "facies",
        "name": name,
        "coordinates": merged,
        "style": style,
    }
    if item_from_record_fn(new_rec) is None:
        return None, None
    cmd = CompositeCommand([
        DeleteFeatureCommand(
            a.to_record(),
            add_feature=add_feature_fn,
            remove_feature=remove_feature_fn,
        ),
        DeleteFeatureCommand(
            b.to_record(),
            add_feature=add_feature_fn,
            remove_feature=remove_feature_fn,
        ),
        CreateFeatureCommand(
            new_rec,
            add_feature=add_feature_fn,
            remove_feature=remove_feature_fn,
        ),
    ])
    return new_id, cmd


def plan_split_facies(
    poly_item: FaciesPolygonItem,
    line_item: LineItem,
    add_feature_fn,
    remove_feature_fn,
    item_from_record_fn,
) -> tuple[list[str] | None, CompositeCommand | None]:
    """Plan splitting of one facies polygon by a line item."""
    if poly_item.has_complex_geometry():
        return None, None
    parts = api.split_ring_by_line(poly_item.coordinates(), line_item.coordinates())
    if not parts or len(parts) < 2:
        return None, None
    base_name = str(poly_item.get_property("name") or "") or "相带"
    poly_style = dict(poly_item.to_record().get("style") or {})
    new_recs = []
    new_ids: list[str] = []
    for i, ring in enumerate(parts):
        nid = new_feature_id("facies")
        new_ids.append(nid)
        new_recs.append({
            "id": nid,
            "kind": "facies",
            "name": f"{base_name}-{i + 1}",
            "coordinates": ring,
            "style": poly_style,
        })
    children: list = [
        DeleteFeatureCommand(
            poly_item.to_record(),
            add_feature=add_feature_fn,
            remove_feature=remove_feature_fn,
        )
    ]
    for rec in new_recs:
        if item_from_record_fn(rec) is None:
            return None, None
        children.append(
            CreateFeatureCommand(
                rec,
                add_feature=add_feature_fn,
                remove_feature=remove_feature_fn,
            )
        )
    return new_ids, CompositeCommand(children)
