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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from paleo_workbench.catalog.db import CatalogIndex
from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
    ImmutableVersionError,
    CatalogError,
    Tag,
    normalize_tag_name,
)
from paleo_workbench.catalog.storage import (
    create_working_copy as _place_working_copy,
    place_managed_file,
)
from paleo_workbench.catalog.store import CatalogStore


@dataclass
class IntegrityReport:
    """Result of :meth:`DataCatalogService.verify_integrity`.

    Statuses: ``verified`` (hash matches), ``modified`` (hash mismatch — the
    catalog record is NOT updated), ``missing`` (payload gone), ``unknown``
    (no recorded hash to verify against, e.g. an unhashed external link).
    """

    statuses: dict[str, str] = field(default_factory=dict)

    def status_for(self, version_id: str) -> str:
        return self.statuses.get(version_id, "unknown")

    @property
    def ok(self) -> bool:
        return all(s in ("verified", "unknown") for s in self.statuses.values())


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

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def open(cls, project_path: str | Path) -> "DataCatalogService":
        """Open (or initialize) the catalog for *project_path*.

        A missing, stale, or corrupt SQLite index is rebuilt from the
        canonical store; index problems never block opening the project.
        """
        project_path = Path(project_path)
        store = CatalogStore(project_path)
        document = store.load()
        index = CatalogIndex(project_path)
        service = cls(project_path, document, store, index)
        service._ensure_index_fresh()
        return service

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
                return
            self._index.rebuild(self.document)
        except Exception:
            try:
                self._index.reset()
                self._index.rebuild(self.document)
            except Exception:
                pass

    def rebuild_index(self) -> None:
        """Force a full index rebuild from the canonical store."""
        self._index.reset()
        self._index.rebuild(self.document)

    def index_revision(self) -> int | None:
        return self._index.revision()

    # -- lookups ------------------------------------------------------------

    def _asset_or_raise(self, asset_id: str) -> DataAsset:
        for asset in self.document.assets:
            if asset.id == asset_id:
                return asset
        raise CatalogError(f"Unknown asset: {asset_id}")

    def _version_or_raise(self, version_id: str) -> DataVersion:
        for version in self.document.versions:
            if version.id == version_id:
                return version
        raise CatalogError(f"Unknown version: {version_id}")

    def get_asset(self, asset_id: str) -> DataAsset:
        return self._asset_or_raise(asset_id)

    def get_version(self, version_id: str) -> DataVersion:
        return self._version_or_raise(version_id)

    def get_run(self, run_id: str) -> DataRun:
        for run in self.document.runs:
            if run.id == run_id:
                return run
        raise CatalogError(f"Unknown run: {run_id}")

    def list_assets(self) -> list[DataAsset]:
        return list(self.document.assets)

    def list_runs(self) -> list[DataRun]:
        return list(self.document.runs)

    def list_versions(self, asset_id: str) -> list[DataVersion]:
        versions = [v for v in self.document.versions if v.asset_id == asset_id]
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
            if asset in self.document.assets:
                self.document.assets.remove(asset)
        for version in versions:
            if version in self.document.versions:
                self.document.versions.remove(version)
        for run in runs:
            if run in self.document.runs:
                self.document.runs.remove(run)
        if restore_current is not None:
            asset, previous = restore_current
            asset.current_version_id = previous
        if payload is not None:
            if restore_payload_to is not None and payload.exists():
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
        numbers = [v.version_number for v in self.document.versions if v.asset_id == asset_id]
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
    ) -> DataVersion:
        """Place *source_path* under managed storage and commit a new version."""
        asset = self._asset_or_raise(asset_id)
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CatalogError(f"Source file not found: {source_path}")
        previous_current = asset.current_version_id
        version, payload = self._build_version(
            asset, source_path, stage,
            version_id=version_id,
            parent_version_ids=list(parent_version_ids),
            run_id=run_id, metadata=metadata, move=move,
        )
        self.document.versions.append(version)
        asset.current_version_id = version.id
        try:
            self._save()
        except Exception:
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
    ) -> DataVersion:
        """Import *source_path* as an immutable managed RAW snapshot.

        Copies (never references) the file into project-managed storage,
        hashing in a single streaming pass. Later edits to the source file
        cannot affect the snapshot.
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
            asset = target
            self.document.assets.append(target)
        try:
            return self.register_version(
                target.id, source_path, DataStage.RAW, metadata=metadata
            )
        except Exception:
            if asset is not None and asset in self.document.assets:
                self.document.assets.remove(asset)
            raise

    def link_external(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        type: str | None = None,
        format: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DataVersion:
        """Register an unmanaged external reference (explicitly not managed).

        No copy, no hash: the project records where the file lives without
        pretending integrity guarantees. Use :meth:`materialize_external` to
        promote it to a managed RAW snapshot.
        """
        path = Path(path)
        if not path.is_file():
            raise CatalogError(f"External file not found: {path}")
        asset = self._new_asset(name or path.name, type, format, metadata)
        asset.metadata["external"] = True
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
        self.document.assets.append(asset)
        self.document.versions.append(version)
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
            self.document.assets.append(asset)
            try:
                return self.register_version(
                    asset.id, working_path, stage,
                    parent_version_ids=parent_version_ids,
                    run_id=run_id, metadata=metadata, move=True,
                    _restore_payload_to=working_path,
                )
            except Exception:
                if asset in self.document.assets:
                    self.document.assets.remove(asset)
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
        self.document.assets.append(asset)
        self.document.versions.append(version)
        asset.current_version_id = version.id
        if run is not None:
            self.document.runs.append(run)
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
    ) -> DataRun:
        run = DataRun(
            operation=operation,
            input_version_ids=list(input_version_ids),
            output_version_ids=list(output_version_ids),
            parameters=dict(parameters or {}),
            generator=generator,
            status=status,
        )
        self.document.runs.append(run)
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
        run = self.get_run(run_id)
        run.status = status
        if extra_parameters:
            run.parameters.update(extra_parameters)
        self._save()
        return run

    # -- lineage ---------------------------------------------------------------

    def get_lineage(self, version_id: str) -> dict[str, Any]:
        """Parents, children, and the producing run for a version."""
        version = self._version_or_raise(version_id)
        parents = [
            self._version_or_raise(pid)
            for pid in version.parent_version_ids
            if any(v.id == pid for v in self.document.versions)
        ]
        children = [
            v for v in self.document.versions if version_id in v.parent_version_ids
        ]
        run = None
        if version.run_id is not None:
            try:
                run = self.get_run(version.run_id)
            except CatalogError:
                run = None
        return {"version": version, "parents": parents, "children": children, "run": run}

    # -- integrity -------------------------------------------------------------

    def verify_integrity(self, version_id: str | None = None) -> IntegrityReport:
        """Re-hash payloads and compare against recorded SHA-256.

        Reports only; a mismatch never updates the catalog. Hashing streams in
        chunks; wrap in a worker thread for large batches in UI contexts.
        """
        if version_id is not None:
            versions = [self._version_or_raise(version_id)]
        else:
            versions = list(self.document.versions)
        report = IntegrityReport()
        for version in versions:
            payload = self.resolve_path(version)
            if not payload.is_file():
                report.statuses[version.id] = "missing"
                continue
            if not version.sha256:
                report.statuses[version.id] = "unknown"
                continue
            try:
                actual = sha256_file(payload)
            except OSError:
                report.statuses[version.id] = "missing"
                continue
            report.statuses[version.id] = (
                "verified" if actual == version.sha256 else "modified"
            )
        return report

    # -- tags ------------------------------------------------------------------

    def _tag_by_name(self, name: str) -> Tag | None:
        normalized = normalize_tag_name(name)
        for tag in self.document.tags:
            if tag.name == normalized:
                return tag
        return None

    def add_tag(
        self,
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
            self._asset_or_raise(asset_id)
        if version_id is not None:
            self._version_or_raise(version_id)
        tag = self._tag_by_name(normalized)
        created = False
        if tag is None:
            tag = Tag(name=normalized, display_name=" ".join(str(name).split()))
            self.document.tags.append(tag)
            created = True
        changed = False
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
        if created or changed:
            try:
                self._save()
            except Exception:
                if created and tag in self.document.tags:
                    self.document.tags.remove(tag)
                if asset_id is not None:
                    self.document.asset_tags[asset_id] = [
                        t for t in self.document.asset_tags.get(asset_id, []) if t != tag.id
                    ]
                if version_id is not None:
                    self.document.version_tags[version_id] = [
                        t for t in self.document.version_tags.get(version_id, []) if t != tag.id
                    ]
                raise
        return tag

    def remove_tag(
        self,
        name: str,
        *,
        asset_id: str | None = None,
        version_id: str | None = None,
    ) -> None:
        tag = self._tag_by_name(name)
        if tag is None:
            return
        changed = False
        if asset_id is not None and tag.id in self.document.asset_tags.get(asset_id, []):
            self.document.asset_tags[asset_id].remove(tag.id)
            changed = True
        if version_id is not None and tag.id in self.document.version_tags.get(version_id, []):
            self.document.version_tags[version_id].remove(tag.id)
            changed = True
        if changed:
            self._save()

    def rename_tag(self, old_name: str, new_name: str) -> Tag:
        """Rename a tag; merges into an existing tag on normalized collision."""
        tag = self._tag_by_name(old_name)
        if tag is None:
            raise CatalogError(f"Unknown tag: {old_name}")
        normalized_new = normalize_tag_name(new_name)
        if not normalized_new:
            raise CatalogError("Empty tag name")
        existing = self._tag_by_name(normalized_new)
        if existing is not None and existing.id == tag.id:
            tag.display_name = " ".join(str(new_name).split())
            self._save()
            return tag
        if existing is not None:
            # Merge: point all associations at the existing tag, drop the old.
            for ids in list(self.document.asset_tags.values()):
                while tag.id in ids:
                    ids.remove(tag.id)
                    if existing.id not in ids:
                        ids.append(existing.id)
            for ids in list(self.document.version_tags.values()):
                while tag.id in ids:
                    ids.remove(tag.id)
                    if existing.id not in ids:
                        ids.append(existing.id)
            self.document.tags.remove(tag)
            self._save()
            return existing
        tag.name = normalized_new
        tag.display_name = " ".join(str(new_name).split())
        self._save()
        return tag

    def list_tags(self) -> list[Tag]:
        return list(self.document.tags)

    def find_assets_by_tag(self, name: str) -> list[str]:
        tag = self._tag_by_name(name)
        if tag is None:
            return []
        try:
            return sorted(self._index.assets_for_tag(tag.name))
        except Exception:
            return sorted(
                aid
                for aid, ids in self.document.asset_tags.items()
                if tag.id in ids
            )

    def find_versions_by_tag(self, name: str) -> list[str]:
        tag = self._tag_by_name(name)
        if tag is None:
            return []
        try:
            return sorted(self._index.versions_for_tag(tag.name))
        except Exception:
            return sorted(
                vid
                for vid, ids in self.document.version_tags.items()
                if tag.id in ids
            )

    # -- search ------------------------------------------------------------------

    def search_assets(
        self,
        *,
        text: str | None = None,
        stage: DataStage | None = None,
        tag: str | None = None,
        type: str | None = None,
    ) -> list[DataAsset]:
        """Filter assets by name substring, stage, tag, and/or type."""
        try:
            rows = self._index.search_assets(
                text=text,
                stage=stage.value if stage else None,
                tag=normalize_tag_name(tag) if tag else None,
                type=type,
            )
            by_id = {a.id: a for a in self.document.assets}
            return [by_id[r["id"]] for r in rows if r["id"] in by_id]
        except Exception:
            pass
        results = list(self.document.assets)
        if text:
            needle = text.casefold()
            results = [a for a in results if needle in a.name.casefold()]
        if type:
            results = [a for a in results if a.type == type]
        if stage is not None:
            with_stage = {v.asset_id for v in self.document.versions if v.stage == stage}
            results = [a for a in results if a.id in with_stage]
        if tag:
            tagged = set(self.find_assets_by_tag(tag))
            results = [a for a in results if a.id in tagged]
        return results

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
            self._save()
        return report
