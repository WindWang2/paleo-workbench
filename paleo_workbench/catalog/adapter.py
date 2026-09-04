"""Core-backed :class:`CatalogPort` adapter.

Wraps :class:`~paleo_workbench.catalog.service.DataCatalogService` — the single
authoritative Data Catalog implementation (ADR 0056) — behind the thin
:class:`~paleo_workbench.catalog.port.CatalogPort` protocol that business
modules (pipeline / prediction / mapping / export / import) consume via
:func:`paleo_workbench.catalog.runtime.get_catalog`.

This is the ONLY production runtime backend. The in-memory reference backend
lives in ``tests/fakes`` and is never used outside tests.

Mapping notes:

- A run's ``domain_task_id`` / ``input_snapshot_hash`` have no dedicated field
  on the Core ``DataRun``; they are stored under reserved ``parameters`` keys
  (``_domain_task_id`` / ``_input_snapshot_hash`` / ``_finished_at``).
- Producing registrations (intermediate / output / derived) place the payload
  into managed storage via the Core service, so every committed version gets
  an immutable copy + SHA-256, and lineage is expressed through the Core's
  ``parent_version_ids`` / run input-output ids (no separate edge store).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.catalog.checksum import sha256_file_or_none
from paleo_workbench.catalog.db import DirtySet
from paleo_workbench.catalog.models import (
    CatalogError,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
)
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.types import (
    DataRunRef,
    DataVersionRef,
    IntegrityStatus,
    LineageEdge,
    _now_iso,
)

_DOMAIN_TASK_KEY = "_domain_task_id"
_SNAPSHOT_HASH_KEY = "_input_snapshot_hash"
_FINISHED_AT_KEY = "_finished_at"

_STATUS_TO_INTEGRITY = {
    "verified": IntegrityStatus.VERIFIED,
    "modified": IntegrityStatus.MODIFIED,
    "missing": IntegrityStatus.MISSING,
    "unknown": IntegrityStatus.UNKNOWN,
}


class CoreCatalogAdapter:
    """Adapt :class:`DataCatalogService` to the :class:`CatalogPort` protocol."""

    def __init__(self, service: DataCatalogService) -> None:
        self._service = service

    @property
    def service(self) -> DataCatalogService:
        """The wrapped Core service (for UI operations beyond the port)."""
        return self._service

    def batch_save(self) -> "_BatchSave":
        """Merge many mutator calls into ONE canonical write (C38 / audit #849-3).

        Bulk registration loops (folder import) wrap their per-file calls in
        this context so the O(N²) full-document rewrite + fsync happens once
        instead of once per registered input. See
        :meth:`DataCatalogService.batch_save`.
        """
        return self._service.batch_save()

    # ------------------------------------------------------------- conversions
    def _tag_by_id(self) -> dict:
        """Tag id→Tag map cached per (document, revision, mutation serial).

        ``_version_ref`` runs once per listed version; rebuilding the map
        there made ``list_versions`` O(versions × tags). The cache invalidates
        on any save (revision bump / serial bump) or document swap (reopen).
        The mutation serial covers saves deferred inside batch_save, where
        the revision now stays put until commit (#1139).
        """
        document = self._service.document
        serial = getattr(self._service, "_mutation_serial", None)
        cache = getattr(self, "_tag_map_cache", None)
        if (
            cache is not None
            and cache[0] is document
            and cache[1] == document.catalog_revision
            and cache[2] == serial
        ):
            return cache[3]
        by_id = {t.id: t for t in document.tags}
        self._tag_map_cache = (document, document.catalog_revision, serial, by_id)
        return by_id

    def _tag_names(self, version: DataVersion) -> list[str]:
        tag_ids = self._service.document.version_tags.get(version.id, [])
        by_id = self._tag_by_id()
        return [
            by_id[tid].display_name or by_id[tid].name
            for tid in tag_ids
            if tid in by_id
        ]

    def _asset_for(self, version: DataVersion) -> DataAsset | None:
        return self._service._ensure_maps().asset_by_id.get(version.asset_id)

    def _version_ref(self, version: DataVersion) -> DataVersionRef:
        asset = self._asset_for(version)
        return DataVersionRef(
            asset_id=version.asset_id,
            version_id=version.id,
            name=asset.name if asset else "",
            stage=version.stage,
            path=self._service.resolve_path(version).as_posix(),
            checksum=version.sha256,
            external=not version.managed,
            producing_run_id=version.run_id,
            created_at=version.created_at,
            tags=self._tag_names(version),
            kind=asset.type if asset else "",
            format=version.format,
            legacy_resource_id=asset.legacy_resource_id if asset else None,
            trashed=version.trashed,
        )

    @staticmethod
    def _run_ref(run: DataRun) -> DataRunRef:
        parameters = {
            k: v for k, v in run.parameters.items() if not k.startswith("_")
        }
        return DataRunRef(
            run_id=run.id,
            operation=run.operation,
            input_version_ids=list(run.input_version_ids),
            output_version_ids=list(run.output_version_ids),
            parameters=parameters,
            generator_version=run.generator or None,
            status=run.status,
            started_at=run.created_at,
            finished_at=run.parameters.get(_FINISHED_AT_KEY),
            domain_task_id=run.parameters.get(_DOMAIN_TASK_KEY),
            input_snapshot_hash=run.parameters.get(_SNAPSHOT_HASH_KEY),
        )

    def _find_asset_by_legacy_id(self, legacy_resource_id: str) -> DataAsset | None:
        """Stable legacy-bridge resolution: an asset whose *id* equals the
        legacy id (a migration projection) wins; otherwise the first asset
        explicitly bridged via ``legacy_resource_id``. The bridge is set once
        (first wins), so a resource always resolves to the same asset.
        Uses the service's maintained legacy index (O(1), no scan)."""
        return self._service._asset_by_legacy_id(legacy_resource_id)

    def _domain_task_asset(self, run: DataRun) -> DataAsset | None:
        """Existing asset produced by the SAME domain task + operation.

        A rerun of one domain task must append a version to the asset it
        already produced (superseding the previous tip) instead of spawning a
        new single-version asset whose tip stays "current" and poisons
        freshness selection with a competing selected tip (issue #373 / C15).
        The operation filter keeps distinct domains that share an id
        (e.g. a prediction task id vs the QC key derived from it) apart.
        """
        domain_task_id = run.parameters.get(_DOMAIN_TASK_KEY)
        if not domain_task_id:
            return None
        service = self._service
        maps = service._ensure_maps()
        # Newest version first: the most recent produced asset wins.
        for version in reversed(service.document.versions):
            if not version.run_id:
                continue
            producing = maps.run_by_id.get(version.run_id)
            if (
                producing is None
                or producing.operation != run.operation
                or producing.parameters.get(_DOMAIN_TASK_KEY) != domain_task_id
            ):
                continue
            asset = maps.asset_by_id.get(version.asset_id)
            if asset is not None and not asset.trashed:
                return asset
        return None

    def _bridge_legacy_id(self, version: DataVersion, legacy_resource_id: str | None) -> None:
        """Record the legacy bridge on an idempotent hit when it is missing.

        The bridge id is set ONCE: an asset that already carries a (different)
        legacy id is left alone, and a legacy id already claimed by another
        asset is never re-assigned — so no two assets can ever collide on the
        same bridge key (ghost prevention).
        """
        if legacy_resource_id is None:
            return
        asset = self._asset_for(version)
        if asset is None or asset.legacy_resource_id is not None:
            return
        if self._find_asset_by_legacy_id(legacy_resource_id) is not None:
            return
        self._service._set_legacy_bridge(asset, legacy_resource_id)
        # Dirty-set incremental write (#1138): a scope-less ``_save()`` here
        # forced a full-store reconcile on every idempotent bridge hit.
        self._service._save(
            DirtySet(assets={asset.id: None})
        )

    # ------------------------------------------------------------------ inputs
    def register_input(
        self,
        *,
        name: str,
        path: str,
        checksum: str | None,
        kind: str = "",
        format: str = "",
        external: bool = False,
        tags: list[str] | None = None,
        legacy_resource_id: str | None = None,
    ) -> DataVersionRef:
        service = self._service
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            # Resource paths are project-relative by contract (import_service
            # relativizes files inside the project dir). Resolve against the
            # PROJECT dir — never the process CWD — so in-project imports
            # register correctly regardless of how the app was launched.
            candidate = service.project_path.expanduser().resolve().parent / candidate
        resolved = candidate.resolve().as_posix()
        if checksum is None and not external:
            # Managed RAW needs a checksum for dedup/idempotence + integrity.
            # A caller passing a project-relative path cannot hash it against
            # the CWD, so hash the correctly-resolved file once here (matches
            # the lifecycle helper's behavior for absolute paths).
            resolved_path = Path(resolved)
            if resolved_path.is_file():
                checksum = sha256_file_or_none(resolved_path)

        # Stable legacy-bridge asset: once a resource id maps to an asset it
        # always maps to that SAME asset (never a phantom duplicate). A
        # TRASHED bridged asset is treated as unbridged so re-importing the
        # file re-registers it fresh (review finding I2: import after trash
        # must not silently dead-bridge).
        bridged_asset = None
        if legacy_resource_id is not None:
            candidate = self._find_asset_by_legacy_id(legacy_resource_id)
            if candidate is not None and not candidate.trashed:
                bridged_asset = candidate

        if external:
            # Idempotence: same external path already linked (index-backed
            # when the SQLite index is healthy, scan fallback otherwise).
            existing = self._find_external_by_path(resolved)
            if existing is not None:
                self._bridge_legacy_id(existing, legacy_resource_id)
                return self._version_ref(existing)
            # Same legacy asset, same external link → return its current version
            # (reopening a project must not accumulate duplicate links).
            if bridged_asset is not None and bridged_asset.current_version_id is not None:
                current = service.get_version(bridged_asset.current_version_id)
                if not current.managed and current.path == resolved:
                    return self._version_ref(current)
            version = service.link_external(
                resolved,
                name=name,
                type=kind or None,
                format=format or None,
                _legacy_resource_id=legacy_resource_id,
            )
        else:
            # Idempotence: same managed source (path + checksum) already
            # imported returns the existing immutable RAW version. Index-backed
            # dedup (O(log N)) when the index is fresh; linear scan fallback.
            existing = self._find_managed_raw(resolved, checksum)
            if existing is not None:
                self._bridge_legacy_id(existing, legacy_resource_id)
                return self._version_ref(existing)
            if bridged_asset is not None and bridged_asset.current_version_id is not None:
                current = service.get_version(bridged_asset.current_version_id)
                # Decide "unchanged" without a caller-supplied checksum by
                # hashing the file once (cheap when it matches the record).
                effective = checksum
                if effective is None:
                    effective = sha256_file_or_none(resolved)
                if effective is not None and effective == current.sha256:
                    self._bridge_legacy_id(current, legacy_resource_id)
                    return self._version_ref(current)
                # The SAME asset's source changed: register V2 of this asset
                # (parent lineage), never a phantom asset.
                version = service.register_version(
                    bridged_asset.id,
                    resolved,
                    DataStage.RAW,
                    parent_version_ids=[current.id],
                )
                self._bridge_legacy_id(version, legacy_resource_id)
                service.add_tags(tags or [], version_id=version.id)
                return self._version_ref(version)
            version = service.import_raw(
                resolved,
                name=name,
                type=kind or None,
                format=format or None,
                _legacy_resource_id=legacy_resource_id,
                known_sha256=checksum,
            )
        service.add_tags(tags or [], version_id=version.id)
        return self._version_ref(version)

    # ------------------------------------------------------------ dedup helpers
    @staticmethod
    def _is_managed_raw_match(
        version: DataVersion, source_uri: str, checksum: str
    ) -> bool:
        return (
            version.managed
            and version.stage == DataStage.RAW
            and not version.trashed
            and version.source_uri == source_uri
            and version.sha256 == checksum
        )

    def _scan_managed_raw(
        self, source_uri: str, checksum: str | None
    ) -> DataVersion | None:
        """Self-healing document scan (the pre-index dedup path)."""
        for version in self._service.document.versions:
            if self._is_managed_raw_match(version, source_uri, checksum):
                return version
        return None

    def _find_managed_raw(self, source_uri: str, checksum: str | None) -> DataVersion | None:
        """Existing managed RAW version for (path, checksum), or None.

        O(1) via the service's in-memory identity index (#1139): the key is
        looked up in ``managed_raw_by_key`` and validated against the live
        document, so trash/restore/purge of the candidate (state flips the
        add/remove hooks cannot see) can never produce a wrong positive.
        Only an invalidated or missing entry pays the linear scan, which then
        heals the index — bulk imports of distinct files never scan at all.
        """
        service = self._service
        maps = service._ensure_maps()
        if checksum is not None:
            key = (source_uri, checksum)
            vid = maps.managed_raw_by_key.get(key)
            if vid is not None:
                version = maps.version_by_id.get(vid)
                if version is not None and self._is_managed_raw_match(
                    version, source_uri, checksum
                ):
                    return version
            found = self._scan_managed_raw(source_uri, checksum)
            if found is not None:
                maps.managed_raw_by_key[key] = found.id
            else:
                maps.managed_raw_by_key.pop(key, None)
            return found
        return self._scan_managed_raw(source_uri, checksum)

    @staticmethod
    def _is_external_match(version: DataVersion, resolved: str) -> bool:
        return not version.managed and not version.trashed and version.path == resolved

    def _scan_external_by_path(self, resolved: str) -> DataVersion | None:
        for version in self._service.document.versions:
            if self._is_external_match(version, resolved):
                return version
        return None

    def _find_external_by_path(self, resolved: str) -> DataVersion | None:
        """Existing unmanaged version linked at *resolved*, or None.

        O(1) via the service's in-memory identity index (#1139), validated
        against the live document; the scan survives only as the self-healing
        fallback. Trashed versions are never dedup targets: re-importing a
        file after trashing it must not silently resolve to the trashed
        version (review finding I2).
        """
        service = self._service
        maps = service._ensure_maps()
        vid = maps.external_by_path.get(resolved)
        if vid is not None:
            version = maps.version_by_id.get(vid)
            if version is not None and self._is_external_match(version, resolved):
                return version
        found = self._scan_external_by_path(resolved)
        if found is not None:
            maps.external_by_path[resolved] = found.id
        else:
            maps.external_by_path.pop(resolved, None)
        return found

    # ------------------------------------------------------------------- runs
    def begin_run(
        self,
        *,
        operation: str,
        input_version_ids: list[str],
        parameters: dict[str, Any] | None = None,
        generator_version: str | None = None,
        domain_task_id: str | None = None,
        input_snapshot_hash: str | None = None,
    ) -> DataRunRef:
        params = dict(parameters or {})
        if domain_task_id is not None:
            params[_DOMAIN_TASK_KEY] = domain_task_id
        if input_snapshot_hash is not None:
            params[_SNAPSHOT_HASH_KEY] = input_snapshot_hash
        run = self._service.register_run(
            operation,
            input_version_ids=list(input_version_ids),
            parameters=params,
            generator=generator_version or "",
            status="running",
        )
        return self._run_ref(run)

    def complete_run(self, run_id: str, *, status: str = "complete") -> DataRunRef:
        run = self._service.update_run_status(
            run_id, status, extra_parameters={_FINISHED_AT_KEY: _now_iso()}
        )
        return self._run_ref(run)

    # -------------------------------------------------------------- producers
    def _register_produced(
        self,
        run_id: str,
        name: str,
        path: str,
        stage: DataStage,
        kind: str,
        format: str,
        tags: list[str] | None,
        checksum: str | None = None,
        reuse_legacy_id: str | None = None,
    ) -> DataVersionRef:
        service = self._service
        # #930 (re-introduction of #617 via the #517 fix): the previous
        # `with service._lock:` wrapper made register_version's careful
        # lock-free payload copy run UNDER the reentrant outer lock — 120 MiB
        # registrations froze every concurrent catalog call for the whole
        # copy+SHA+fsync window. Structure now mirrors
        # register_result_asset: short locked resolution phase, copy/hash with
        # NO lock, short locked commit phase. The #517 zero-version invariant
        # is preserved because the new asset is only added to the document in
        # the same locked save that commits its version.
        with service._lock:
            run = service.get_run(run_id)
            asset = None
            if reuse_legacy_id:
                ref = self.resolve_legacy_resource(reuse_legacy_id)
                if ref is not None:
                    try:
                        asset = service.get_asset(ref.asset_id)
                    except CatalogError:
                        asset = None
            if asset is None:
                asset = self._domain_task_asset(run)
            created = asset is None
            if created:
                asset = service._new_asset(name, kind or None, format or None, None)
                if (
                    reuse_legacy_id
                    and service._asset_by_legacy_id(reuse_legacy_id) is None
                ):
                    # Bridge the new asset so the NEXT registration with the
                    # same reuse key appends a version instead of spawning an
                    # asset.
                    asset.legacy_resource_id = reuse_legacy_id
            parents = list(run.input_version_ids)

        if not created:
            # Existing asset: register_version already keeps copy+hash outside
            # its own locks and re-validates existence atomically.
            version = service.register_version(
                asset.id,
                path,
                stage,
                parent_version_ids=parents,
                run_id=run.id,
                known_sha256=checksum,
            )
        else:
            # New asset: build the version with no lock held, then commit
            # asset+version+run linkage in one locked save (the
            # register_result_asset pattern — no zero-version window).
            version, payload = service._build_version(
                asset,
                Path(path),
                stage,
                version_id=None,
                parent_version_ids=parents,
                run_id=run.id,
                metadata=None,
                move=False,
                known_sha256=checksum,
            )
            with service._lock:
                run_output_added = False
                service._add_asset(asset)
                try:
                    service._add_version(version)
                    asset.current_version_id = version.id
                    if version.id not in run.output_version_ids:
                        run.output_version_ids.append(version.id)
                        run_output_added = True
                    # Dirty-set incremental write (#1138): asset + version +
                    # run linkage are exactly what this branch mutated — a
                    # scope-less ``_save()`` forced a full-store reconcile on
                    # every produced asset.
                    service._save(
                        DirtySet(
                            assets={asset.id: None},
                            versions={version.id: None},
                            runs={run.id: None},
                        )
                    )
                except Exception:
                    if run_output_added:
                        run.output_version_ids.remove(version.id)
                    if asset in service.document.assets:
                        service._remove_asset(asset)
                    service._rollback(payload=payload)
                    raise
        with service._lock:
            for tag in tags or []:
                if tag:
                    service.add_tag(tag, version_id=version.id)
            return self._version_ref(version)

    def register_intermediate(
        self,
        *,
        run_id: str,
        name: str,
        path: str,
        checksum: str | None = None,
        kind: str = "",
        format: str = "",
        tags: list[str] | None = None,
    ) -> DataVersionRef:
        return self._register_produced(
            run_id, name, path, DataStage.INTERMEDIATE, kind, format, tags,
            checksum=checksum,
        )

    def register_output(
        self,
        *,
        run_id: str,
        name: str,
        path: str,
        checksum: str | None = None,
        kind: str = "",
        format: str = "",
        tags: list[str] | None = None,
        reuse_legacy_id: str | None = None,
    ) -> DataVersionRef:
        return self._register_produced(
            run_id, name, path, DataStage.OUTPUT, kind, format, tags,
            checksum=checksum, reuse_legacy_id=reuse_legacy_id,
        )

    def register_derived(
        self,
        *,
        run_id: str,
        name: str,
        path: str,
        checksum: str | None = None,
        kind: str = "",
        format: str = "",
        tags: list[str] | None = None,
    ) -> DataVersionRef:
        # Directory-backed stores (zarr) are NOT single managed files: they
        # register through the store path (structural fingerprint integrity)
        # instead of the managed-file move. P2 attribute/inference providers
        # rely on this branch.
        from pathlib import Path

        if Path(path).is_dir():
            return self.register_derived_store(
                name=name,
                store_path=path,
                run_id=run_id,
                type=kind or None,
                format=format or "zarr-v3",
            )
        return self._register_produced(
            run_id, name, path, DataStage.DERIVED, kind, format, tags,
            checksum=checksum,
        )

    def register_derived_store(self, *, name, store_path, run_id=None, parent_version_ids=(), type=None, format="zarr-v3", asset_metadata=None, version_metadata=None) -> DataVersionRef:
        """Port-level view of the service's directory-store DERIVED path."""
        version = self._service.register_derived_store(
            name=name,
            store_path=store_path,
            run_id=run_id,
            parent_version_ids=parent_version_ids,
            type=type,
            format=format,
            asset_metadata=asset_metadata,
            version_metadata=version_metadata,
        )
        return self._version_ref(version)

    # --------------------------------------------------------------- lineage
    def attach_lineage(
        self,
        *,
        source_version_id: str,
        target_version_id: str,
        run_id: str | None = None,
    ) -> LineageEdge:
        """Record a lineage edge source → target.

        Appending to ``parent_version_ids`` is a lineage-metadata addition,
        not a payload/version mutation — committed version payloads stay
        immutable. Self-loops are rejected: a version can never be its own
        ancestor.
        """
        if source_version_id == target_version_id:
            raise CatalogError(
                f"Cannot attach lineage from a version to itself: {source_version_id}"
            )
        service = self._service
        # Mutate + save under the lock (#517): the unlocked _append_parent
        # window let a concurrent save persist a torn lineage edge.
        with service._lock:
            target = service.get_version(target_version_id)
            service.get_version(source_version_id)  # raises if unknown
            if source_version_id not in target.parent_version_ids:
                service._append_parent(target_version_id, source_version_id)
                try:
                    # Dirty-set incremental write (#1138): the touched
                    # version's row (lineage included) is reconciled by
                    # apply_changes — no full-store reconcile needed.
                    service._save(
                        DirtySet(versions={target_version_id: None})
                    )
                except Exception:
                    # Snapshot-rollback on a failed save: undo the in-memory
                    # edge (and the maintained children index) so memory never
                    # diverges from the disk state until a later unrelated
                    # save.
                    target.parent_version_ids.remove(source_version_id)
                    children = service._children_by_parent
                    if children is not None:
                        bucket = children.get(source_version_id)
                        if bucket is not None and target in bucket:
                            bucket.remove(target)
                    raise
        return LineageEdge(
            source_version_id=source_version_id,
            target_version_id=target_version_id,
            run_id=run_id,
        )

    def _children_of(self, version_id: str) -> list[DataVersion]:
        return list(self._service._ensure_maps().children_by_parent.get(version_id, ()))

    def _lineage_maps(self) -> tuple[dict[str, DataVersion], dict[str, list[str]]]:
        """Prebuilt ``(by_id, children_by_parent)`` for lineage BFS (P4).

        Building the child map ONCE per walk turns descendants BFS from
        O(V²) (scanning every version per frontier node) into O(V + E).
        """
        maps = self._service._ensure_maps()
        by_id = maps.version_by_id
        children: dict[str, list[str]] = {}
        for parent_id, children_list in maps.children_by_parent.items():
            children[parent_id] = [c.id for c in children_list]
        return by_id, children

    def query_lineage(
        self, version_id: str, *, direction: str = "ancestors"
    ) -> list[DataVersionRef]:
        by_id, children = self._lineage_maps()
        # Seed with the start node so a cycle can never list a version as its
        # own ancestor/descendant.
        visited: set[str] = {version_id}
        ordered: list[DataVersionRef] = []
        frontier = [version_id]
        while frontier:
            nxt: list[str] = []
            for vid in frontier:
                if direction == "ancestors":
                    version = by_id.get(vid)
                    neighbors = version.parent_version_ids if version else []
                elif direction == "descendants":
                    neighbors = children.get(vid, [])
                else:
                    raise ValueError(f"unknown lineage direction: {direction!r}")
                for nid in neighbors:
                    if nid in visited or nid not in by_id:
                        continue
                    visited.add(nid)
                    ordered.append(self._version_ref(by_id[nid]))
                    nxt.append(nid)
            frontier = nxt
        return ordered

    def direct_ancestors(self, version_id: str) -> list[DataVersionRef]:
        by_id = self._service._ensure_maps().version_by_id
        version = by_id.get(version_id)
        if version is None:
            return []
        out: list[DataVersionRef] = []
        seen: set[str] = set()
        for pid in version.parent_version_ids:
            if pid in seen or pid not in by_id:
                continue
            seen.add(pid)
            out.append(self._version_ref(by_id[pid]))
        return out

    # ------------------------------------------------------------- resolution
    def resolve_version(self, version_id: str) -> DataVersionRef | None:
        try:
            return self._version_ref(self._service.get_version(version_id))
        except CatalogError:
            return None

    def resolve_run(self, run_id: str) -> DataRunRef | None:
        try:
            return self._run_ref(self._service.get_run(run_id))
        except CatalogError:
            return None

    def resolve_legacy_resource(self, resource_id: str) -> DataVersionRef | None:
        asset = self._find_asset_by_legacy_id(resource_id)
        if (
            asset is None
            or asset.trashed
            or asset.current_version_id is None
        ):
            return None
        return self._version_ref(self._service.get_version(asset.current_version_id))

    # --------------------------------------------------------------- tags / integrity
    def add_tags(self, version_id: str, tags: list[str]) -> None:
        self._service.add_tags(tags, version_id=version_id)

    def verify_integrity(self, version_id: str) -> IntegrityStatus:
        try:
            report = self._service.verify_integrity(version_id)
        except CatalogError:
            return IntegrityStatus.UNKNOWN
        return _STATUS_TO_INTEGRITY.get(
            report.status_for(version_id), IntegrityStatus.UNKNOWN
        )

    # ------------------------------------------------------------------ listing
    def list_versions(
        self,
        *,
        stage: DataStage | str | None = None,
        asset_id: str | None = None,
    ) -> list[DataVersionRef]:
        stage_val: str | None = None
        if stage is not None:
            stage_val = stage.value if isinstance(stage, DataStage) else str(stage).lower()
        result = []
        for version in self._service.document.versions:
            if stage_val is not None and version.stage.value != stage_val:
                continue
            if asset_id is not None and version.asset_id != asset_id:
                continue
            result.append(self._version_ref(version))
        result.sort(key=lambda r: r.created_at)
        return result

    def list_runs(self) -> list[DataRunRef]:
        runs = sorted(
            self._service.document.runs, key=lambda r: r.created_at
        )
        return [self._run_ref(r) for r in runs]
