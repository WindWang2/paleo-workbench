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

    # ------------------------------------------------------------- conversions
    def _tag_names(self, version: DataVersion) -> list[str]:
        tag_ids = self._service.document.version_tags.get(version.id, [])
        by_id = {t.id: t for t in self._service.document.tags}
        return [
            by_id[tid].display_name or by_id[tid].name
            for tid in tag_ids
            if tid in by_id
        ]

    def _asset_for(self, version: DataVersion) -> DataAsset | None:
        for asset in self._service.document.assets:
            if asset.id == version.asset_id:
                return asset
        return None

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
        for asset in self._service.document.assets:
            if asset.id == legacy_resource_id or asset.legacy_resource_id == legacy_resource_id:
                return asset
        return None

    def _bridge_legacy_id(self, version: DataVersion, legacy_resource_id: str | None) -> None:
        """Record the legacy bridge on an idempotent hit when it is missing.

        First wins: an asset that already carries a (different) legacy id is
        left alone, matching the fake's external-dedup semantics.
        """
        if legacy_resource_id is None:
            return
        asset = self._asset_for(version)
        if asset is not None and asset.legacy_resource_id is None:
            asset.legacy_resource_id = legacy_resource_id
            self._service._save()

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
        # Idempotence 1: the legacy bridge — a resource already migrated or
        # registered returns its current version instead of duplicating.
        if legacy_resource_id is not None:
            asset = self._find_asset_by_legacy_id(legacy_resource_id)
            if asset is not None and asset.current_version_id is not None:
                return self._version_ref(service.get_version(asset.current_version_id))

        resolved = Path(path).expanduser().resolve().as_posix()

        if external:
            # Idempotence 2: same external path already linked.
            for version in service.document.versions:
                if not version.managed and version.path == resolved:
                    self._bridge_legacy_id(version, legacy_resource_id)
                    return self._version_ref(version)
            version = service.link_external(
                resolved, name=name, type=kind or None, format=format or None
            )
            if legacy_resource_id is not None:
                asset = self._asset_for(version)
                if asset is not None:
                    asset.legacy_resource_id = legacy_resource_id
                    service._save()
        else:
            # Idempotence 3: same managed source (path + checksum) already
            # imported returns the existing immutable RAW version.
            for version in service.document.versions:
                if (
                    version.managed
                    and version.stage == DataStage.RAW
                    and version.source_uri == resolved
                    and version.sha256 == checksum
                ):
                    self._bridge_legacy_id(version, legacy_resource_id)
                    return self._version_ref(version)
            version = service.import_raw(
                resolved, name=name, type=kind or None, format=format or None
            )
            if legacy_resource_id is not None:
                asset = self._asset_for(version)
                if asset is not None:
                    asset.legacy_resource_id = legacy_resource_id
                    service._save()
        for tag in tags or []:
            if tag:
                service.add_tag(tag, version_id=version.id)
        return self._version_ref(version)

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
    ) -> DataVersionRef:
        service = self._service
        run = service.get_run(run_id)
        asset = service._new_asset(name, kind or None, format or None, None)
        service.document.assets.append(asset)
        try:
            # register_version links the run's output in the same atomic save.
            version = service.register_version(
                asset.id,
                path,
                stage,
                parent_version_ids=list(run.input_version_ids),
                run_id=run.id,
            )
        except Exception:
            if asset in service.document.assets:
                service.document.assets.remove(asset)
            raise
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
            run_id, name, path, DataStage.INTERMEDIATE, kind, format, tags
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
    ) -> DataVersionRef:
        return self._register_produced(
            run_id, name, path, DataStage.OUTPUT, kind, format, tags
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
        return self._register_produced(
            run_id, name, path, DataStage.DERIVED, kind, format, tags
        )

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
        target = service.get_version(target_version_id)
        service.get_version(source_version_id)  # raises if unknown
        if source_version_id not in target.parent_version_ids:
            target.parent_version_ids.append(source_version_id)
            service._save()
        return LineageEdge(
            source_version_id=source_version_id,
            target_version_id=target_version_id,
            run_id=run_id,
        )

    def _children_of(self, version_id: str) -> list[DataVersion]:
        return [
            v
            for v in self._service.document.versions
            if version_id in v.parent_version_ids
        ]

    def query_lineage(
        self, version_id: str, *, direction: str = "ancestors"
    ) -> list[DataVersionRef]:
        service = self._service
        by_id = {v.id: v for v in service.document.versions}
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
                    neighbors = [c.id for c in self._children_of(vid)]
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
        service = self._service
        by_id = {v.id: v for v in service.document.versions}
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
        if asset is None or asset.current_version_id is None:
            return None
        return self._version_ref(self._service.get_version(asset.current_version_id))

    # --------------------------------------------------------------- tags / integrity
    def add_tags(self, version_id: str, tags: list[str]) -> None:
        for tag in tags:
            if tag:
                self._service.add_tag(tag, version_id=version_id)

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
