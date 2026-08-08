"""In-memory :class:`CatalogPort` fake for tests.

This backend exists ONLY for tests: it lets business-integration intent be
verified without a project on disk. It is NOT a second production catalog —
the authoritative runtime backend is
:class:`paleo_workbench.catalog.adapter.CoreCatalogAdapter` over the Core
``DataCatalogService``. State is held in plain dicts so it can be
serialized/deserialized for test round-trips.

Design notes (mirroring the production contract):

- ``register_input`` is idempotent on (path, checksum): the same managed source
  re-imported returns the same asset_id + version_id (RAW immutability).
- Producing operations (intermediate / output / derived) ALWAYS create a new
  version per call, so a rerun never clobbers a committed prior version.
- Integrity verification recomputes the on-disk SHA-256 and compares it to the
  recorded checksum; a mismatch is reported as MODIFIED and the recorded value
  is left untouched (no silent overwrite).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.catalog.checksum import sha256_file_or_none
from paleo_workbench.catalog.types import (
    DataRunRef,
    DataStage,
    DataVersionRef,
    IntegrityStatus,
    LineageEdge,
    _id,
    _now_iso,
)


def sha256_of_file(path: str | Path) -> str | None:
    """Stream-hash a file; return None if unreadable (missing / permissions)."""
    return sha256_file_or_none(path)


def _asset_key(path: str, checksum: str | None) -> str:
    """Deterministic asset identity for managed inputs (path + checksum)."""
    return f"{path}::{checksum or '<none>'}"


class InMemoryCatalog:
    """Minimal in-memory implementation of :class:`CatalogPort` (test fake)."""

    def __init__(self) -> None:
        self._versions: dict[str, DataVersionRef] = {}
        self._runs: dict[str, DataRunRef] = {}
        self._lineage: list[LineageEdge] = []
        # Deterministic managed-input identity: asset_key -> version_id
        self._managed_index: dict[str, str] = {}
        # Legacy ResourceItem.id -> version_id (migration bridge).
        self._legacy_index: dict[str, str] = {}

    # --------------------------------------------------------------- helpers
    def _new_version(
        self,
        *,
        name: str,
        stage: DataStage,
        path: str,
        checksum: str | None,
        kind: str,
        format: str,
        external: bool,
        producing_run_id: str | None,
        tags: list[str] | None,
        legacy_resource_id: str | None,
    ) -> DataVersionRef:
        asset_id = _id("asset")
        version_id = _id("ver")
        ref = DataVersionRef(
            asset_id=asset_id,
            version_id=version_id,
            name=name,
            stage=stage,
            path=path,
            checksum=checksum,
            external=external,
            producing_run_id=producing_run_id,
            tags=tags,
            kind=kind,
            format=format,
            legacy_resource_id=legacy_resource_id,
        )
        self._versions[version_id] = ref
        return ref

    def _link_inputs_to_output(self, run: DataRunRef, output_id: str) -> None:
        # Record one lineage edge per *distinct* input (deduped), and register
        # the output on the run exactly once (never once per input).
        seen: set[str] = set()
        for in_id in run.input_version_ids:
            if in_id in seen:
                continue
            seen.add(in_id)
            self._lineage.append(
                LineageEdge(
                    source_version_id=in_id, target_version_id=output_id, run_id=run.run_id
                )
            )
        if output_id not in run.output_version_ids:
            run.output_version_ids.append(output_id)

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
        # External inputs are RAW stage with external=True (externality is not
        # a lifecycle stage in the unified Core vocabulary).
        stage = DataStage.RAW
        # Managed RAW inputs are idempotent on (path, checksum): re-importing
        # the same source returns the existing version (RAW immutability).
        if not external:
            key = _asset_key(path, checksum)
            existing_id = self._managed_index.get(key)
            if existing_id is not None and existing_id in self._versions:
                existing = self._versions[existing_id]
                # Keep the legacy bridge current (resource may have a new id).
                if legacy_resource_id is not None:
                    self._legacy_index[legacy_resource_id] = existing_id
                return existing
        elif legacy_resource_id is not None:
            # External inputs are deduped by legacy resource id so reopening a
            # project does not accumulate duplicate external versions or drift
            # the bridge away from prior runs' lineage (first registration wins).
            existing_id = self._legacy_index.get(legacy_resource_id)
            if existing_id is not None and existing_id in self._versions:
                return self._versions[existing_id]
        ref = self._new_version(
            name=name,
            stage=stage,
            path=path,
            checksum=checksum,
            kind=kind,
            format=format,
            external=external,
            producing_run_id=None,
            tags=tags,
            legacy_resource_id=legacy_resource_id,
        )
        if not external:
            self._managed_index[_asset_key(path, checksum)] = ref.version_id
        if legacy_resource_id is not None:
            self._legacy_index[legacy_resource_id] = ref.version_id
        return ref

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
        run = DataRunRef(
            run_id=_id("run"),
            operation=operation,
            input_version_ids=list(input_version_ids),
            parameters=parameters,
            generator_version=generator_version,
            status="running",
            domain_task_id=domain_task_id,
            input_snapshot_hash=input_snapshot_hash,
        )
        self._runs[run.run_id] = run
        return run

    def complete_run(self, run_id: str, *, status: str = "complete") -> DataRunRef:
        run = self._runs[run_id]
        run.status = status
        run.finished_at = _now_iso()
        return run

    # -------------------------------------------------------------- producers
    def _register_produced(
        self,
        run_id: str,
        name: str,
        path: str,
        stage: DataStage,
        checksum: str | None,
        kind: str,
        format: str,
        tags: list[str] | None,
    ) -> DataVersionRef:
        run = self._runs[run_id]
        ref = self._new_version(
            name=name,
            stage=stage,
            path=path,
            checksum=checksum,
            kind=kind,
            format=format,
            external=False,
            producing_run_id=run_id,
            tags=tags,
            legacy_resource_id=None,
        )
        self._link_inputs_to_output(run, ref.version_id)
        return ref

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
            run_id, name, path, DataStage.INTERMEDIATE, checksum, kind, format, tags
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
            run_id, name, path, DataStage.OUTPUT, checksum, kind, format, tags
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
            run_id, name, path, DataStage.DERIVED, checksum, kind, format, tags
        )

    # --------------------------------------------------------------- lineage
    def attach_lineage(
        self,
        *,
        source_version_id: str,
        target_version_id: str,
        run_id: str | None = None,
    ) -> LineageEdge:
        edge = LineageEdge(
            source_version_id=source_version_id,
            target_version_id=target_version_id,
            run_id=run_id,
        )
        self._lineage.append(edge)
        return edge

    def query_lineage(
        self, version_id: str, *, direction: str = "ancestors"
    ) -> list[DataVersionRef]:
        if direction == "ancestors":
            # BFS up the provenance graph.
            visited: set[str] = set()
            ordered: list[DataVersionRef] = []
            frontier = [version_id]
            while frontier:
                nxt: list[str] = []
                for vid in frontier:
                    for edge in self._lineage:
                        if edge.target_version_id == vid and edge.source_version_id not in visited:
                            visited.add(edge.source_version_id)
                            ref = self._versions.get(edge.source_version_id)
                            if ref is not None:
                                ordered.append(ref)
                            nxt.append(edge.source_version_id)
                frontier = nxt
            return ordered
        if direction == "descendants":
            visited = set()
            ordered = []
            frontier = [version_id]
            while frontier:
                nxt = []
                for vid in frontier:
                    for edge in self._lineage:
                        if edge.source_version_id == vid and edge.target_version_id not in visited:
                            visited.add(edge.target_version_id)
                            ref = self._versions.get(edge.target_version_id)
                            if ref is not None:
                                ordered.append(ref)
                            nxt.append(edge.target_version_id)
                frontier = nxt
            return ordered
        raise ValueError(f"unknown lineage direction: {direction!r}")

    def direct_ancestors(self, version_id: str) -> list[DataVersionRef]:
        """Immediate parent versions (one hop up the lineage graph)."""
        out: list[DataVersionRef] = []
        seen: set[str] = set()
        for edge in self._lineage:
            if edge.target_version_id == version_id and edge.source_version_id not in seen:
                seen.add(edge.source_version_id)
                ref = self._versions.get(edge.source_version_id)
                if ref is not None:
                    out.append(ref)
        return out

    # ------------------------------------------------------------- resolution
    def resolve_version(self, version_id: str) -> DataVersionRef | None:
        return self._versions.get(version_id)

    def resolve_run(self, run_id: str) -> DataRunRef | None:
        return self._runs.get(run_id)

    def resolve_legacy_resource(self, resource_id: str) -> DataVersionRef | None:
        version_id = self._legacy_index.get(resource_id)
        if version_id is None:
            return None
        return self._versions.get(version_id)

    # --------------------------------------------------------------- tags / integrity
    def add_tags(self, version_id: str, tags: list[str]) -> None:
        ref = self._versions.get(version_id)
        if ref is None:
            return
        for tag in tags:
            if tag and tag not in ref.tags:
                ref.tags.append(tag)

    def verify_integrity(self, version_id: str) -> IntegrityStatus:
        ref = self._versions.get(version_id)
        if ref is None:
            return IntegrityStatus.UNKNOWN
        if not ref.path:
            return IntegrityStatus.UNKNOWN
        # External / unmanaged sources may be missing; that is a valid state.
        current = sha256_of_file(ref.path)
        if current is None:
            return IntegrityStatus.MISSING
        if ref.checksum is None:
            # Never had a recorded checksum — cannot verify, do not fabricate one.
            return IntegrityStatus.UNKNOWN
        # Recorded checksum is never overwritten on mismatch.
        return IntegrityStatus.VERIFIED if current == ref.checksum else IntegrityStatus.MODIFIED

    # ------------------------------------------------------------------ listing
    def list_versions(
        self,
        *,
        stage: DataStage | str | None = None,
        asset_id: str | None = None,
    ) -> list[DataVersionRef]:
        stage_val = stage.value if isinstance(stage, DataStage) else stage
        result = []
        for ref in self._versions.values():
            if stage_val is not None and ref.stage.value != stage_val:
                continue
            if asset_id is not None and ref.asset_id != asset_id:
                continue
            result.append(ref)
        result.sort(key=lambda r: r.created_at)
        return result

    def list_runs(self) -> list[DataRunRef]:
        return sorted(self._runs.values(), key=lambda r: r.started_at)

    # --------------------------------------------------- (de)serialization for tests
    def to_dict(self) -> dict[str, Any]:
        return {
            "versions": [v.to_dict() for v in self._versions.values()],
            "runs": [r.to_dict() for r in self._runs.values()],
            "lineage": [e.to_dict() for e in self._lineage],
            "legacy_index": dict(self._legacy_index),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InMemoryCatalog":
        cat = cls()
        for v in data.get("versions", []):
            ref = DataVersionRef.from_dict(v)
            cat._versions[ref.version_id] = ref
        for r in data.get("runs", []):
            run = DataRunRef.from_dict(r)
            cat._runs[run.run_id] = run
        for e in data.get("lineage", []):
            cat._lineage.append(
                LineageEdge(
                    source_version_id=e["source_version_id"],
                    target_version_id=e["target_version_id"],
                    run_id=e.get("run_id"),
                )
            )
        cat._legacy_index = dict(data.get("legacy_index", {}))
        # Rebuild the managed-input identity index from managed RAW versions.
        for ref in cat._versions.values():
            if ref.stage == DataStage.RAW and not ref.external:
                cat._managed_index[_asset_key(ref.path, ref.checksum)] = ref.version_id
        return cat
