"""Central legacy-project → WorkArea-domain migration (schema v1 → v2).

Deterministic + idempotent:

- Entities are discovered from existing ``resources`` using STRONG evidence
  only (``well_head`` files parsed via the canonical engine backend,
  ``seismic`` SEG-Y headers, LAS headers).  Filenames are never identity.
- Legacy ``ResourceItem`` rows are left untouched — old views keep working
  and the migration is reversible by ignoring the domain sections.
- Re-running on a migrated project is a no-op: resolution matches existing
  entities by UWI/canonical-name keys before creating new ones, so repeated
  open/save cycles never duplicate wells or surveys.
- Failure safety: every per-resource step is individually guarded; a parse
  failure becomes a report issue, never a raised exception, so opening an old
  project can never corrupt or block it.

The in-memory document is upgraded immediately (UI sees entities) while the
new schema reaches ``*.paleo.json`` only on the next successful save —
satisfying "save new schema only after successful migration" without
mutating user files behind their back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.domain_binding import BindingReport, bind_resources
from paleo_workbench.project.domain import ensure_workarea, sync_workarea_with_coordinate

SCHEMA_VERSION_LEGACY = 1
SCHEMA_VERSION_WORKAREA = 2


@dataclass
class WorkAreaMigrationReport:
    migrated: bool = False
    already_migrated: bool = False
    binding: BindingReport = field(default_factory=BindingReport)
    resources_scanned: int = 0
    resources_without_asset: int = 0

    @property
    def issues(self) -> list[str]:
        return self.binding.issues


def project_needs_domain_migration(project: Any) -> bool:
    """True when the document predates the WorkArea domain layer."""
    if getattr(project, "schema_version", SCHEMA_VERSION_LEGACY) >= SCHEMA_VERSION_WORKAREA:
        return False
    return (
        getattr(project, "workarea", None) is None
        and not getattr(project, "wells", None)
        and not getattr(project, "seismic_surveys", None)
        and not getattr(project, "entity_asset_links", None)
    )


def migrate_project_to_workarea(
    project: Any,
    *,
    asset_id_by_legacy: dict[str, str] | None = None,
    project_path: Path | None = None,
    engine: Any | None = None,
) -> WorkAreaMigrationReport:
    """Upgrade a legacy ProjectDocument to the WorkArea schema in memory.

    ``asset_id_by_legacy`` maps ResourceItem.id → catalog DataAsset.id.  When
    the catalog is unavailable the mapping may be empty/partial: entities are
    still created, links wait for a later pass (idempotent).
    """
    report = WorkAreaMigrationReport()
    if not project_needs_domain_migration(project):
        report.already_migrated = True
        # Late-binding pass: a previously migrated project may still carry
        # resources whose catalog assets appeared only after the initial
        # migration (e.g. first open had no catalog).  Bind ONLY resources
        # whose asset is not referenced by any existing link — idempotent
        # and free when everything is already linked.
        mapping = dict(asset_id_by_legacy or {})
        if mapping:
            linked_assets = {link.asset_id for link in getattr(project, "entity_asset_links", [])}
            pending = [
                r
                for r in sorted(
                    getattr(project, "resources", []) or [],
                    key=lambda item: str(getattr(item, "id", "")),
                )
                if str(getattr(r, "id", "")) in mapping
                and mapping[str(r.id)] not in linked_assets
            ]
            if pending:
                report.resources_scanned = len(pending)
                try:
                    report.binding = bind_resources(
                        project,
                        pending,
                        asset_id_by_legacy=mapping,
                        path_resolver=_default_path_resolver(project_path),
                        engine=engine,
                    )
                except Exception as exc:
                    report.binding.issues.append(f"补挂载失败: {exc.__class__.__name__}: {exc}")
        sync_workarea_with_coordinate(project)
        return report

    ensure_workarea(project)
    mapping = dict(asset_id_by_legacy or {})
    resolver = _default_path_resolver(project_path)
    resources = sorted(
        getattr(project, "resources", []) or [],
        key=lambda item: str(getattr(item, "id", "")),
    )
    report.resources_scanned = len(resources)

    try:
        report.binding = bind_resources(
            project,
            resources,
            asset_id_by_legacy=mapping,
            path_resolver=resolver,
            engine=engine,
        )
    except Exception as exc:  # never let migration break project open
        report.binding.issues.append(f"工区迁移中断: {exc.__class__.__name__}: {exc}")
        return report

    report.resources_without_asset = sum(1 for r in resources if str(r.id) not in mapping)
    project.schema_version = SCHEMA_VERSION_WORKAREA
    workarea = project.workarea
    if workarea is not None:
        workarea.metadata["migrated_from_schema"] = SCHEMA_VERSION_LEGACY
    sync_workarea_with_coordinate(project)
    report.migrated = True
    return report


def _default_path_resolver(project_path: Path | None):
    """Resolve resource paths against the open project file location."""

    def resolve(relative: str) -> Path:
        raw = Path(relative)
        if raw.is_absolute() or project_path is None:
            return raw
        try:
            from paleo_workbench.project.paths import resolve_project_path  # noqa: PLC0415

            return Path(resolve_project_path(relative, Path(project_path)))
        except Exception:
            return raw

    return resolve


def build_asset_id_mapping(service: Any) -> dict[str, str]:
    """legacy_resource_id → DataAsset.id map from a catalog service."""
    mapping: dict[str, str] = {}
    if service is None:
        return mapping
    try:
        assets = service.list_assets(include_trashed=False)
    except Exception:
        return mapping
    for asset in assets:
        legacy = getattr(asset, "legacy_resource_id", None)
        if legacy and legacy not in mapping:
            mapping[legacy] = asset.id
    return mapping
