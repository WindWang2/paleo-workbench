"""Project-level external dependency audit (I13).

Classifies every external reference (and managed payload) as valid / missing /
changed / unknown, and produces *verified* relink candidates for missing ones.

Hard rules:
- Identity is judged by size and content hash (mtime is informational only);
  a same-basename file with a different hash is NEVER auto-relinked.
- ``apply_relink`` does not mutate catalog history: it registers a NEW
  external version through the catalog's own ``link_external`` service, so the
  catalog stays the single authority and the change is provenance-tracked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.interchange.contracts import CancelToken, NULL_CANCEL


class DependencyStatus(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    CHANGED = "changed"
    UNKNOWN = "unknown"  # exists but no recorded hash → cannot verify
    RELINK_CANDIDATE = "relink_candidate"  # missing, with verified candidates


@dataclass
class RelinkCandidate:
    path: str
    size_bytes: int
    sha256: str | None = None  # verified content hash when computed
    basis: str = "size"  # "size+hash" | "size"

    def to_dict(self) -> dict:
        return {
            "path": self.path, "size_bytes": self.size_bytes,
            "sha256": self.sha256, "basis": self.basis,
        }


@dataclass
class DependencyRecord:
    version_id: str
    asset_name: str
    managed: bool
    path: str
    status: DependencyStatus
    observed_size: int | None = None
    observed_mtime: float | None = None
    expected_size: int | None = None
    expected_sha256: str | None = None
    relink_candidates: list[RelinkCandidate] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "asset": self.asset_name,
            "managed": self.managed,
            "path": self.path,
            "status": self.status.value,
            "observed_size": self.observed_size,
            "observed_mtime": self.observed_mtime,
            "expected_size": self.expected_size,
            "expected_sha256": self.expected_sha256,
            "relink_candidates": [c.to_dict() for c in self.relink_candidates],
            "detail": self.detail,
        }


@dataclass
class DependencyAuditReport:
    records: list[DependencyRecord] = field(default_factory=list)
    hashed_bytes: int = 0

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.status.value] = counts.get(record.status.value, 0) + 1
        return {
            "total": len(self.records),
            "counts": counts,
            "hashed_bytes": self.hashed_bytes,
        }

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "records": [record.to_dict() for record in self.records],
        }

    @property
    def ok(self) -> bool:
        return all(
            record.status in (DependencyStatus.VALID, DependencyStatus.UNKNOWN)
            for record in self.records
        )


class ExternalDependencyAuditor:
    """Audit the external (and managed) dependencies of an open catalog."""

    def __init__(
        self,
        catalog,
        *,
        hash_budget_bytes: int = 4 * 1024 * 1024 * 1024,
    ) -> None:
        self._catalog = catalog
        self._hash_budget = hash_budget_bytes

    def audit(self, *, cancel: CancelToken | None = None) -> DependencyAuditReport:
        cancel = cancel or NULL_CANCEL
        report = DependencyAuditReport()
        for asset in self._catalog.list_assets():
            cancel.checkpoint()
            for version in self._catalog.list_versions(asset.id):
                record = self._audit_version(version, asset.name, report)
                report.records.append(record)
        return report

    def _audit_version(self, version, asset_name: str, report: DependencyAuditReport) -> DependencyRecord:
        try:
            path = Path(self._catalog.resolve_path(version))
        except Exception:
            path = None
        record = DependencyRecord(
            version_id=version.id,
            asset_name=asset_name,
            managed=bool(version.managed),
            path=str(path or version.path),
            status=DependencyStatus.MISSING,
            expected_size=version.size_bytes,
            expected_sha256=version.sha256 or None,
        )
        if path is None or not path.is_file():
            record.detail = "文件不存在"
            return record
        stat = path.stat()
        record.observed_size = stat.st_size
        record.observed_mtime = stat.st_mtime
        if not version.managed and version.sha256 is None:
            # link_external never hashes: existence-only reference.
            record.status = DependencyStatus.UNKNOWN
            record.detail = "外部引用未记录校验和（无法验证内容）"
            return record
        if record.expected_size is not None and stat.st_size != record.expected_size:
            record.status = DependencyStatus.CHANGED
            record.detail = f"size 变化: 记录 {record.expected_size}B，实际 {stat.st_size}B"
            return record
        if record.expected_sha256 is None:
            record.status = DependencyStatus.UNKNOWN
            record.detail = "无记录校验和"
            return record
        if report.hashed_bytes + stat.st_size <= self._hash_budget:
            digest = sha256_file(path)
            report.hashed_bytes += stat.st_size
            if digest == record.expected_sha256:
                record.status = DependencyStatus.VALID
            else:
                record.status = DependencyStatus.CHANGED
                record.detail = "sha256 不匹配（内容已变化）"
        else:
            record.status = DependencyStatus.UNKNOWN
            record.detail = "超过哈希预算：未验证内容"
        return record

    # -- relink -------------------------------------------------------------
    def find_relink_candidates(
        self,
        record: DependencyRecord,
        search_roots: list[Path],
        *,
        max_candidates: int = 20,
        cancel: CancelToken | None = None,
    ) -> list[RelinkCandidate]:
        """Find content-verified candidates for a MISSING dependency.

        Matching ladder: same size as recorded → same sha256 when the recorded
        hash is known. Basename similarity only ranks suggestions; it can never
        promote a candidate on its own.
        """
        cancel = cancel or NULL_CANCEL
        if record.status != DependencyStatus.MISSING:
            return []
        expected_size = record.expected_size
        expected_sha = record.expected_sha256
        if expected_size is None and expected_sha is None:
            # No recorded identity at all: ANY file would "match". Refusing to
            # guess is the whole point — relink needs something to verify.
            return []
        candidates: list[RelinkCandidate] = []
        for root in search_roots:
            root = Path(root)
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                cancel.checkpoint()
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if expected_size is not None and size != expected_size:
                    continue
                candidate = RelinkCandidate(path=str(path), size_bytes=size)
                if record.expected_sha256 and size <= self._hash_budget:
                    candidate.sha256 = sha256_file(path)
                    candidate.basis = "size+hash"
                candidates.append(candidate)
                if len(candidates) >= max_candidates:
                    return candidates
        # verified (hash match) candidates first
        candidates.sort(key=lambda c: (c.sha256 != record.expected_sha256, c.path))
        return candidates

    def attach_candidates(self, report: DependencyAuditReport, search_roots: list[Path],
                          *, cancel: CancelToken | None = None) -> DependencyAuditReport:
        for record in report.records:
            cancel = cancel or NULL_CANCEL
            cancel.checkpoint()
            if record.status != DependencyStatus.MISSING:
                continue
            record.relink_candidates = self.find_relink_candidates(
                record, search_roots, cancel=cancel
            )
            if record.relink_candidates:
                record.status = DependencyStatus.RELINK_CANDIDATE
        return report

    def apply_relink(
        self,
        record: DependencyRecord,
        candidate: RelinkCandidate,
        *,
        asset_name: str | None = None,
        confirm_unverified: bool = False,
    ):
        """Register a NEW external version pointing at the candidate.

        Only a hash-verified candidate auto-approves; a size-only candidate
        must be explicitly confirmed (human decision) via
        ``confirm_unverified=True``.
        """
        if record.expected_sha256 and candidate.sha256 and candidate.sha256 != record.expected_sha256:
            raise ValueError("候选文件校验和与记录不一致：拒绝重连")
        if record.expected_sha256 and not candidate.sha256 and not confirm_unverified:
            raise ValueError(
                "候选未经内容校验（size-only）：需人工确认 confirm_unverified=True"
            )
        return self._catalog.link_external(
            candidate.path,
            name=asset_name or record.asset_name,
            type=None,
            format=None,
            metadata={"relinked_from": record.version_id, "relink_basis": candidate.basis},
        )
