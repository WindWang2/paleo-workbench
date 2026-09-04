"""Legacy ``ResourceItem`` → catalog projection migration (ADR 0056, D2).

One-way, deterministic, idempotent projection from the legacy
``ProjectDocument.resources: list[ResourceItem]`` (stored in ``.paleo.json``)
into the canonical :class:`CatalogDocument` (``metadata/catalog.json``). Each
``ResourceItem`` becomes exactly one ``DataAsset`` plus one RAW ``DataVersion``;
the asset id reuses the legacy resource id (``res_xxx``) and
``legacy_resource_id`` is recorded, so existing references held by
FactorMap/Prediction/WellTable/JointAnalysis/ExportArtifact keep working.

The migration is a pure metadata projection: it never mutates ``ResourceItem``,
never touches ``.paleo.json``, never copies files, and never re-hashes payloads
(file materialization and integrity work belong to the service layer).
Because no file is ever copied, NO projected version is ``managed``: every
legacy resource is registered as an unmanaged link to the user's file in
place (absolute path), which is exactly what the audit's ``path_mismatch``
rule expects from unmanaged versions. Registering the original in-place file
as "managed" violated the managed layout contract and made the health audit
report permanent MEDIUM ``path_mismatch`` for every legacy resource
(issue #396 / C34).

Idempotence: re-running with the same document skips resources already
represented in it — either as a projected asset (id == resource id) or as an
adapter-registered asset bridged via ``legacy_resource_id`` (counted in
``skipped_count``). Determinism: version ids are derived from the resource id
and timestamps come from an injectable clock, so migrating the same resources
into fresh documents yields identical documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataStage,
    DataVersion,
)
from paleo_workbench.catalog.storage import is_safe_entity_id
from paleo_workbench.project.models import _id, _now_iso, ResourceItem
from paleo_workbench.project.paths import project_dir_for

# Candidate parsed_summary keys that may hold the original absolute path.
_ABS_PATH_KEYS = ("source_path", "absolute_path", "path")


@dataclass
class MigrationReport:
    """Outcome of one legacy resources → catalog projection run."""

    migrated_count: int = 0
    skipped_count: int = 0
    asset_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _absolute_posix(path: str, project_dir: Path) -> str:
    """Return *path* as an absolute POSIX path, verbatim when already absolute."""
    p = Path(path)
    if p.is_absolute():
        return p.as_posix()
    return (project_dir / p).resolve().as_posix()


def _file_path(resource: ResourceItem, project_dir: Path) -> Path:
    """The on-disk location of a resource: absolute or joined to the project."""
    p = Path(resource.path)
    return p if p.is_absolute() else project_dir / p


def _file_exists(resource: ResourceItem, project_dir: Path) -> bool:
    return _file_path(resource, project_dir).exists()


def _stored_path(
    resource: ResourceItem, project_path: Path, project_dir: Path
) -> tuple[str, bool]:
    """Return the projected version's ``(path, managed)``.

    The migration never copies files, so no legacy resource is ``managed``
    (managed = immutable copy under ``<project>.artifacts/<stage>/...``):
    every projected version links the user's file in place as an unmanaged
    version with an absolute path. Projecting the original in-place file as
    managed violated the managed path layout and made the health audit
    report permanent MEDIUM ``path_mismatch`` for every legacy resource
    (issue #396 / C34).
    """
    return _absolute_posix(resource.path, project_dir), False


def _source_uri(resource: ResourceItem) -> str | None:
    """Original absolute path when derivable, else None."""
    if resource.path and Path(resource.path).is_absolute():
        return Path(resource.path).as_posix()
    for key in _ABS_PATH_KEYS:
        value = resource.parsed_summary.get(key)
        if isinstance(value, str) and value and Path(value).is_absolute():
            return value
    return None


def _size_bytes(resource: ResourceItem) -> int | None:
    value = resource.parsed_summary.get("size_bytes")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _legacy_metadata(resource: ResourceItem) -> dict[str, Any]:
    """Legacy resource state preserved on the projected asset and version.

    Tags stay as the original string list under ``legacy_tags``; they are not
    upgraded to :class:`Tag` entities here — that is an explicit service action.
    """
    metadata: dict[str, Any] = {"legacy_tags": list(resource.tags)}
    for key in ("status", "source", "artifact_role", "crs"):
        value = getattr(resource, key, None)
        if value is not None:
            metadata[key] = value
    return metadata


def _existing_resource_ids(document: CatalogDocument) -> set[str]:
    """Legacy resource ids already represented in the catalog.

    Includes both projected assets (id == legacy resource id) and assets
    registered through the adapter/UI import path, which carry a generated id
    but record the bridge via ``legacy_resource_id``. Without the latter,
    migration would project a second phantom asset for the same resource.
    """
    ids: set[str] = set()
    for asset in document.assets:
        ids.add(asset.id)
        if asset.legacy_resource_id is not None:
            ids.add(asset.legacy_resource_id)
    return ids


def migrate_resources(
    resources: list[ResourceItem],
    project_path: Path,
    document: CatalogDocument,
    *,
    now: Callable[[], str] | None = None,
) -> MigrationReport:
    """Project each unmigrated ``ResourceItem`` into *document* in place.

    Each resource becomes one ``DataAsset`` (id reused from the resource id,
    ``legacy_resource_id`` set) plus one RAW ``DataVersion`` (version 1).
    Resources already present in *document* are skipped and counted.

    ``now`` supplies the created/updated timestamps (injectable for
    deterministic tests); defaults to the catalog's ``_now_iso``.

    Robustness: a missing file produces a warning but does not stop the
    migration; ``checksum=None`` maps to ``sha256=None`` without re-hashing.
    """
    now_fn = now or _now_iso
    project_dir = project_dir_for(project_path)
    existing_ids = _existing_resource_ids(document)
    report = MigrationReport()

    for resource in resources:
        if resource.id in existing_ids:
            report.skipped_count += 1
            continue
        if not _file_exists(resource, project_dir):
            report.warnings.append(
                f"resource {resource.id}: file not found at "
                f"{_file_path(resource, project_dir).resolve().as_posix()}"
            )
        path, managed = _stored_path(resource, project_path, project_dir)
        legacy = _legacy_metadata(resource)
        timestamp = now_fn()
        # #1175: the resource id becomes the asset id, which storage joins
        # into managed paths ({stage}/{asset_id}/{version_id}/) when the
        # resource is later materialized. A user-crafted id carrying ``/``,
        # ``..`` or an absolute prefix is sanitized to a fresh safe id; the
        # ORIGINAL id is still recorded as ``legacy_resource_id`` (a pure
        # map key, never a path segment) so existing references resolve.
        asset_id = resource.id
        if not is_safe_entity_id(asset_id):
            asset_id = _id("asset")
            report.warnings.append(
                f"resource {resource.id}: id unsafe as storage path segment; "
                f"migrated under sanitized asset id {asset_id}"
            )

        version = DataVersion(
            id=f"ver_{asset_id}",
            asset_id=asset_id,
            version_number=1,
            stage=DataStage.RAW,
            managed=managed,
            path=path,
            source_uri=_source_uri(resource),
            format=resource.format,
            size_bytes=_size_bytes(resource),
            sha256=resource.checksum,
            metadata=dict(legacy),
            created_at=timestamp,
        )
        asset = DataAsset(
            id=asset_id,
            name=resource.name,
            type=resource.type,
            current_version_id=version.id,
            legacy_resource_id=resource.id,
            metadata=dict(legacy),
            created_at=timestamp,
            updated_at=timestamp,
        )
        document.assets.append(asset)
        document.versions.append(version)
        existing_ids.add(resource.id)
        report.migrated_count += 1
        report.asset_ids.append(asset_id)

    return report


def needs_migration(
    resources: list[ResourceItem], document: CatalogDocument
) -> list[ResourceItem]:
    """Return the subset of *resources* not yet projected into *document*."""
    existing_ids = _existing_resource_ids(document)
    return [r for r in resources if r.id not in existing_ids]
