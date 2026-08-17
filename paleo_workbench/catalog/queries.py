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
    tags: list[str] | tuple[str, ...] | None = None,
    tag_op: str = "and",
    type: str | None = None,
    metadata: dict | None = None,
    include_trashed: bool = False,
) -> list:
    """Filter assets by name substring, stage, tag(s), type, and/or metadata.

    ``tags`` accepts several tag names combined with ``tag_op`` (``"and"`` /
    ``"or"``); the single-``tag`` parameter is kept for compatibility and is
    unioned into ``tags``. ``metadata`` matches ``asset.metadata[key]`` by
    string equality (governance fields live there). Trashed (soft-deleted)
    assets are excluded unless ``include_trashed``. When the SQLite index is
    missing/unavailable the in-memory document scan below is used, so search
    always reflects the canonical document.
    """
    tag_list = [t for t in (list(tags) if tags else []) if str(t).strip()]
    if tag is not None and str(tag).strip():
        tag_list.append(str(tag))
    tag_list = [normalize_tag_name(t) for t in tag_list]
    if tag_op not in ("and", "or"):
        raise ValueError(f"tag_op must be 'and' or 'or', got {tag_op!r}")
    metadata_pairs = [
        (str(k), str(v))
        for k, v in (metadata or {}).items()
        if str(v).strip() != ""
    ]
    try:
        if service.index_revision() != service.document.catalog_revision:
            # A readable-but-stale index must not be queried (I3): only the
            # canonical document scan reflects the current state.
            raise RuntimeError("index stale — falling back to scan")
        rows = service._index.search_assets(
            text=text,
            stage=stage.value if stage else None,
            tags=tag_list or None,
            tag_op=tag_op,
            type=type,
            metadata=metadata_pairs or None,
        )
        # Use the service's maintained id→asset map (O(1) per row) instead of
        # rebuilding it per query, so a filtered search is O(result), not O(N).
        by_id = service._ensure_maps().asset_by_id
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
    if metadata_pairs:
        results = [
            a
            for a in results
            if all(
                str(a.metadata.get(k, "")) == v for k, v in metadata_pairs
            )
        ]
    if stage is not None:
        with_stage = {v.asset_id for v in service.document.versions if v.stage == stage}
        results = [a for a in results if a.id in with_stage]
    if tag_list:
        per_tag = [set(find_assets_by_tag(service, t)) for t in tag_list]
        if tag_op == "and":
            tagged: set[str] | None = None
            for ids in per_tag:
                tagged = ids if tagged is None else tagged & ids
        else:
            tagged = set()
            for ids in per_tag:
                tagged |= ids
        results = [a for a in results if a.id in (tagged or set())]
    return results
