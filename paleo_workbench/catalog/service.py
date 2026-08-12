"""DataCatalogService — the single write entry point for data lifecycle (ADR 0056).

UI and business code must go through this service instead of appending to
``project.resources`` or hand-editing artifact files. The service hides file
layout, hashing, transactions, canonical persistence, and the SQLite index
behind a small stable API.

Invariants enforced:

- Managed RAW versions are immutable: payloads are placed atomically and
  marked read-only; committing over an existing version id raises
  :class:`ImmutableVersionError`.
- Every committed DataVersion is immutable; change produces a new version.
- Checksum mismatches are reported, never silently adopted.
- The canonical store (``metadata/catalog.json``) is the source of truth; the
  SQLite index is rebuilt whenever it is missing, stale, or corrupt.

The API is synchronous and IO-bound; UI integration should wrap calls in a
worker thread (all state lives in this object, no globals).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Iterable

from paleo_workbench.catalog import queries as _queries
from paleo_workbench.catalog import tags as _tags
from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.db import CatalogIndex
from paleo_workbench.catalog.gc import (
    GcReport,
    cleanup_working_copies as _gc_cleanup_working_copies,
    plan_gc as _gc_plan,
    sweep_gc as _gc_sweep,
)
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
    is_cas_path,
    place_managed_file,
    purge_trashed_payload,
    restore_payload as _restore_trashed_payload,
    trash_dir_for as _trash_dir_for,
    trash_payload as _move_to_trash,
)
from paleo_workbench.catalog.store import CatalogStore
from paleo_workbench.project.models import _now_iso
from paleo_workbench.project.paths import artifact_dir_for


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
        # Maintained id→object indexes (P4): every document list mutation goes
        # through ``_add_*`` / ``_remove_*`` so lookups stay O(1) instead of
        # linear scans. ``None`` = not yet built (built lazily from the
        # document on first use). A lookup miss rebuilds the maps from the
        # document as a self-healing safety net, so a missed maintenance site
        # can never return a wrong *negative* answer (only rebuild cost).
        self._asset_by_id: dict[str, DataAsset] | None = None
        self._version_by_id: dict[str, DataVersion] | None = None
        self._run_by_id: dict[str, DataRun] | None = None
        self._versions_by_asset: dict[str, list[DataVersion]] | None = None
        self._children_by_parent: dict[str, list[DataVersion]] | None = None
        self._assets_by_legacy_id: dict[str, DataAsset] | None = None

    # -- maintained indexes -------------------------------------------------

    def _invalidate_maps(self) -> None:
        """Drop the cached indexes; they rebuild lazily on next use."""
        self._asset_by_id = None
        self._version_by_id = None
        self._run_by_id = None
        self._versions_by_asset = None
        self._children_by_parent = None
        self._assets_by_legacy_id = None

    def _ensure_maps(self) -> None:
        """Build the id→object indexes from the document (idempotent)."""
        if self._asset_by_id is not None:
            return
        self._asset_by_id = {a.id: a for a in self.document.assets}
        self._version_by_id = {v.id: v for v in self.document.versions}
        self._run_by_id = {r.id: r for r in self.document.runs}
        versions_by_asset: dict[str, list[DataVersion]] = {}
        children: dict[str, list[DataVersion]] = {}
        for version in self.document.versions:
            versions_by_asset.setdefault(version.asset_id, []).append(version)
            for pid in version.parent_version_ids:
                children.setdefault(pid, []).append(version)
        self._versions_by_asset = versions_by_asset
        self._children_by_parent = children
        # Legacy-bridge resolution order mirrors ``_find_asset_by_legacy_id``:
        # an asset whose *id* equals the legacy id wins; otherwise the first
        # asset bridged via ``legacy_resource_id`` (first-wins via setdefault).
        legacy: dict[str, DataAsset] = {}
        for asset in self.document.assets:
            legacy[asset.id] = asset
        for asset in self.document.assets:
            if asset.legacy_resource_id is not None:
                legacy.setdefault(asset.legacy_resource_id, asset)
        self._assets_by_legacy_id = legacy

    def _maps_consistent(self) -> bool:
        """Debug/self-check: cached indexes match the document exactly."""
        if self._asset_by_id is None:
            self._ensure_maps()
        if len(self._asset_by_id) != len(self.document.assets):
            return False
        if len(self._version_by_id) != len(self.document.versions):
            return False
        if len(self._run_by_id) != len(self.document.runs):
            return False
        for asset in self.document.assets:
            if self._asset_by_id.get(asset.id) is not asset:
                return False
        for version in self.document.versions:
            if self._version_by_id.get(version.id) is not version:
                return False
            if self._versions_by_asset.get(version.asset_id) is None:
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
        if asset in self.document.assets:
            self.document.assets.remove(asset)
        if self._asset_by_id is not None:
            self._asset_by_id.pop(asset.id, None)
        if self._assets_by_legacy_id is not None:
            # Removing the (first-wins) claimant must reveal the next claimant;
            # rebuild this small index from the remaining assets. A live
            # asset takes the bridge over a trashed one (I2).
            legacy: dict[str, DataAsset] = {}
            for a in self.document.assets:
                legacy[a.id] = a
            for a in sorted(
                self.document.assets, key=lambda x: int(bool(x.trashed))
            ):
                if a.legacy_resource_id is not None:
                    legacy.setdefault(a.legacy_resource_id, a)
            self._assets_by_legacy_id = legacy

    def _add_version(self, version: DataVersion) -> None:
        self.document.versions.append(version)
        if self._version_by_id is not None:
            self._version_by_id[version.id] = version
            self._versions_by_asset.setdefault(version.asset_id, []).append(version)
            for pid in version.parent_version_ids:
                self._children_by_parent.setdefault(pid, []).append(version)

    def _remove_version(self, version: DataVersion) -> None:
        if version in self.document.versions:
            self.document.versions.remove(version)
        if self._version_by_id is not None:
            self._version_by_id.pop(version.id, None)
            bucket = self._versions_by_asset.get(version.asset_id)
            if bucket is not None and version in bucket:
                bucket.remove(version)
            for pid in version.parent_version_ids:
                children = self._children_by_parent.get(pid)
                if children is not None and version in children:
                    children.remove(version)

    def _add_run(self, run: DataRun) -> None:
        self.document.runs.append(run)
        if self._run_by_id is not None:
            self._run_by_id[run.id] = run

    def _remove_run(self, run: DataRun) -> None:
        if run in self.document.runs:
            self.document.runs.remove(run)
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
        ensure_index: bool = True,
        sweep_temp: bool = True,
    ) -> "DataCatalogService":
        """Open (or initialize) the catalog for *project_path*.

        A missing, stale, or corrupt SQLite index is rebuilt from the
        canonical store when ``ensure_index`` is true.  Project-session open
        may set it false because all catalog reads have a canonical in-memory
        fallback; the next write rebuilds/synchronizes the disposable index.
        ``sweep_temp`` is likewise optional session maintenance, never a
        prerequisite for canonical catalog availability.
        """
        project_path = Path(project_path)
        store = CatalogStore(project_path)
        document = store.load()
        index = CatalogIndex(project_path)
        service = cls(project_path, document, store, index)
        if ensure_index:
            service._ensure_index_fresh()
        if sweep_temp:
            service._sweep_temp_on_open()
        return service

    def _sweep_temp_on_open(self) -> None:
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
        try:
            self._index.close()
        except Exception:
            pass

    # -- persistence --------------------------------------------------------

    def _save(self) -> None:
        """Persist canonical document and sync the index.

        The revision only advances if the canonical save succeeds, so a
        failed save leaves no half-bumped state.
        """
        with self._lock:
            self.document.catalog_revision += 1
            try:
                self._store.save(self.document)
            except Exception:
                self.document.catalog_revision -= 1
                raise
            self._sync_index_best_effort()

    def _sync_index_best_effort(self) -> None:
        try:
            self._index.sync(self.document)
        except Exception:
            try:
                self._index.reset()
                self._index.rebuild(self.document)
            except Exception:
                # The index is a cache; canonical truth is already saved.
                pass

    def _ensure_index_fresh(self) -> None:
        try:
            if self._index.is_fresh(self.document):
                # Record the row snapshot so the first save of this process
                # syncs incrementally instead of a full rebuild.
                self._index.prime(self.document)
                return
            self._index.rebuild(self.document)
        except Exception:
            try:
                self._index.reset()
                self._index.rebuild(self.document)
            except Exception:
                pass

    def ensure_index_ready(self) -> None:
        """Synchronously rebuild/prime the disposable index on explicit demand.

        Most catalogue operations can use their canonical-document fallback,
        so this method is intentionally opt-in for session startup.  It is
        public to give UI/controller code an honest point at which to request
        index readiness without making SQLite authoritative.
        """
        self._ensure_index_fresh()

    def rebuild_index(self) -> None:
        """Force a full index rebuild from the canonical store."""
        self._index.reset()
        self._index.rebuild(self.document)

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
        self._ensure_maps()
        asset = self._asset_by_id.get(asset_id)
        if asset is not None:
            return asset
        # Safety net: a missed maintenance site (or a stale map) rebuilds from
        # the document, so an unknown id is genuinely unknown before raising.
        self._invalidate_maps()
        self._ensure_maps()
        asset = self._asset_by_id.get(asset_id)
        if asset is None:
            raise CatalogError(f"Unknown asset: {asset_id}")
        return asset

    def _version_or_raise(self, version_id: str) -> DataVersion:
        self._ensure_maps()
        version = self._version_by_id.get(version_id)
        if version is not None:
            return version
        self._invalidate_maps()
        self._ensure_maps()
        version = self._version_by_id.get(version_id)
        if version is None:
            raise CatalogError(f"Unknown version: {version_id}")
        return version

    def _asset_by_legacy_id(self, legacy_resource_id: str) -> DataAsset | None:
        """Stable legacy-bridge resolution (id match wins, then first bridge)."""
        self._ensure_maps()
        return self._assets_by_legacy_id.get(legacy_resource_id)

    def _live_asset_by_legacy_id(self, legacy_resource_id: str) -> DataAsset | None:
        """Like :meth:`_asset_by_legacy_id` but ignores trashed assets.

        A trashed asset still holds its legacy id; import-after-trash must be
        able to re-bridge a fresh asset instead of dead-ending on the trashed
        one (review finding I2).
        """
        self._ensure_maps()
        asset = self._assets_by_legacy_id.get(legacy_resource_id)
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

    def get_asset(self, asset_id: str) -> DataAsset:
        return self._asset_or_raise(asset_id)

    def get_version(self, version_id: str) -> DataVersion:
        return self._version_or_raise(version_id)

    def get_run(self, run_id: str) -> DataRun:
        self._ensure_maps()
        run = self._run_by_id.get(run_id)
        if run is not None:
            return run
        self._invalidate_maps()
        self._ensure_maps()
        run = self._run_by_id.get(run_id)
        if run is None:
            raise CatalogError(f"Unknown run: {run_id}")
        return run

    def list_assets(self, include_trashed: bool = False) -> list[DataAsset]:
        """List assets; trashed (soft-deleted) assets are hidden by default."""
        if include_trashed:
            return list(self.document.assets)
        return [asset for asset in self.document.assets if not asset.trashed]

    def get_trashed_assets(self) -> list[DataAsset]:
        """Assets currently in the trash (tombstoned, recoverable)."""
        return [asset for asset in self.document.assets if asset.trashed]

    def list_runs(self) -> list[DataRun]:
        return list(self.document.runs)

    def list_versions(self, asset_id: str) -> list[DataVersion]:
        self._ensure_maps()
        versions = list(self._versions_by_asset.get(asset_id, ()))
        return sorted(versions, key=lambda v: v.version_number)

    def resolve_path(self, version: DataVersion) -> Path:
        """Runtime absolute path for a version's payload."""
        if version.managed:
            project_dir = self.project_path.expanduser().resolve().parent
            return project_dir / version.path
        return Path(version.path)

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
                try:
                    payload.unlink()
                except OSError:
                    pass
                # Prune the now-empty version/asset directories.
                for directory in (payload.parent, payload.parent.parent):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

    # -- version registration ------------------------------------------------

    def _next_version_number(self, asset_id: str) -> int:
        self._ensure_maps()
        numbers = [v.version_number for v in self._versions_by_asset.get(asset_id, ())]
        return max(numbers, default=0) + 1

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
        """
        asset = self._asset_or_raise(asset_id)
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CatalogError(f"Source file not found: {source_path}")
        run: DataRun | None = None
        if run_id is not None:
            run = self.get_run(run_id)  # raises before any payload is placed
        previous_current = asset.current_version_id
        version, payload = self._build_version(
            asset, source_path, stage,
            version_id=version_id,
            parent_version_ids=list(parent_version_ids),
            run_id=run_id, metadata=metadata, move=move,
            known_sha256=known_sha256,
            register_blob=_register_blob,
        )
        self._add_version(version)
        asset.current_version_id = version.id
        run_output_added = False
        if run is not None and version.id not in run.output_version_ids:
            run.output_version_ids.append(version.id)
            run_output_added = True
        try:
            self._save()
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
        """Create a result asset and register its version in ONE locked,
        atomic operation (thread-safe: workers must not mutate
        ``document.assets`` directly — this is the only sanctioned path).

        On failure the newly-created asset is rolled back from the document,
        so no half-registered asset survives. Returns the committed version.
        """
        with self._lock:
            asset = self._new_asset(name, type, format, asset_metadata)
            self._add_asset(asset)
            try:
                return self.register_version(
                    asset.id,
                    source_path,
                    stage,
                    run_id=run_id,
                    metadata=version_metadata,
                )
            except Exception:
                self._remove_asset(asset)
                raise

    # -- import / link / materialize -----------------------------------------

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
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CatalogError(f"Source file not found: {source_path}")
        asset: DataAsset | None = None
        if asset_id is not None:
            target = self._asset_or_raise(asset_id)
        else:
            target = self._new_asset(
                name or source_path.name, type, format, metadata
            )
            if (
                _legacy_resource_id is not None
                and target.legacy_resource_id is None
                and self._live_asset_by_legacy_id(_legacy_resource_id) is None
            ):
                target.legacy_resource_id = _legacy_resource_id
            asset = target
            self._add_asset(target)
        try:
            return self.register_version(
                target.id, source_path, DataStage.RAW, metadata=metadata,
                known_sha256=known_sha256, _register_blob=True,
            )
        except Exception:
            if asset is not None and asset in self.document.assets:
                self._remove_asset(asset)
            raise

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
        asset = self._new_asset(name or path.name, type, format, metadata)
        asset.metadata["external"] = True
        if (
            _legacy_resource_id is not None
            and self._asset_by_legacy_id(_legacy_resource_id) is None
        ):
            asset.legacy_resource_id = _legacy_resource_id
        version = DataVersion(
            asset_id=asset.id,
            version_number=1,
            stage=DataStage.RAW,
            managed=False,
            path=path.resolve().as_posix(),
            source_uri=path.resolve().as_posix(),
            format=format or "",
            size_bytes=path.stat().st_size,
        )
        asset.current_version_id = version.id
        self._add_asset(asset)
        self._add_version(version)
        try:
            self._save()
        except Exception:
            self._rollback(assets=[asset], versions=[version])
            raise
        return version

    def materialize_external(self, version_id: str) -> DataVersion:
        """Promote an external link to a managed immutable RAW snapshot."""
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
        )

    # -- working copies / derived --------------------------------------------

    def create_working_copy(self, version_id: str) -> Path:
        """Materialize a mutable working copy of a committed version.

        Always a real copy (never a hardlink), so editing it cannot touch the
        managed original.
        """
        version = self._version_or_raise(version_id)
        payload = self.resolve_path(version)
        if not payload.is_file():
            raise CatalogError(f"Payload not available: {payload}")
        return _place_working_copy(self.project_path, payload, version.id)

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
        """
        working_path = Path(working_path)
        if parent_version_ids is None:
            candidate = working_path.parent.name
            parent_version_ids = (
                [candidate]
                if any(v.id == candidate for v in self.document.versions)
                else []
            )
        if asset_id is None:
            asset = self._new_asset(name or working_path.stem, None, None, metadata)
            self._add_asset(asset)
            try:
                return self.register_version(
                    asset.id, working_path, stage,
                    parent_version_ids=parent_version_ids,
                    run_id=run_id, metadata=metadata, move=True,
                    _restore_payload_to=working_path,
                )
            except Exception:
                if asset in self.document.assets:
                    self._remove_asset(asset)
                raise
        return self.register_version(
            asset_id, working_path, stage,
            parent_version_ids=parent_version_ids,
            run_id=run_id, metadata=metadata, move=True,
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
        run: DataRun | None = None
        if operation is not None:
            run = DataRun(
                operation=operation,
                input_version_ids=[p.id for p in parents],
                parameters=dict(parameters or {}),
                generator=generator,
            )
        version, payload = self._build_version(
            asset, source_path, DataStage.DERIVED,
            version_id=None,
            parent_version_ids=[p.id for p in parents],
            run_id=run.id if run else None, metadata=metadata, move=False,
        )
        if run is not None:
            run.output_version_ids = [version.id]
        self._add_asset(asset)
        self._add_version(version)
        asset.current_version_id = version.id
        if run is not None:
            self._add_run(run)
        try:
            self._save()
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
            self._save()
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
        """
        with self._lock:
            run = self.get_run(run_id)
            run.status = status
            if extra_parameters:
                run.parameters.update(extra_parameters)
            self._save()
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
        """Register (or update) a logical model. Idempotent on ``model_id``:
        re-registering refreshes name/capability/provider/status/metadata so
        defaults can be repaired without duplicating entries.

        ``force_status`` (default False) protects an existing model from being
        silently downgraded by a seed/defaults call: when the model already
        exists and ``force_status`` is False, its ``status`` and ``metadata``
        are preserved (an explicit promote must never be clobbered by
        ``ensure_default_models`` — review finding C2). Pass True only when
        the caller deliberately changes status (e.g. promote/demote)."""
        if not model_id or not model_name:
            raise CatalogError("register_model requires model_id and model_name")
        existing = None
        for model in self.document.models:
            if model.model_id == model_id:
                existing = model
                break
        if existing is not None:
            existing.model_name = model_name
            existing.model_type = model_type or existing.model_type
            existing.capability = capability
            existing.provider = provider or existing.provider
            if force_status:
                existing.status = status
                existing.metadata = dict(metadata or {})
            if provenance:
                existing.provenance.update(provenance)
            self._save()
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
            self._save()
        except Exception:
            if model in self.document.models:
                self.document.models.remove(model)
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
        status: str = "production",
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ModelVersion:
        """Register a concrete model version for an existing :class:`Model`.

        When ``checksum`` is omitted and ``artifact_uri`` points at a readable
        file, the checksum is computed from it (streaming). A duplicate
        ``(model_id, model_version)`` pair raises :class:`CatalogError`.
        """
        self._model_or_raise(model_id)  # validate the model exists
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
            status=status,
            metadata=dict(metadata or {}),
            provenance=dict(provenance or {}),
        )
        self.document.model_versions.append(version)
        try:
            self._save()
        except Exception:
            if version in self.document.model_versions:
                self.document.model_versions.remove(version)
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
            model.status = "production"
            version.status = "production"
            version.demo_only = False
            self._save()
            return version

    def find_production_model(self, capability: str) -> ModelVersion | None:
        """Return the newest production :class:`ModelVersion` for *capability*.

        A version qualifies only when BOTH its model and the version are
        ``status == "production"`` and the version is not ``demo_only``.
        Returns None when no production model exists — callers must surface an
        honest "no production model" state instead of running a mock.
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
            if best is None or version.created_at > best.created_at:
                best = version
        return best

    # -- lineage ---------------------------------------------------------------

    def get_lineage(self, version_id: str) -> dict[str, Any]:
        """Parents, children, and the producing run for a version."""
        version = self._version_or_raise(version_id)
        self._ensure_maps()
        parents = [
            self._version_by_id[pid]
            for pid in version.parent_version_ids
            if pid in self._version_by_id
        ]
        children = list(self._children_by_parent.get(version_id, ()))
        run = None
        if version.run_id is not None:
            try:
                run = self.get_run(version.run_id)
            except CatalogError:
                run = None
        return {"version": version, "parents": parents, "children": children, "run": run}

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
        self._ensure_maps()
        active = [
            v
            for v in self._versions_by_asset.get(asset.id, ())
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
            try:
                self._save()
            except Exception:
                self._rollback_tombstone(version, asset, previous_current)
                raise
            if self._move_payload_to_trash(version):
                try:
                    self._save()
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
            try:
                self._save()
            except Exception:
                for version in versions:
                    self._rollback_tombstone(version, asset, previous_current)
                asset.trashed = False
                asset.trashed_at = None
                raise
            moved = [v for v in versions if self._move_payload_to_trash(v)]
            if moved:
                try:
                    self._save()
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
            self._untombstone_version(version)
            if asset.current_version_id is None or not any(
                v.id == asset.current_version_id and not v.trashed
                for v in self.document.versions
            ):
                asset.current_version_id = version.id
            try:
                self._save()
            except Exception:
                self._rollback_untombstone(version, asset, previous_current)
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
            for version in versions:
                if version.trashed:
                    self._untombstone_version(version)
            asset.trashed = False
            asset.trashed_at = None
            if asset.current_version_id is None and versions:
                active = [v for v in versions if not v.trashed]
                asset.current_version_id = active[-1].id if active else None
            try:
                self._save()
            except Exception:
                asset.trashed = previous_trashed
                asset.trashed_at = previous_trashed_at
                for version in versions:
                    self._rollback_untombstone(version, asset, previous_current)
                raise
            return asset

    def _rollback_untombstone(
        self, version: DataVersion, asset: DataAsset, previous_current: str | None
    ) -> None:
        """Re-apply a tombstone after a failed restore save (payload moved back
        into ``trash/``)."""
        reason = None
        if version.metadata.get("trash"):
            reason = version.metadata["trash"].get("reason")
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
            for version in trashed_versions:
                if version.managed:
                    shared = (
                        version.sha256 is not None
                        and version.sha256 in surviving_digests
                    )
                    purge_trashed_payload(
                        self.project_path, self.resolve_path(version), shared=shared
                    )
                self._remove_version(version)
            # An asset is removed only when NONE of its versions survives the
            # purge. restore_version() can untrash a single version of a
            # trashed asset; deleting the asset then would orphan that live
            # version (ghost version whose asset_id no longer exists — review
            # finding C3). Such assets are kept and un-trashed.
            surviving_asset_ids = {
                v.asset_id for v in self.document.versions if not v.trashed
            }
            for asset in trashed_assets:
                if asset.id in surviving_asset_ids:
                    asset.trashed = False
                    asset.trashed_at = None
                    asset.metadata.pop("trash", None)
                    continue
                self._remove_asset(asset)
            for vid in removed_version_tags:
                self.document.version_tags.pop(vid, None)
            for aid in removed_asset_tags:
                self.document.asset_tags.pop(aid, None)
            try:
                self._save()
            except Exception:
                for version in trashed_versions:
                    self._add_version(version)
                for asset in trashed_assets:
                    # Only re-add assets actually removed (un-trashed assets
                    # stayed in the document the whole time).
                    if asset not in self.document.assets:
                        self._add_asset(asset)
                self.document.version_tags.update(removed_version_tags)
                self.document.asset_tags.update(removed_asset_tags)
                raise
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
        self._add_version(version)
        self._add_run(run)
        asset.current_version_id = version.id
        try:
            self._save()
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

    def verify_integrity(self, version_id: str | None = None) -> IntegrityReport:
        """Re-hash payloads and compare against recorded SHA-256.

        Reports only; a mismatch never updates the catalog. Hashing streams in
        chunks; wrap in a worker thread for large batches in UI contexts.
        Trashed versions are skipped (their payloads live in ``trash/``).

        Delegates to :func:`paleo_workbench.catalog.queries.verify_integrity`.
        """
        return _queries.verify_integrity(self, version_id=version_id)

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
        """
        with self._lock:
            if asset_id is None and version_id is None:
                raise CatalogError("add_tags requires asset_id or version_id")
            if asset_id is not None:
                self._asset_or_raise(asset_id)
            if version_id is not None:
                self._version_or_raise(version_id)

            # A deep copy is bounded to this explicit metadata batch and only
            # retained until the single canonical write finishes.  It is never
            # on normal project-save/open paths.
            before_tags = list(self.document.tags)
            before_asset_tags = {
                key: list(value) for key, value in self.document.asset_tags.items()
            }
            before_version_tags = {
                key: list(value)
                for key, value in self.document.version_tags.items()
            }
            result: list[Tag] = []
            changed = False
            try:
                for name in names:
                    if not str(name or "").strip():
                        continue
                    normalized = self._normalize_tag_for_batch(str(name))
                    tag = self._tag_by_normalized_name(normalized)
                    if tag is None:
                        tag = Tag(
                            name=normalized,
                            display_name=" ".join(str(name).split()),
                        )
                        self.document.tags.append(tag)
                        changed = True
                    if asset_id is not None:
                        ids = self.document.asset_tags.setdefault(asset_id, [])
                        if tag.id not in ids:
                            ids.append(tag.id)
                            changed = True
                    if version_id is not None:
                        ids = self.document.version_tags.setdefault(version_id, [])
                        if tag.id not in ids:
                            ids.append(tag.id)
                            changed = True
                    result.append(tag)
                if changed:
                    self._save()
                return result
            except Exception:
                self.document.tags = before_tags
                self.document.asset_tags = before_asset_tags
                self.document.version_tags = before_version_tags
                raise

    def _tag_by_normalized_name(self, normalized: str) -> Tag | None:
        for tag in self.document.tags:
            if tag.name == normalized:
                return tag
        return None

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

    def rename_tag(self, old_name: str, new_name: str) -> Tag:
        """Rename a tag; merges into an existing tag on normalized collision.

        Delegates to :func:`paleo_workbench.catalog.tags.rename_tag`.
        """
        return _tags.rename_tag(self, old_name, new_name)

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
        type: str | None = None,
        include_trashed: bool = False,
    ) -> list[DataAsset]:
        """Filter assets by name substring, stage, tag, and/or type.

        Trashed (soft-deleted) assets are excluded unless ``include_trashed``.

        Delegates to :func:`paleo_workbench.catalog.queries.search_assets`.
        """
        return _queries.search_assets(
            self,
            text=text,
            stage=stage,
            tag=tag,
            type=type,
            include_trashed=include_trashed,
        )

    def _rebase_artifact_paths(self) -> bool:
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
        for version in self.document.versions:
            if not version.managed:
                continue
            head, sep, rest = version.path.partition("/")
            if sep and head.endswith(".artifacts") and head != current:
                version.path = f"{current}/{rest}"
                changed = True
        if changed:
            self._save()
        return changed

    # -- legacy migration ---------------------------------------------------------

    def migrate_legacy_resources(self, resources: Iterable[Any]):
        """Project legacy ResourceItems into catalog assets (ADR 0056, D2).

        Deterministic and idempotent; legacy resource ids are reused as asset
        ids so existing references keep resolving. Pure metadata projection —
        no files are copied.
        """
        from paleo_workbench.catalog.migration import migrate_resources

        report = migrate_resources(list(resources), self.project_path, self.document)
        if report.migrated_count:
            # Migration mutates the document lists directly (it is a pure
            # document projection), so drop the maintained indexes.
            self._invalidate_maps()
            self._save()
        return report
