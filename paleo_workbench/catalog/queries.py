"""Query/integrity collaborator functions for :class:`DataCatalogService` (private).

The queries and integrity sections of ``catalog/service.py`` (behind the
``# -- integrity --`` / ``# -- search --`` banners) extracted into a private
collaborator module. Each function takes the service as its first argument and
is composed by the service's thin delegator methods — the PUBLIC API of
``DataCatalogService`` (including :class:`IntegrityReport`, re-exported from
``catalog.service``) stays identical.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.models import DataStage, normalize_tag_name

from .tags import find_assets_by_tag


@dataclass
class IntegrityReport:
    """Result of :meth:`DataCatalogService.verify_integrity`.

    Statuses: ``verified`` (hash matches), ``modified`` (hash mismatch — the
    catalog record is NOT updated), ``missing`` (payload gone), ``unknown``
    (no recorded hash to verify against, e.g. an unhashed external link).
    """

    statuses: dict[str, str] = field(default_factory=dict)

    def status_for(self, version_id: str) -> str:
        return self.statuses.get(version_id, "unknown")

    @property
    def ok(self) -> bool:
        return all(s in ("verified", "unknown") for s in self.statuses.values())


def verify_integrity(service, version_id: str | None = None) -> IntegrityReport:
    """Re-hash payloads and compare against recorded SHA-256.

    Reports only; a mismatch never updates the catalog. Hashing streams in
    chunks; wrap in a worker thread for large batches in UI contexts.
    Trashed versions are skipped (their payloads live in ``trash/``).
    """
    with service._lock:
        if version_id is not None:
            versions = [
                service._version_or_raise(version_id)
            ]
        else:
            versions = list(service.document.versions)
    report = IntegrityReport()
    for version in versions:
        if version.trashed:
            continue
        payload = service.resolve_path(version)
        if not payload.is_file():
            report.statuses[version.id] = "missing"
            continue
        if not version.sha256:
            report.statuses[version.id] = "unknown"
            continue
        try:
            actual = sha256_file(payload)
        except OSError:
            report.statuses[version.id] = "missing"
            continue
        report.statuses[version.id] = (
            "verified" if actual == version.sha256 else "modified"
        )
    return report


def search_assets(
    service,
    *,
    text: str | None = None,
    stage: DataStage | None = None,
    tag: str | None = None,
    type: str | None = None,
    include_trashed: bool = False,
) -> list:
    """Filter assets by name substring, stage, tag, and/or type.

    Trashed (soft-deleted) assets are excluded unless ``include_trashed``.
    When the SQLite index is missing/unavailable the in-memory document scan
    below is used, so search always reflects the canonical document.
    """
    try:
        if service.index_revision() is None:
            raise RuntimeError("index unavailable — falling back to scan")
        rows = service._index.search_assets(
            text=text,
            stage=stage.value if stage else None,
            tag=normalize_tag_name(tag) if tag else None,
            type=type,
        )
        by_id = {a.id: a for a in service.document.assets}
        return [
            by_id[r["id"]]
            for r in rows
            if r["id"] in by_id and (include_trashed or not by_id[r["id"]].trashed)
        ]
    except Exception:
        pass
    results = list(service.document.assets)
    if not include_trashed:
        results = [a for a in results if not a.trashed]
    if text:
        needle = text.casefold()
        results = [a for a in results if needle in a.name.casefold()]
    if type:
        results = [a for a in results if a.type == type]
    if stage is not None:
        with_stage = {v.asset_id for v in service.document.versions if v.stage == stage}
        results = [a for a in results if a.id in with_stage]
    if tag:
        tagged = set(find_assets_by_tag(service, tag))
        results = [a for a in results if a.id in tagged]
    return results
