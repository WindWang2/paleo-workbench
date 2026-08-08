"""Domain models for the Data Catalog / Data Lifecycle Core (ADR 0056).

This package is the canonical data architecture for asset lifecycle management:
DataAsset + immutable DataVersion + DataRun (provenance) + Tag. It is distinct
from ``paleo_workbench.resources.data_asset_registry.DataAssetRegistry`` (a
format/IO registry) and from ``VersionSet``/``VersionSnapshot`` (expert map
finalization semantics) — neither is replaced by these models.

Invariants enforced here and in ``service.DataCatalogService``:

- RAW managed versions are immutable once committed (ADR 0056).
- Any committed DataVersion is immutable; change produces a new version.
- Lifecycle stage is a first-class enum, never a plain tag.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from paleo_workbench.project.models import _id, _now_iso

CATALOG_SCHEMA_VERSION = 1


class DataStage(str, Enum):
    """Formal data lifecycle stages. Never express these via tags."""

    RAW = "raw"
    DERIVED = "derived"
    INTERMEDIATE = "intermediate"
    OUTPUT = "output"


class ImmutableVersionError(RuntimeError):
    """Raised when an operation would mutate a committed DataVersion."""


class CatalogError(RuntimeError):
    """Base error for catalog operations (missing asset/version, conflicts)."""


class DataAsset(BaseModel):
    """A logical data asset: stable identity plus current-version pointer."""

    id: str = Field(default_factory=lambda: _id("asset"))
    name: str
    type: str = "unknown"
    description: str = ""
    current_version_id: str | None = None
    # Set when this asset is a migration projection of a legacy ResourceItem;
    # the asset id then reuses the legacy resource id so existing references
    # (FactorMap/Prediction/WellTable/JointAnalysis/ExportArtifact) keep working.
    legacy_resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class DataVersion(BaseModel):
    """An immutable, committed version of a DataAsset.

    ``path`` is a project-relative POSIX path for managed versions and an
    absolute path for external (unmanaged) versions. ``sha256`` is the source
    of truth for integrity; a missing value means "not yet verifiable".
    """

    id: str = Field(default_factory=lambda: _id("ver"))
    asset_id: str
    version_number: int
    stage: DataStage
    managed: bool = True
    path: str = ""
    source_uri: str | None = None
    format: str = ""
    size_bytes: int | None = None
    sha256: str | None = None
    parent_version_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)


class DataRun(BaseModel):
    """A processing run: the provenance record linking input/output versions."""

    id: str = Field(default_factory=lambda: _id("run"))
    operation: str
    input_version_ids: list[str] = Field(default_factory=list)
    output_version_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    generator: str = ""
    status: str = "completed"
    created_at: str = Field(default_factory=_now_iso)


class Tag(BaseModel):
    """A normalized, queryable tag. ``name`` is unique after normalization."""

    id: str = Field(default_factory=lambda: _id("tag"))
    name: str
    display_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def normalize_tag_name(name: str) -> str:
    """Normalize a tag name: collapse whitespace, casefold for uniqueness."""
    return " ".join(str(name).split()).casefold()


class CatalogDocument(BaseModel):
    """Root of the portable canonical store (``metadata/catalog.json``).

    This is the single source of truth for catalog data; the SQLite database
    is a rebuildable index over it, keyed by ``catalog_revision``.
    """

    schema_version: int = CATALOG_SCHEMA_VERSION
    catalog_revision: int = 0
    assets: list[DataAsset] = Field(default_factory=list)
    versions: list[DataVersion] = Field(default_factory=list)
    runs: list[DataRun] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)
    # Association maps: asset_id -> [tag_id], version_id -> [tag_id].
    asset_tags: dict[str, list[str]] = Field(default_factory=dict)
    version_tags: dict[str, list[str]] = Field(default_factory=dict)
