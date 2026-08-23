"""井位矢量地图同步 — 工区井注册表落成项目内一张专用 PaleoMapDocument。

The Data page embeds the well-location map as a collapsible panel; the
panel renders ``project.wells`` live, while this module persists the same
points as a dedicated vector map document so the saved project carries an
explicit 井位图 artifact (consumed as ``well_overlays`` by the mapping
page and export pipeline).  Sync is idempotent: unchanged content is left
untouched so snapshot-diff dirty tracking stays quiet.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.models import PaleoMapDocument

WELL_LOCATION_MAP_ID = "map_well_locations"
WELL_LOCATION_MAP_NAME = "井位图"


def _well_overlays(project: Any) -> list[dict[str, Any]]:
    """Project-CRS points first, source coords as fallback; skip coord-less."""
    overlays: list[dict[str, Any]] = []
    for well in getattr(project, "wells", None) or []:
        x = getattr(well, "project_x", None)
        y = getattr(well, "project_y", None)
        if x is None or y is None:
            x = getattr(well, "surface_x", None)
            y = getattr(well, "surface_y", None)
        if x is None or y is None:
            continue
        overlays.append({"name": str(getattr(well, "name", "") or ""), "x": x, "y": y})
    return overlays


def sync_well_location_map(project: Any) -> tuple[PaleoMapDocument | None, bool]:
    """Create/update the dedicated well-location vector map document.

    Returns ``(document, changed)``.  ``(None, False)`` when the project has
    no wells — an empty project never gets a fabricated map document.
    """
    wells = getattr(project, "wells", None) or []
    docs = getattr(project, "paleomap_documents", None)
    if not wells or docs is None:
        return None, False
    overlays = _well_overlays(project)
    crs = str(getattr(getattr(project, "coordinate", None), "project_crs", "") or "") or None
    existing = next((doc for doc in docs if doc.id == WELL_LOCATION_MAP_ID), None)
    if existing is not None:
        changed = False
        if existing.well_overlays != overlays:
            existing.well_overlays = overlays
            changed = True
        if existing.map_crs != crs:
            existing.map_crs = crs
            changed = True
        return existing, changed
    document = PaleoMapDocument(
        id=WELL_LOCATION_MAP_ID,
        name=WELL_LOCATION_MAP_NAME,
        linked_target_horizon="",
        well_overlays=overlays,
        map_crs=crs,
    )
    docs.append(document)
    return document, True
