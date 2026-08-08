"""Catalog → UI display payload helpers.

These build the metadata the Data Manager UI (Gemini's ``feat/data-manager-ui2``)
needs to render provenance for a version. This is intentionally a *thin read*
over the catalog — it does not duplicate state, it only shapes it for display
(section 15 of the integration goal): Produced by Run X, Inputs A/B/C, Stage,
Version, Integrity, Path, Timestamp.

Gemini's UI files own the actual rendering; this module only provides the
contract payload so business-produced assets have enough metadata to show.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.catalog import CatalogPort, IntegrityStatus, get_catalog


def version_display_payload(
    version_id: str,
    *,
    catalog: CatalogPort | None = None,
) -> dict[str, Any] | None:
    """Build a display-ready metadata dict for a version (None if unknown).

    Shape (stable contract for the Data Manager UI)::

        {
          "version_id", "asset_id", "name", "stage", "path", "format", "kind",
          "external", "integrity", "checksum", "created_at", "tags",
          "producing_run_id", "producing_operation", "generator_version",
          "inputs": [{"version_id","name","stage"}, ...],   # direct ancestors
        }
    """
    cat = catalog or get_catalog()
    ref = cat.resolve_version(version_id)
    if ref is None:
        return None
    run = cat.resolve_run(ref.producing_run_id) if ref.producing_run_id else None
    direct_inputs = cat.direct_ancestors(version_id)
    return {
        "version_id": ref.version_id,
        "asset_id": ref.asset_id,
        "name": ref.name,
        "stage": ref.stage.value,
        "path": ref.path,
        "format": ref.format,
        "kind": ref.kind,
        "external": ref.external,
        "integrity": _integrity_label(cat.verify_integrity(version_id)),
        "checksum": ref.checksum,
        "created_at": ref.created_at,
        "tags": list(ref.tags),
        "producing_run_id": ref.producing_run_id,
        "producing_operation": run.operation if run else None,
        "generator_version": run.generator_version if run else None,
        "inputs": [
            {
                "version_id": i.version_id,
                "name": i.name,
                "stage": i.stage.value,
            }
            for i in direct_inputs
        ],
    }


def _integrity_label(status: IntegrityStatus) -> str:
    return {
        IntegrityStatus.VERIFIED: "verified",
        IntegrityStatus.MODIFIED: "modified",
        IntegrityStatus.MISSING: "missing",
        IntegrityStatus.UNKNOWN: "unknown",
    }.get(status, "unknown")
