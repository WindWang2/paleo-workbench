"""Data Catalog seam — :class:`CatalogPort` protocol.

The minimal set of operations business modules need from a Data Catalog.

A backend implementing this protocol provides:
  - resolving inputs to versions
  - registering runs / intermediate / output / derived versions
  - attaching provenance (lineage edges)
  - resolving legacy ``resource_id`` → version_id (migration bridge)
  - querying lineage and integrity

The protocol is the contract satisfied by the canonical Data Catalog Core via
:class:`paleo_workbench.catalog.adapter.CoreCatalogAdapter` — the only
production backend. An in-memory fake for tests lives under ``tests/fakes``.

This module deliberately depends only on the standard library plus the seam
value types so it can be imported without the heavyweight catalog stack.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from paleo_workbench.catalog.types import (
    DataRunRef,
    DataStage,
    DataVersionRef,
    IntegrityStatus,
    LineageEdge,
)


@runtime_checkable
class CatalogPort(Protocol):
    """Minimal data-lifecycle operations for the workbench business layer.

    Implementations MUST be idempotent on asset identity: registering the same
    managed input twice (same path + checksum) returns the same asset with a
    stable version, while a rerun of a producing operation always yields a NEW
    version (never overwriting a committed one).
    """

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
        """Register a user-imported / source asset as a RAW version.

        ``external=True`` marks an unmanaged link (source may go missing);
        otherwise the asset is treated as managed/immutable RAW.
        """
        ...

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
        """Open a processing run consuming the given input versions."""
        ...

    def complete_run(
        self,
        run_id: str,
        *,
        status: str = "complete",
    ) -> DataRunRef:
        """Mark a run finished (``complete`` / ``failed``)."""
        ...

    # -------------------------------------------------------------- producers
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
        """Register an INTERMEDIATE output of a run (reconstructible)."""
        ...

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
        """Register a final OUTPUT of a run (user-delivered result)."""
        ...

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
        """Register a DERIVED output (processed, but reused as a downstream input)."""
        ...

    # --------------------------------------------------------------- lineage
    def attach_lineage(
        self,
        *,
        source_version_id: str,
        target_version_id: str,
        run_id: str | None = None,
    ) -> LineageEdge:
        """Record a directed provenance edge (input → output)."""
        ...

    def query_lineage(
        self, version_id: str, *, direction: str = "ancestors"
    ) -> list[DataVersionRef]:
        """Walk lineage. ``ancestors`` = inputs that fed this version;
        ``descendants`` = versions produced from it."""
        ...

    def direct_ancestors(self, version_id: str) -> list[DataVersionRef]:
        """Immediate parent versions (one hop). Cheaper than a full walk;
        used by display payloads."""
        ...

    # ------------------------------------------------------------- resolution
    def resolve_version(self, version_id: str) -> DataVersionRef | None:
        """Look up a version by id (None if unknown)."""
        ...

    def resolve_run(self, run_id: str) -> DataRunRef | None:
        """Look up a run by id (None if unknown)."""
        ...

    def resolve_legacy_resource(self, resource_id: str) -> DataVersionRef | None:
        """Bridge a legacy ``ResourceItem.id`` to its registered version.

        Returns None when the resource has not been migrated/registered yet.
        Business modules must degrade gracefully (the legacy path still works).
        """
        ...

    # --------------------------------------------------------------- tags / integrity
    def add_tags(self, version_id: str, tags: list[str]) -> None:
        """Attach free-form tags to a version (UI filter surface)."""
        ...

    def verify_integrity(self, version_id: str) -> IntegrityStatus:
        """Recompute the on-disk checksum and compare to the recorded one.

        Returns ``verified`` / ``modified`` / ``missing``. The recorded
        checksum is NEVER auto-overwritten — a tamper stays visible until the
        user explicitly re-registers.
        """
        ...

    # ------------------------------------------------------------------ listing
    def list_versions(
        self,
        *,
        stage: DataStage | str | None = None,
        asset_id: str | None = None,
    ) -> list[DataVersionRef]:
        """List versions, optionally filtered by stage or asset."""
        ...

    def list_runs(self) -> list[DataRunRef]:
        """List all registered runs (newest last)."""
        ...
