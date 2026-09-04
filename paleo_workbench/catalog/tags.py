"""Tag collaborator functions for :class:`DataCatalogService` (private).

The tags section of ``catalog/service.py`` (behind the ``# -- tags --``
banner) extracted into a private collaborator module. Each function takes the
service as its first argument and is composed by the service's thin delegator
methods — the PUBLIC API of ``DataCatalogService`` stays identical.
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.catalog.db import DirtySet
from paleo_workbench.catalog.models import CatalogError, Tag, normalize_tag_name


class _TagJournal:
    """Lazy rollback journal for tag mutations (#1182).

    The old up-front ``_usage_snapshot`` deep-copied the whole tag list and
    BOTH association maps on every mutation — O(tags + associations) paid on
    the success path too. The journal records only the entries a mutator
    actually touches (prior association lists, removed tag positions, tag
    field values); ``rollback()`` replays it to restore the exact pre-call
    state. Success pays nothing beyond the per-mutation bookkeeping below.
    """

    __slots__ = ("_document", "_lists", "_removed_tags", "_created_tags", "_fields")

    def __init__(self, document: Any) -> None:
        self._document = document
        # (attr, key) -> prior list, or None when the key did not exist yet
        self._lists: dict[tuple[str, str], list[str] | None] = {}
        # (index-at-removal, tag) pairs; rollback re-inserts in reverse order
        self._removed_tags: list[tuple[int, Tag]] = []
        # Entities CREATED during the mutation; rollback removes them again
        self._created_tags: list[Tag] = []
        # (tag, field, prior value) triples
        self._fields: list[tuple[Tag, str, Any]] = []

    def record_list(self, attr: str, key: str) -> None:
        """Capture the prior association list for *key* (first capture wins)."""
        if (attr, key) in self._lists:
            return
        mapping = getattr(self._document, attr)
        self._lists[(attr, key)] = (
            None if key not in mapping else list(mapping[key])
        )

    def record_tag_field(self, tag: Tag, field: str) -> None:
        self._fields.append((tag, field, getattr(tag, field)))

    def record_tag_removed(self, tag: Tag) -> None:
        self._removed_tags.append((self._document.tags.index(tag), tag))

    def record_tag_created(self, tag: Tag) -> None:
        """Record an entity appended during the mutation (rollback un-appends)."""
        self._created_tags.append(tag)

    def drop_empty_keys(self) -> None:
        """``_drop_empty_associations`` with each deleted key journaled."""
        for attr in ("asset_tags", "version_tags"):
            mapping = getattr(self._document, attr)
            for key in [k for k, ids in mapping.items() if not ids]:
                self.record_list(attr, key)
                del mapping[key]

    def rollback(self) -> None:
        for tag, field, value in reversed(self._fields):
            setattr(tag, field, value)
        # Reverse removal order: each captured index is a position in the
        # list as it stood at that removal, so re-inserting in reverse
        # reproduces the original arrangement exactly.
        for index, tag in reversed(self._removed_tags):
            self._document.tags.insert(index, tag)
        for tag in reversed(self._created_tags):
            tags = self._document.tags
            for position, existing in enumerate(tags):
                if existing is tag:
                    del tags[position]
                    break
        for (attr, key), prior in self._lists.items():
            mapping = getattr(self._document, attr)
            if prior is None:
                mapping.pop(key, None)
            else:
                mapping[key] = prior


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
    """Get-or-create a normalized tag and associate it. Idempotent.

    Holds the service lock across mutation and save so a concurrent import /
    save can never interleave a half-applied association into the document.
    """
    with service._lock:
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
            dirty = DirtySet(tags={tag.id: None} if created else {})
            if asset_id is not None and changed:
                dirty.mark_asset_tags(asset_id)
            if version_id is not None and changed:
                dirty.mark_version_tags(version_id)
            try:
                service._save(dirty)
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
    """Remove one tag association; unknown tag name is a no-op.

    Journaled rollback on a failed canonical save (same discipline as the
    other tag mutators): a failed removal must not leave a half-applied
    association in memory while the disk still holds the old state.
    """
    with service._lock:
        tag = _tag_by_name(service, name)
        if tag is None:
            return
        journal = _TagJournal(service.document)
        try:
            changed = False
            if asset_id is not None and tag.id in service.document.asset_tags.get(asset_id, []):
                journal.record_list("asset_tags", asset_id)
                service.document.asset_tags[asset_id].remove(tag.id)
                changed = True
            if version_id is not None and tag.id in service.document.version_tags.get(version_id, []):
                journal.record_list("version_tags", version_id)
                service.document.version_tags[version_id].remove(tag.id)
                changed = True
            if changed:
                journal.drop_empty_keys()
                dirty = DirtySet()
                if asset_id is not None:
                    dirty.mark_asset_tags(asset_id)
                if version_id is not None:
                    dirty.mark_version_tags(version_id)
                service._save(dirty)
        except Exception:
            journal.rollback()
            raise


def rename_tag(
    service,
    old_name: str,
    new_name: str,
    *,
    on_collision: str = "merge",
) -> Tag:
    """Rename a tag.

    On normalized collision with an existing tag the default (``merge``,
    historical behavior) re-points every association at the existing tag and
    drops the old one; ``on_collision="error"`` refuses the rename instead so
    callers can ask the user how to proceed. Every mutating branch restores the
    pre-call state when the canonical save fails.
    """
    with service._lock:
        tag = _tag_by_name(service, old_name)
        if tag is None:
            raise CatalogError(f"Unknown tag: {old_name}")
        normalized_new = normalize_tag_name(new_name)
        if not normalized_new:
            raise CatalogError("Empty tag name")
        existing = _tag_by_name(service, normalized_new)
        if existing is not None and existing.id == tag.id:
            journal = _TagJournal(service.document)
            try:
                journal.record_tag_field(tag, "display_name")
                tag.display_name = " ".join(str(new_name).split())
                service._save(DirtySet(tags={tag.id: None}))
                return tag
            except Exception:
                journal.rollback()
                raise
        if existing is not None:
            if on_collision == "error":
                raise CatalogError(
                    f"Tag '{normalized_new}' already exists; rename would merge"
                )
            return merge_tag_into(service, tag, existing)
        journal = _TagJournal(service.document)
        try:
            journal.record_tag_field(tag, "name")
            journal.record_tag_field(tag, "display_name")
            tag.name = normalized_new
            tag.display_name = " ".join(str(new_name).split())
            service._save(DirtySet(tags={tag.id: None}))
            return tag
        except Exception:
            journal.rollback()
            raise


def merge_tag_into(service, source: Tag, target: Tag) -> Tag:
    """Re-point every association from *source* at *target* and drop *source*.

    Journaled rollback: a failed canonical save restores the pre-merge state
    so a "failed" merge can never be silently persisted by a later write.
    """
    journal = _TagJournal(service.document)
    touched_assets: dict[str, None] = {}
    touched_versions: dict[str, None] = {}
    try:
        for owner, ids in service.document.asset_tags.items():
            if source.id in ids:
                touched_assets[owner] = None
                journal.record_list("asset_tags", owner)
                ids[:] = [i for i in ids if i != source.id]
                if target.id not in ids:
                    ids.append(target.id)
        for owner, ids in service.document.version_tags.items():
            if source.id in ids:
                touched_versions[owner] = None
                journal.record_list("version_tags", owner)
                ids[:] = [i for i in ids if i != source.id]
                if target.id not in ids:
                    ids.append(target.id)
        if source in service.document.tags:
            journal.record_tag_removed(source)
            service.document.tags.remove(source)
        journal.drop_empty_keys()
        service._save(
            DirtySet(
                tags={source.id, target.id},
                asset_tags=touched_assets,
                version_tags=touched_versions,
            )
        )
        return target
    except Exception:
        journal.rollback()
        raise


def merge_tags(service, source_name: str, target_name: str) -> Tag:
    """Merge *source_name* into *target_name* (both must exist)."""
    with service._lock:
        source = _tag_by_name(service, source_name)
        if source is None:
            raise CatalogError(f"Unknown tag: {source_name}")
        target = _tag_by_name(service, target_name)
        if target is None:
            raise CatalogError(f"Unknown tag: {target_name}")
        if source.id == target.id:
            return target
        return merge_tag_into(service, source, target)


def create_tag(service, name: str) -> Tag:
    """Create (or return) a tag entity WITHOUT associating it with anything.

    Single-transaction create for Tag Manager-style governance UIs; keeps the
    catalog free of the add-then-remove workaround and its partial-failure
    states. Idempotent on the normalized name (display name refreshed).
    """
    normalized = normalize_tag_name(name)
    if not normalized:
        raise CatalogError("Empty tag name")
    with service._lock:
        tag = _tag_by_name(service, normalized)
        if tag is not None:
            return tag
        tag = Tag(name=normalized, display_name=" ".join(str(name).split()))
        service.document.tags.append(tag)
        try:
            service._save(DirtySet(tags={tag.id: None}))
            return tag
        except Exception:
            if tag in service.document.tags:
                service.document.tags.remove(tag)
            raise


def list_tags(service) -> list[Tag]:
    return list(service.document.tags)


def bulk_add_tag(
    service,
    name: str,
    *,
    asset_ids: tuple[str, ...] | list[str] = (),
    version_ids: tuple[str, ...] | list[str] = (),
) -> Tag:
    """Associate one tag with MANY assets/versions in a single catalog write.

    Get-or-create semantics (same as :func:`add_tag`); idempotent per target.
    """
    asset_ids = list(asset_ids)
    version_ids = list(version_ids)
    if not asset_ids and not version_ids:
        raise CatalogError("bulk_add_tag requires asset_ids or version_ids")
    normalized = normalize_tag_name(name)
    if not normalized:
        raise CatalogError("Empty tag name")
    with service._lock:
        for asset_id in asset_ids:
            service._asset_or_raise(asset_id)
        for version_id in version_ids:
            service._version_or_raise(version_id)
        journal = _TagJournal(service.document)
        try:
            tag = _tag_by_name(service, normalized)
            changed = False
            created = False
            if tag is None:
                tag = Tag(name=normalized, display_name=" ".join(str(name).split()))
                service.document.tags.append(tag)
                # A failed save must un-create the entity again.
                journal.record_tag_created(tag)
                created = True
                changed = True
            for asset_id in asset_ids:
                ids = service.document.asset_tags.get(asset_id)
                if ids is None or tag.id not in ids:
                    # Capture BEFORE setdefault can create the key.
                    journal.record_list("asset_tags", asset_id)
                    ids = service.document.asset_tags.setdefault(asset_id, [])
                    if tag.id not in ids:
                        ids.append(tag.id)
                        changed = True
            for version_id in version_ids:
                ids = service.document.version_tags.get(version_id)
                if ids is None or tag.id not in ids:
                    journal.record_list("version_tags", version_id)
                    ids = service.document.version_tags.setdefault(version_id, [])
                    if tag.id not in ids:
                        ids.append(tag.id)
                        changed = True
            if changed:
                service._save(
                    DirtySet(
                        tags={tag.id: None} if created else {},
                        asset_tags=dict.fromkeys(asset_ids),
                        version_tags=dict.fromkeys(version_ids),
                    )
                )
            return tag
        except Exception:
            journal.rollback()
            raise


def bulk_remove_tag(
    service,
    name: str,
    *,
    asset_ids: tuple[str, ...] | list[str] = (),
    version_ids: tuple[str, ...] | list[str] = (),
) -> None:
    """Remove one tag association from MANY assets/versions in one write.

    The tag entity itself survives (use :func:`delete_unused_tag` /
    :func:`prune_unused_tags` for that). Unknown tag name is a no-op.
    """
    asset_ids = list(asset_ids)
    version_ids = list(version_ids)
    if not asset_ids and not version_ids:
        raise CatalogError("bulk_remove_tag requires asset_ids or version_ids")
    with service._lock:
        tag = _tag_by_name(service, name)
        if tag is None:
            return
        journal = _TagJournal(service.document)
        try:
            changed = False
            for asset_id in asset_ids:
                ids = service.document.asset_tags.get(asset_id)
                if ids and tag.id in ids:
                    journal.record_list("asset_tags", asset_id)
                    ids.remove(tag.id)
                    changed = True
            for version_id in version_ids:
                ids = service.document.version_tags.get(version_id)
                if ids and tag.id in ids:
                    journal.record_list("version_tags", version_id)
                    ids.remove(tag.id)
                    changed = True
            if changed:
                journal.drop_empty_keys()
                service._save(
                    DirtySet(
                        asset_tags=dict.fromkeys(asset_ids),
                        version_tags=dict.fromkeys(version_ids)
                    )
                )
        except Exception:
            journal.rollback()
            raise


def tag_usage(service) -> dict[str, dict]:
    """Association counts per tag id: ``{"name", "display_name", "assets",
    "versions"}`` — Asset Tags and Version Tags are counted separately."""
    counts = {
        tag.id: {
            "name": tag.name,
            "display_name": tag.display_name or tag.name,
            "assets": 0,
            "versions": 0,
        }
        for tag in service.document.tags
    }
    for ids in service.document.asset_tags.values():
        for tag_id in ids:
            entry = counts.get(tag_id)
            if entry is not None:
                entry["assets"] += 1
    for ids in service.document.version_tags.values():
        for tag_id in ids:
            entry = counts.get(tag_id)
            if entry is not None:
                entry["versions"] += 1
    return counts


def search_tags(service, text: str, *, limit: int | None = None) -> list[Tag]:
    """Substring search over tag names (normalized on both sides)."""
    needle = normalize_tag_name(text)
    if not needle:
        matches = list(service.document.tags)
    else:
        matches = [
            tag
            for tag in service.document.tags
            if needle in tag.name
            or (tag.display_name and needle in normalize_tag_name(tag.display_name))
        ]
    return matches if limit is None else matches[:limit]


def delete_unused_tag(service, name: str) -> Tag:
    """Delete a tag entity that has ZERO associations (refuses otherwise).

    Holds the service lock across the usage check and the removal so a
    concurrent association write cannot race the check (which would persist a
    dangling association).
    """
    with service._lock:
        tag = _tag_by_name(service, name)
        if tag is None:
            raise CatalogError(f"Unknown tag: {name}")
        usage = tag_usage(service).get(tag.id, {})
        if usage.get("assets", 0) or usage.get("versions", 0):
            raise CatalogError(
                f"Tag '{tag.name}' is still in use "
                f"({usage.get('assets', 0)} assets, {usage.get('versions', 0)} versions)"
            )
        journal = _TagJournal(service.document)
        try:
            journal.record_tag_removed(tag)
            service.document.tags.remove(tag)
            service._save(DirtySet(tags={tag.id: None}))
            return tag
        except Exception:
            journal.rollback()
            raise


def prune_unused_tags(service) -> list[Tag]:
    """Delete every zero-association tag entity; returns the removed tags.

    Locked end-to-end for the same race reason as :func:`delete_unused_tag`.
    """
    with service._lock:
        usage = tag_usage(service)
        unused = [
            tag
            for tag in service.document.tags
            if not usage.get(tag.id, {}).get("assets")
            and not usage.get(tag.id, {}).get("versions")
        ]
        if not unused:
            return []
        journal = _TagJournal(service.document)
        try:
            for tag in unused:
                journal.record_tag_removed(tag)
                service.document.tags.remove(tag)
            service._save(DirtySet(tags=dict.fromkeys(t.id for t in unused)))
            return unused
        except Exception:
            journal.rollback()
            raise


def find_assets_by_tag(service, name: str) -> list[str]:
    tag = _tag_by_name(service, name)
    if tag is None:
        return []
    try:
        # During batch_save the SQLite store lags the document by design
        # (rows commit at batch exit) while the revision stays aligned
        # (#1139) — the document scan is the authoritative view there.
        if (
            service._batch_depth
            or service.index_revision() != service.document.catalog_revision
        ):
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
        if (
            service._batch_depth
            or service.index_revision() != service.document.catalog_revision
        ):
            raise RuntimeError("index stale — falling back to scan")
        return sorted(service._index.versions_for_tag(tag.name))
    except Exception:
        return sorted(
            vid
            for vid, ids in service.document.version_tags.items()
            if tag.id in ids
        )
