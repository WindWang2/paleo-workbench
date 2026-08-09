"""Content-address storage for managed payloads (P4, staged dedup).

Full content-addressing (every version's ``path`` pointing at one shared
read-only blob) is the long-term direction, but a full migration of the
established ``{stage}/{asset}/{version}/{file}`` layout is deferred: the
trash/restore/purge lifecycle moves payloads per-version, which conflicts with
blob sharing until those paths are refcount-aware. This module ships the
dedup *abstraction* + duplicate detection + metrics now:

- ``blobs/`` payload directory: one file per SHA-256 (``blobs/{d[:2]}/{d}``),
  placed atomically, read-only, content-addressed by construction.
- ``place_blob`` — idempotent atomic placement; O(1) when the digest exists.
- ``has_blob`` — O(1) existence check (the import fast path).
- ``plan_blob_gc`` / ``sweep_unreferenced_blobs`` — reachability (refcount)
  GC: a blob is referenced iff a managed version record carries its digest.
- ``blob_metrics`` — duplication/storage reporting.

Version identity stays separate from physical blob identity: a ``DataVersion``
always carries its ``sha256`` (digest) and either a stage-copy path or a
blob path (``is_cas_path``). Version records never point at a missing blob:
blobs are placed atomically and only ever deleted when unreferenced.

Staged migration path (documented, not TODO): once trash/restore/purge are
fully refcount-aware, ``place_managed_file`` can point every managed version
at its blob (making stage dirs thin), then the stage layout is retired.

No writable hardlink is ever created to an immutable blob; deduped versions
reference the read-only blob directly, and integrity re-hashes the payload.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from paleo_workbench.catalog.checksum import CHUNK_SIZE
from paleo_workbench.catalog.models import CatalogDocument
from paleo_workbench.catalog.storage import catalog_dir_for, fsync_dir

BLOBS_DIRNAME = "blobs"


def blob_dir_for(project_path: str | Path) -> Path:
    """Return ``<project>.artifacts/blobs`` (content-address store root)."""
    return catalog_dir_for(Path(project_path)).parent / BLOBS_DIRNAME


def blob_path(project_path: str | Path, digest: str) -> Path:
    """Absolute path of the blob for *digest* (sharded by the first 2 chars)."""
    root = blob_dir_for(Path(project_path))
    return root / digest[:2] / digest


def is_cas_path(project_path: str | Path, rel_path: str) -> bool:
    """True when a project-relative payload path points into ``blobs/``.

    Blob-backed versions share their payload with other versions, so the
    lifecycle must treat them by refcount (never move/unlink a shared blob).
    """
    root = blob_dir_for(Path(project_path))
    candidate = root / rel_path
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except (ValueError, OSError):
        return False


def has_blob(project_path: str | Path, digest: str) -> bool:
    """O(1) existence check: is *digest* already in the content store?"""
    return bool(digest) and blob_path(project_path, digest).is_file()


def blob_size(project_path: str | Path, digest: str) -> int:
    """Size in bytes of an existing blob (0 when missing)."""
    path = blob_path(project_path, digest)
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _make_readonly(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    except OSError:
        pass


def _place_blob_bytes(project_path: str | Path, digest: str, source: Path) -> None:
    """Atomically place the content of *source* as the blob for *digest*.

    Idempotent: an existing blob is left untouched (content-addressed name
    guarantees equality). Temp file + fsync + rename + directory fsync; the
    blob is marked read-only.
    """
    root = blob_dir_for(Path(project_path))
    target_dir = root / digest[:2]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / digest
    if target.is_file():
        return
    fd, tmp_name = tempfile.mkstemp(prefix=".blob-", dir=str(target_dir))
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_name, target)
        fsync_dir(target_dir)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _make_readonly(target)


def place_blob(
    project_path: str | Path,
    source: Path,
    digest: str | None = None,
) -> tuple[bool, str]:
    """Register *source*'s content in the content store.

    Returns ``(newly_placed, digest)``. When *digest* is given it is trusted
    (the caller already hashed the bytes); otherwise it is computed by
    streaming *source* once. An already-present digest is O(1) and copies
    nothing (``newly_placed=False``).
    """
    source = Path(source)
    if digest is None:
        digest = _digest_of(source)
    if has_blob(project_path, digest):
        return False, digest
    _place_blob_bytes(project_path, digest, source)
    return True, digest


def _digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def referenced_digests(document: CatalogDocument) -> set[str]:
    """Digests reachable from managed version records (the GC keep-set).

    Every managed version's recorded ``sha256`` references its content, whether
    the payload is a stage copy or a shared blob.
    """
    return {
        v.sha256
        for v in document.versions
        if v.managed and v.sha256
    }


def scan_blobs(project_path: str | Path) -> dict[str, int]:
    """Map of every blob digest on disk to its size in bytes."""
    root = blob_dir_for(Path(project_path))
    if not root.is_dir():
        return {}
    blobs: dict[str, int] = {}
    for shard in root.iterdir():
        if not shard.is_dir():
            continue
        for blob_file in shard.iterdir():
            if blob_file.is_file() and blob_file.name not in (".", ".."):
                blobs[blob_file.name] = blob_file.stat().st_size
    return blobs


def plan_blob_gc(
    project_path: str | Path, document: CatalogDocument
) -> list[str]:
    """Unreferenced blobs: on disk but not reachable from any version record.

    Returns digest strings (dry-run safe; nothing is deleted). A blob becomes
    unreferenced after the last version carrying its digest is purged and the
    blob was left behind (e.g. a promoted copy whose source version was
    purged). ``referenced_digests`` is the refcount keep-set.
    """
    keep = referenced_digests(document)
    return [digest for digest in scan_blobs(project_path) if digest not in keep]


def sweep_unreferenced_blobs(
    project_path: str | Path, document: CatalogDocument
) -> list[str]:
    """Delete unreferenced blobs; returns the removed digests.

    Conservative by construction: the keep-set is every managed version's
    recorded digest, so a reachable committed ``DataVersion`` can never lose
    its payload here. Crash safety: a blob is only removed when zero version
    records reference it (removal is metadata-free).
    """
    removed: list[str] = []
    for digest in plan_blob_gc(project_path, document):
        path = blob_path(project_path, digest)
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        removed.append(digest)
        fsync_dir(path.parent)
    return removed


def blob_metrics(
    project_path: str | Path, document: CatalogDocument
) -> dict[str, object]:
    """Storage metrics for the content store (P4 reporting).

    ``blobs_on_disk`` / ``bytes_on_disk`` count what exists;
    ``referenced_digests`` / ``unreferenced_blobs`` split it by reachability;
    ``bytes_deduped`` is the physical saving from blob sharing (each
    referenced digest's size × (references − 1)).
    """
    blobs = scan_blobs(project_path)
    keep = referenced_digests(document)
    ref_counts: dict[str, int] = {}
    for version in document.versions:
        if version.managed and version.sha256 in blobs:
            ref_counts[version.sha256] = ref_counts.get(version.sha256, 0) + 1
    bytes_deduped = 0
    for digest, size in blobs.items():
        count = ref_counts.get(digest, 0)
        if count > 1:
            bytes_deduped += size * (count - 1)
    return {
        "blobs_on_disk": len(blobs),
        "bytes_on_disk": sum(blobs.values()),
        "referenced_digests": len(keep & set(blobs)),
        "unreferenced_blobs": len(set(blobs) - keep),
        "bytes_deduped": bytes_deduped,
    }


def blob_report(project_path: str | Path, document: CatalogDocument) -> dict:
    """JSON-serializable summary for tests/UI (mirrors :func:`blob_metrics`)."""
    metrics = blob_metrics(project_path, document)
    return {
        "metrics": metrics,
        "unreferenced": sorted(plan_blob_gc(project_path, document)),
        "referenced": sorted(referenced_digests(document)),
    }
