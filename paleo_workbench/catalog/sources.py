"""Missing-source detection and explicit relink (catalog-scale-v5 D9).

Two operations the lifecycle previously lacked:

* :func:`find_missing_sources` — a stat-only scan over live versions that
  reports payloads the recorded path can no longer resolve. Derived state,
  never persisted: a scan that wrote "missing" flags into the canonical
  store would multiply writes and fight the cross-process revision guard.
* :func:`relink_external_source` — the explicit, fail-closed re-pointing of
  an EXTERNAL version's path after its file moved. Identity against the
  recorded facts is mandatory (sha256 first, then the recorded
  size+mtime_ns fingerprint); anything else refuses with
  :class:`CatalogRelinkIdentityError` — a same-basename stranger is the
  exact silent-rebinding #1140 forbids. Every success appends an auditable
  entry to ``version.metadata["relink_history"]`` (inside the canonical
  store — no second authority).

Managed payloads are deliberately NOT relinkable: a missing managed payload
is corruption/theft, not relocation — re-import it (new version).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from paleo_workbench.catalog.checksum import sha256_file_or_none
from paleo_workbench.catalog.db import DirtySet
from paleo_workbench.catalog.models import CatalogError, DataStage, DataVersion

EXTERNAL_STAT_KEY = "external_stat"
RELINK_HISTORY_KEY = "relink_history"


class CatalogRelinkIdentityError(CatalogError):
    """Raised when a relink candidate cannot be proven to be the same data."""


@dataclass
class MissingSource:
    """One live version whose payload cannot be resolved."""

    version_id: str
    asset_id: str
    asset_name: str
    stage: DataStage
    managed: bool
    recorded_path: str
    source_uri: str | None
    size_bytes: int | None
    relinkable: bool  # external + stage RAW（relink 只改引用，不改科学身份）
    recorded_fingerprint: dict | None = None


@dataclass
class MissingSourceReport:
    entries: list[MissingSource] = field(default_factory=list)
    scanned: int = 0

    @property
    def relinkable(self) -> list[MissingSource]:
        return [entry for entry in self.entries if entry.relinkable]

    def by_asset(self) -> dict[str, list[MissingSource]]:
        grouped: dict[str, list[MissingSource]] = {}
        for entry in self.entries:
            grouped.setdefault(entry.asset_id, []).append(entry)
        return grouped


def _probe_path(service, version: DataVersion) -> Path:
    """The path a missing-scan must check (cheap ladder, no identity probe)."""
    project_dir = service.project_path.expanduser().resolve().parent
    raw = Path(version.path or "")
    if version.managed:
        return project_dir / version.path
    if raw.is_absolute():
        return raw
    return project_dir / raw


def find_missing_sources(
    service,
    *,
    include_managed: bool = True,
    cancel: Callable[[], bool] | None = None,
) -> MissingSourceReport:
    """Stat-only scan for live versions whose payload is gone.

    ``cancel`` is polled per version (UI worker cooperation). The scan is
    O(versions) with one stat per entry — run it off the GUI thread.
    """
    report = MissingSourceReport()
    maps = service._ensure_maps()
    for version in service.document.versions:
        if cancel is not None and cancel():
            break
        if version.trashed:
            continue
        if not include_managed and version.managed:
            continue
        report.scanned += 1
        asset = maps.asset_by_id.get(version.asset_id)
        probe = _probe_path(service, version)
        try:
            resolved = probe.is_file()
        except OSError:
            resolved = False
        if resolved:
            continue
        fingerprint = version.metadata.get(EXTERNAL_STAT_KEY)
        report.entries.append(
            MissingSource(
                version_id=version.id,
                asset_id=version.asset_id,
                asset_name=asset.name if asset is not None else version.asset_id,
                stage=version.stage,
                managed=version.managed,
                recorded_path=version.path,
                source_uri=version.source_uri,
                size_bytes=version.size_bytes,
                relinkable=(not version.managed)
                and version.stage == DataStage.RAW,
                recorded_fingerprint=fingerprint
                if isinstance(fingerprint, dict)
                else None,
            )
        )
    return report


def relink_external_source(
    service,
    version_id: str,
    new_path: str | Path,
    *,
    actor: str = "user",
) -> DataVersion:
    """Re-point an external RAW version at its relocated file — fail-closed.

    Identity must be provable against RECORDED facts:

    1. recorded ``sha256`` matches the candidate's digest (strong proof);
    2. the recorded ``external_stat`` fingerprint (size + mtime_ns, written
       by :func:`link_external` and by earlier relinks) matches the
       candidate's stat.

    Everything else — including a size-only match on legacy links with no
    fingerprint — refuses. A successful relink updates the pointer fields,
    records the new fingerprint, and appends to ``relink_history``; the
    payload itself is never touched and RAW identity (the digest, once
    known) never changes.
    """
    candidate = Path(new_path).expanduser()
    with service._lock:
        version = service._version_or_raise(version_id)
        if version.trashed:
            raise CatalogError("Cannot relink a trashed version (restore it first)")
        if version.managed:
            raise CatalogRelinkIdentityError(
                "托管版本的载荷缺失属于损坏，不能改链接；请重新导入生成新版本"
            )
        if version.stage != DataStage.RAW:
            raise CatalogRelinkIdentityError(
                "只有外部 RAW 版本支持 relink；派生数据请重新生成"
            )
        if not candidate.is_file():
            raise CatalogRelinkIdentityError(f"Candidate file not found: {candidate}")
        candidate = candidate.resolve()
        stat = candidate.stat()

        proof = _identity_proof(version, candidate)
        if proof is None:
            raise CatalogRelinkIdentityError(
                "无法证明新文件与记录是同一份数据（sha256 与 size+mtime 指纹均不符或缺失）。"
                "为避免静默错绑已拒绝；若确为新数据，请走导入生成新版本。"
            )

        old_path = version.path
        old_stat = version.metadata.get(EXTERNAL_STAT_KEY)
        history = list(version.metadata.get(RELINK_HISTORY_KEY) or [])
        prior_fields = (version.path, version.source_uri, version.size_bytes, dict(version.metadata))
        try:
            version.path = candidate.as_posix()
            version.source_uri = candidate.as_posix()
            version.size_bytes = stat.st_size
            version.metadata[EXTERNAL_STAT_KEY] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
            history.append(
                {
                    "at": _now_iso(),
                    "proof": proof,
                    "old_path": old_path,
                    "new_path": version.path,
                    "actor": actor,
                }
            )
            version.metadata[RELINK_HISTORY_KEY] = history
            service._save(DirtySet(versions={version.id: None}))
        except Exception:
            (
                version.path,
                version.source_uri,
                version.size_bytes,
                version.metadata,
            ) = prior_fields
            raise
        return version


def _identity_proof(version: DataVersion, candidate: Path) -> str | None:
    """The recorded-fact proof tier for a relink, or None."""
    recorded_sha = version.sha256
    if recorded_sha:
        candidate_sha = sha256_file_or_none(candidate)
        if candidate_sha is None:
            return None
        if candidate_sha != recorded_sha:
            return None
        return "sha256"
    fingerprint = version.metadata.get(EXTERNAL_STAT_KEY)
    if isinstance(fingerprint, dict):
        stat = candidate.stat()
        if (
            fingerprint.get("size") == stat.st_size
            and fingerprint.get("mtime_ns") == stat.st_mtime_ns
        ):
            return "stat_fingerprint"
    return None


def _now_iso() -> str:
    from paleo_workbench.project.models import _now_iso

    return _now_iso()
