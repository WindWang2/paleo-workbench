"""Data Catalog / Data Lifecycle Core (ADR 0056).

Public API for the canonical data architecture: DataAsset + immutable
DataVersion + managed storage + portable canonical metadata + SQLite index +
tags + lineage + integrity.

This package is the single authoritative Data Catalog. Integration surface:

- All lifecycle writes go through :class:`DataCatalogService` — never append
  to ``project.resources`` or hand-edit artifact files for cataloged data.
- ``DataAsset``/``DataVersion`` here are lifecycle models, unrelated to
  ``resources.data_asset_registry.DataAssetRegistry`` (format/IO registry)
  and to ``VersionSet``/``VersionSnapshot`` (expert map finalization).
- Legacy ``ResourceItem`` projects keep working; use
  ``DataCatalogService.migrate_legacy_resources`` for the deterministic,
  idempotent projection (asset ids reuse legacy resource ids).
- Business modules (pipeline / prediction / export / workflow) consume the
  thin :class:`CatalogPort` protocol via :func:`get_catalog`; in production
  the active backend is :class:`CoreCatalogAdapter` over the Core service.
  ``DataVersionRef`` / ``DataRunRef`` / ``LineageEdge`` / ``IntegrityStatus``
  are reference DTOs for that seam, not a second domain model. The
  ``InMemoryCatalog`` test fake lives under ``tests/fakes``.
"""

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.checksum import sha256_file, sha256_file_or_none
from paleo_workbench.catalog.db import CatalogIndex
from paleo_workbench.catalog.migration import (
    MigrationReport,
    migrate_resources,
    needs_migration,
)
from paleo_workbench.catalog.models import (
    CatalogDocument,
    CatalogError,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
    ImmutableVersionError,
    Tag,
    normalize_tag_name,
)
from paleo_workbench.catalog.port import CatalogPort
from paleo_workbench.catalog.runtime import (
    get_catalog,
    get_catalog_service,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.catalog.service import DataCatalogService, IntegrityReport
from paleo_workbench.catalog.store import CatalogStore
from paleo_workbench.catalog.types import (
    DataRunRef,
    DataVersionRef,
    IntegrityStatus,
    LineageEdge,
)

__all__ = [
    "CatalogDocument",
    "CatalogError",
    "CatalogIndex",
    "CatalogPort",
    "CatalogStore",
    "CoreCatalogAdapter",
    "DataAsset",
    "DataCatalogService",
    "DataRun",
    "DataRunRef",
    "DataStage",
    "DataVersion",
    "DataVersionRef",
    "ImmutableVersionError",
    "IntegrityReport",
    "IntegrityStatus",
    "LineageEdge",
    "MigrationReport",
    "Tag",
    "get_catalog",
    "get_catalog_service",
    "migrate_resources",
    "needs_migration",
    "normalize_tag_name",
    "reset_catalog",
    "set_catalog",
    "sha256_file",
    "sha256_file_or_none",
]
