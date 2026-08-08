"""Data Catalog seam package.

Thin adapter layer between workbench business modules and the canonical Data
Catalog Core (``feat/data-catalog-core``). See :mod:`paleo_workbench.catalog.port`.

Public surface:
- :class:`DataStage`, :class:`IntegrityStatus` — stage / integrity enums.
- :class:`DataVersionRef`, :class:`DataRunRef`, :class:`LineageEdge` — refs.
- :class:`CatalogPort` — the protocol the Core must satisfy.
- :class:`InMemoryCatalog` — reference backend (fallback while Core is absent).
- :func:`get_catalog` / :func:`set_catalog` — runtime backend accessor.
- :func:`sha256_of_file` — shared checksum helper (no duplicate impls).
"""

from __future__ import annotations

from paleo_workbench.catalog.backend import InMemoryCatalog, sha256_of_file
from paleo_workbench.catalog.port import CatalogPort
from paleo_workbench.catalog.runtime import get_catalog, reset_catalog, set_catalog
from paleo_workbench.catalog.types import (
    DataRunRef,
    DataStage,
    DataVersionRef,
    IntegrityStatus,
    LineageEdge,
)

__all__ = [
    "CatalogPort",
    "DataRunRef",
    "DataStage",
    "DataVersionRef",
    "InMemoryCatalog",
    "IntegrityStatus",
    "LineageEdge",
    "get_catalog",
    "reset_catalog",
    "set_catalog",
    "sha256_of_file",
]
