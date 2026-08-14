"""Data Catalog seam — lifecycle value types.

Thin reference shapes passed between workbench business modules
(pipeline / prediction / mapping / export / import) and the canonical Data
Catalog Core (:mod:`paleo_workbench.catalog.models`).

Scope rules (post-integration):

- The authoritative domain models (``DataAsset`` / ``DataVersion`` /
  ``DataRun`` / ``Tag`` / ``DataStage``), managed storage, canonical
  persistence and the SQLite index live in the Core
  (:class:`~paleo_workbench.catalog.service.DataCatalogService`).
  Nothing here re-implements them.
- These value types describe what the business layer *needs* to express
  (version refs, run refs, lineage edges, integrity status). They are
  intentionally minimal DTOs, not a second domain model.
- ``DataStage`` is the Core's enum, re-exported so business and UI code share
  one lifecycle vocabulary (RAW / DERIVED / INTERMEDIATE / OUTPUT). An
  "external" input is ``DataStage.RAW`` with ``DataVersionRef.external=True``
  (Core: ``DataVersion.managed=False``) — externality is not a stage.
- ``paleo_workbench/catalog/runtime.py`` resolves which backend implements
  :class:`~paleo_workbench.catalog.port.CatalogPort`; in production that is
  :class:`~paleo_workbench.catalog.adapter.CoreCatalogAdapter` over the Core
  service. Tests may inject the fake from ``tests/fakes``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from paleo_workbench.catalog.models import DataStage

__all__ = [
    "DataRunRef",
    "DataStage",
    "DataVersionRef",
    "IntegrityStatus",
    "LineageEdge",
]


def _coerce_stage(stage: DataStage | str) -> DataStage:
    """Coerce strings (any case) to the canonical :class:`DataStage`."""
    if isinstance(stage, DataStage):
        return stage
    return DataStage(str(stage).strip().lower())


class IntegrityStatus(str, Enum):
    """Result of verifying a managed asset's recorded checksum against bytes."""

    VERIFIED = "verified"
    MODIFIED = "modified"
    MISSING = "missing"
    UNKNOWN = "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class DataVersionRef:
    """Lightweight, serializable reference to a registered data version.

    Business modules pass these around instead of raw ``resource_id`` strings.
    A ref always carries the owning ``asset_id`` and the specific ``version_id``
    so reruns produce new versions without losing the old ones.

    This is a *reference* shape — the authoritative version payload (bytes,
    full metadata, tags) lives in the Core catalog. We only mirror the fields
    the business layer and UI contract need to display provenance.
    """

    __slots__ = (
        "asset_id",
        "version_id",
        "name",
        "stage",
        "path",
        "checksum",
        "external",
        "producing_run_id",
        "created_at",
        "tags",
        "kind",
        "format",
        "integrity",
        "legacy_resource_id",
        "trashed",
    )

    def __init__(
        self,
        *,
        asset_id: str,
        version_id: str,
        name: str = "",
        stage: DataStage | str = DataStage.INTERMEDIATE,
        path: str = "",
        checksum: str | None = None,
        external: bool = False,
        producing_run_id: str | None = None,
        created_at: str | None = None,
        tags: list[str] | None = None,
        kind: str = "",
        format: str = "",
        integrity: IntegrityStatus | str = IntegrityStatus.UNKNOWN,
        legacy_resource_id: str | None = None,
        trashed: bool = False,
    ) -> None:
        self.asset_id = asset_id
        self.version_id = version_id
        self.name = name
        self.stage = _coerce_stage(stage)
        self.path = path
        self.checksum = checksum
        self.external = external
        self.producing_run_id = producing_run_id
        self.created_at = created_at or _now_iso()
        self.tags = list(tags or [])
        self.kind = kind
        self.format = format
        self.integrity = (
            IntegrityStatus(integrity) if isinstance(integrity, str) else integrity
        )
        # Bridge to the legacy ResourceItem that produced this version (migration).
        self.legacy_resource_id = legacy_resource_id
        # Tombstone flag mirrored from the canonical DataVersion (H5-a: trashed
        # versions must never be resolved as production inputs).
        self.trashed = trashed

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "version_id": self.version_id,
            "name": self.name,
            "stage": self.stage.value,
            "path": self.path,
            "checksum": self.checksum,
            "external": self.external,
            "producing_run_id": self.producing_run_id,
            "created_at": self.created_at,
            "tags": list(self.tags),
            "kind": self.kind,
            "format": self.format,
            "integrity": self.integrity.value,
            "legacy_resource_id": self.legacy_resource_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataVersionRef":
        return cls(
            asset_id=data["asset_id"],
            version_id=data["version_id"],
            name=data.get("name", ""),
            stage=data.get("stage", DataStage.INTERMEDIATE),
            path=data.get("path", ""),
            checksum=data.get("checksum"),
            external=data.get("external", False),
            producing_run_id=data.get("producing_run_id"),
            created_at=data.get("created_at"),
            tags=data.get("tags"),
            kind=data.get("kind", ""),
            format=data.get("format", ""),
            integrity=data.get("integrity", IntegrityStatus.UNKNOWN),
            legacy_resource_id=data.get("legacy_resource_id"),
        )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"DataVersionRef({self.stage.value} {self.name!r} "
            f"asset={self.asset_id} ver={self.version_id})"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DataVersionRef) and (
            self.asset_id == other.asset_id and self.version_id == other.version_id
        )

    def __hash__(self) -> int:
        return hash((self.asset_id, self.version_id))


class DataRunRef:
    """Reference to a registered processing run (the data-provenance layer).

    This is intentionally distinct from the *domain* workflow tasks
    (``FactorMapTask`` / ``PredictionTask`` / ``CompilationRun``). A domain task
    describes *what the user is doing*; a ``DataRun`` describes *which data
    versions a computation consumed and produced* for lineage. See
    ``paleo_workbench/catalog/port.py`` for the mapping contract.
    """

    __slots__ = (
        "run_id",
        "operation",
        "input_version_ids",
        "output_version_ids",
        "parameters",
        "generator_version",
        "status",
        "started_at",
        "finished_at",
        "domain_task_id",
        "input_snapshot_hash",
    )

    def __init__(
        self,
        *,
        run_id: str,
        operation: str,
        input_version_ids: list[str] | None = None,
        output_version_ids: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        generator_version: str | None = None,
        status: str = "running",
        started_at: str | None = None,
        finished_at: str | None = None,
        domain_task_id: str | None = None,
        input_snapshot_hash: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.operation = operation
        self.input_version_ids = list(input_version_ids or [])
        self.output_version_ids = list(output_version_ids or [])
        self.parameters = dict(parameters or {})
        self.generator_version = generator_version
        self.status = status
        self.started_at = started_at or _now_iso()
        self.finished_at = finished_at
        # Bridge back to the domain workflow task this run represents.
        self.domain_task_id = domain_task_id
        self.input_snapshot_hash = input_snapshot_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "operation": self.operation,
            "input_version_ids": list(self.input_version_ids),
            "output_version_ids": list(self.output_version_ids),
            "parameters": dict(self.parameters),
            "generator_version": self.generator_version,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "domain_task_id": self.domain_task_id,
            "input_snapshot_hash": self.input_snapshot_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataRunRef":
        return cls(
            run_id=data["run_id"],
            operation=data["operation"],
            input_version_ids=data.get("input_version_ids"),
            output_version_ids=data.get("output_version_ids"),
            parameters=data.get("parameters"),
            generator_version=data.get("generator_version"),
            status=data.get("status", "running"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            domain_task_id=data.get("domain_task_id"),
            input_snapshot_hash=data.get("input_snapshot_hash"),
        )


class LineageEdge:
    """A directed edge: ``source`` (input version) → ``target`` (output version).

    The full ancestor walk is reconstructed by the catalog from these edges
    (``query_lineage``). Edges are stored eagerly so lineage survives even if
    intermediate runs are later reorganized.
    """

    __slots__ = ("source_version_id", "target_version_id", "run_id")

    def __init__(
        self,
        *,
        source_version_id: str,
        target_version_id: str,
        run_id: str | None = None,
    ) -> None:
        self.source_version_id = source_version_id
        self.target_version_id = target_version_id
        self.run_id = run_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_version_id": self.source_version_id,
            "target_version_id": self.target_version_id,
            "run_id": self.run_id,
        }
