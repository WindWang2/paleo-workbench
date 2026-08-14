"""Tag collaborator functions for :class:`DataCatalogService` (private).

The tags section of ``catalog/service.py`` (behind the ``# -- tags --``
banner) extracted into a private collaborator module. Each function takes the
service as its first argument and is composed by the service's thin delegator
methods — the PUBLIC API of ``DataCatalogService`` stays identical.
"""
from __future__ import annotations

from paleo_workbench.catalog.models import CatalogError, Tag, normalize_tag_name


def _tag_by_name(service, name: str) -> Tag | None:
    normalized = normalize_tag_name(name)
    for tag in service.document.tags:
        if tag.name == normalized:
            return tag
    return None


def add_tag(
    service,
    name: str,
    *,
    asset_id: str | None = None,
    version_id: str | None = None,
) -> Tag:
    """Get-or-create a normalized tag and associate it. Idempotent."""
    if asset_id is None and version_id is None:
        raise CatalogError("add_tag requires asset_id or version_id")
    normalized = normalize_tag_name(name)
    if not normalized:
        raise CatalogError("Empty tag name")
    if asset_id is not None:
        service._asset_or_raise(asset_id)
    if version_id is not None:
        service._version_or_raise(version_id)
    tag = _tag_by_name(service, normalized)
    created = False
    if tag is None:
        tag = Tag(name=normalized, display_name=" ".join(str(name).split()))
        service.document.tags.append(tag)
        created = True
    changed = False
    if asset_id is not None:
        ids = service.document.asset_tags.setdefault(asset_id, [])
        if tag.id not in ids:
            ids.append(tag.id)
            changed = True
    if version_id is not None:
        ids = service.document.version_tags.setdefault(version_id, [])
        if tag.id not in ids:
            ids.append(tag.id)
            changed = True
    if created or changed:
        try:
            service._save()
        except Exception:
            if created and tag in service.document.tags:
                service.document.tags.remove(tag)
            if asset_id is not None:
                service.document.asset_tags[asset_id] = [
                    t for t in service.document.asset_tags.get(asset_id, []) if t != tag.id
                ]
            if version_id is not None:
                service.document.version_tags[version_id] = [
                    t for t in service.document.version_tags.get(version_id, []) if t != tag.id
                ]
            raise
    return tag


def remove_tag(
    service,
    name: str,
    *,
    asset_id: str | None = None,
    version_id: str | None = None,
) -> None:
    tag = _tag_by_name(service, name)
    if tag is None:
        return
    changed = False
    if asset_id is not None and tag.id in service.document.asset_tags.get(asset_id, []):
        service.document.asset_tags[asset_id].remove(tag.id)
        changed = True
    if version_id is not None and tag.id in service.document.version_tags.get(version_id, []):
        service.document.version_tags[version_id].remove(tag.id)
        changed = True
    if changed:
        service._save()


def rename_tag(service, old_name: str, new_name: str) -> Tag:
    """Rename a tag; merges into an existing tag on normalized collision."""
    tag = _tag_by_name(service, old_name)
    if tag is None:
        raise CatalogError(f"Unknown tag: {old_name}")
    normalized_new = normalize_tag_name(new_name)
    if not normalized_new:
        raise CatalogError("Empty tag name")
    existing = _tag_by_name(service, normalized_new)
    if existing is not None and existing.id == tag.id:
        tag.display_name = " ".join(str(new_name).split())
        service._save()
        return tag
    if existing is not None:
        # Merge: point all associations at the existing tag, drop the old.
        for ids in list(service.document.asset_tags.values()):
            while tag.id in ids:
                ids.remove(tag.id)
                if existing.id not in ids:
                    ids.append(existing.id)
        for ids in list(service.document.version_tags.values()):
            while tag.id in ids:
                ids.remove(tag.id)
                if existing.id not in ids:
                    ids.append(existing.id)
        service.document.tags.remove(tag)
        service._save()
        return existing
    tag.name = normalized_new
    tag.display_name = " ".join(str(new_name).split())
    service._save()
    return tag


def list_tags(service) -> list[Tag]:
    return list(service.document.tags)


def find_assets_by_tag(service, name: str) -> list[str]:
    tag = _tag_by_name(service, name)
    if tag is None:
        return []
    try:
        if service.index_revision() != service.document.catalog_revision:
            raise RuntimeError("index stale — falling back to scan")
        return sorted(service._index.assets_for_tag(tag.name))
    except Exception:
        return sorted(
            aid
            for aid, ids in service.document.asset_tags.items()
            if tag.id in ids
        )


def find_versions_by_tag(service, name: str) -> list[str]:
    tag = _tag_by_name(service, name)
    if tag is None:
        return []
    try:
        if service.index_revision() != service.document.catalog_revision:
            raise RuntimeError("index stale — falling back to scan")
        return sorted(service._index.versions_for_tag(tag.name))
    except Exception:
        return sorted(
            vid
            for vid, ids in service.document.version_tags.items()
            if tag.id in ids
        )
