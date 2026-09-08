"""DataCatalogService — the single write entry point for data lifecycle (ADR 0056).

UI and business code must go through this service instead of appending to
``project.resources`` or hand-editing artifact files. The service hides file
layout, hashing, transactions, canonical persistence, and the SQLite store
behind a small stable API.

Invariants enforced:

- Managed RAW versions are immutable: payloads are placed atomically and
  marked read-only; committing over an existing version id raises
  :class:`ImmutableVersionError`.
- Every committed DataVersion is immutable; change produces a new version.
- Checksum mismatches are reported, never silently adopted.
- The canonical store is ``metadata/catalog.sqlite`` (WAL, one transaction
  per mutation, row-level writes driven by dirty sets — #1027);
  ``metadata/catalog.json`` is a checkpoint/export manifest written on
  close/explicit export and by legacy app versions.

The API is synchronous and IO-bound; UI integration should wrap calls in a
worker thread (all state lives in this object, no globals).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from paleo_workbench.catalog import audit as _audit
from paleo_workbench.catalog import lineage_graph as _lineage
from paleo_workbench.catalog import queries as _queries
from paleo_workbench.catalog import sources as _sources
from paleo_workbench.catalog import tags as _tags
from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.db import (
    STORE_SCHEMA_VERSION,
    CatalogIndex,
    CatalogStaleWriteError,
    DirtySet,
    normalize_asset_search_name,
)
from paleo_workbench.catalog.gc import (
    GcReport,
    cleanup_working_copies as _gc_cleanup_working_copies,
    plan_gc as _gc_plan,
    sweep_gc as _gc_sweep,
)
from paleo_workbench.catalog.model_gates import can_promote_to_production
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
    ImmutableVersionError,
    CatalogError,
    Model,
    ModelVersion,
    Tag,
)
from paleo_workbench.catalog.queries import IntegrityReport
from paleo_workbench.catalog.storage import (
    create_working_copy as _place_working_copy,
    ensure_catalog_layout as _ensure_catalog_layout,
    is_cas_path,
    is_safe_entity_id,
    place_managed_file,
    purge_trashed_payload,
    restore_payload as _restore_trashed_payload,
    safe_unlink,
    trash_dir_for as _trash_dir_for,
    trash_payload as _move_to_trash,
)
from paleo_workbench.catalog.store import CatalogStore, catalog_file_for
from paleo_workbench.project.models import _now_iso
from paleo_workbench.project.paths import artifact_dir_for


class _CatalogMaps:
    """One immutable-swap container for the id / dedup indexes.

    The dicts inside stay mutable for incremental ``_add_*`` / ``_remove_*``
    updates. Readers must hold this object (from ``_ensure_maps()``) rather
    than re-reading the attributes after a concurrent invalidate.
    """

    __slots__ = (
        "asset_by_id",
        "version_by_id",
        "run_by_id",
        "versions_by_asset",
        "children_by_parent",
        "assets_by_legacy_id",
        # Import-dedup identity indexes (#1139): the exact keys the adapter's
        # ``_find_managed_raw`` / ``_find_external_by_path`` look up, kept in
        # memory so bulk imports stay O(1) per file regardless of SQLite
        # freshness. Candidates are validated against the live document at
        # lookup, so a missed maintenance site degrades to the self-healing
        # scan — never a wrong positive.
        "managed_raw_by_key",
        "external_by_path",
    )

    def __init__(
        self,
        *,
        asset_by_id: dict[str, DataAsset],
        version_by_id: dict[str, DataVersion],
        run_by_id: dict[str, DataRun],
        versions_by_asset: dict[str, list[DataVersion]],
        children_by_parent: dict[str, list[DataVersion]],
        assets_by_legacy_id: dict[str, DataAsset],
        managed_raw_by_key: dict[tuple[str, str], str],
        external_by_path: dict[str, str],
    ) -> None:
        self.asset_by_id = asset_by_id
        self.version_by_id = version_by_id
        self.run_by_id = run_by_id
        self.versions_by_asset = versions_by_asset
        self.children_by_parent = children_by_parent
        self.assets_by_legacy_id = assets_by_legacy_id
        self.managed_raw_by_key = managed_raw_by_key
        self.external_by_path = external_by_path


def _managed_raw_dedup_key(version: DataVersion) -> tuple[str, str] | None:
    """Identity key used by managed-RAW import dedup, or None (not eligible)."""
    if (
        version.managed
        and version.stage == DataStage.RAW
        and not version.trashed
        and version.source_uri
        and version.sha256
    ):
        return (version.source_uri, version.sha256)
    return None


def _external_dedup_key(version: DataVersion) -> str | None:
    """Identity key used by external-link dedup, or None (not eligible)."""
    if not version.managed and not version.trashed and version.path:
        return version.path
    return None


class _BatchSave:
    """Context manager returned by :meth:`DataCatalogService.batch_save`.

    Accumulates the mutations' dirty sets and persists them in ONE SQLite
    transaction at outermost exit — no full-document serialization, no
    in-memory deep copy (#1027). Atomicity comes from the transaction: when
    the body (or the flush) fails, the database rolls back and the in-memory
    document is reloaded from the store, so memory never diverges from disk.
    """

    def __init__(self, service: "DataCatalogService") -> None:
        self._service = service

    def __enter__(self) -> "DataCatalogService":
        service = self._service
        with service._lock:
            if service._batch_depth == 0:
                # #1139: sample the index freshness baseline once per batch.
                # The SQLite index only learns about this batch at exit
                # flush, so during the batch it is complete exactly for the
                # pre-batch rows — unioned with the overlay, absence proofs
                # need no document scan.
                service._batch_base_revision = service.document.catalog_revision
                service._batch_overlay_managed = {}
                service._batch_overlay_external = {}
            service._batch_depth += 1
        return service

    def __exit__(self, exc_type, exc, tb) -> bool:
        service = self._service
        with service._lock:
            service._batch_depth -= 1
            if service._batch_depth:
                return False  # an outer batch still owns the flush
            service._batch_base_revision = None
            service._batch_overlay_managed = {}
            service._batch_overlay_external = {}
            if exc_type is not None or (
                service._pending_dirty.is_empty() and not service._pending_reconcile
            ):
                # Body failed or nothing changed: nothing may persist —
                # reload the (untouched) canonical state so memory matches
                # the store again.
                service._reload_document_locked()
                return False
            combined = service._pending_dirty
            reconcile = service._pending_reconcile
            service._pending_dirty = DirtySet()
            service._pending_reconcile = False
            # The revision advances exactly once, HERE, with the batch's
            # single transaction (#1139): bumping it per in-batch _save made
            # ``document.catalog_revision`` run ahead of the store's view for
            # the whole batch, so every freshness check that compares the two
            # (dedup, tag lookups) failed and degraded to linear scans. A
            # failed flush below reloads the document from the store, which
            # also restores the pre-batch revision — the old
            # "flush failure rolls the revision back" semantics keep holding.
            service.document.catalog_revision += 1
            try:
                service._flush_canonical_locked(combined, reconcile=reconcile)
            except Exception:
                service._reload_document_locked()
                raise
            service._maybe_checkpoint_manifest_locked()
            return False
def _disk_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _discard_by_identity(items: list, target: object) -> None:
    """Remove *target* from *items* by identity in one pointer-compare scan.

    ``list.remove`` matches by value — for pydantic models that is an
    O(fields) comparison per probe and can evict a different-but-equal twin
    (#1044). Identity is the correct key for entities owned by the document.
    """
    for index, item in enumerate(items):
        if item is target:
            del items[index]
            return


def _recorded_manifest_mtime_ns(index: CatalogIndex) -> int | None:
    """mtime the manifest had when we (or nobody) last wrote it."""
    raw = index._read_sync_state("manifest_mtime_ns")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _record_manifest_mtime_ns(index: CatalogIndex, path: Path) -> None:
    mtime = _disk_mtime_ns(path)
    if mtime is None:
        return
    conn = index.open()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)",
                ("manifest_mtime_ns", str(mtime)),
            )
    except Exception:
        pass  # bookkeeping only; never fails a checkpoint


class DataCatalogService:
    """Unified lifecycle service for one project."""

    def __init__(
        self,
        project_path: str | Path,
        document: CatalogDocument,
        store: CatalogStore,
        index: CatalogIndex,
    ):
        self.project_path = Path(project_path)
        self.document = document
        self._store = store
        self._index = index
        # Guards document mutation vs. concurrent readers: the UI hashes
        # payloads (verify_integrity) on a worker thread while the UI thread
        # may be saving. Re-entrant so public methods can nest under _save.
        self._lock = threading.RLock()
        # Monotonic counter advanced by EVERY _save call — including the ones
        # deferred inside batch_save. Revision-keyed caches (adapter tag map,
        # lineage summaries) use it alongside catalog_revision so a mutation
        # inside a batch (where the revision now stays put until commit,
        # #1139) still invalidates them.
        self._mutation_serial: int = 0
        # Active :meth:`batch_save` nesting depth: >0 accumulates dirty sets.
        self._batch_depth = 0
        # Dirty entities accumulated by the current (outermost) batch, and
        # whether any unmarked mutation requires a full reconcile at exit.
        self._pending_dirty = DirtySet()
        self._pending_reconcile = False
        # #1139: batch dedup overlay. While a batch is open, versions added
        # via _add_version are recorded here so _find_managed_raw /
        # _find_external_by_path can prove absence from (index ∪ overlay)
        # without the O(N) document scan. Reset at every batch boundary.
        self._batch_base_revision: int | None = None
        self._batch_overlay_managed: dict[tuple[str | None, str | None], str] = {}
        self._batch_overlay_external: dict[str, str] = {}
        # Cross-process stale-write baseline: the store's catalog_revision as
        # of open / last successful flush. A flush whose on-disk revision
        # differs means another process committed since we last looked
        # (#411); the revision is read from the store itself, which is both
        # portable and immune to mtime granularity.
        self._flushed_revision: int | None = None
        # Mutations since the last catalog.json manifest checkpoint; the
        # manifest is rewritten only at close / explicit export / throttled
        # checkpoints so single-row mutations never pay an O(N) rewrite.
        self._mutations_since_manifest = 0
        # Maintained id→object indexes (P4): every document list mutation goes
        # through ``_add_*`` / ``_remove_*`` so lookups stay O(1) instead of
        # linear scans. ``None`` = not yet built (built lazily from the
        # document on first use). A lookup miss rebuilds the maps from the
        # document as a self-healing safety net, so a missed maintenance site
        # can never return a wrong *negative* answer (only rebuild cost).
        # Published as one snapshot so unlocked readers never observe a
        # mid-rebuild / mid-invalidate None window (#619).
        self._maps: _CatalogMaps | None = None
        # Lazy open (#1212): a service opened ``lazy=True`` starts with an
        # EMPTY document and serves hot reads (get/list/page/count/aggregate)
        # straight from the canonical SQLite store until a background
        # ``warm_document()`` (or the first mutation / full-document read,
        # which materializes inline) swaps in the fully materialized document.
        # ``_warm`` is True for every eagerly-opened service, so all
        # pre-existing behavior is unchanged unless lazy was requested.
        self._lazy: bool = False
        self._warm: bool = True
        # Asset ids appended by an in-flight commit_working_copy whose
        # version has not landed yet (the #1218 lock-free payload window):
        # zombie classifiers must not treat these as removable (R2#5).
        self._pending_commit_assets: set[str] = set()
        # id→model cache for lazy reads before warmup: keeps object identity
        # stable within the pre-warm window (the UI holds these objects).
        # Cleared when the warm document swaps in.
        self._lazy_read_cache: dict[str, Any] = {}

    # -- change tracking ------------------------------------------------------

    @property
    def mutation_serial(self) -> int:
        """Monotonic counter advanced by EVERY mutation, batch or not.

        Public read-only contract for revision-keyed caches (freshness
        dependency graphs, adapter tag maps, lineage summaries):
        ``catalog_revision`` alone cannot key them because inside
        :meth:`batch_save` the revision is held until the batch commits
        (#1139) while the in-memory document has already changed. This
        serial bumps on every ``_save`` — including saves deferred inside a
        batch — so a cache keyed on it never serves a pre-mutation view of
        the document. It never resets; only ever increases.
        """
        return self._mutation_serial

    # -- maintained indexes -------------------------------------------------

    @property
    def _asset_by_id(self) -> dict[str, DataAsset] | None:
        maps = self._maps
        return None if maps is None else maps.asset_by_id

    @property
    def _version_by_id(self) -> dict[str, DataVersion] | None:
        maps = self._maps
        return None if maps is None else maps.version_by_id

    @property
    def _run_by_id(self) -> dict[str, DataRun] | None:
        maps = self._maps
        return None if maps is None else maps.run_by_id

    @property
    def _versions_by_asset(self) -> dict[str, list[DataVersion]] | None:
        maps = self._maps
        return None if maps is None else maps.versions_by_asset

    @property
    def _children_by_parent(self) -> dict[str, list[DataVersion]] | None:
        maps = self._maps
        return None if maps is None else maps.children_by_parent

    @property
    def _assets_by_legacy_id(self) -> dict[str, DataAsset] | None:
        maps = self._maps
        return None if maps is None else maps.assets_by_legacy_id

    @_assets_by_legacy_id.setter
    def _assets_by_legacy_id(self, value: dict[str, DataAsset] | None) -> None:
        maps = self._maps
        if maps is not None and value is not None:
            maps.assets_by_legacy_id = value

    def _invalidate_maps(self) -> None:
        """Drop the cached indexes; they rebuild lazily on next use."""
        self._maps = None

    # -- lazy open warmup (#1212) ---------------------------------------------

    @property
    def is_warm(self) -> bool:
        """True once the full document is materialized (always true when the
        service was opened eagerly)."""
        return self._warm

    def require_warm(self) -> None:
        """Block until the full document is materialized.

        No-op for eager services and already-warm lazy services. For a lazy
        service still pre-warm, materializes inline (same cost the eager
        open used to pay, paid by whichever caller needs the full document
        first). Correct-by-construction: there is exactly one document
        object and one identity space — no merge logic.
        """
        if self._warm:
            return
        with self._lock:
            if not self._warm:
                self._warm_locked()

    def warm_document(self) -> None:
        """Background warmup for a lazily-opened service.

        Loads the full document off the service lock, then swaps it in under
        the lock. Safe to race ``require_warm`` (inline materialization) and
        arbitrary mutations: any mutation path materializes first via
        ``_ensure_maps``, so a store revision that moved past the loaded
        snapshot implies an inline warm already happened and this load is
        simply discarded.
        """
        if self._warm:
            return
        document = self._index.load_document()
        with self._lock:
            if self._warm:
                return  # inline warm won the race; discard this snapshot
            if document is None:
                # Unreadable mid-warmup (rare; open health-checked it):
                # fall back to the inline path so the error surfaces from
                # whichever caller needs the document.
                self._warm_locked()
                return
            stored = self._index.revision()
            if (
                stored is not None
                and document.catalog_revision is not None
                and stored != document.catalog_revision
            ):
                # The store advanced past the loaded snapshot: a mutation
                # committed while we were loading — but every mutation
                # implies an inline warm (see above), so this cannot happen
                # without ``_warm`` already being set. Reachable only via a
                # legacy json-canonical writer; discard and warm inline.
                self._warm_locked()
                return
            self.document = document
            self._invalidate_maps()
            # _warm BEFORE _ensure_maps (see _warm_locked): the maps builder
            # itself branches on _warm for the inline trigger.
            self._warm = True
            self._ensure_maps()
            self._lazy_read_cache.clear()

    def _warm_locked(self) -> None:
        """Materialize the full document; caller holds ``_lock``."""
        document = self._index.load_document()
        if document is None:
            raise CatalogError(
                "Canonical catalog store became unreadable while opening; "
                "resolve the read failure (close other instances) and reopen."
            )
        self.document = document
        self._invalidate_maps()
        # Set _warm BEFORE building the maps: _ensure_maps itself branches
        # on _warm for the inline-materialization trigger and would recurse
        # otherwise.
        self._warm = True
        self._ensure_maps()
        self._lazy_read_cache.clear()

    def _require_warm(self) -> None:
        """Internal alias used by the warm-guard method wrappers."""
        self.require_warm()

    def _drop_dedup_keys(self, version: DataVersion) -> None:
        """Remove *version*'s dedup-index entries (only when still its own).

        Keys are computed trash-agnostically: an entry may have been indexed
        while live and survived a later trash flip (trash does not go through
        add/remove). Lookups validate candidates against the live document
        and self-heal via the scan fallback anyway (#1139) — this is just the
        cheap steady-state maintenance.
        """
        maps = self._maps
        if maps is None:
            return
        if (
            version.managed
            and version.stage == DataStage.RAW
            and version.source_uri
            and version.sha256
            and maps.managed_raw_by_key.get(
                (version.source_uri, version.sha256)
            )
            == version.id
        ):
            del maps.managed_raw_by_key[(version.source_uri, version.sha256)]
        if (
            not version.managed
            and version.path
            and maps.external_by_path.get(version.path) == version.id
        ):
            del maps.external_by_path[version.path]

    def _ensure_maps(self) -> _CatalogMaps:
        """Build the id→object indexes from the document (idempotent)."""
        if not self._warm:
            # Lazy pre-warm: the document is empty by design. Materialize it
            # now (inline warmup) so the maps — and every mutation that
            # follows — see the real entity graph. This is the single
            # convergence point that keeps lazy and eager behavior
            # identical after the first mutation.
            self._warm_locked()
            return self._maps  # type: ignore[return-value]
        maps = self._maps
        if maps is not None:
            return maps
        versions_by_asset: dict[str, list[DataVersion]] = {}
        children: dict[str, list[DataVersion]] = {}
        managed_raw_by_key: dict[tuple[str, str], str] = {}
        external_by_path: dict[str, str] = {}
        for version in self.document.versions:
            versions_by_asset.setdefault(version.asset_id, []).append(version)
            for pid in version.parent_version_ids:
                children.setdefault(pid, []).append(version)
            raw_key = _managed_raw_dedup_key(version)
            if raw_key is not None:
                managed_raw_by_key.setdefault(raw_key, version.id)
            ext_key = _external_dedup_key(version)
            if ext_key is not None:
                external_by_path.setdefault(ext_key, version.id)
        # Legacy-bridge resolution order mirrors ``_find_asset_by_legacy_id``:
        # an asset whose *id* equals the legacy id wins; otherwise the first
        # asset bridged via ``legacy_resource_id`` (first-wins via setdefault).
        legacy: dict[str, DataAsset] = {}
        for asset in self.document.assets:
            legacy[asset.id] = asset
        for asset in self.document.assets:
            if asset.legacy_resource_id is not None:
                legacy.setdefault(asset.legacy_resource_id, asset)
        maps = _CatalogMaps(
            asset_by_id={a.id: a for a in self.document.assets},
            version_by_id={v.id: v for v in self.document.versions},
            run_by_id={r.id: r for r in self.document.runs},
            versions_by_asset=versions_by_asset,
            children_by_parent=children,
            assets_by_legacy_id=legacy,
            managed_raw_by_key=managed_raw_by_key,
            external_by_path=external_by_path,
        )
        self._maps = maps
        return maps

    def _maps_consistent(self) -> bool:
        """Debug/self-check: cached indexes match the document exactly."""
        maps = self._ensure_maps()
        if len(maps.asset_by_id) != len(self.document.assets):
            return False
        if len(maps.version_by_id) != len(self.document.versions):
            return False
        if len(maps.run_by_id) != len(self.document.runs):
            return False
        for asset in self.document.assets:
            if maps.asset_by_id.get(asset.id) is not asset:
                return False
        for version in self.document.versions:
            if maps.version_by_id.get(version.id) is not version:
                return False
            if maps.versions_by_asset.get(version.asset_id) is None:
                return False
        return True

    def _add_asset(self, asset: DataAsset) -> None:
        self.document.assets.append(asset)
        if self._asset_by_id is not None:
            self._asset_by_id[asset.id] = asset
            if self._assets_by_legacy_id is not None:
                self._assets_by_legacy_id[asset.id] = asset
                if asset.legacy_resource_id is not None:
                    holder = self._assets_by_legacy_id.get(
                        asset.legacy_resource_id
                    )
                    # A trashed asset still holds its legacy id; a fresh
                    # (live) re-import takes over the bridge so the legacy id
                    # resolves to live data (review finding I2).
                    if holder is None or holder.trashed:
                        self._assets_by_legacy_id[asset.legacy_resource_id] = asset
                    else:
                        self._assets_by_legacy_id.setdefault(
                            asset.legacy_resource_id, asset
                        )

    def _remove_asset(self, asset: DataAsset) -> None:
        """Drop one asset by identity without touching sibling mappings.

        Pydantic value-equality (``in``/``list.remove``) costs an O(N)
        field-comparing scan per probe and can even discard a *different but
        equal* object; identity removal plus a targeted legacy-bridge
        rebridge keeps single deletions O(N) with cheap pointer compares and
        batch deletions near O(N + M) via :meth:`_remove_assets_bulk` (#1044).
        """
        _discard_by_identity(self.document.assets, asset)
        if self._asset_by_id is not None:
            self._asset_by_id.pop(asset.id, None)
        if self._assets_by_legacy_id is not None:
            affected_keys = {asset.id}
            if asset.legacy_resource_id is not None:
                affected_keys.add(asset.legacy_resource_id)
            self._rebridge_legacy_keys(affected_keys)

    def _remove_assets_bulk(self, assets: list[DataAsset]) -> None:
        """Remove many assets in one pass; legacy bridge rebridged once.

        A purge of M assets from an N-asset document must cost O(N + M), not
        M full reindex-and-sort rounds (#1044). Order of survivors is
        preserved.
        """
        if not assets:
            return
        targets = {id(a) for a in assets}
        remaining = [a for a in self.document.assets if id(a) not in targets]
        self.document.assets[:] = remaining
        if self._asset_by_id is not None:
            for asset in assets:
                self._asset_by_id.pop(asset.id, None)
        if self._assets_by_legacy_id is not None:
            affected = {a.id for a in assets}
            for asset in assets:
                if asset.legacy_resource_id is not None:
                    affected.add(asset.legacy_resource_id)
            self._rebridge_legacy_keys(affected, survivors=remaining)

    def _rebridge_legacy_keys(
        self,
        keys: set[str],
        survivors: list[DataAsset] | None = None,
    ) -> None:
        """Recompute legacy-bridge holders for *keys* only.

        A live claimant takes a legacy-bridge key over a trashed one;
        otherwise the first remaining claimant wins (I2). id-keys mirror
        ``_ensure_maps`` survivor order. Only the affected keys are
        normalized — unaffected keys keep their current holder (unlike the
        old full rebuild, which re-sorted everything). One O(N) survivor
        scan per call; the per-deletion sort is gone.
        """
        bridge = self._assets_by_legacy_id
        if bridge is None:
            return
        if survivors is None:
            survivors = self.document.assets
        candidates: dict[str, list[DataAsset]] = {key: [] for key in keys}
        for asset in survivors:
            if asset.id in candidates:
                candidates[asset.id].append(asset)
            legacy_id = asset.legacy_resource_id
            if legacy_id is not None and legacy_id in candidates:
                candidates[legacy_id].append(asset)
        for key, claimants in candidates.items():
            if not claimants:
                # No claimant remains among survivors — drop the stale entry.
                bridge.pop(key, None)
                continue
            if any(a.id == key for a in claimants):
                # id-keys mirror _ensure_maps: survivor order wins
                # unconditionally (no trash preference — review finding C1).
                bridge[key] = next(a for a in claimants if a.id == key)
                continue
            # legacy-bridge keys keep the removal-path semantics: a live
            # claimant takes over a trashed one (I2).
            live = [a for a in claimants if not a.trashed]
            bridge[key] = live[0] if live else claimants[0]

    def _add_version(self, version: DataVersion) -> None:
        self.document.versions.append(version)
        if self._batch_depth:
            # #1139: record batch-added versions for the dedup overlay.
            # Lookups validate liveness/predicates via get_version, so later
            # in-batch removal/trashing can only force a fallback scan,
            # never a wrong hit.
            if version.managed:
                self._batch_overlay_managed[(version.source_uri, version.sha256)] = version.id
            else:
                self._batch_overlay_external[version.path] = version.id
        if self._version_by_id is not None:
            self._version_by_id[version.id] = version
            self._versions_by_asset.setdefault(version.asset_id, []).append(version)
            for pid in version.parent_version_ids:
                self._children_by_parent.setdefault(pid, []).append(version)
            maps = self._maps
            raw_key = _managed_raw_dedup_key(version)
            if raw_key is not None:
                maps.managed_raw_by_key[raw_key] = version.id
            ext_key = _external_dedup_key(version)
            if ext_key is not None:
                maps.external_by_path[ext_key] = version.id

    def _remove_version(self, version: DataVersion) -> None:
        _discard_by_identity(self.document.versions, version)
        if self._version_by_id is not None:
            self._version_by_id.pop(version.id, None)
            bucket = self._versions_by_asset.get(version.asset_id)
            if bucket is not None:
                _discard_by_identity(bucket, version)
            for pid in version.parent_version_ids:
                children = self._children_by_parent.get(pid)
                if children is not None:
                    _discard_by_identity(children, version)
            self._drop_dedup_keys(version)

    def _remove_versions_bulk(self, versions: list[DataVersion]) -> None:
        """Remove many versions in one pass over each affected container (#1044)."""
        if not versions:
            return
        targets = {id(v) for v in versions}
        self.document.versions[:] = [
            v for v in self.document.versions if id(v) not in targets
        ]
        if self._version_by_id is None:
            return
        affected_assets: set[str] = set()
        affected_parents: set[str] = set()
        for version in versions:
            self._version_by_id.pop(version.id, None)
            self._drop_dedup_keys(version)
            affected_assets.add(version.asset_id)
            affected_parents.update(version.parent_version_ids)
        for asset_id in affected_assets:
            bucket = self._versions_by_asset.get(asset_id)
            if bucket is not None:
                bucket[:] = [v for v in bucket if id(v) not in targets]
                if not bucket:
                    # no versions left for this asset: drop the stale bucket
                    # key so versions-for lookups cannot report on removed
                    # assets (review finding on bulk purge maps)
                    del self._versions_by_asset[asset_id]
        for pid in affected_parents:
            children = self._children_by_parent.get(pid)
            if children is not None:
                children[:] = [v for v in children if id(v) not in targets]

    def _add_run(self, run: DataRun) -> None:
        self.document.runs.append(run)
        if self._run_by_id is not None:
            self._run_by_id[run.id] = run

    def _remove_run(self, run: DataRun) -> None:
        _discard_by_identity(self.document.runs, run)
        if self._run_by_id is not None:
            self._run_by_id.pop(run.id, None)

    def _append_parent(self, version_id: str, parent_id: str) -> None:
        """Record a lineage parent on an existing version (attach_lineage)."""
        version = self._version_or_raise(version_id)
        if parent_id not in version.parent_version_ids:
            version.parent_version_ids.append(parent_id)
            if self._children_by_parent is not None:
                self._children_by_parent.setdefault(parent_id, []).append(version)

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def open(
        cls,
        project_path: str | Path,
        *,
        lazy: bool = False,
        sweep_temp: bool = True,
    ) -> "DataCatalogService":
        """Open (or initialize) the catalog for *project_path*.

        Storage resolution (#1027):

        1. A canonical ``catalog.sqlite`` (store layout ≥ 5) is loaded
           directly — unless the JSON manifest changed externally (an OLD
           app version still writing it), in which case the newer revision
           wins and is re-imported transactionally.
        2. Otherwise a legacy ``catalog.json`` project is MIGRATED: the
           document is imported in one transaction; only the verified
           result becomes canonical. The legacy file is never modified, so a
           crash mid-migration leaves the source project fully recoverable.
        3. Neither present → an empty canonical store is initialized.

        ``sweep_temp`` is optional session maintenance, never a prerequisite
        for canonical catalog availability.

        ``lazy=True`` (#1212) skips the O(N) full-document materialization:
        the service opens with the store's revision baseline only and serves
        hot reads (get/list/page/count/aggregate) from SQLite. A background
        ``warm_document()`` swaps in the materialized document; the first
        mutation or full-document read materializes inline instead. Use for
        the GUI project-open path so 100k-scale projects reach a responsive
        shell without waiting for the eager load.
        """
        project_path = Path(project_path)
        store = CatalogStore(project_path)
        index = CatalogIndex(project_path)

        document: CatalogDocument | None = None
        json_path = catalog_file_for(project_path)
        health = index.store_health()
        if health == "canonical" and not lazy:
            document = index.load_document()
            if document is None:
                # Partial corruption: the store passed the health probes
                # but its rows cannot be read (e.g. a data page the probes
                # did not touch). Downgrade to the corrupt flow — forensics
                # + manifest rebuild — instead of silently falling into it
                # (#1027 review, path B).
                health = "corrupt"
        if health == "error":
            # The store EXISTS but is transiently unreadable (busy/locked).
            # Falling through to the manifest would silently overwrite
            # committed canonical data with a stale checkpoint — the exact
            # last-writer-wins #411 refuses. Surface and retry.
            raise CatalogError(
                f"Canonical catalog store exists but is unreadable: "
                f"{index.db_path}. Not overwriting it with the manifest; "
                f"resolve the read failure (close other instances, retry) "
                f"and reopen."
            )
        if health == "corrupt":
            # Deterministic damage (torn/garbage bytes): the store provably
            # holds nothing readable. Isolate the bytes for forensics, then
            # rebuild transactionally from the manifest checkpoint — the
            # disposable-store recovery the project has always had.
            from datetime import datetime as _datetime

            isolated = index.db_path.with_name(
                f"{index.db_path.name}.corrupt-{_datetime.now():%Y%m%d-%H%M%S-%f}"
            )
            # Windows: the health probe's pooled connection holds the file
            # open and blocks the rename — drop the pool first (open-time
            # path is single-threaded; connections reconnect lazily).
            index.close()
            try:
                os.replace(index.db_path, isolated)
            except PermissionError:
                # A reference-cycled sqlite handle (e.g. the throwaway
                # health-probe index) is only released at the next gc
                # collection, and Windows refuses to rename a file an
                # open handle holds. Collect and retry briefly; if a real
                # holder persists, stay best-effort (reset removes the
                # bytes anyway).
                import gc as _gc
                import time as _time

                for _ in range(10):
                    _gc.collect()
                    _time.sleep(0.05)
                    try:
                        os.replace(index.db_path, isolated)
                        break
                    except PermissionError:
                        continue
            except OSError:
                pass  # best-effort forensics; reset() removes the bytes anyway
            index.reset()
        if health == "canonical" and lazy:
            # Lazy path: the store is canonical and healthy. The manifest
            # mtime bookkeeping still runs (cheap mtime compare; the full
            # manifest parse only happens when the mtime moved, i.e. an old
            # json-canonical app version wrote behind our back) so a newer
            # legacy revision is honored BEFORE any read is served.
            revision = index.revision()
            if json_path.is_file():
                recorded = _recorded_manifest_mtime_ns(index)
                current = _disk_mtime_ns(json_path)
                if recorded is None or current is None or recorded != current:
                    try:
                        legacy = store.load()
                    except CatalogError:
                        legacy = None
                    if (
                        legacy is not None
                        and revision is not None
                        and legacy.catalog_revision > revision
                    ):
                        index.write_all(legacy)
                        revision = legacy.catalog_revision
            service = cls(
                project_path,
                CatalogDocument(
                    catalog_revision=revision if revision is not None else 0
                ),
                store,
                index,
            )
            service._flushed_revision = service.document.catalog_revision
            service._lazy = True
            service._warm = False
            return service
        if document is not None and json_path.is_file():
            # The manifest should be exactly what we last checkpointed. A
            # different mtime means an old (json-canonical) app version wrote
            # it behind our back — honor the newer revision. A CORRUPT
            # manifest never blocks open: the store is canonical, so the
            # damage is healed by the next checkpoint instead.
            recorded = _recorded_manifest_mtime_ns(index)
            current = _disk_mtime_ns(json_path)
            if recorded is None or current is None or recorded != current:
                try:
                    legacy = store.load()
                except CatalogError:
                    legacy = None
                if (
                    legacy is not None
                    and legacy.catalog_revision > document.catalog_revision
                ):
                    index.write_all(legacy)
                    document = legacy
        if document is None:
            document = store.load()
            # Transactional migration / initialization. A failure propagates:
            # the legacy json is untouched and the retry starts clean.
            index.write_all(document)
            # F8: record the manifest baseline now so subsequent opens skip
            # the full manifest parse.
            if json_path.is_file():
                _record_manifest_mtime_ns(index, json_path)

        service = cls(project_path, document, store, index)
        service._flushed_revision = document.catalog_revision
        service._ensure_maps()  # eager: the first mutation stays O(Δ)
        if sweep_temp:
            service.sweep_temp_on_open()
        return service

    def sweep_temp_on_open(self) -> None:
        """Conservative cleanup on open: stale temp files and empty dirs.

        Only files that can NEVER be referenced by a version record are
        removed (temp/placement leftovers from crashed saves); payloads,
        working copies and trash are never touched here. Best-effort and
        silent: a failure must never block project open.
        """
        try:
            _gc_sweep(self, dry_run=False, explicit=False)
        except Exception:
            pass

    def close(self) -> None:
        """Checkpoint the JSON manifest, then release the store.

        Lazy-session fast path (#1212): a lazily-opened service that made NO
        mutations skips the manifest rewrite entirely — the on-disk manifest
        already matches the store's committed revision (verified via the
        recorded mtime baseline), so re-exporting would force a full document
        materialization just to reproduce bytes we already have.
        """
        try:
            if self._lazy and self._mutations_since_manifest == 0:
                json_path = catalog_file_for(self.project_path)
                manifest_current = (
                    json_path.is_file()
                    and _recorded_manifest_mtime_ns(self._index)
                    == _disk_mtime_ns(json_path)
                )
                if not manifest_current:
                    self.export_manifest()
            else:
                self.export_manifest()
        except Exception:
            # A manifest failure must never block closing the canonical store.
            pass
        try:
            self._index.close()
        except Exception:
            pass

    def export_manifest(self, *, pretty: bool = False) -> None:
        """Write ``catalog.json`` as a portable manifest of the current state.

        The manifest keeps the project openable by older app versions and
        doubles as a human-readable export artifact; the SQLite store remains
        the only authority (#1027). Atomic write + ``.bak`` via CatalogStore.

        #1183: compact by default (close/checkpoint path); pass
        pretty=True only for an explicit human-readable export.
        """
        with self._lock:
            # #1172: the manifest checkpoint obeys the same #411 stale-write
            # guard as the canonical flush — a session whose commit was
            # refused must not resurrect its rejected state over another
            # process's submission via close(). close() already swallows
            # this; explicit callers get an honest error.
            stored = self._index.revision()
            if stored is not None and stored != self._flushed_revision:
                raise CatalogStaleWriteError(
                    "数据目录元数据已被其他实例修改；为避免覆盖他人提交，"
                    "本次 manifest 导出已中止。请重新打开工程后重试。"
                )
            self._store.save(self.document, pretty=pretty)
            _record_manifest_mtime_ns(self._index, catalog_file_for(self.project_path))
            self._mutations_since_manifest = 0

    # -- persistence --------------------------------------------------------

    def _save(self, dirty: DirtySet | None = None) -> None:
        """Persist the canonical document (dirty rows only when known).

        The revision only advances if the flush succeeds. Inside
        :meth:`batch_save` the write AND the revision bump are deferred to
        the context exit (one transaction for the whole batch) so the
        document's revision keeps matching the store's committed view
        mid-batch (#1139); the mutation serial still advances so
        revision-keyed caches invalidate. Before writing, the store's
        on-disk revision is compared against this session's baseline: a
        store that advanced since we last wrote was committed by another
        process, and overwriting it would silently drop that process's data
        (last-writer-wins, #411) — refuse instead.
        """
        with self._lock:
            self._mutation_serial += 1
            if self._batch_depth:
                if dirty is None:
                    # Unknown mutation scope: the batch exit must reconcile.
                    self._pending_reconcile = True
                else:
                    self._pending_dirty.merge(dirty)
                return
            self.document.catalog_revision += 1
            try:
                self._flush_canonical_locked(
                    dirty or DirtySet(), reconcile=dirty is None
                )
            except Exception:
                self.document.catalog_revision -= 1
                raise
            self._mutations_since_manifest += 1
            self._maybe_checkpoint_manifest_locked()

    def _flush_canonical_locked(
        self, dirty: DirtySet, *, reconcile: bool = False
    ) -> None:
        """Write the canonical store under the #411 stale-write guard.

        Caller must hold ``_lock``. Refuses to overwrite a store that
        advanced since this session's baseline, commits *dirty*'s rows in
        ONE transaction, then refreshes the baseline. The revision compare
        is enforced INSIDE the write transaction (#1220 CAS): the pre-check
        below stays as a cheap fast-fail, but a foreign commit landing
        between the pre-check and the transaction is aborted by the store
        layer — at most one conflicting writer ever succeeds.
        """
        stored = self._index.revision()
        if stored is not None and stored != self._flushed_revision:
            raise CatalogStaleWriteError(
                "数据目录元数据已被其他实例修改；为避免覆盖他人提交，"
                "本次保存已中止。请重新打开工程后重试。"
            )
        if reconcile:
            self._index.reconcile(
                self.document, expected_revision=self._flushed_revision
            )
        else:
            maps = self._ensure_maps()
            self._index.apply_changes(
                self.document,
                dirty,
                lookups={
                    "assets": maps.asset_by_id,
                    "versions": maps.version_by_id,
                    "runs": maps.run_by_id,
                },
                expected_revision=self._flushed_revision,
            )
        self._flushed_revision = self.document.catalog_revision

    def _reload_document_locked(self) -> None:
        """Restore the in-memory document from the canonical store.

        Failure/rollback path: after a rolled-back transaction the store
        still holds the last committed state, so reloading it is the exact
        pre-batch snapshot — without ever deep-copying the graph (#1027).
        """
        reloaded = self._index.load_document()
        if reloaded is None:
            self._pending_dirty = DirtySet()
            self._pending_reconcile = False
            raise CatalogError(
                "Canonical store became unreadable while rolling back; "
                "in-memory state may diverge from disk. Reopen the project."
            )
        self.document = reloaded
        self._invalidate_maps()
        self._pending_dirty = DirtySet()
        self._pending_reconcile = False
        self._batch_base_revision = None
        self._batch_overlay_managed = {}
        self._batch_overlay_external = {}
        self._flushed_revision = self._index.revision()

    def _maybe_checkpoint_manifest_locked(self) -> None:
        """Throttled manifest rewrite; O(1) checks, never per mutation.

        One exception keeps fresh projects immediately portable: when NO
        manifest exists yet (brand-new project, or legacy file deleted), the
        first successful flush writes one. A new project's document is small,
        so this is never the multi-megabyte rewrite #1027 removes; at scale
        the manifest already exists and this is a no-op until close/export.
        """
        if self._mutations_since_manifest > 1:
            return
        if catalog_file_for(self.project_path).exists():
            return
        try:
            self.export_manifest()
        except Exception:
            pass  # the manifest is a convenience artifact, never a gate

    def batch_save(self) -> "_BatchSave":
        """Context manager merging many mutator calls into ONE transaction.

        While active, :meth:`_save` accumulates the touched entities; the
        outermost exit commits them all in a single SQLite transaction (one
        WAL fsync) instead of one per mutation. Bulk registration /
        recompute loops therefore pay O(Δ) rows + one commit, never a
        full-document serialization (the O(N²) write path, C38 / #1027).

        Atomicity is preserved: when the body raises, nothing is committed
        and the in-memory document is reloaded from the store; a failed
        flush likewise rolls back, reloads, and re-raises. Nested batches
        are supported — only the outermost exit flushes.
        """
        return _BatchSave(self)

    def _ensure_index_fresh(self) -> None:
        """Verify/repair store consistency with the document — guarded.

        Honors the #411 stale-write rule like every other write path: a
        store that advanced past this session's baseline belongs to another
        process, and reconciling over it would silently drop that process's
        commits (the full diff would DELETE its rows).
        """
        try:
            if self._index.is_fresh(self.document):
                return
            stored = self._index.revision()
            if stored is not None and stored != self._flushed_revision:
                raise CatalogStaleWriteError(
                    "数据目录元数据已被其他实例修改；为避免覆盖他人提交，"
                    "本次同步已中止。请重新打开工程后重试。"
                )
            self._index.reconcile(
                self.document, expected_revision=self._flushed_revision
            )
        except CatalogStaleWriteError:
            raise
        except Exception:
            pass

    def ensure_index_ready(self) -> None:
        """Explicitly verify/repair store consistency with the document."""
        self._ensure_index_fresh()

    def rebuild_index(self) -> None:
        """Force a full store rewrite from the in-memory document.

        Guarded like every write path (#1220): a store that advanced past
        this session's baseline is another process's commits, and rebuilding
        over it from our snapshot would destroy them. The reset+rebuild runs
        under the service lock so in-process flushes cannot interleave with
        a half-deleted database.
        """
        with self._lock:
            stored = self._index.revision()
            if stored is not None and stored != self._flushed_revision:
                raise CatalogStaleWriteError(
                    "数据目录元数据已被其他实例修改；rebuild 已中止以免覆盖他人提交。"
                    "请重新打开工程后重试。"
                )
            self._index.reset()
            self._index.rebuild(self.document)
            self._flushed_revision = self.document.catalog_revision
            # The maintained maps reflect the document that was loaded at open;
            # a caller swapping ``document`` before rebuilding leaves them stale.
            self._invalidate_maps()

    def index_revision(self) -> int | None:
        return self._index.revision()

    # -- garbage collection (P4, conservative) --------------------------------

    def plan_gc(self, dry_run: bool = True) -> GcReport:
        """Classify orphaned files in the artifacts tree (deletes nothing).

        Orphan classes: stage payloads without a version record, abandoned
        working copies, stale temp/placement files, unreferenced trash
        payloads, and unreferenced content-store blobs. See
        :func:`paleo_workbench.catalog.gc.plan_gc`.

        ``dry_run`` is accepted for interface compatibility (the spec's
        ``plan_gc(dry_run=True)`` contract) but planning is ALWAYS
        non-destructive — use :meth:`sweep_gc` to actually remove orphans.
        """
        return _gc_plan(self)

    def sweep_gc(self, *, dry_run: bool = True, explicit: bool = False) -> GcReport:
        """Sweep orphans; ``dry_run=True`` (default) only reports.

        With ``explicit=False`` (the conservative sweep, also run on open)
        only stale temp files and empty dirs are removed. With
        ``explicit=True`` the full safe set is swept: unreferenced stage and
        trash payloads plus unreferenced blobs. Reachable committed
        DataVersions and external source files are never touched; working
        copies require :meth:`cleanup_working_copies`.
        """
        return _gc_sweep(self, dry_run=dry_run, explicit=explicit)

    def cleanup_working_copies(self) -> GcReport:
        """Remove abandoned working copies (explicit user action).

        Only working-copy dirs whose version id does not exist in the catalog
        at all are removed; live versions' working copies may hold uncommitted
        edits and are never touched.
        """
        return _gc_cleanup_working_copies(self)

    # -- lookups ------------------------------------------------------------

    def _asset_or_raise(self, asset_id: str) -> DataAsset:
        maps = self._ensure_maps()
        asset = maps.asset_by_id.get(asset_id)
        if asset is not None:
            return asset
        # Safety net: a missed maintenance site (or a stale map) rebuilds from
        # the document, so an unknown id is genuinely unknown before raising.
        self._invalidate_maps()
        maps = self._ensure_maps()
        asset = maps.asset_by_id.get(asset_id)
        if asset is None:
            raise CatalogError(f"Unknown asset: {asset_id}")
        return asset

    def _version_or_raise(self, version_id: str) -> DataVersion:
        maps = self._ensure_maps()
        version = maps.version_by_id.get(version_id)
        if version is not None:
            return version
        self._invalidate_maps()
        maps = self._ensure_maps()
        version = maps.version_by_id.get(version_id)
        if version is None:
            raise CatalogError(f"Unknown version: {version_id}")
        return version

    def _asset_by_legacy_id(self, legacy_resource_id: str) -> DataAsset | None:
        """Stable legacy-bridge resolution (id match wins, then first bridge)."""
        return self._ensure_maps().assets_by_legacy_id.get(legacy_resource_id)

    def _live_asset_by_legacy_id(self, legacy_resource_id: str) -> DataAsset | None:
        """Like :meth:`_asset_by_legacy_id` but ignores trashed assets.

        A trashed asset still holds its legacy id; import-after-trash must be
        able to re-bridge a fresh asset instead of dead-ending on the trashed
        one (review finding I2).
        """
        asset = self._ensure_maps().assets_by_legacy_id.get(legacy_resource_id)
        if asset is not None and asset.trashed:
            return None
        return asset

    def _set_legacy_bridge(self, asset: DataAsset, legacy_resource_id: str) -> None:
        """Record a legacy bridge on *asset*, keeping the legacy index current.

        Used by the adapter's bridge path (a metadata-only update that does
        not go through ``_add_asset``/``_remove_asset``).
        """
        asset.legacy_resource_id = legacy_resource_id
        if self._assets_by_legacy_id is not None:
            self._assets_by_legacy_id.setdefault(legacy_resource_id, asset)

    # -- lazy hot reads (#1212) ------------------------------------------------
    #
    # Before warmup these serve straight from the canonical store (bounded
    # per-entity / per-asset queries) with a small id→model cache for object
    # identity. After warmup they use the maintained maps exactly as before.

    def _lazy_active(self) -> bool:
        return self._lazy and not self._warm

    def _lazy_get_asset(self, asset_id: str) -> DataAsset | None:
        cached = self._lazy_read_cache.get(asset_id)
        if cached is not None:
            return cached
        model = self._index.get_asset_model(asset_id)
        if model is not None:
            self._lazy_read_cache[asset_id] = model
        return model

    def _lazy_get_version(self, version_id: str) -> DataVersion | None:
        cached = self._lazy_read_cache.get(version_id)
        if cached is not None:
            return cached
        model = self._index.get_version_model(version_id)
        if model is not None:
            self._lazy_read_cache[version_id] = model
        return model

    def _lazy_get_run(self, run_id: str) -> DataRun | None:
        cached = self._lazy_read_cache.get(run_id)
        if cached is not None:
            return cached
        model = self._index.get_run_model(run_id)
        if model is not None:
            self._lazy_read_cache[run_id] = model
        return model

    def get_asset(self, asset_id: str) -> DataAsset:
        if self._lazy_active():
            # Pre-warm the store IS the committed truth (mutations and
            # batches only exist post-warm), so a clean miss is a genuine
            # unknown id — raise without paying the full materialization.
            try:
                asset = self._lazy_get_asset(asset_id)
            except Exception:
                asset = None  # store read failed; warm path handles errors
            else:
                if asset is None:
                    raise CatalogError(f"Unknown asset: {asset_id}")
                return asset
            self.require_warm()
        return self._asset_or_raise(asset_id)

    def get_version(self, version_id: str) -> DataVersion:
        if self._lazy_active():
            try:
                version = self._lazy_get_version(version_id)
            except Exception:
                version = None
            else:
                if version is None:
                    raise CatalogError(f"Unknown version: {version_id}")
                return version
            self.require_warm()
        return self._version_or_raise(version_id)

    def get_run(self, run_id: str) -> DataRun:
        if self._lazy_active():
            try:
                run = self._lazy_get_run(run_id)
            except Exception:
                run = None
            else:
                if run is None:
                    raise CatalogError(f"Unknown run: {run_id}")
                return run
            self.require_warm()
        maps = self._ensure_maps()
        run = maps.run_by_id.get(run_id)
        if run is not None:
            return run
        self._invalidate_maps()
        maps = self._ensure_maps()
        run = maps.run_by_id.get(run_id)
        if run is None:
            raise CatalogError(f"Unknown run: {run_id}")
        return run

    def list_assets(self, include_trashed: bool = False) -> list[DataAsset]:
        """List assets; trashed (soft-deleted) assets are hidden by default."""
        if self._lazy_active():
            models = self._index.list_asset_models(
                include_trashed=include_trashed, trashed_only=False
            )
            for model in models:
                self._lazy_read_cache.setdefault(model.id, model)
            return models
        if include_trashed:
            return list(self.document.assets)
        return [asset for asset in self.document.assets if not asset.trashed]

    def get_trashed_assets(self) -> list[DataAsset]:
        """Assets currently in the trash (tombstoned, recoverable)."""
        if self._lazy_active():
            models = self._index.list_asset_models(
                include_trashed=True, trashed_only=True
            )
            for model in models:
                self._lazy_read_cache.setdefault(model.id, model)
            return models
        return [asset for asset in self.document.assets if asset.trashed]

    def list_runs(self) -> list[DataRun]:
        if self._lazy_active():
            models = self._index.list_run_models()
            for model in models:
                self._lazy_read_cache.setdefault(model.id, model)
            return models
        return list(self.document.runs)

    def list_versions(self, asset_id: str) -> list[DataVersion]:
        if self._lazy_active():
            models = self._index.list_version_models_for_asset(asset_id)
            for model in models:
                self._lazy_read_cache.setdefault(model.id, model)
            return sorted(models, key=lambda v: v.version_number)
        versions = list(self._ensure_maps().versions_by_asset.get(asset_id, ()))
        return sorted(versions, key=lambda v: v.version_number)

    def list_all_versions(self) -> list[DataVersion]:
        """Every version in document order (rowid); lazy-safe."""
        if self._lazy_active():
            models = self._index.list_all_version_models()
            for model in models:
                self._lazy_read_cache.setdefault(model.id, model)
            return models
        return list(self.document.versions)

    def resolve_asset_models(self, asset_ids: Iterable[str]) -> list[DataAsset]:
        """Identity-stable asset models for *asset_ids* (lazy-safe).

        Pre-warm: served from the lazy read cache (populated per id from the
        store). Post-warm: the maintained document objects. Used by the
        materialized search path so index rows never filter to empty on a
        not-yet-warm document.
        """
        if self._lazy_active():
            # V8 M9: batch fetch — the per-id loop was one store query per
            # search-result row (N+1 on every materialized search pre-warm).
            ids = [str(i) for i in asset_ids]
            cached: dict = {}
            missing: list[str] = []
            for asset_id in ids:
                model = self._lazy_read_cache.get(asset_id)
                if model is not None:
                    cached[asset_id] = model
                else:
                    missing.append(asset_id)
            if missing:
                fetched = self._index.get_asset_models(missing)
                for asset_id, model in fetched.items():
                    self._lazy_read_cache.setdefault(asset_id, model)
                cached.update(fetched)
            return [cached[i] for i in ids if i in cached]
        by_id = self._ensure_maps().asset_by_id
        return [by_id[i] for i in asset_ids if i in by_id]

    def resolve_path(self, version: DataVersion) -> Path:
        """Runtime absolute path for a version's payload.

        Exact-match ladder only (#1140): managed versions resolve to the
        project-dir-joined recorded path; external versions resolve to the
        recorded absolute path when it exists, a project-relative join when
        that exists, or — for a recorded path containing the project dir
        name — the subpath re-anchored onto the CURRENT project dir (project
        relocation). There is deliberately NO basename / last-two-segments
        guess: an external RAW that moved must surface as missing (integrity
        reports it), never silently re-bind to an unrelated in-project file
        that happens to share the name.
        """
        project_dir = self.project_path.expanduser().resolve().parent
        if version.managed:
            return project_dir / version.path
        raw_path = Path(version.path)
        if raw_path.is_file():
            return raw_path.resolve()
        rel_candidate = (project_dir / raw_path).resolve()
        if rel_candidate.is_file():
            return rel_candidate
        posix_str = raw_path.as_posix()
        parts = [p for p in posix_str.split("/") if p]
        proj_name = project_dir.name
        if proj_name in parts:
            idx = parts.index(proj_name)
            subpath = "/".join(parts[idx + 1:])
            if subpath:
                cand = (project_dir / subpath).resolve()
                if cand.is_file() and self._fallback_identity_ok(cand, version):
                    return cand
        if len(parts) >= 2:
            two_part = "/".join(parts[-2:])
            cand = (project_dir / two_part).resolve()
            if cand.is_file() and self._fallback_identity_ok(cand, version):
                return cand
        if parts:
            one_part = parts[-1]
            cand = (project_dir / one_part).resolve()
            if cand.is_file() and self._fallback_identity_ok(cand, version):
                return cand
        return raw_path

    @staticmethod
    def _fallback_identity_ok(cand: Path, version: DataVersion) -> bool:
        """#1140/#1221: basename fallbacks must not silently bind a same-named
        stranger. Verify size/sha256 when the record carries them; a mismatch
        keeps searching so the caller fails clean (missing file) instead of
        reading wrong data. A record with NEITHER fact has nothing to verify
        against — fail CLOSED (#1221): an identity-less version surfaces as
        missing (integrity/relink handle it) rather than silently binding an
        unrelated same-named scientific file."""
        try:
            if version.sha256:
                from paleo_workbench.catalog.checksum import sha256_file_or_none

                return sha256_file_or_none(cand) == version.sha256
            if version.size_bytes is not None:
                return cand.stat().st_size == version.size_bytes
        except OSError:
            return False
        # No identity evidence at all: refuse the basename guess.
        return False

    # -- rollback helper ----------------------------------------------------

    def _rollback(
        self,
        *,
        assets: Iterable[DataAsset] = (),
        versions: Iterable[DataVersion] = (),
        runs: Iterable[DataRun] = (),
        payload: Path | None = None,
        restore_current: tuple[DataAsset, str | None] | None = None,
        restore_payload_to: Path | None = None,
    ) -> None:
        for asset in assets:
            self._remove_asset(asset)
        for version in versions:
            self._remove_version(version)
        for run in runs:
            self._remove_run(run)
        if restore_current is not None:
            asset, previous = restore_current
            asset.current_version_id = previous
        if payload is not None:
            if is_cas_path(self.project_path, payload.as_posix()):
                # Blob-backed payloads are shared, content-addressed and
                # immutable: a failed save must never unlink them (other
                # versions may reference the same blob).
                pass
            elif restore_payload_to is not None and payload.exists():
                # A moved (consumed) working copy goes back where it came
                # from — a failed commit must not destroy the user's data.
                try:
                    os.replace(payload, restore_payload_to)
                except OSError:
                    pass
            else:
                safe_unlink(payload)
                # Prune the now-empty version/asset directories.
                for directory in (payload.parent, payload.parent.parent):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

    # -- version registration ------------------------------------------------

    def _is_safe_version_id(self, version_id: str) -> bool:
        """True when *version_id* is safe to use as a storage path segment."""
        return is_safe_entity_id(version_id)

    def _next_version_number(self, asset_id: str) -> int:
        numbers = [
            v.version_number
            for v in self._ensure_maps().versions_by_asset.get(asset_id, ())
        ]
        return max(numbers, default=0) + 1

    def _staging_target(self, stage: DataStage | None, asset_id: str | None) -> str:
        """Project-relative posix prefix of a payload target dir (lease key).

        Matches the rel-path convention GC computes for orphan candidates:
        ``<name>.artifacts/<stage>/<asset_id>``.
        """
        from paleo_workbench.catalog.storage import STAGE_DIRS

        parts = [artifact_dir_for(self.project_path).name]
        if stage is not None:
            # The ON-DISK directory name (e.g. OUTPUT → "outputs"), NOT
            # stage.value ("output") — GC computes rel paths from the real
            # layout, so a value-based key would never prefix-match (R3#1).
            parts.append(STAGE_DIRS[stage])
        if asset_id is not None:
            parts.append(asset_id)
        return "/".join(parts)

    def _blob_staging_target(self) -> str:
        return f"{artifact_dir_for(self.project_path).name}/blobs"

    @contextmanager
    def _payload_staging_lease(self, *targets: str, kind: str = "register"):
        """Bridge the place-on-disk → metadata-commit window (#1222).

        Payload bytes land outside the service lock by design; until the
        metadata transaction references them, a concurrent explicit GC sweep
        would classify them as orphans. The lease records ownership of the
        target dirs; GC skips leased paths and re-validates under this
        service's lock before every deletion chunk. Best-effort: when the
        lease store is unavailable the registration proceeds with the
        pre-lease semantics instead of failing.
        """
        lease_id: str | None = None
        try:
            lease_id = self._index.acquire_staging_lease(targets, kind)
        except Exception:
            lease_id = None
        try:
            yield lease_id
        finally:
            if lease_id is not None:
                try:
                    self._index.release_staging_lease(lease_id)
                except Exception:
                    pass

    def _build_version(
        self,
        asset: DataAsset,
        source_path: Path,
        stage: DataStage,
        *,
        version_id: str | None,
        parent_version_ids: list[str],
        run_id: str | None,
        metadata: dict[str, Any] | None,
        move: bool,
        known_sha256: str | None = None,
        register_blob: bool = False,
    ) -> tuple[DataVersion, Path]:
        """Place the payload and build the (not yet appended) DataVersion."""
        if not self._is_safe_version_id(asset.id):
            # #1175: asset.id flows into the same storage path segments as
            # version_id and is equally attacker-controlled via project docs.
            raise CatalogError(
                f"Unsafe asset id {asset.id!r}: only [A-Za-z0-9._-] allowed"
            )
        version = DataVersion(
            asset_id=asset.id,
            version_number=self._next_version_number(asset.id),
            stage=stage,
            managed=True,
            source_uri=source_path.resolve().as_posix(),
            format=asset.metadata.get("format", ""),
            parent_version_ids=list(parent_version_ids),
            run_id=run_id,
            metadata=dict(metadata or {}),
        )
        if version_id is not None:
            # Defensive id sanitization (audit #848): a caller-supplied id like
            # "../.." could otherwise escape the ledger tree through the
            # managed-storage placement path. No production caller passes ids
            # today, but the seam must not trust them when someday one does.
            if not self._is_safe_version_id(version_id):
                raise CatalogError(
                    f"Unsafe version id {version_id!r}: only [A-Za-z0-9._-] allowed"
                )
            if any(v.id == version_id for v in self.document.versions):
                raise ImmutableVersionError(
                    f"Version {version_id} is already committed and immutable"
                )
            version.id = version_id
        rel_path, size, digest = place_managed_file(
            source_path, self.project_path, stage, asset.id, version.id,
            keep_source=not move,
            known_sha256=known_sha256,
            register_blob=register_blob,
        )
        version.path = rel_path
        version.size_bytes = size
        version.sha256 = digest
        return version, self.resolve_path(version)

    def register_version(
        self,
        asset_id: str,
        source_path: str | Path,
        stage: DataStage,
        *,
        parent_version_ids: Iterable[str] = (),
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        version_id: str | None = None,
        move: bool = False,
        _restore_payload_to: Path | None = None,
        known_sha256: str | None = None,
        _register_blob: bool = False,
    ) -> DataVersion:
        """Place *source_path* under managed storage and commit a new version.

        When *run_id* is given, the run's ``output_version_ids`` is updated in
        the SAME save as the version commit (atomic run-output linkage), and
        restored on rollback.

        ``known_sha256`` / ``_register_blob`` (private; adapter import path):
        see :func:`paleo_workbench.catalog.storage.place_managed_file`.

        Payload copy+hash+fsync happens OUTSIDE the lock (same reason as
        :meth:`register_result_asset`). Version numbers are assigned at
        commit time so concurrent registrations on one asset stay sequential.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CatalogError(f"Source file not found: {source_path}")
        with self._lock:
            asset = self._asset_or_raise(asset_id)
            if run_id is not None:
                self.get_run(run_id)  # raises before any payload is placed
            if version_id is not None:
                if any(v.id == version_id for v in self.document.versions):
                    raise ImmutableVersionError(
                        f"Version {version_id} is already committed and immutable"
                    )
        # Copy+hash+fsync — no lock held while the bytes land on disk. The
        # staging lease (#1222) marks the target dir (and the blob root for
        # dedup imports) as in-flight for the whole place→commit window so a
        # concurrent explicit GC sweep cannot delete live-but-uncommitted
        # bytes; it is released only after the metadata transaction commits.
        _lease_targets = [self._staging_target(stage, asset_id)]
        if _register_blob:
            _lease_targets.append(self._blob_staging_target())
        with self._payload_staging_lease(*_lease_targets):
            version, payload = self._build_version(
                asset, source_path, stage,
                version_id=version_id,
                parent_version_ids=list(parent_version_ids),
                run_id=run_id, metadata=metadata, move=move,
                known_sha256=known_sha256,
                register_blob=_register_blob,
            )
            with self._lock:
                try:
                    asset = self._asset_or_raise(asset_id)
                except CatalogError:
                    self._rollback(
                        payload=payload, restore_payload_to=_restore_payload_to,
                    )
                    raise
                if any(v.id == version.id for v in self.document.versions):
                    self._rollback(
                        payload=payload, restore_payload_to=_restore_payload_to,
                    )
                    raise ImmutableVersionError(
                        f"Version {version.id} is already committed and immutable"
                    )
                run: DataRun | None = None
                if run_id is not None:
                    try:
                        run = self.get_run(run_id)
                    except CatalogError:
                        self._rollback(
                            payload=payload, restore_payload_to=_restore_payload_to,
                        )
                        raise
                version.version_number = self._next_version_number(asset.id)
                previous_current = asset.current_version_id
                self._add_version(version)
                asset.current_version_id = version.id
                run_output_added = False
                if run is not None and version.id not in run.output_version_ids:
                    run.output_version_ids.append(version.id)
                    run_output_added = True
                _dirty = DirtySet(assets={asset.id: None}, versions={version.id: None})
                if run is not None:
                    _dirty.mark_runs(run.id)
                try:
                    self._save(_dirty)
                except Exception:
                    if run is not None and run_output_added:
                        run.output_version_ids.remove(version.id)
                    self._rollback(
                        versions=[version], payload=payload,
                        restore_current=(asset, previous_current),
                        restore_payload_to=_restore_payload_to,
                    )
                    raise
                return version

    def register_intermediate(
        self, asset_id: str, source_path: str | Path, **kwargs: Any
    ) -> DataVersion:
        return self.register_version(
            asset_id, source_path, DataStage.INTERMEDIATE, **kwargs
        )

    def register_output(
        self, asset_id: str, source_path: str | Path, **kwargs: Any
    ) -> DataVersion:
        return self.register_version(asset_id, source_path, DataStage.OUTPUT, **kwargs)

    def register_result_asset(
        self,
        *,
        name: str,
        type: str | None,
        format: str | None,
        asset_metadata: dict[str, Any] | None,
        source_path: str | Path,
        stage: DataStage,
        run_id: str | None = None,
        version_metadata: dict[str, Any] | None = None,
    ) -> DataVersion:
        """Create a result asset and register its version in ONE atomic
        document operation (thread-safe: workers must not mutate
        ``document.assets`` directly — this is the only sanctioned path).

        The payload copy+hash (potentially large, disk-bound) happens OUTSIDE
        the lock: holding the lock across it would stall every concurrent
        GUI-thread catalog call (``register_run``/``add_tags``/...) for the
        whole I/O duration.  Only the document mutation and canonical save
        are locked, so asset + version + run linkage still commit atomically.

        When *run_id* is given, the new version's lineage parents are set to
        the run's input versions, so DERIVED/OUTPUT results stay traceable to
        their inputs through the version graph (not only via the run record).
        Inputs that no longer exist (e.g. purged after the run was recorded)
        are filtered out so new versions are never born with broken lineage —
        the run record itself keeps the full historical reference list.

        On failure the newly-created asset is rolled back from the document,
        so no half-registered asset survives. Returns the committed version.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CatalogError(f"Source file not found: {source_path}")
        with self._lock:
            parents: list[str] = []
            run: DataRun | None = None
            if run_id is not None:
                known = self._ensure_maps().version_by_id
                run = self.get_run(run_id)
                parents = [
                    pid for pid in run.input_version_ids if pid in known
                ]
            asset = self._new_asset(name, type, format, asset_metadata)
        # Copy+hash+fsync of the payload — no lock held while the bytes land
        # on disk, so GUI-thread catalog calls never wait for worker I/O.
        # The staging lease (#1222) guards the target dir through the
        # place→commit window against a concurrent explicit GC sweep.
        with self._payload_staging_lease(
            self._staging_target(stage, asset.id), kind="register"
        ):
            version, payload = self._build_version(
                asset, source_path, stage,
                version_id=None,
                parent_version_ids=parents,
                run_id=run_id,
                metadata=version_metadata,
                move=False,
            )
            with self._lock:
                self._add_asset(asset)
                self._add_version(version)
                asset.current_version_id = version.id
                run_output_added = False
                if run is not None and version.id not in run.output_version_ids:
                    run.output_version_ids.append(version.id)
                    run_output_added = True
                _dirty = DirtySet(assets={asset.id: None}, versions={version.id: None})
                if run is not None:
                    _dirty.mark_runs(run.id)
                try:
                    self._save(_dirty)
                except Exception:
                    if run_output_added:
                        run.output_version_ids.remove(version.id)
                    self._rollback(
                        assets=[asset], versions=[version], payload=payload,
                    )
                    raise
                return version

    # -- import / link / materialize -----------------------------------------

    def register_derived_store(
        self,
        *,
        name: str,
        store_path: str | Path,
        run_id: str | None = None,
        parent_version_ids: Iterable[str] = (),
        type: str | None = None,
        format: str = "zarr-v3",
        asset_metadata: dict[str, Any] | None = None,
        version_metadata: dict[str, Any] | None = None,
        store_dirname: str = "store",
    ) -> DataVersion:
        """Register a DIRECTORY-backed DERIVED payload (e.g. a chunked zarr
        store, #1079) as a managed version.

        Unlike :meth:`register_result_asset` there is no copy+hash: the store
        is MOVED atomically into ``derived/{asset_id}/{version_id}/`` (same
        filesystem as the working area), and integrity is recorded as a
        structural fingerprint (file count + total bytes) instead of a
        payload sha256 — a 100 GB store is never re-read just to register.
        Lineage: parents come from ``parent_version_ids`` (or the run's
        inputs when ``run_id`` is given), mirroring register_result_asset.
        """
        store = Path(store_path)
        if not store.is_dir():
            raise CatalogError(f"Derived store directory not found: {store}")
        # Size/fingerprint scan outside the lock (large trees).
        n_files = 0
        total = 0
        for f in store.rglob("*"):
            if f.is_file():
                n_files += 1
                total += f.stat().st_size
        with self._lock:
            known = self._ensure_maps().version_by_id
            parents = [pid for pid in parent_version_ids if pid in known]
            run = None
            if run_id is not None:
                run = self.get_run(run_id)
                for pid in run.input_version_ids:
                    if pid in known and pid not in parents:
                        parents.append(pid)
            asset = self._new_asset(name, type, format, asset_metadata)
            version = DataVersion(
                asset_id=asset.id,
                version_number=self._next_version_number(asset.id),
                stage=DataStage.DERIVED,
                managed=True,
                source_uri=store.resolve().as_posix(),
                format=format,
                parent_version_ids=parents,
                run_id=run_id,
                metadata=dict(version_metadata or {}),
            )
            version.metadata["store_fingerprint"] = {
                "files": n_files,
                "bytes": total,
            }
            layout = _ensure_catalog_layout(self.project_path)
            # The asset/version ids become storage path segments (#1175).
            if not is_safe_entity_id(asset.id) or not is_safe_entity_id(version.id):
                raise CatalogError(
                    f"Unsafe entity id for managed layout: asset={asset.id!r} "
                    f"version={version.id!r}: only [A-Za-z0-9._-] allowed"
                )
            target = layout / "derived" / asset.id / version.id
            target.mkdir(parents=True, exist_ok=True)
            final = target / store_dirname
            if final.exists():
                raise CatalogError(f"derived store target already exists: {final}")
            try:
                os.replace(store, final)
            except OSError as exc:
                raise CatalogError(
                    f"cannot move derived store into managed layout: {exc}"
                ) from exc
            version.path = final.relative_to(
                Path(self.project_path).expanduser().resolve().parent
            ).as_posix()
            version.size_bytes = total
            asset.current_version_id = version.id
            self._add_asset(asset)
            self._add_version(version)
            run_output_added = False
            if run is not None and version.id not in run.output_version_ids:
                run.output_version_ids.append(version.id)
                run_output_added = True
            _dirty = DirtySet(assets={asset.id: None}, versions={version.id: None})
            if run is not None:
                _dirty.mark_runs(run.id)
            try:
                self._save(_dirty)
            except Exception:
                if run_output_added:
                    run.output_version_ids.remove(version.id)
                self._rollback(assets=[asset], versions=[version])
                # put the store back where it came from (best effort)
                try:
                    os.replace(final, store)
                    target.rmdir()
                except OSError:
                    pass
                raise
            return version

    def _new_asset(
        self,
        name: str,
        type: str | None,
        format: str | None,
        metadata: dict[str, Any] | None,
    ) -> DataAsset:
        asset = DataAsset(
            name=name,
            type=type or "unknown",
            metadata=dict(metadata or {}),
        )
        if format:
            asset.metadata["format"] = format
        return asset

    def import_raw(
        self,
        source_path: str | Path,
        *,
        name: str | None = None,
        type: str | None = None,
        format: str | None = None,
        metadata: dict[str, Any] | None = None,
        asset_id: str | None = None,
        _legacy_resource_id: str | None = None,
        known_sha256: str | None = None,
    ) -> DataVersion:
        """Import *source_path* as an immutable managed RAW snapshot.

        Copies (never references) the file into project-managed storage,
        hashing in a single streaming pass. Later edits to the source file
        cannot affect the snapshot.

        ``_legacy_resource_id`` (private; adapter-only) records the legacy
        bridge on the asset in the SAME registering save, so the adapter's
        ``register_input`` needs no second ``_save`` per import.

        ``known_sha256`` (private; adapter-only) enables the content-store
        dedup fast path: when the digest is already present and the source is
        the same size, no copy happens and the version references the shared
        blob (O(1)). Every managed RAW import also registers its payload in
        the content store so later imports of the same content dedup to it.

        Payload copy+hash happens outside the lock. The new asset is added
        and persisted in the same locked section as its first version, so a
        concurrent save can never persist a zombie zero-version asset.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CatalogError(f"Source file not found: {source_path}")
        if asset_id is not None:
            return self.register_version(
                asset_id, source_path, DataStage.RAW, metadata=metadata,
                known_sha256=known_sha256, _register_blob=True,
            )
        asset = self._new_asset(
            name or source_path.name, type, format, metadata
        )
        if _legacy_resource_id is not None:
            with self._lock:
                if self._live_asset_by_legacy_id(_legacy_resource_id) is None:
                    asset.legacy_resource_id = _legacy_resource_id
        # Staging lease (#1222, R3#2): import_raw is the PRIMARY bulk-import
        # funnel (every interchange adapter) and its payload placement runs
        # lock-free — guard the RAW target dir AND the blob root (dedup
        # imports adopt blobs) for the whole place→commit window.
        with self._payload_staging_lease(
            self._staging_target(DataStage.RAW, asset.id),
            self._blob_staging_target(),
        ):
            version, payload = self._build_version(
                asset, source_path, DataStage.RAW,
                version_id=None,
                parent_version_ids=[],
                run_id=None, metadata=metadata, move=False,
                known_sha256=known_sha256,
                register_blob=True,
            )
            with self._lock:
                if (
                    _legacy_resource_id is not None
                    and self._live_asset_by_legacy_id(_legacy_resource_id) is not None
                ):
                    asset.legacy_resource_id = None
                self._add_asset(asset)
                self._add_version(version)
                asset.current_version_id = version.id
                try:
                    self._save(
                        DirtySet(assets={asset.id: None}, versions={version.id: None})
                    )
                except Exception:
                    self._rollback(
                        assets=[asset], versions=[version], payload=payload,
                    )
                    raise
                return version

    def link_external(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        type: str | None = None,
        format: str | None = None,
        metadata: dict[str, Any] | None = None,
        _legacy_resource_id: str | None = None,
    ) -> DataVersion:
        """Register an unmanaged external reference (explicitly not managed).

        No copy, no hash: the project records where the file lives without
        pretending integrity guarantees. Use :meth:`materialize_external` to
        promote it to a managed RAW snapshot.

        ``_legacy_resource_id`` (private; adapter-only) records the legacy
        bridge in the same registering save (no second ``_save`` per import).
        """
        path = Path(path)
        if not path.is_file():
            raise CatalogError(f"External file not found: {path}")
        # Mutate + save under the lock (#517): link_external was fully
        # unlocked, so a concurrent locked save could interleave between the
        # document append and this write.
        with self._lock:
            asset = self._new_asset(name or path.name, type, format, metadata)
            asset.metadata["external"] = True
            if (
                _legacy_resource_id is not None
                and self._asset_by_legacy_id(_legacy_resource_id) is None
            ):
                asset.legacy_resource_id = _legacy_resource_id
            stat = path.stat()
            version = DataVersion(
                asset_id=asset.id,
                version_number=1,
                stage=DataStage.RAW,
                managed=False,
                path=path.resolve().as_posix(),
                source_uri=path.resolve().as_posix(),
                format=format or "",
                size_bytes=stat.st_size,
                # Identity fingerprint for a later fail-closed relink (D9):
                # size + mtime_ns are the recorded facts a relocated file
                # must match when no digest was ever taken.
                metadata={
                    "external_stat": {
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                },
            )
            asset.current_version_id = version.id
            self._add_asset(asset)
            self._add_version(version)
            try:
                self._save(DirtySet(assets={asset.id: None}, versions={version.id: None}))
            except Exception:
                self._rollback(assets=[asset], versions=[version])
                raise
            return version

    def materialize_external(
        self, version_id: str, *, run_id: str | None = None
    ) -> DataVersion:
        """Promote an external link to a managed immutable RAW snapshot.

        When *run_id* is given the snapshot version is linked as that run's
        output (same atomic save), recording who/when materialized the file.
        """
        linked = self._version_or_raise(version_id)
        if linked.managed:
            raise CatalogError(f"Version {version_id} is already managed")
        source = Path(linked.path)
        if not source.is_file():
            raise CatalogError(f"External file not available: {source}")
        return self.register_version(
            linked.asset_id,
            source,
            DataStage.RAW,
            parent_version_ids=[linked.id],
            run_id=run_id,
        )

    # -- missing sources / relink (D9) -----------------------------------------

    def find_missing_sources(
        self,
        *,
        include_managed: bool = True,
        cancel: Callable[[], bool] | None = None,
    ) -> "_sources.MissingSourceReport":
        """Stat-only scan for live versions whose payload no longer resolves.

        Derived state — never persisted (a scan that wrote flags into the
        canonical store would multiply writes and fight the cross-process
        revision guard). Run off the GUI thread at catalog scale; ``cancel``
        is polled per version.
        """
        return _sources.find_missing_sources(
            self, include_managed=include_managed, cancel=cancel
        )

    def relink_external_source(
        self,
        version_id: str,
        new_path: str | Path,
        *,
        actor: str = "user",
    ) -> DataVersion:
        """Fail-closed relink of an external RAW version to its moved file.

        Delegates to
        :func:`paleo_workbench.catalog.sources.relink_external_source`;
        identity must be provable against recorded facts (sha256 or the
        size+mtime fingerprint), otherwise
        :class:`~paleo_workbench.catalog.sources.CatalogRelinkIdentityError`.
        """
        return _sources.relink_external_source(
            self, version_id, new_path, actor=actor
        )

    # -- working copies / derived --------------------------------------------

    def create_working_copy(self, version_id: str, *, allow_replace: bool = False) -> Path:
        """Materialize a mutable working copy of a committed version.

        Always a real copy (never a hardlink), so editing it cannot touch the
        managed original.

        Lifecycle (#1211): checkouts are REGISTERED (source version, path,
        state, timestamps) in the canonical store. A live uncommitted copy of
        the same source version is REUSED — a repeat checkout can no longer
        silently discard uncommitted edits; pass ``allow_replace=True`` for an
        explicit discard-and-recreate. The copy's identity is its registry id
        + source version id, never the display/file name, so duplicate names
        cannot collide. Enumerate via :meth:`list_working_copies`; abandon
        explicitly via :meth:`discard_working_copy`; crash recovery via
        :meth:`recover_working_copies`.
        """
        version = self._version_or_raise(version_id)
        live = None
        try:
            live = self._index.get_live_working_copy_for_source(version.id)
        except Exception:
            live = None
        if live is not None:
            existing = (
                Path(self.project_path).expanduser().resolve().parent / live["path"]
            )
            if existing.is_file():
                if not allow_replace:
                    return existing  # reuse: never clobber uncommitted edits
                self._discard_working_copy_row_and_file(live, existing)
            else:
                # Row without a file (save-as/packaging drops working/):
                # dead row, drop it and check out fresh.
                try:
                    self._index.remove_working_copy(live["working_id"])
                except Exception:
                    pass
        payload = self.resolve_path(version)
        if not payload.is_file():
            raise CatalogError(f"Payload not available: {payload}")
        # Fail-CLOSED on disk evidence (R3#3): the registry is bookkeeping
        # and can degrade (missing/corrupt table, failed INSERT, pre-v6
        # copy with no row) — but an existing file at the target path IS
        # uncommitted user work. Never clobber it just because the registry
        # forgot; reuse it (or require allow_replace). #1211 must not fail
        # open when its bookkeeping does.
        from paleo_workbench.catalog.storage import working_dir_for

        disk_existing = (
            working_dir_for(Path(self.project_path)) / version.id / payload.name
        )
        if disk_existing.is_file() and live is None and not allow_replace:
            return disk_existing
        # Concurrent checkouts of the same version converge on one copy:
        # placement writes identical bytes to the same target via temp+
        # replace, so a racing replace can transiently collide on Windows —
        # retry briefly; the loser's bytes are identical anyway.
        target = None
        for attempt in range(4):
            try:
                target = _place_working_copy(self.project_path, payload, version.id)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                import time as _time

                _time.sleep(0.05 * (attempt + 1))
        assert target is not None
        try:
            rel = target.relative_to(
                Path(self.project_path).expanduser().resolve().parent
            ).as_posix()
            stat = target.stat()
            self._index.register_working_copy(
                source_version_id=version.id,
                path=rel,
                display_name=payload.name,
                payload_mtime_ns=stat.st_mtime_ns,
                source_size_bytes=version.size_bytes,
            )
        except Exception:
            pass  # registry is lifecycle bookkeeping, never a checkout gate
        return target

    # -- working-copy lifecycle (#1211) ----------------------------------------

    def _working_copy_status(self, row: dict) -> dict[str, Any]:
        project_dir = Path(self.project_path).expanduser().resolve().parent
        path = project_dir / row["path"]
        try:
            stat = path.stat()
            exists = True
            mtime_ns = stat.st_mtime_ns
            size = stat.st_size
        except OSError:
            exists = False
            mtime_ns = None
            size = None
        # Conservative dirty hint: any mtime drift from checkout time or size
        # divergence from the source counts as edited (false positives are
        # safe — the user is told the copy may hold edits).
        dirty_hint = bool(
            exists
            and row.get("state") in ("checked_out", "dirty")
            and (
                (row.get("payload_mtime_ns") is not None
                 and mtime_ns != row.get("payload_mtime_ns"))
                or (row.get("source_size_bytes") is not None
                    and size != row.get("source_size_bytes"))
            )
        )
        maps = self._ensure_maps()
        return {
            "working_id": row["working_id"],
            "source_version_id": row["source_version_id"],
            "path": path,
            "state": row["state"],
            "display_name": row.get("display_name") or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "exists": exists,
            "dirty_hint": dirty_hint,
            "source_version_known": row["source_version_id"] in maps.version_by_id,
        }

    def list_working_copies(self) -> list[dict[str, Any]]:
        """Enumerate unfinished working copies (any state, newest last)."""
        try:
            rows = self._index.list_working_copies()
        except Exception:
            return []
        return [self._working_copy_status(row) for row in rows]

    def working_copy_state(self, working_path: str | Path) -> dict[str, Any] | None:
        """Lifecycle status of the copy at *working_path*, or None."""
        path = Path(working_path)
        try:
            rel = path.relative_to(
                Path(self.project_path).expanduser().resolve().parent
            ).as_posix()
        except ValueError:
            return None
        try:
            row = self._index.get_working_copy_by_path(rel)
        except Exception:
            return None
        if row is None:
            return None
        return self._working_copy_status(row)

    def _discard_working_copy_row_and_file(self, row: dict, path: Path) -> None:
        from paleo_workbench.catalog.storage import safe_unlink

        try:
            safe_unlink(path)
        except OSError:
            pass
        try:
            self._index.remove_working_copy(row["working_id"])
        except Exception:
            pass

    def discard_working_copy(self, working_path: str | Path) -> bool:
        """Explicitly abandon an uncommitted copy (file + registry row).

        Returns True when a registered copy was discarded. This is the ONLY
        sanctioned way to destroy uncommitted edits besides committing them.
        """
        status = self.working_copy_state(working_path)
        if status is None:
            path = Path(working_path)
            if path.is_file():
                from paleo_workbench.catalog.storage import safe_unlink

                safe_unlink(path)
                return True
            return False
        if status["state"] == "committing":
            raise CatalogError(
                "工作副本正在提交中，不能丢弃；请等待提交完成或重启后恢复。"
            )
        try:
            row = self._index.get_working_copy_by_path(
                str(status["path"].relative_to(
                    Path(self.project_path).expanduser().resolve().parent
                ).as_posix())
            )
        except Exception:
            row = None
        if row is not None:
            self._discard_working_copy_row_and_file(row, status["path"])
            return True
        return False

    def recover_working_copies(self) -> list[dict[str, Any]]:
        """Crash/save-as recovery for the working-copy registry.

        - ``committing`` rows: a committed version whose source_uri is the
          working path means the commit landed and only the row removal was
          lost — drop the row. Otherwise the commit never landed — the copy
          is recoverable user work; back to ``dirty``.
        - rows whose file is gone (save-as/portable packaging drops
          ``working/``) — drop the row.
        Returns the surviving copies' statuses.
        """
        self._ensure_maps()
        project_dir = Path(self.project_path).expanduser().resolve().parent
        try:
            rows = self._index.list_working_copies()
        except Exception:
            return []
        source_uris = {
            v.source_uri: v for v in self.document.versions if v.source_uri
        }
        healed = {"committing_dropped": 0, "reverted_to_dirty": 0, "missing_dropped": 0}
        for row in rows:
            path = project_dir / row["path"]
            if not path.is_file():
                try:
                    self._index.remove_working_copy(row["working_id"])
                    healed["missing_dropped"] += 1
                except Exception:
                    pass
                continue
            if row["state"] == "committing":
                committed = source_uris.get(path.resolve().as_posix())
                if committed is not None:
                    # The commit landed (version exists, payload moved);
                    # only the row removal was lost.
                    try:
                        self._index.remove_working_copy(row["working_id"])
                        healed["committing_dropped"] += 1
                    except Exception:
                        pass
                else:
                    # Interrupted mid-commit: the file never moved (move is
                    # atomic), so the user's edits are intact — recoverable.
                    try:
                        self._index.update_working_copy_state(
                            row["working_id"], "dirty"
                        )
                        healed["reverted_to_dirty"] += 1
                    except Exception:
                        pass
        # V8 M9: durable recovery telemetry — what was healed and how.
        from paleo_workbench.catalog.telemetry import record_catalog_event

        record_catalog_event(
            self.project_path,
            "working_copy.recovery",
            detail={**healed, "surviving": len(self.list_working_copies())},
        )
        return self.list_working_copies()

    def commit_working_copy(
        self,
        working_path: str | Path,
        *,
        asset_id: str | None = None,
        name: str | None = None,
        stage: DataStage = DataStage.DERIVED,
        parent_version_ids: Iterable[str] | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DataVersion:
        """Promote a working copy to a new immutable version (move semantics).

        When *parent_version_ids* is omitted, the parent is inferred from the
        working-copy directory created by :meth:`create_working_copy`.

        ``name`` names the new ASSET when *asset_id* is None; when committing
        onto an existing asset it is stored as ``metadata["name"]`` on the new
        version (so the New Version dialog's "version name" input survives
        persistence instead of being silently dropped). An empty name writes
        no metadata key.
        """
        working_path = Path(working_path)
        if parent_version_ids is None:
            candidate = working_path.parent.name
            parent_version_ids = (
                [candidate]
                if any(v.id == candidate for v in self.document.versions)
                else []
            )
        # Registry transition (#1211): checked_out/dirty → committing BEFORE
        # the payload moves. A crash here is healed by recover_working_copies
        # (committed version present → row dropped; else back to dirty with
        # the file intact). Legacy copies without a registry row commit with
        # their pre-registry semantics.
        _wc_row = self.working_copy_state(working_path)
        _wc_working_id = _wc_row["working_id"] if _wc_row else None
        if _wc_working_id is not None:
            try:
                self._index.update_working_copy_state(_wc_working_id, "committing")
            except Exception:
                pass
        try:
            committed = self._commit_working_copy_inner(
                working_path,
                asset_id=asset_id,
                name=name,
                stage=stage,
                parent_version_ids=parent_version_ids,
                run_id=run_id,
                metadata=metadata,
            )
        except Exception:
            if _wc_working_id is not None:
                try:
                    # The move is atomic inside _build_version: on failure the
                    # file is back at (or never left) the working path — the
                    # copy is still live user work.
                    self._index.update_working_copy_state(_wc_working_id, "dirty")
                except Exception:
                    pass
            raise
        # Success: the payload moved into managed storage and the copy no
        # longer exists — drop the registry row.
        if _wc_working_id is not None:
            try:
                self._index.remove_working_copy(_wc_working_id)
            except Exception:
                pass
        return committed

    def _commit_working_copy_inner(
        self,
        working_path: Path,
        *,
        asset_id: str | None,
        name: str | None,
        stage: DataStage,
        parent_version_ids,
        run_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> DataVersion:
        if asset_id is None:
            # #1218: the payload move+hash must NOT run with the service lock
            # held (a GB-scale working copy would freeze every concurrent
            # catalog call for the whole I/O). The asset is appended first so
            # register_version can resolve it, and rolled back on failure —
            # the unlocked document-scan window (asset without a version for
            # the copy duration) is served consistently by every SQL-backed
            # read path, which only see committed state.
            with self._lock:
                asset = self._new_asset(name or working_path.stem, None, None, metadata)
                self._add_asset(asset)
                self._pending_commit_assets.add(asset.id)
            try:
                return self.register_version(
                    asset.id, working_path, stage,
                    parent_version_ids=parent_version_ids,
                    run_id=run_id, metadata=metadata, move=True,
                    _restore_payload_to=working_path,
                )
            except Exception:
                with self._lock:
                    if asset in self.document.assets:
                        self._remove_asset(asset)
                    self._pending_commit_assets.discard(asset.id)
                raise
            finally:
                with self._lock:
                    self._pending_commit_assets.discard(asset.id)
        version_metadata = dict(metadata or {})
        if name:
            version_metadata["name"] = name
        return self.register_version(
            asset_id, working_path, stage,
            parent_version_ids=parent_version_ids,
            run_id=run_id, metadata=version_metadata, move=True,
            _restore_payload_to=working_path,
        )

    def create_derived(
        self,
        source_path: str | Path,
        *,
        parent_version_ids: Iterable[str],
        name: str | None = None,
        operation: str | None = None,
        parameters: dict[str, Any] | None = None,
        generator: str = "",
        type: str | None = None,
        format: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DataVersion:
        """Create a new DERIVED asset+version from *parent_version_ids*.

        When *operation* is given, a DataRun is registered linking the input
        and output versions, so the result answers the full provenance set:
        parents, run, parameters, generator, time, hash, and payload location.
        """
        parents = [self._version_or_raise(pid) for pid in parent_version_ids]
        parent_type = None
        if parents:
            try:
                parent_type = self._asset_or_raise(parents[0].asset_id).type
            except CatalogError:
                parent_type = None
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CatalogError(f"Source file not found: {source_path}")
        asset = self._new_asset(
            name or source_path.stem, type or parent_type, format, metadata
        )
        # Build everything up front so a single save commits asset + version +
        # run atomically — a failure must not leave an orphaned version or
        # payload behind (review finding: two-phase save was not atomic).
        # The staging lease (#1222) spans build → commit so a concurrent
        # explicit GC sweep cannot classify the not-yet-committed payload.
        run: DataRun | None = None
        if operation is not None:
            run = DataRun(
                operation=operation,
                input_version_ids=[p.id for p in parents],
                parameters=dict(parameters or {}),
                generator=generator,
            )
        with self._payload_staging_lease(
            self._staging_target(DataStage.DERIVED, asset.id)
        ):
            version, payload = self._build_version(
                asset, source_path, DataStage.DERIVED,
                version_id=None,
                parent_version_ids=[p.id for p in parents],
                run_id=run.id if run else None, metadata=metadata, move=False,
            )
            if run is not None:
                run.output_version_ids = [version.id]
            # Commit under the lock (#517); the payload copy/hash above stays
            # outside so the lock is never held across disk I/O.
            with self._lock:
                self._add_asset(asset)
                self._add_version(version)
                asset.current_version_id = version.id
                if run is not None:
                    self._add_run(run)
                _dirty = DirtySet(
                    assets={asset.id: None}, versions={version.id: None}
                )
                if run is not None:
                    _dirty.mark_runs(run.id)
                try:
                    self._save(_dirty)
                except Exception:
                    self._rollback(
                        assets=[asset], versions=[version],
                        runs=[run] if run else [], payload=payload,
                    )
                    raise
                return version

    def register_run(
        self,
        operation: str,
        *,
        input_version_ids: Iterable[str] = (),
        output_version_ids: Iterable[str] = (),
        parameters: dict[str, Any] | None = None,
        generator: str = "",
        status: str = "completed",
        model_ref: dict[str, Any] | None = None,
    ) -> DataRun:
        run = DataRun(
            operation=operation,
            input_version_ids=list(input_version_ids),
            output_version_ids=list(output_version_ids),
            parameters=dict(parameters or {}),
            generator=generator,
            status=status,
            model_ref=dict(model_ref) if model_ref else None,
        )
        self._add_run(run)
        try:
            self._save(DirtySet(runs={run.id: None}))
        except Exception:
            self._rollback(runs=[run])
            raise
        return run

    def update_run_status(
        self,
        run_id: str,
        status: str,
        *,
        extra_parameters: dict[str, Any] | None = None,
    ) -> DataRun:
        """Update a run's status (e.g. running → complete/failed) and persist.

        ``extra_parameters`` are merged into the run's parameters (used by the
        CatalogPort adapter to record finish timestamps).

        Terminal statuses (complete/failed/cancelled) cannot be overwritten
        by a different status. A failed or cancelled run must not later be
        marked complete; retry creates a new run.
        """
        with self._lock:
            run = self.get_run(run_id)
            current = (run.status or "").lower()
            target = (status or "").lower()
            aliases = {"complete", "completed"}
            terminal = {"complete", "completed", "failed", "cancelled", "canceled"}
            if current in terminal and current != target:
                if not (current in aliases and target in aliases):
                    raise CatalogError(
                        f"cannot change terminal run {run_id} from {run.status!r} to {status!r}"
                    )
            before_status = run.status
            before_parameters = dict(run.parameters)
            run.status = status
            if extra_parameters:
                run.parameters.update(extra_parameters)
            try:
                self._save(DirtySet(runs={run.id: None}))
            except Exception:
                # Snapshot-rollback: a failed save must not leave the run
                # half-updated in memory while the disk keeps the old state
                # (failure-compensation paths rely on this, e.g. _fail_run).
                run.status = before_status
                run.parameters = before_parameters
                raise
            return run

    # -- model registry --------------------------------------------------------

    def _model_or_raise(self, model_id: str) -> Model:
        for model in self.document.models:
            if model.model_id == model_id:
                return model
        raise CatalogError(f"Unknown model: {model_id}")

    def register_model(
        self,
        *,
        model_id: str,
        model_name: str,
        model_type: str = "unknown",
        capability: str = "",
        provider: str = "",
        status: str = "demo",
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        force_status: bool = False,
    ) -> Model:
        """Register (or update) a logical model. Idempotent on ``model_id``.

        Re-registering with non-empty identity fields refreshes
        name/type/capability/provider so an explicit package update still
        works. Empty optional fields never wipe a previously stored value
        (``capability=""`` must not hide a production model from
        :meth:`find_production_model`).

        ``force_status`` (default False) protects an existing model from being
        silently downgraded by a seed/defaults call: when the model already
        exists and ``force_status`` is False, its ``status`` and ``metadata``
        are preserved (an explicit promote must never be clobbered by
        ``ensure_default_models`` — review finding C2). Seeds additionally
        never touch existing models at all (``ensure_default_models`` skips
        them), so a seeded id can never rebind a promoted model to a
        heuristic/demo provider. Pass True only when the caller deliberately
        changes status (e.g. promote/demote).
        No-op re-registrations do not rewrite the catalog file."""
        if not model_id or not model_name:
            raise CatalogError("register_model requires model_id and model_name")
        # Mutate + save under the lock (#517).
        with self._lock:
            return self._register_model_locked(
                model_id=model_id, model_name=model_name, model_type=model_type,
                capability=capability, provider=provider, status=status,
                metadata=metadata, provenance=provenance,
                force_status=force_status,
            )

    def _register_model_locked(
        self, *, model_id, model_name, model_type, capability, provider,
        status, metadata, provenance, force_status,
    ) -> Model:
        existing = None
        for model in self.document.models:
            if model.model_id == model_id:
                existing = model
                break
        if existing is not None:
            before = (
                existing.model_name,
                existing.model_type,
                existing.capability,
                existing.provider,
                existing.status,
                dict(existing.metadata),
                dict(existing.provenance),
            )
            changed = False
            if existing.model_name != model_name:
                existing.model_name = model_name
                changed = True
            if (
                model_type
                and model_type != "unknown"
                and existing.model_type != model_type
            ):
                existing.model_type = model_type
                changed = True
            if capability and existing.capability != capability:
                existing.capability = capability
                changed = True
            if provider and existing.provider != provider:
                existing.provider = provider
                changed = True
            if force_status:
                new_meta = dict(metadata or {})
                if existing.status != status or existing.metadata != new_meta:
                    existing.status = status
                    existing.metadata = new_meta
                    changed = True
            if provenance:
                existing.provenance.update(provenance)
                changed = True
            if changed:
                try:
                    self._save(DirtySet(models={existing.id: None}))
                except Exception:
                    (
                        existing.model_name,
                        existing.model_type,
                        existing.capability,
                        existing.provider,
                        existing.status,
                        existing.metadata,
                        existing.provenance,
                    ) = before
                    raise
            return existing
        model = Model(
            model_id=model_id,
            model_name=model_name,
            model_type=model_type or "unknown",
            capability=capability,
            provider=provider,
            status=status,
            metadata=dict(metadata or {}),
            provenance=dict(provenance or {}),
        )
        self.document.models.append(model)
        try:
            self._save(DirtySet(models={model.id: None}))
        except Exception:
            if model in self.document.models:
                _discard_by_identity(self.document.models, model)
            raise
        return model

    def register_model_version(
        self,
        model_id: str,
        *,
        model_version: str = "1",
        artifact_uri: str = "",
        checksum: str | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        preprocessing_version: str = "",
        runtime: str = "",
        deterministic: bool = True,
        demo_only: bool = False,
        status: str = "demo",
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ModelVersion:
        """Register a concrete model version for an existing :class:`Model`.

        When ``checksum`` is omitted and ``artifact_uri`` points at a readable
        file, the checksum is computed from it (streaming). A duplicate
        ``(model_id, model_version)`` pair raises :class:`CatalogError`.

        Stage-13: default status is ``demo``. Requesting ``status="production"``
        is rejected here — callers must use :meth:`promote_model` so demo/heuristic
        safety gates cannot be bypassed.
        """
        self._model_or_raise(model_id)  # validate the model exists
        if str(status) == "production":
            raise CatalogError(
                "register_model_version cannot set status=production; "
                "register as demo then call promote_model()"
            )
        if any(
            v.model_id == model_id and v.model_version == str(model_version)
            for v in self.document.model_versions
        ):
            raise CatalogError(
                f"ModelVersion {model_id}@{model_version} already registered"
            )
        if checksum is None and artifact_uri:
            candidate = Path(artifact_uri).expanduser()
            if candidate.is_file():
                try:
                    checksum = sha256_file(candidate)
                except OSError:
                    checksum = None
        version = ModelVersion(
            model_id=model_id,
            model_version=str(model_version),
            artifact_uri=artifact_uri,
            checksum=checksum,
            input_schema=dict(input_schema or {}),
            output_schema=dict(output_schema or {}),
            preprocessing_version=preprocessing_version,
            runtime=runtime,
            deterministic=deterministic,
            demo_only=demo_only,
            status=status or "demo",
            metadata=dict(metadata or {}),
            provenance=dict(provenance or {}),
        )
        # Append + save under the lock (#517); the checksum hashing above
        # stays outside so the lock is never held across disk I/O.
        with self._lock:
            self.document.model_versions.append(version)
            try:
                self._save(DirtySet(model_versions={version.id: None}))
            except Exception:
                if version in self.document.model_versions:
                    _discard_by_identity(self.document.model_versions, version)
                raise
            return version

    def get_model(self, model_id: str) -> Model:
        return self._model_or_raise(model_id)

    def get_model_version(self, model_id: str, model_version: str) -> ModelVersion:
        key = str(model_version)
        for version in self.document.model_versions:
            if version.model_id == model_id and version.model_version == key:
                return version
        raise CatalogError(f"Unknown model version: {model_id}@{model_version}")

    def get_model_version_by_id(self, model_version_id: str) -> ModelVersion:
        for version in self.document.model_versions:
            if version.id == model_version_id:
                return version
        raise CatalogError(f"Unknown model version: {model_version_id}")

    def list_models(self) -> list[Model]:
        return list(self.document.models)

    def list_model_versions(self, model_id: str | None = None) -> list[ModelVersion]:
        versions = [
            v
            for v in self.document.model_versions
            if model_id is None or v.model_id == model_id
        ]
        return sorted(versions, key=lambda v: v.created_at)

    def promote_model(self, model_id: str, model_version: str) -> ModelVersion:
        """Promote a model version to production in ONE atomic save.

        Sets BOTH the logical ``Model.status`` and the concrete
        ``ModelVersion.status`` to ``"production"`` and clears
        ``demo_only``, so ``find_production_model`` starts returning it.
        This is the sanctioned production-promotion act: nothing else
        (including ``ensure_default_models`` seeds) may silently downgrade
        it afterwards (review finding C2).

        Stage-13 safety: Demo/heuristic providers and ``demo_only`` versions
        cannot be promoted (prevents fabricated science via status flip).
        """
        with self._lock:
            model = self._model_or_raise(model_id)
            key = str(model_version)
            version = None
            for v in self.document.model_versions:
                if v.model_id == model_id and v.model_version == key:
                    version = v
                    break
            if version is None:
                raise CatalogError(
                    f"ModelVersion {model_id}@{model_version} not registered"
                )
            # Safety gates (Stage 13): never promote demo/heuristic into production.

            ok, reason = can_promote_to_production(self, model_id, model_version)
            if not ok:
                raise CatalogError(f"Cannot promote to production: {reason}")
            before_model_status = model.status
            before_version_status = version.status
            before_demo_only = version.demo_only
            model.status = "production"
            version.status = "production"
            version.demo_only = False
            try:
                self._save(
                    DirtySet(models={model.id: None}, model_versions={version.id: None})
                )
            except Exception:
                model.status = before_model_status
                version.status = before_version_status
                version.demo_only = before_demo_only
                raise
            return version

    def find_production_model(self, capability: str) -> ModelVersion | None:
        """Return the newest production :class:`ModelVersion` for *capability*.

        A version qualifies only when BOTH its model and the version are
        ``status == "production"`` and the version is not ``demo_only``.
        Re-runs the promote gates so a model whose identity was mutated after
        promotion (provider/model_type/scientific/schema) is never served as
        production (H4-3a/H4-3c). Returns None when no production model
        exists — callers must surface an honest "no production model" state
        instead of running a mock.
        """
        best: ModelVersion | None = None
        for version in self.document.model_versions:
            if version.demo_only or version.status != "production":
                continue
            try:
                model = self._model_or_raise(version.model_id)
            except CatalogError:
                continue
            if model.status != "production" or model.capability != capability:
                continue

            ok, _reason = can_promote_to_production(
                self,
                model.model_id,
                version.model_version,
                # Schema is enforced at promote time; legacy pre-schema
                # promotions must not vanish from reads on upgrade.
                require_input_schema=False,
            )
            if not ok:
                continue
            if best is None or version.created_at > best.created_at:
                best = version
        return best

    # -- lineage ---------------------------------------------------------------

    def get_lineage(self, version_id: str) -> dict[str, Any]:
        """Parents, children, and the producing run for a version."""
        if self._lazy_active():
            version = self._lazy_get_version(version_id)
            if version is None:
                raise CatalogError(f"Unknown version: {version_id}")
            parents = []
            for pid in version.parent_version_ids:
                parent = self._lazy_get_version(pid)
                if parent is not None:
                    parents.append(parent)
            children = self._index.child_version_models(version_id)
            for child in children:
                self._lazy_read_cache.setdefault(child.id, child)
            run = None
            if version.run_id is not None:
                run = self._lazy_get_run(version.run_id)
            return {
                "version": version,
                "parents": parents,
                "children": children,
                "run": run,
            }
        version = self._version_or_raise(version_id)
        maps = self._ensure_maps()
        parents = [
            maps.version_by_id[pid]
            for pid in version.parent_version_ids
            if pid in maps.version_by_id
        ]
        children = list(maps.children_by_parent.get(version_id, ()))
        run = None
        if version.run_id is not None:
            try:
                run = self.get_run(version.run_id)
            except CatalogError:
                run = None
        return {"version": version, "parents": parents, "children": children, "run": run}

    def get_lineage_chain(
        self,
        version_id: str,
        *,
        direction: str = "ancestors",
        max_depth: int | None = None,
    ) -> "_lineage.LineageChain":
        """Full lineage tree from *version_id* (version→run→input chain).

        ``direction="ancestors"`` walks to the RAW inputs, ``"descendants"``
        to downstream products. Delegates to
        :func:`paleo_workbench.catalog.lineage_graph.build_lineage_chain`
        (walks the maintained id maps — no per-query rebuild, cycle-safe).
        """
        return _lineage.build_lineage_chain(
            self, version_id, direction=direction, max_depth=max_depth
        )

    def lineage_summaries(self) -> dict[str, dict[str, Any]]:
        """Per-version lineage status ``{"to_raw", "broken", "has_parents"}``.

        Computed once per catalog revision and cached (table columns ask for
        every asset on each refresh; the walk itself is O(V+E) memoized DFS).
        Keyed on (revision, mutation serial) so mutations deferred inside a
        batch_save (revision held until commit, #1139) still invalidate.
        """
        with self._lock:
            revision = (self.document.catalog_revision, self.mutation_serial)
            cache = getattr(self, "_lineage_summary_cache", None)
            cache_rev = getattr(self, "_lineage_summary_cache_rev", None)
            if cache is None or cache_rev != revision:
                cache = _lineage.compute_summaries(self)
                self._lineage_summary_cache = cache
                self._lineage_summary_cache_rev = revision
            return cache

    # -- governance metadata ----------------------------------------------------

    def update_asset_metadata(
        self, asset_id: str, patch: dict[str, Any]
    ) -> DataAsset:
        """Apply a metadata patch to an ASSET with validation + rollback.

        Governance fields (source/region/creator/discipline/confidence/
        review_status — see :mod:`paleo_workbench.catalog.governance`) are
        normalized against their controlled vocabularies; other keys pass
        through. Asset metadata is identity-level and mutable; VERSION
        metadata stays immutable with the version (there is deliberately no
        version-level counterpart of this method).

        Snapshot-rollback on save failure mirrors :meth:`add_tags`.
        """
        from paleo_workbench.catalog.governance import (
            GovernanceError,
            normalize_governance_patch,
        )

        with self._lock:
            asset = self._asset_or_raise(asset_id)
            normalized = normalize_governance_patch(patch)
            before_metadata = dict(asset.metadata)
            before_updated = asset.updated_at
            changed = False
            for key, value in normalized.items():
                stored = None if value in (None, "") else value
                if asset.metadata.get(key) != stored:
                    if stored is None:
                        asset.metadata.pop(key, None)
                    else:
                        asset.metadata[key] = stored
                    changed = True
            if not changed:
                return asset
            asset.updated_at = _now_iso()
            try:
                self._save(DirtySet(assets={asset.id: None}))
            except Exception:
                asset.metadata = before_metadata
                asset.updated_at = before_updated
                raise
            return asset

    # -- trash / restore / purge ----------------------------------------------

    def _tombstone_version(self, version: DataVersion, reason: str | None) -> str:
        """Apply the trashed tombstone in memory ONLY — the payload is NOT
        moved here. Callers must persist the tombstone first, then move the
        payload (:meth:`_move_payload_to_trash`) and persist the path update,
        so a crash between the steps never leaves a tombstoned version whose
        recorded path points at a moved-away payload. Returns the original
        project-relative path (recorded in metadata for rollback/restore).
        """
        original_path = version.path
        version.trashed = True
        version.trashed_at = _now_iso()
        version.metadata["trash"] = {
            "reason": reason,
            "original_stage": version.stage.value,
            "original_path": original_path,
            "trashed_at": version.trashed_at,
        }
        return original_path

    def _move_payload_to_trash(self, version: DataVersion) -> bool:
        """Move a managed payload into ``trash/{version_id}/`` and update
        ``version.path``. Returns True when the payload actually moved; False
        for external versions, blob-backed payloads (already shared), or a
        payload that is already missing (metadata-only tombstone)."""
        if not version.managed:
            return False
        try:
            new_rel = _move_to_trash(
                self.project_path, self.resolve_path(version), version.id
            )
        except CatalogError:
            # Payload already missing → metadata-only tombstone.
            return False
        version.path = new_rel
        return True

    def _rollback_trash_move(self, version: DataVersion) -> None:
        """Undo a payload move after the post-move save failed: move the
        payload back to its recorded original location and restore the path.
        The persisted tombstone (saved before the move) is kept — the version
        stays trashed with its payload at the original path, which restore
        handles correctly."""
        meta = version.metadata.get("trash") or {}
        original_path = meta.get("original_path")
        if version.managed and original_path and version.path != original_path:
            try:
                _restore_trashed_payload(
                    self.project_path, self.resolve_path(version), original_path
                )
                version.path = original_path
            except CatalogError:
                pass

    def _probe_trash_payload(self, version_id: str) -> str | None:
        """Crash-window recovery: return the project-relative path of a
        payload sitting under ``trash/{version_id}/`` whose path was never
        re-recorded (tombstone persisted, move happened, path-update save did
        not), else None."""
        root = _trash_dir_for(self.project_path) / version_id
        if not root.is_dir():
            return None
        files = sorted(p for p in root.iterdir() if p.is_file())
        if not files:
            return None
        project_dir = self.project_path.expanduser().resolve().parent
        return files[0].relative_to(project_dir).as_posix()

    def _untombstone_version(self, version: DataVersion) -> str:
        """Reverse a tombstone in memory; returns the restored path (best-effort
        payload move back to the recorded original location)."""
        meta = version.metadata.get("trash") or {}
        original_path = meta.get("original_path") or version.path
        if version.managed:
            try:
                version.path = _restore_trashed_payload(
                    self.project_path, self.resolve_path(version), original_path
                )
            except CatalogError:
                # Crash-window recovery: the recorded path may still be the
                # original location while the payload actually sits under
                # trash/{version_id}/ (tombstone persisted before the path
                # update was saved). Probe for it before declaring the payload
                # lost (integrity will report missing otherwise).
                probed = self._probe_trash_payload(version.id)
                if probed is not None:
                    version.path = probed
                    try:
                        version.path = _restore_trashed_payload(
                            self.project_path,
                            self.resolve_path(version),
                            original_path,
                        )
                    except CatalogError:
                        version.path = original_path
                else:
                    # No payload in trash (metadata-only trash or payload lost)
                    # — keep the original location; integrity will report missing.
                    version.path = original_path
        else:
            version.path = original_path
        version.trashed = False
        version.trashed_at = None
        version.metadata.pop("trash", None)
        return original_path

    def _active_current_candidate(self, asset: DataAsset, exclude_id: str) -> str | None:
        """Newest non-trashed version of *asset* (excluding *exclude_id*)."""
        active = [
            v
            for v in self._ensure_maps().versions_by_asset.get(asset.id, ())
            if not v.trashed and v.id != exclude_id
        ]
        return active[-1].id if active else None

    def trash_version(self, version_id: str, *, reason: str | None = None) -> DataVersion:
        """Soft-delete a version: tombstone + managed payload moved to ``trash/``.

        External (unmanaged) versions are metadata-only — the external source
        file is NEVER touched. Lineage and runs keep pointing at the trashed
        version (``get_lineage`` still includes it, marked trashed);
        :meth:`verify_integrity` skips trashed versions. Recoverable via
        :meth:`restore_version`.

        Crash-safe ordering: the tombstone is persisted BEFORE the payload
        moves, so a process crash in between leaves a tombstoned version whose
        recorded path still points at an existing payload (consistent state);
        a crash after the move but before the path-update save is recovered by
        :meth:`_probe_trash_payload` on restore.
        """
        with self._lock:
            version = self._version_or_raise(version_id)
            if version.trashed:
                return version
            asset = self._asset_or_raise(version.asset_id)
            previous_current = asset.current_version_id
            self._tombstone_version(version, reason)
            if asset.current_version_id == version.id:
                asset.current_version_id = self._active_current_candidate(asset, version.id)
            _dirty = DirtySet(assets={asset.id: None}, versions={version.id: None})
            try:
                self._save(_dirty)
            except Exception:
                self._rollback_tombstone(version, asset, previous_current)
                raise
            if self._move_payload_to_trash(version):
                try:
                    self._save(DirtySet(assets={asset.id: None}, versions={version.id: None}))
                except Exception:
                    self._rollback_trash_move(version)
                    raise
            return version

    def trash_asset(self, asset_id: str, *, reason: str | None = None) -> DataAsset:
        """Soft-delete an asset and every one of its versions (payloads to
        ``trash/``); the asset disappears from active listings. Recoverable via
        :meth:`restore_asset`."""
        with self._lock:
            asset = self._asset_or_raise(asset_id)
            if asset.trashed:
                return asset
            versions = [
                v for v in self.document.versions
                if v.asset_id == asset_id and not v.trashed
            ]
            previous_current = asset.current_version_id
            for version in versions:
                self._tombstone_version(version, reason)
            asset.trashed = True
            asset.trashed_at = _now_iso()
            asset.current_version_id = None
            _dirty = DirtySet(
                assets={asset.id: None}, versions=dict.fromkeys(v.id for v in versions)
            )
            try:
                self._save(_dirty)
            except Exception:
                for version in versions:
                    self._rollback_tombstone(version, asset, previous_current)
                asset.trashed = False
                asset.trashed_at = None
                raise
            moved = [v for v in versions if self._move_payload_to_trash(v)]
            if moved:
                try:
                    self._save(
                        DirtySet(assets={asset.id: None}, versions=dict.fromkeys(v.id for v in moved))
                    )
                except Exception:
                    for version in moved:
                        self._rollback_trash_move(version)
                    raise
            return asset

    def _rollback_tombstone(
        self, version: DataVersion, asset: DataAsset, previous_current: str | None
    ) -> None:
        """Undo an in-memory tombstone after a failed tombstone save. The
        payload has NOT moved yet (save-then-move order), so only the
        in-memory flags/metadata are cleared."""
        version.trashed = False
        version.trashed_at = None
        version.metadata.pop("trash", None)
        asset.current_version_id = previous_current

    def restore_version(self, version_id: str) -> DataVersion:
        """Restore a trashed version: tombstone cleared and managed payload
        moved back to its original stage location."""
        with self._lock:
            version = self._version_or_raise(version_id)
            if not version.trashed:
                return version
            asset = self._asset_or_raise(version.asset_id)
            previous_current = asset.current_version_id
            trash_meta = version.metadata.get("trash") or {}
            reason = trash_meta.get("reason")
            self._untombstone_version(version)
            if asset.current_version_id is None or not any(
                v.id == asset.current_version_id and not v.trashed
                for v in self.document.versions
            ):
                asset.current_version_id = version.id
            try:
                self._save(DirtySet(assets={asset.id: None}, versions={version.id: None}))
            except Exception:
                self._rollback_untombstone(
                    version, asset, previous_current, reason=reason
                )
                raise
            return version

    def restore_asset(self, asset_id: str) -> DataAsset:
        """Restore a trashed asset and every one of its trashed versions."""
        with self._lock:
            asset = self._asset_or_raise(asset_id)
            versions = [v for v in self.document.versions if v.asset_id == asset_id]
            previous_current = asset.current_version_id
            previous_trashed = asset.trashed
            previous_trashed_at = asset.trashed_at
            # (version, reason) pairs for the versions this restore actually
            # untombstones; the trash reason must be captured before
            # _untombstone_version pops the metadata.
            restore_targets: list[tuple[DataVersion, str | None]] = []
            for version in versions:
                if version.trashed:
                    trash_meta = version.metadata.get("trash") or {}
                    restore_targets.append((version, trash_meta.get("reason")))
                    self._untombstone_version(version)
            asset.trashed = False
            asset.trashed_at = None
            if asset.current_version_id is None and versions:
                active = [v for v in versions if not v.trashed]
                asset.current_version_id = active[-1].id if active else None
            try:
                self._save(
                    DirtySet(
                        assets={asset.id: None},
                        versions=dict.fromkeys(v.id for v, _ in restore_targets),
                    )
                )
            except Exception:
                asset.trashed = previous_trashed
                asset.trashed_at = previous_trashed_at
                # Roll back ONLY the versions the restore modified; versions
                # that were already live must stay live.
                for version, reason in restore_targets:
                    self._rollback_untombstone(
                        version, asset, previous_current, reason=reason
                    )
                raise
            return asset

    def _rollback_untombstone(
        self,
        version: DataVersion,
        asset: DataAsset,
        previous_current: str | None,
        reason: str | None = None,
    ) -> None:
        """Re-apply a tombstone after a failed restore save (payload moved back
        into ``trash/``)."""
        self._tombstone_version(version, reason)
        if version.managed:
            self._move_payload_to_trash(version)
        asset.current_version_id = previous_current

    def purge_trashed(self) -> int:
        """Permanently delete every trashed version (payload removed from
        ``trash/``) and every trashed asset. Only trashed items are touched;
        active assets are never removed. Runs are retained as historical
        provenance. Returns the number of trashed entries removed."""
        with self._lock:
            trashed_versions = [v for v in self.document.versions if v.trashed]
            trashed_assets = [a for a in self.document.assets if a.trashed]
            purged_ids = {v.id for v in trashed_versions} | {a.id for a in trashed_assets}
            removed_version_tags = {
                vid: tags
                for vid, tags in list(self.document.version_tags.items())
                if vid in purged_ids
            }
            removed_asset_tags = {
                aid: tags
                for aid, tags in list(self.document.asset_tags.items())
                if aid in purged_ids
            }
            # Digests still referenced by versions that SURVIVE the purge:
            # a blob backed by them must not be unlinked (shared refcount).
            surviving_digests = {
                v.sha256
                for v in self.document.versions
                if not v.trashed and v.sha256
            }
            # Payload unlink jobs are collected up front and run only AFTER a
            # successful save: a failed save must leave the trash payloads
            # restorable (catalog.json still references them).
            payload_purges = [
                (
                    self.resolve_path(version),
                    version.sha256 is not None
                    and version.sha256 in surviving_digests,
                )
                for version in trashed_versions
                if version.managed
            ]
            self._remove_versions_bulk(trashed_versions)
            # A live asset whose EVERY version was individually trashed and
            # purged is a zombie (zero versions, current_version_id=None):
            # drop it so listings cannot show an empty asset row (I3).
            live_asset_ids = {v.asset_id for v in self.document.versions}
            # In-flight working-copy commits own a version-less asset
            # for the lock-free payload window (#1218, R2#5).
            live_asset_ids |= self._pending_commit_assets
            zombie_assets = [
                a
                for a in self.document.assets
                if not a.trashed and a.id not in live_asset_ids
            ]
            removed_zombie_tags = {
                aid: tags
                for aid, tags in list(self.document.asset_tags.items())
                if aid in {a.id for a in zombie_assets}
            }
            self._remove_assets_bulk(zombie_assets)
            for asset in zombie_assets:
                self.document.asset_tags.pop(asset.id, None)
            # An asset is removed only when NONE of its versions survives the
            # purge. restore_version() can untrash a single version of a
            # trashed asset; deleting the asset then would orphan that live
            # version (ghost version whose asset_id no longer exists — review
            # finding C3). Such assets are kept and un-trashed.
            surviving_asset_ids = {
                v.asset_id for v in self.document.versions if not v.trashed
            }
            untrashed_snapshots: list[
                tuple[DataAsset, bool, str | None, dict[str, Any]]
            ] = []
            removed_trashed_assets: list[DataAsset] = []
            for asset in trashed_assets:
                if asset.id in surviving_asset_ids:
                    untrashed_snapshots.append(
                        (
                            asset,
                            asset.trashed,
                            asset.trashed_at,
                            dict(asset.metadata),
                        )
                    )
                    asset.trashed = False
                    asset.trashed_at = None
                    asset.metadata.pop("trash", None)
                    continue
                removed_trashed_assets.append(asset)
            self._remove_assets_bulk(removed_trashed_assets)
            for vid in removed_version_tags:
                self.document.version_tags.pop(vid, None)
            for aid in removed_asset_tags:
                self.document.asset_tags.pop(aid, None)
            try:
                self._save(
                    DirtySet(
                        versions=dict.fromkeys(v.id for v in trashed_versions),
                        assets=dict.fromkeys(
                            [a.id for a in trashed_assets]
                            + [a.id for a in zombie_assets]
                        ),
                        version_tags=dict.fromkeys(removed_version_tags),
                        asset_tags=dict.fromkeys(removed_asset_tags),
                    )
                )
            except Exception:
                for version in trashed_versions:
                    self._add_version(version)
                for asset in zombie_assets:
                    self._add_asset(asset)
                for asset in trashed_assets:
                    # Only re-add assets actually removed (un-trashed assets
                    # stayed in the document the whole time).
                    if not any(existing is asset for existing in self.document.assets):
                        self._add_asset(asset)
                for asset, was_trashed, was_at, was_meta in untrashed_snapshots:
                    asset.trashed = was_trashed
                    asset.trashed_at = was_at
                    asset.metadata = was_meta
                self.document.version_tags.update(removed_version_tags)
                self.document.asset_tags.update(removed_asset_tags)
                self.document.asset_tags.update(removed_zombie_tags)
                raise
            # State is durable now; the unlink is best-effort and cannot
            # corrupt it (a leftover trash payload is a harmless orphan).
            for payload_path, shared in payload_purges:
                purge_trashed_payload(self.project_path, payload_path, shared=shared)
            return len(trashed_versions) + len(trashed_assets)

    # -- promote ---------------------------------------------------------------

    def promote_version(
        self,
        version_id: str,
        *,
        to_stage: DataStage = DataStage.OUTPUT,
        reviewed_by: str | None = None,
        note: str | None = None,
    ) -> DataVersion:
        """Promote a committed version to *to_stage* as a NEW immutable version.

        Honors "committed versions are immutable; change produces a new
        version": the payload is copied (never moved) into the target stage,
        the new version records ``parent_version_ids=[source]``, a ``promote``
        DataRun links source → promoted version, and the asset's
        ``current_version_id`` advances to the promoted version. The source
        version stays as-is (provenance preserved).
        """
        source = self._version_or_raise(version_id)
        if source.trashed:
            raise CatalogError(f"Cannot promote a trashed version: {version_id}")
        if not isinstance(to_stage, DataStage):
            to_stage = DataStage(to_stage)
        source_payload = self.resolve_path(source)
        if not source_payload.is_file():
            raise CatalogError(f"Source payload not available: {source_payload}")
        asset = self._asset_or_raise(source.asset_id)
        previous_current = asset.current_version_id
        run = DataRun(
            operation="promote",
            input_version_ids=[source.id],
            parameters={
                "to_stage": to_stage.value,
                "reviewed_by": reviewed_by,
                "note": note,
            },
        )
        # Staging lease (#1222) spans the payload copy → commit window.
        with self._payload_staging_lease(
            self._staging_target(to_stage, asset.id)
        ):
            version, payload = self._build_version(
                asset, source_payload, to_stage,
                version_id=None,
                parent_version_ids=[source.id],
                run_id=run.id,
                metadata={
                    "promoted_from": source.id,
                    "reviewed_by": reviewed_by,
                    "note": note,
                },
                move=False,
            )
            run.output_version_ids = [version.id]
            # Commit under the lock (#517); the payload build above stays outside.
            # Version numbers are re-allocated INSIDE the lock (mirroring
            # register_version): the number computed in ``_build_version`` ran
            # outside it, so concurrent promotes of the same asset could both
            # compute max+1 and commit duplicates [1,2,2] (audit #849-1).
            with self._lock:
                version.version_number = self._next_version_number(asset.id)
                self._add_version(version)
                self._add_run(run)
                asset.current_version_id = version.id
                try:
                    self._save(
                        DirtySet(
                            assets={asset.id}, versions={version.id}, runs={run.id}
                        )
                    )
                except Exception:
                    self._rollback(
                        versions=[version], runs=[run], payload=payload,
                        restore_current=(asset, previous_current),
                    )
                    raise
                return version

    def promote_asset(
        self,
        asset_id: str,
        to_stage: DataStage = DataStage.OUTPUT,
        *,
        reviewed_by: str | None = None,
        note: str | None = None,
    ) -> DataVersion:
        """Promote an asset's current version (convenience)."""
        asset = self._asset_or_raise(asset_id)
        if asset.current_version_id is None:
            raise CatalogError(f"Asset has no current version: {asset_id}")
        return self.promote_version(
            asset.current_version_id,
            to_stage=to_stage,
            reviewed_by=reviewed_by,
            note=note,
        )

    # -- integrity -------------------------------------------------------------

    def verify_integrity(
        self,
        version_id: str | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> IntegrityReport:
        """Re-hash payloads and compare against recorded SHA-256.

        Reports only; a mismatch never updates the catalog. Hashing streams in
        chunks; wrap in a worker thread for large batches in UI contexts.
        Trashed versions are skipped (their payloads live in ``trash/``).
        ``cancel`` (#1224) propagates INTO the chunk loop: a multi-GB hash is
        interruptible at MiB granularity, not only between payloads.

        Delegates to :func:`paleo_workbench.catalog.queries.verify_integrity`.
        """
        return _queries.verify_integrity(self, version_id=version_id, cancel=cancel)

    def repair_ghost_runs(self) -> list[str]:
        """Mark ghost completed runs failed (#1219) and return their ids.

        A "ghost" is a terminal-completed run of an always-producing
        operation with zero outputs (a crash between the old pre-book
        pattern's booking and its output registration). Failing them is the
        honest state: the run claims success but produced nothing. Existing
        outputs are never touched; non-producing operations are exempt.
        """
        always_producing = {
            "materialize",
            "working_copy_commit",
            "map_product_assembly",
            "interchange.import",
        }
        repaired: list[str] = []
        with self._lock:
            for run in list(self.document.runs):
                if (
                    run.operation in always_producing
                    and run.status in ("completed", "complete")
                    and not run.output_version_ids
                ):
                    run.status = "failed"
                    parameters = dict(run.parameters or {})
                    parameters["ghost_repair"] = (
                        "v6 repair: completed run had no outputs"
                    )
                    run.parameters = parameters
                    repaired.append(run.id)
            if repaired:
                self._save()
        return repaired

    def audit(
        self,
        *,
        deep: bool = False,
        cancel: Callable[[], bool] | None = None,
    ) -> "_audit.AuditReport":
        """Structural audit of the catalog (detection only, never mutates).

        Checks payload existence, lineage references, tag associations,
        ``current_version_id`` validity, storage layout, and orphan files.
        ``deep=True`` additionally re-hashes payloads (integrity mismatches).

        ``cancel``: optional ``Callable[[], bool]`` polled between payload
        checks so a closing dialog can stop a long deep audit promptly
        (#1056); the returned report carries ``cancelled=True`` and a
        partial issue list.

        Delegates to :func:`paleo_workbench.catalog.audit.audit_catalog`.
        """
        return _audit.audit_catalog(self, deep=deep, cancel=cancel)

    # -- tags ------------------------------------------------------------------

    def _tag_by_name(self, name: str) -> Tag | None:
        return _tags._tag_by_name(self, name)

    def add_tag(
        self,
        name: str,
        *,
        asset_id: str | None = None,
        version_id: str | None = None,
    ) -> Tag:
        """Get-or-create a normalized tag and associate it. Idempotent.

        Delegates to :func:`paleo_workbench.catalog.tags.add_tag`.
        """
        return _tags.add_tag(self, name, asset_id=asset_id, version_id=version_id)

    def add_tags(
        self,
        names: Iterable[str],
        *,
        asset_id: str | None = None,
        version_id: str | None = None,
    ) -> list[Tag]:
        """Add several tags with at most one canonical catalog write.

        This is deliberately a narrow metadata-only transaction rather than a
        generic deferred-save context.  Version/artifact placement has its own
        immediate rollback guarantees; deferring those commits would enlarge a
        crash window.  Here every mutation is in the CatalogDocument, so a
        failed canonical save can restore the exact pre-batch metadata state.

        Rollback is journal-based (same discipline as ``bulk_add_tag``): only
        the entries this call actually touches are recorded, so the cost is
        O(names) instead of a deep copy of BOTH full association maps — which
        at catalog scale (100k+ owners) dominated every batch tag add.
        """
        with self._lock:
            if asset_id is None and version_id is None:
                raise CatalogError("add_tags requires asset_id or version_id")
            if asset_id is not None:
                self._asset_or_raise(asset_id)
            if version_id is not None:
                self._version_or_raise(version_id)

            journal = _tags._TagJournal(self.document)
            tags_by_name = {
                tag.name: tag for tag in self.document.tags
            }
            result: list[Tag] = []
            changed = False
            created_tags: list[Tag] = []
            touched_assets: dict[str, None] = {}
            touched_versions: dict[str, None] = {}
            try:
                for name in names:
                    if not str(name or "").strip():
                        continue
                    normalized = self._normalize_tag_for_batch(str(name))
                    tag = tags_by_name.get(normalized)
                    if tag is None:
                        tag = Tag(
                            name=normalized,
                            display_name=" ".join(str(name).split()),
                        )
                        self.document.tags.append(tag)
                        tags_by_name[normalized] = tag
                        journal.record_tag_created(tag)
                        created_tags.append(tag)
                        changed = True
                    if asset_id is not None:
                        ids = self.document.asset_tags.get(asset_id)
                        if ids is None or tag.id not in ids:
                            # Capture BEFORE setdefault can create the key.
                            journal.record_list("asset_tags", asset_id)
                            ids = self.document.asset_tags.setdefault(asset_id, [])
                            if tag.id not in ids:
                                ids.append(tag.id)
                                changed = True
                                touched_assets[asset_id] = None
                    if version_id is not None:
                        ids = self.document.version_tags.get(version_id)
                        if ids is None or tag.id not in ids:
                            journal.record_list("version_tags", version_id)
                            ids = self.document.version_tags.setdefault(version_id, [])
                            if tag.id not in ids:
                                ids.append(tag.id)
                                changed = True
                                touched_versions[version_id] = None
                    result.append(tag)
                if changed:
                    self._save(
                        DirtySet(
                            tags=dict.fromkeys(t.id for t in created_tags),
                            asset_tags=touched_assets,
                            version_tags=touched_versions,
                        )
                    )
                return result
            except Exception:
                journal.rollback()
                raise

    @staticmethod
    def _normalize_tag_for_batch(name: str) -> str:
        from paleo_workbench.catalog.models import normalize_tag_name

        normalized = normalize_tag_name(name)
        if not normalized:
            raise CatalogError("Empty tag name")
        return normalized

    def remove_tag(
        self,
        name: str,
        *,
        asset_id: str | None = None,
        version_id: str | None = None,
    ) -> None:
        """Delegates to :func:`paleo_workbench.catalog.tags.remove_tag`."""
        return _tags.remove_tag(self, name, asset_id=asset_id, version_id=version_id)

    def rename_tag(
        self,
        old_name: str,
        new_name: str,
        *,
        on_collision: str = "merge",
    ) -> Tag:
        """Rename a tag. On normalized collision with an existing tag the
        default ``merge`` re-points associations at the existing tag;
        ``on_collision="error"`` refuses the rename instead.

        Delegates to :func:`paleo_workbench.catalog.tags.rename_tag`.
        """
        return _tags.rename_tag(
            self, old_name, new_name, on_collision=on_collision
        )

    def merge_tags(self, source_name: str, target_name: str) -> Tag:
        """Merge *source_name* into *target_name* (both must exist); the source
        tag entity is dropped with no dangling associations.

        Delegates to :func:`paleo_workbench.catalog.tags.merge_tags`.
        """
        return _tags.merge_tags(self, source_name, target_name)

    def create_tag(self, name: str) -> Tag:
        """Create (or return) a tag entity with no associations (one write).

        Delegates to :func:`paleo_workbench.catalog.tags.create_tag`.
        """
        return _tags.create_tag(self, name)

    def bulk_add_tag(
        self,
        name: str,
        *,
        asset_ids: Iterable[str] = (),
        version_ids: Iterable[str] = (),
    ) -> Tag:
        """Associate one tag with many assets/versions in ONE catalog write.

        Delegates to :func:`paleo_workbench.catalog.tags.bulk_add_tag`.
        """
        return _tags.bulk_add_tag(
            self, name, asset_ids=list(asset_ids), version_ids=list(version_ids)
        )

    def bulk_remove_tag(
        self,
        name: str,
        *,
        asset_ids: Iterable[str] = (),
        version_ids: Iterable[str] = (),
    ) -> None:
        """Remove one tag association from many assets/versions in ONE write.

        Delegates to :func:`paleo_workbench.catalog.tags.bulk_remove_tag`.
        """
        return _tags.bulk_remove_tag(
            self, name, asset_ids=list(asset_ids), version_ids=list(version_ids)
        )

    def tag_ids_for_asset(self, asset_id: str) -> list[str]:
        """Ids of the tags attached to *asset_id* (read-only service seam).

        UI consumers must resolve tag ownership through this method rather
        than reaching into ``document.asset_tags`` — the representation may
        change (e.g. a maintained inverse index) without breaking callers.
        """
        asset = self._asset_or_raise(asset_id)
        with self._lock:
            return list(self.document.asset_tags.get(asset.id, ()))

    def tag_usage(self) -> dict[str, dict]:
        """Per-tag association counts: ``{tag_id: {"name", "display_name",
        "assets", "versions"}}`` — Asset Tags and Version Tags counted apart.

        Delegates to :func:`paleo_workbench.catalog.tags.tag_usage`.
        """
        return _tags.tag_usage(self)

    def search_tags(
        self, text: str, *, limit: int | None = None
    ) -> list[Tag]:
        """Substring search over tag names (normalized both sides).

        Delegates to :func:`paleo_workbench.catalog.tags.search_tags`.
        """
        return _tags.search_tags(self, text, limit=limit)

    def delete_unused_tag(self, name: str) -> Tag:
        """Delete a zero-association tag entity; refuses tags still in use.

        Delegates to :func:`paleo_workbench.catalog.tags.delete_unused_tag`.
        """
        return _tags.delete_unused_tag(self, name)

    def prune_unused_tags(self) -> list[Tag]:
        """Delete every zero-association tag entity; returns the removed ones.

        Delegates to :func:`paleo_workbench.catalog.tags.prune_unused_tags`.
        """
        return _tags.prune_unused_tags(self)

    def list_tags(self) -> list[Tag]:
        """Delegates to :func:`paleo_workbench.catalog.tags.list_tags`."""
        return _tags.list_tags(self)

    def find_assets_by_tag(self, name: str) -> list[str]:
        """Delegates to :func:`paleo_workbench.catalog.tags.find_assets_by_tag`."""
        return _tags.find_assets_by_tag(self, name)

    def find_versions_by_tag(self, name: str) -> list[str]:
        """Delegates to :func:`paleo_workbench.catalog.tags.find_versions_by_tag`."""
        return _tags.find_versions_by_tag(self, name)

    # -- search ------------------------------------------------------------------

    def search_assets(
        self,
        *,
        text: str | None = None,
        stage: DataStage | None = None,
        tag: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        tag_op: str = "and",
        type: str | None = None,
        metadata: dict[str, Any] | None = None,
        include_trashed: bool = False,
    ) -> list[DataAsset]:
        """Filter assets by name substring, stage, tag(s), type, and/or
        metadata key-value pairs (governance fields included).

        ``tags`` accepts several tag names combined with ``tag_op``
        (``"and"`` / ``"or"``). ``metadata`` values match by string equality
        against ``asset.metadata[key]``. Trashed (soft-deleted) assets are
        excluded unless ``include_trashed``.

        Delegates to :func:`paleo_workbench.catalog.queries.search_assets`.
        """
        return _queries.search_assets(
            self,
            text=text,
            stage=stage,
            tag=tag,
            tags=tags,
            tag_op=tag_op,
            type=type,
            metadata=metadata,
            include_trashed=include_trashed,
        )

    # -- paged queries (explorer scale path) ---------------------------------
    #
    # The read-only query seam the Data Explorer consumes: bounded pages,
    # index-backed counts and group-by aggregates. The SQLite index answers
    # whenever it can be proven current (not mid-batch, revision in sync);
    # otherwise the same page contract is served from the in-memory document
    # through a revision-keyed fallback so callers never fall back to
    # materializing every asset in UI code.

    def search_assets_page(
        self,
        *,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        tag_op: str = "and",
        type: str | None = None,
        asset_id: str | None = None,
        asset_ids: list[str] | tuple[str, ...] | None = None,
        include_trashed: bool = False,
        trashed_only: bool = False,
        order_by: str | None = None,
        limit: int = 500,
        offset: int = 0,
        after: tuple[str, str] | None = None,
    ) -> list[dict]:
        """One deterministic page of assets joined with the current version.

        Row shape (dicts) matches ``CatalogIndex.search_assets_page``: asset
        columns plus ``current_stage`` / ``current_version_number`` /
        ``current_size_bytes`` / ``current_sha256`` / ``current_managed`` /
        ``current_format`` / ``current_path`` / ``current_created_at``.

        Served from the SQLite index when it is provably current; inside a
        ``batch_save`` (or when the index cannot be trusted) the page is
        computed from the in-memory document with identical semantics, so a
        caller paging mid-import sees the pending state instead of stale
        rows. Never raises for query-shape reasons; an index hiccup degrades
        to the document fallback, not an empty result.
        """
        index = self._query_index_if_current()
        if index is not None:
            try:
                return index.search_assets_page(
                    text=text,
                    stage=stage,
                    tags=tags,
                    tag_op=tag_op,
                    type=type,
                    asset_id=asset_id,
                    asset_ids=asset_ids,
                    include_trashed=include_trashed,
                    trashed_only=trashed_only,
                    order_by=order_by,
                    limit=limit,
                    offset=offset,
                    after=after,
                )
            except Exception:
                pass  # fall through to the document-backed page
        return self._paged_rows_from_document(
            text=text,
            stage=stage,
            tags=tags,
            tag_op=tag_op,
            type=type,
            asset_id=asset_id,
            asset_ids=asset_ids,
            include_trashed=include_trashed,
            trashed_only=trashed_only,
            order_by=order_by,
            limit=limit,
            offset=offset,
            after=after,
        )

    def count_assets(
        self,
        *,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        tag_op: str = "and",
        type: str | None = None,
        asset_id: str | None = None,
        asset_ids: list[str] | tuple[str, ...] | None = None,
        include_trashed: bool = False,
        trashed_only: bool = False,
    ) -> int:
        """Count of assets matching the paged-path predicates."""
        index = self._query_index_if_current()
        if index is not None:
            try:
                return int(
                    index.count_assets(
                        text=text,
                        stage=stage,
                        tags=tags,
                        tag_op=tag_op,
                        type=type,
                        asset_id=asset_id,
                        asset_ids=asset_ids,
                        include_trashed=include_trashed,
                        trashed_only=trashed_only,
                    )
                )
            except Exception:
                pass
        return len(
            self._paged_fallback_rows(
                text=text,
                stage=stage,
                tags=tags,
                tag_op=tag_op,
                type=type,
                asset_id=asset_id,
                asset_ids=asset_ids,
                include_trashed=include_trashed,
                trashed_only=trashed_only,
            )
        )

    def cached_catalog_aggregates(
        self, include_trashed: bool = False
    ) -> dict | None:
        """The cached aggregates when fresh, else None (never computes).

        Lets the UI serve badges synchronously on the warm path and defer
        the ~389 ms cold group-by pass off the GUI thread at 100k.
        """
        with self._lock:
            cache_key = (
                self.document.catalog_revision,
                self.mutation_serial,
                bool(include_trashed),
            )
            cache = getattr(self, "_aggregates_cache", None)
            cache_rev = getattr(self, "_aggregates_cache_rev", None)
            if cache is not None and cache_rev == cache_key:
                return cache
        return None

    def catalog_aggregates(self, include_trashed: bool = False) -> dict:
        """Group-by counts for explorer badges: ``total``/``stages``/
        ``types``/``tags``/``review_status`` (same shape as the index).

        Cached per (revision, mutation serial, include_trashed): the tree
        re-reads badges on every refresh while the aggregates only change
        when the catalog mutates (~389 ms per uncached pass at 100k).
        """
        with self._lock:
            cache_key = (self.document.catalog_revision, self.mutation_serial, bool(include_trashed))
            cache = getattr(self, "_aggregates_cache", None)
            cache_rev = getattr(self, "_aggregates_cache_rev", None)
            if cache is not None and cache_rev == cache_key:
                return cache
        index = self._query_index_if_current()
        if index is not None:
            try:
                computed = index.catalog_aggregates(include_trashed=include_trashed)
            except Exception:
                computed = None
        else:
            computed = None
        if computed is None:
            computed = self._aggregates_from_document(include_trashed=include_trashed)
        with self._lock:
            self._aggregates_cache = computed
            self._aggregates_cache_rev = cache_key
        return computed

    def _aggregates_from_document(self, include_trashed: bool = False) -> dict:
        """Aggregates from the in-memory document (index unavailable)."""
        rows = self._paged_fallback_rows(include_trashed=include_trashed)
        stages: dict[str, int] = {}
        types: dict[str, int] = {}
        review: dict[str, int] = {}
        for row in rows:
            stage_key = str(row.get("current_stage") or "")
            if stage_key:
                stages[stage_key] = stages.get(stage_key, 0) + 1
            type_key = str(row.get("type") or "")
            if type_key:
                types[type_key] = types.get(type_key, 0) + 1
            raw_metadata = row.get("metadata")
            try:
                metadata = (
                    json.loads(raw_metadata)
                    if isinstance(raw_metadata, str)
                    else (raw_metadata or {})
                )
            except (TypeError, ValueError):
                metadata = {}
            status = (metadata or {}).get("review_status")
            if status:
                review[str(status)] = review.get(str(status), 0) + 1
        tags_counts: dict[str, int] = {}
        tags_by_id = {tag.id: tag for tag in self.document.tags}
        for row in rows:
            for tag_id in self.document.asset_tags.get(str(row["id"]), ()):
                tag = tags_by_id.get(tag_id)
                if tag is None:
                    continue
                key = str(tag.display_name or tag.name)
                tags_counts[key] = tags_counts.get(key, 0) + 1
        return {
            "total": len(rows),
            "stages": stages,
            "types": types,
            "tags": tags_counts,
            "review_status": review,
        }

    def _query_index_if_current(self) -> CatalogIndex | None:
        """The index when it can be trusted for a read, else None.

        Mid-batch the document holds unflushed mutations the store has never
        seen; a stale revision means the same. Reads must reflect the
        document, so both cases take the document-backed fallback.
        """
        if self._batch_depth:
            return None
        if self._lazy and not self._warm:
            # Pre-warm the document is EMPTY by design, so the document
            # fallback below can only serve wrong-empty rows — and a
            # revision drift here means a FOREIGN process committed (every
            # local mutation implies an inline warm), making the store the
            # fresh truth. Serve the store (R1#1/R2#3).
            return self._index
        try:
            if self._index.revision() != self.document.catalog_revision:
                return None
        except Exception:
            return None
        return self._index

    def _tag_by_id(self, tag_id: str):
        for tag in self.document.tags:
            if tag.id == tag_id:
                return tag
        return None

    def _paged_fallback_rows(
        self,
        *,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        tag_op: str = "and",
        type: str | None = None,
        asset_id: str | None = None,
        asset_ids: list[str] | tuple[str, ...] | None = None,
        include_trashed: bool = False,
        trashed_only: bool = False,
    ) -> list[dict]:
        """Filtered assets as paged-shape row dicts, cached per revision.

        Single-slot cache keyed on (revision, mutation serial, query): the
        explorer re-issues the same query for counts while paging, and the
        cache keeps that O(1) instead of O(N) per page call.
        """
        query_key = (
            normalize_asset_search_name(text or ""),
            str(getattr(stage, "value", stage) or ""),
            tuple(sorted(str(t) for t in (tags or ()))),
            str(tag_op or "and"),
            str(type or ""),
            str(asset_id or ""),
            tuple(sorted(str(a) for a in (asset_ids or ()))),
            bool(include_trashed),
            bool(trashed_only),
        )
        with self._lock:
            cache_key = (self.document.catalog_revision, self.mutation_serial, query_key)
            cache = getattr(self, "_paged_fallback_cache", None)
            cache_rev = getattr(self, "_paged_fallback_cache_rev", None)
            if cache is not None and cache_rev == cache_key:
                return cache
            needle = query_key[0] or None
            stage_value = str(getattr(stage, "value", stage)) if stage is not None else None
            wanted_tags = {
                _tags.normalize_tag_name(t) for t in (tags or ()) if str(t).strip()
            }
            tags_by_id = {tag.id: tag.name for tag in self.document.tags}
            asset_id_set = {str(a) for a in (asset_ids or ())}
            rows: list[dict] = []
            maps = self._ensure_maps()
            for asset in self.document.assets:
                if trashed_only:
                    if not asset.trashed:
                        continue
                elif not include_trashed and asset.trashed:
                    continue
                if asset_id and asset.id != asset_id:
                    continue
                if asset_ids and asset.id not in asset_id_set:
                    continue
                if type is not None and asset.type != str(type):
                    continue
                if wanted_tags:
                    owned = {
                        tags_by_id.get(tid)
                        for tid in self.document.asset_tags.get(asset.id, ())
                    }
                    owned.discard(None)
                    if tag_op == "or":
                        if not (owned & wanted_tags):
                            continue
                    elif not wanted_tags.issubset(owned):
                        continue
                version = maps.version_by_id.get(asset.current_version_id or "")
                if stage_value is not None:
                    if version is None or version.stage.value != stage_value:
                        continue
                if needle and needle not in normalize_asset_search_name(asset.name):
                    continue
                rows.append(self._asset_page_row(asset, version))
            self._paged_fallback_cache = rows
            self._paged_fallback_cache_rev = cache_key
            return rows

    def _asset_page_row(self, asset: DataAsset, version: DataVersion | None) -> dict:
        """Paged-shape row dict from in-memory objects (fallback path)."""
        row = {
            "id": asset.id,
            "name": asset.name,
            "name_search": normalize_asset_search_name(asset.name),
            "type": asset.type,
            "description": asset.description,
            "current_version_id": asset.current_version_id,
            "legacy_resource_id": asset.legacy_resource_id,
            # JSON TEXT, matching the SQL row contract byte-for-byte.
            "metadata": json.dumps(asset.metadata or {}, ensure_ascii=False),
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
            "trashed": 1 if asset.trashed else 0,
            "trashed_at": asset.trashed_at,
            "current_stage": version.stage.value if version is not None else None,
            "current_version_number": (
                version.version_number if version is not None else None
            ),
            "current_size_bytes": version.size_bytes if version is not None else None,
            "current_sha256": version.sha256 if version is not None else None,
            "current_managed": (
                (1 if version.managed else 0) if version is not None else None
            ),
            "current_format": version.format if version is not None else None,
            "current_path": version.path if version is not None else None,
            "current_created_at": version.created_at if version is not None else None,
        }
        return row

    _PAGE_FALLBACK_SORT_KEYS = {
        "name": lambda row: (row["name"], row["id"]),
        "type": lambda row: (row["type"], row["name"], row["id"]),
        "modified": lambda row: (row["updated_at"], row["name"], row["id"]),
    }

    def _paged_rows_from_document(
        self,
        *,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        tag_op: str = "and",
        type: str | None = None,
        asset_id: str | None = None,
        asset_ids: list[str] | tuple[str, ...] | None = None,
        include_trashed: bool = False,
        trashed_only: bool = False,
        order_by: str | None = None,
        limit: int,
        offset: int,
        after: tuple[str, str] | None,
    ) -> list[dict]:
        """Serve one page from the document (index unavailable/in-batch)."""
        rows = self._paged_fallback_rows(
            text=text,
            stage=stage,
            tags=tags,
            tag_op=tag_op,
            type=type,
            asset_id=asset_id,
            asset_ids=asset_ids,
            include_trashed=include_trashed,
            trashed_only=trashed_only,
        )
        order = order_by or "name"
        if order == "name_desc":
            # Stable two-pass sort: (name DESC, id ASC), matching the SQL
            # ORDER BY a.name DESC, a.id tail.
            rows = sorted(rows, key=lambda row: row["id"])
            rows = sorted(rows, key=lambda row: row["name"], reverse=True)
        elif order in ("stage", "size", "version"):
            def sort_key(row, _order=order):
                value = row.get(
                    {
                        "stage": "current_stage",
                        "size": "current_size_bytes",
                        "version": "current_version_number",
                    }[_order]
                )
                # SQLite ASC sorts NULLs FIRST — the fallback must interleave
                # identically or a mid-refresh gate flip would reorder rows.
                return (
                    0 if value is None else 1,
                    value if value is not None else "",
                    row["name"],
                    row["id"],
                )

            rows = sorted(rows, key=sort_key)
        else:
            rows = sorted(
                rows, key=self._PAGE_FALLBACK_SORT_KEYS.get(order, self._PAGE_FALLBACK_SORT_KEYS["name"])
            )
        if after is not None and order in (None, "name"):
            cursor_name, cursor_id = str(after[0]), str(after[1])
            rows = [
                row
                for row in rows
                if row["name"] > cursor_name
                or (row["name"] == cursor_name and row["id"] > cursor_id)
            ]
        start = max(0, int(offset))
        return rows[start : start + max(0, int(limit))]

    def rebase_artifact_paths(self) -> bool:
        """Rewrite managed version paths after a save-as relocation.

        Version paths are stored relative to the project dir and include the
        ``<name>.artifacts/`` prefix, which changes when the project file is
        saved under a different name (the artifacts dir derives its name from
        it). Rewrites the prefix to the CURRENT artifacts dir name and
        persists; returns True when anything changed. Only the first path
        segment is touched — payload file names and stage/asset/version
        nesting are preserved.
        """
        current = artifact_dir_for(self.project_path).name
        changed = False

        def _rewrite(raw: str | None) -> str | None:
            if not raw:
                return None
            posix = Path(str(raw)).as_posix()
            head, sep, rest = posix.partition("/")
            if sep and head.endswith(".artifacts") and head != current:
                return f"{current}/{rest}"
            return None

        for version in self.document.versions:
            if not version.managed:
                continue
            rewritten = _rewrite(version.path)
            if rewritten is not None:
                version.path = rewritten
                changed = True
            trash = version.metadata.get("trash")
            if isinstance(trash, dict):
                original = _rewrite(trash.get("original_path"))
                if original is not None:
                    trash["original_path"] = original
                    changed = True
        for model_version in self.document.model_versions:
            rewritten = _rewrite(getattr(model_version, "artifact_uri", "") or "")
            if rewritten is not None:
                model_version.artifact_uri = rewritten
                changed = True
        if changed:
            self._save()  # bulk path-rewrite: full reconcile by design
        return changed

    # -- legacy migration ---------------------------------------------------------

    def migrate_legacy_resources(self, resources: Iterable[Any]):
        """Project legacy ResourceItems into catalog assets (ADR 0056, D2).

        Deterministic and idempotent; legacy resource ids are reused as asset
        ids so existing references keep resolving. Pure metadata projection —
        no files are copied.
        """
        from paleo_workbench.catalog.migration import migrate_resources

        # Document projection + save under the lock (#517).
        with self._lock:
            report = migrate_resources(list(resources), self.project_path, self.document)
            if report.migrated_count:
                # Migration mutates the document lists directly (it is a pure
                # document projection), so drop the maintained indexes.
                self._invalidate_maps()
                self._save()
            return report


# -- lazy-open warm guards (#1212) ---------------------------------------------
#
# Every DataCatalogService method that inherently needs the FULL document
# (mutators, tag/model registry access, lineage chains, GC/audit/integrity,
# manifest export, index maintenance) is wrapped to materialize the document
# first via ``require_warm()``. For eagerly-opened services (``_warm`` is True
# from construction) the wrapper is a no-op flag check, so behavior outside
# lazy open is byte-identical. Hot per-entity/per-page reads are deliberately
# NOT wrapped — they serve from the canonical store pre-warm (see the lazy
# hot-read section above).

_WARM_REQUIRED_METHODS = (
    # session/maintenance
    "sweep_temp_on_open",
    "export_manifest",
    "ensure_index_ready",
    "rebuild_index",
    "plan_gc",
    "sweep_gc",
    "cleanup_working_copies",
    "find_missing_sources",
    "verify_integrity",
    "audit",
    "rebase_artifact_paths",
    "migrate_legacy_resources",
    # registration / lifecycle mutators
    "register_version",
    "register_intermediate",
    "register_output",
    "register_result_asset",
    "register_derived_store",
    "import_raw",
    "link_external",
    "materialize_external",
    "relink_external_source",
    "create_working_copy",
    "commit_working_copy",
    "create_derived",
    "register_run",
    "update_run_status",
    "update_asset_metadata",
    "trash_version",
    "trash_asset",
    "restore_version",
    "restore_asset",
    "purge_trashed",
    "promote_version",
    "promote_asset",
    # model registry (full-list scans of small collections)
    "register_model",
    "register_model_version",
    "get_model",
    "get_model_version",
    "get_model_version_by_id",
    "list_models",
    "list_model_versions",
    "promote_model",
    "find_production_model",
    # lineage full-graph walks
    "get_lineage_chain",
    "lineage_summaries",
    # tags (mutators + document-list reads)
    "add_tag",
    "add_tags",
    "remove_tag",
    "rename_tag",
    "merge_tags",
    "create_tag",
    "bulk_add_tag",
    "bulk_remove_tag",
    "tag_ids_for_asset",
    "tag_usage",
    "search_tags",
    "delete_unused_tag",
    "prune_unused_tags",
    "list_tags",
    "find_assets_by_tag",
    "find_versions_by_tag",
    # working-copy lifecycle (registry + document lookups)
    "list_working_copies",
    "working_copy_state",
    "discard_working_copy",
    "recover_working_copies",
    "repair_ghost_runs",
)


def _apply_warm_guards() -> None:
    import functools

    for name in _WARM_REQUIRED_METHODS:
        method = getattr(DataCatalogService, name, None)
        if method is None:
            raise RuntimeError(
                f"warm-guard list references missing method {name!r}; "
                "the list must track the class surface"
            )

        @functools.wraps(method)
        def wrapper(self, *args, _method=method, **kwargs):
            self._require_warm()
            return _method(self, *args, **kwargs)

        setattr(DataCatalogService, name, wrapper)


_apply_warm_guards()
