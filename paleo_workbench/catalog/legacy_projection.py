"""Legacy ``ProjectDocument.resources`` projection over the data catalog (#1032).

ADR 0056 keeps ``.paleo.json`` ``resources[]`` as the master store for legacy
``ResourceItem`` while the ``DataCatalogService`` owns the lifecycle. That
split historically forced every UI mutation site to hand-maintain *both*
worlds with its own filtering/appending rules — the "dual data world"
divergence surface.

This module is the single owner of that boundary. Direction is fixed:
**the catalog is authoritative; ``resources[]`` is a derived mirror**. Every
operation takes the catalog entities that actually changed and projects them
onto the legacy list:

* bridge id of an asset is ``asset.legacy_resource_id or asset.id`` — the
  same identity rule ``migrate_legacy_resources`` established at project open;
* removal drops exactly the legacy items whose bridge id maps to a catalog
  asset that was trashed/removed;
* re-surfacing (restore / derived companion) is idempotent on that same id.

No third data model is introduced and no sync runs in the opposite
(legacy → catalog) direction here — registration stays in the catalog
service.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from paleo_workbench.project.models import ResourceItem

if TYPE_CHECKING:  # pragma: no cover - typing only
    from paleo_workbench.catalog.models import DataAsset
    from paleo_workbench.project.models import ProjectDocument


def legacy_bridge_id(asset: "DataAsset") -> str:
    """The legacy ``ResourceItem.id`` an asset projects onto (open-migration rule)."""
    return asset.legacy_resource_id or asset.id


def remove_legacy_resources_for_assets(
    project: "ProjectDocument",
    assets: Iterable["DataAsset"],
) -> int:
    """Drop legacy items mirrored by *assets* (catalog trashed/removed them).

    Returns how many legacy rows were removed. Filtering is by the bridge id
    set of the actually-affected catalog assets — never by a separately
    computed UI selection, which can disagree with what the catalog really
    trashed (the divergence #1032 describes).
    """
    bridge_ids = {legacy_bridge_id(asset) for asset in assets}
    if not bridge_ids:
        return 0
    return remove_legacy_resources_by_ids(project, bridge_ids)


def remove_legacy_resources_by_ids(
    project: "ProjectDocument",
    ids: Iterable[str],
) -> int:
    """Single-pass removal of legacy rows (and matching export artifacts) by id."""
    target = set(ids)
    if not target:
        return 0
    before = len(project.resources) + len(project.export_artifacts)
    project.resources[:] = [r for r in project.resources if r.id not in target]
    project.export_artifacts[:] = [
        a for a in project.export_artifacts if a.id not in target
    ]
    return before - (len(project.resources) + len(project.export_artifacts))


def upsert_legacy_resource(
    project: "ProjectDocument",
    item: ResourceItem | None,
) -> bool:
    """Idempotently re-surface one legacy companion built from catalog state.

    Returns True when the projection changed. ``None`` items (builder
    failure) are a no-op so callers never inject a half-built companion.
    """
    if item is None:
        return False
    for index, existing in enumerate(project.resources):
        if existing.id == item.id:
            project.resources[index] = item
            return True
    project.resources.append(item)
    return True
