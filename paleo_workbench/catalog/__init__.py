"""Data Catalog / Data Lifecycle Core (ADR 0056).

Public API for the canonical data architecture: DataAsset + immutable
DataVersion + managed storage + portable canonical metadata + SQLite index +
tags + lineage + integrity.

This package is the integration surface for the UI (Gemini branch) and
workflow (zcode branch) work:

- All lifecycle writes go through :class:`DataCatalogService` — never append
  to ``project.resources`` or hand-edit artifact files for cataloged data.
- ``DataAsset``/``DataVersion`` here are lifecycle models, unrelated to
  ``resources.data_asset_registry.DataAssetRegistry`` (format/IO registry)
  and to ``VersionSet``/``VersionSnapshot`` (expert map finalization).
- Legacy ``ResourceItem`` projects keep working; use
  ``DataCatalogService.migrate_legacy_resources`` for the deterministic,
  idempotent projection (asset ids reuse legacy resource ids).
"""

from paleo_workbench.catalog.checksum import sha256_file
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
from paleo_workbench.catalog.service import DataCatalogService, IntegrityReport
from paleo_workbench.catalog.store import CatalogStore

__all__ = [
    "CatalogDocument",
    "CatalogError",
    "CatalogIndex",
    "CatalogStore",
    "DataAsset",
    "DataCatalogService",
    "DataRun",
    "DataStage",
    "DataVersion",
    "ImmutableVersionError",
    "IntegrityReport",
    "MigrationReport",
    "Tag",
    "migrate_resources",
    "needs_migration",
    "normalize_tag_name",
    "sha256_file",
]
