"""Managed storage layout and atomic file placement (ADR 0056).

Evolves the existing ``<project>.artifacts/`` layout without relocating the
legacy ``factor_maps/predictions/paleomaps/qc/exports`` directories. Managed
files live at ``{stage_dir}/{asset_id}/{version_id}/{filename}`` and committed
files are placed atomically (temp file + fsync + rename + directory fsync).

Immutability: committed payloads are marked read-only as an accident guard;
the recorded SHA-256 remains the source of truth. Working copies are plain
writable copies — never hardlinks, so derived writes can never mutate the
managed original.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from paleo_workbench.catalog.checksum import CHUNK_SIZE
from paleo_workbench.catalog.models import CatalogError, DataStage
from paleo_workbench.project.paths import artifact_dir_for

BLOBS_DIRNAME = "blobs"

STAGE_DIRS = {
    DataStage.RAW: "raw",
    DataStage.DERIVED: "derived",
    DataStage.INTERMEDIATE: "intermediate",
    DataStage.OUTPUT: "outputs",
}
EXTRA_DIRS = ["working", "metadata", "trash"]


def catalog_dir_for(project_path: Path) -> Path:
    """Return ``<project>.artifacts/metadata`` (canonical store + SQLite live here)."""
    return artifact_dir_for(Path(project_path)) / "metadata"


def ensure_catalog_layout(project_path: Path) -> Path:
    """Create the catalog storage directories; returns the artifacts root."""
    root = artifact_dir_for(Path(project_path))
    for name in list(STAGE_DIRS.values()) + EXTRA_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def working_dir_for(project_path: Path) -> Path:
    return artifact_dir_for(Path(project_path)) / "working"


def trash_dir_for(project_path: Path) -> Path:
    """Return ``<project>.artifacts/trash`` (recoverable payloads live here)."""
    return artifact_dir_for(Path(project_path)) / "trash"


# ---------------------------------------------------------------------------
# Content-address store (P4 staged dedup). The blob LAYOUT lives here next to
# the other storage dirs; the GC/metrics semantics live in ``dedup.py``.
# ---------------------------------------------------------------------------


def blob_dir_for(project_path: Path) -> Path:
    """Return ``<project>.artifacts/blobs`` (content-address store root)."""
    return artifact_dir_for(Path(project_path)) / BLOBS_DIRNAME


def blob_path(project_path: Path, digest: str) -> Path:
    """Absolute path of the blob for *digest* (sharded by the first 2 chars)."""
    root = blob_dir_for(Path(project_path))
    return root / digest[:2] / digest


def is_cas_path(project_path: Path, rel_path: str) -> bool:
    """True when a project-relative payload path points into ``blobs/``.

    Accepts either a project-relative path (as stored on a ``DataVersion``,
    e.g. ``demo.artifacts/blobs/ab/<digest>``) or an absolute path. Blob-backed
    versions share their payload with other versions, so the lifecycle must
    treat them by refcount (never move/unlink a shared blob).
    """
    project = Path(project_path)
    candidate = Path(rel_path)
    if not candidate.is_absolute():
        candidate = _project_dir(project) / candidate
    blobs_root = blob_dir_for(project).resolve()
    try:
        return candidate.resolve().is_relative_to(blobs_root)
    except (ValueError, OSError):
        return False


def has_blob(project_path: Path, digest: str) -> bool:
    """O(1) existence check: is *digest* already in the content store?"""
    return bool(digest) and blob_path(project_path, digest).is_file()


def blob_size(project_path: Path, digest: str) -> int:
    """Size in bytes of an existing blob (0 when missing)."""
    try:
        return blob_path(project_path, digest).stat().st_size
    except OSError:
        return 0


def _digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _place_blob_bytes(project_path: Path, digest: str, source: Path) -> None:
    """Atomically place the content of *source* as the blob for *digest*.

    Idempotent: an existing blob is left untouched (the content-addressed name
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
    project_path: Path,
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
    if has_blob(Path(project_path), digest):
        return False, digest
    _place_blob_bytes(Path(project_path), digest, source)
    return True, digest


def _project_dir(project_path: Path) -> Path:
    """The directory that project-relative version paths resolve against."""
    return Path(project_path).expanduser().resolve().parent


def _prune_empty_ancestors(directory: Path, levels: int) -> None:
    """Best-effort removal of now-empty version/asset/stage directories."""
    target = directory
    for _ in range(levels):
        try:
            target.rmdir()
        except OSError:
            return
        target = target.parent


def trash_payload(project_path: Path, version_path: Path, version_id: str) -> str:
    """Move a managed payload into ``trash/{version_id}/``; returns the new
    project-relative path. Atomic same-filesystem move with directory fsyncs;
    raises ``CatalogError`` when the payload is missing (callers decide whether
    a metadata-only tombstone is acceptable).

    Blob-backed payloads (``blobs/``) are NEVER moved — the blob may be shared
    with other versions; their path is returned unchanged (refcount semantics).
    """
    source = Path(version_path)
    project = Path(project_path)
    if is_cas_path(project, _relpath_for(project, source)):
        return _relpath_for(project, source)
    if not source.is_file():
        raise CatalogError(f"Managed payload not found: {source}")
    root = ensure_catalog_layout(project)
    trash_dir = root / "trash" / version_id
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / source.name
    os.replace(source, target)
    fsync_dir(trash_dir)
    fsync_dir(source.parent)
    _prune_empty_ancestors(source.parent, 2)
    return target.relative_to(_project_dir(project)).as_posix()


def restore_payload(
    project_path: Path,
    version_path: Path,
    original_rel_path: str,
) -> str:
    """Move a trashed payload back to its original managed location.

    ``version_path`` is the current (trash) payload location, ``original_rel_path``
    the project-relative path recorded before trashing. Re-marks the payload
    read-only (managed immutability restored). Returns the restored
    project-relative path.

    Blob-backed payloads are never moved; the recorded blob path is returned
    unchanged (the blob stayed in ``blobs/`` the whole time).
    """
    source = Path(version_path)
    project = Path(project_path)
    if is_cas_path(project, _relpath_for(project, source)):
        return _relpath_for(project, source)
    if not source.is_file():
        raise CatalogError(f"Trashed payload not found: {source}")
    target = _project_dir(project) / original_rel_path
    if target.exists():
        raise CatalogError(f"Restore target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    _make_readonly(target)
    fsync_dir(target.parent)
    _prune_empty_ancestors(source.parent, 1)
    return target.relative_to(_project_dir(project)).as_posix()


def purge_trashed_payload(
    project_path: Path, version_path: Path, *, shared: bool = False
) -> None:
    """Permanently delete a trashed payload (purge only ever runs on trashed
    versions). Best-effort; missing payloads are treated as already gone.

    For blob-backed payloads ``shared`` must say whether another version still
    references the blob: a shared blob is left in place (the version record is
    the only thing being purged) and only unlinked when this was the last
    reference.
    """
    source = Path(version_path)
    project = Path(project_path)
    if is_cas_path(project, _relpath_for(project, source)):
        if shared:
            return
        try:
            source.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return
        fsync_dir(source.parent)
        return
    try:
        source.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return
    fsync_dir(source.parent)
    _prune_empty_ancestors(source.parent, 1)


def _relpath_for(project_path: Path, absolute: Path) -> str:
    """Project-relative POSIX path for an absolute path under the project."""
    return absolute.relative_to(_project_dir(project_path)).as_posix()


def fsync_dir(directory: Path) -> None:
    """Best-effort fsync of a directory so rename metadata survives a crash."""
    flag = getattr(os, "O_DIRECTORY", 0)
    if sys.platform == "win32" or not flag:
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY | flag)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _make_readonly(path: Path) -> None:
    """Best-effort read-only bit: accident guard, not a security boundary."""
    try:
        current = path.stat().st_mode
        path.chmod(current & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    except OSError:
        pass


def _make_writable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    except OSError:
        pass


def place_managed_file(
    source: Path,
    project_path: Path,
    stage: DataStage,
    asset_id: str,
    version_id: str,
    *,
    keep_source: bool = True,
    known_sha256: str | None = None,
    register_blob: bool = False,
) -> tuple[str, int, str]:
    """Copy *source* into managed storage atomically, hashing in one pass.

    Reads the source exactly once: streams it to a temp file in the target
    directory while accumulating SHA-256, then fsync + rename into place and
    marks the committed payload read-only.

    Dedup (P4): when *known_sha256* names a blob already present in the
    content store AND the source is the same size, no copy happens at all —
    the version's path points at the shared read-only blob (O(1), copy-free).
    The caller-provided digest is trusted (the adapter computes it with our
    own hasher before calling; integrity re-hashes the payload). With
    *register_blob*, the placed payload is also registered in the content
    store so later imports of the same content dedup to it.

    Returns ``(relative_path, size_bytes, sha256)``. On failure the temp file
    is removed and no partial payload is left behind.

    ``keep_source=False`` moves instead of copying (used when committing a
    working copy that is being promoted to immutable).
    """
    source = Path(source)
    project = Path(project_path)
    if known_sha256 is not None and has_blob(project, known_sha256):
        try:
            if source.stat().st_size == blob_size(project, known_sha256) \
                    and _digest_of(source) == known_sha256:
                # The caller's digest names an existing blob AND the source
                # content actually matches it: share the read-only blob, O(1)
                # (hash-only verification — never trust a size+digest pair
                # without content proof, or a stale digest could silently link
                # a version to content that differs from the source file).
                blob = blob_path(project, known_sha256)
                if not keep_source:
                    # Dedup hit must not orphan the source working file in
                    # working/{version_id}/ (same move semantics as below).
                    try:
                        source.unlink()
                    except OSError:
                        pass
                project_dir = _project_dir(project)
                return blob.relative_to(project_dir).as_posix(), blob.stat().st_size, known_sha256
        except OSError:
            pass  # source unreadable → fall through to the normal copy path
    root = ensure_catalog_layout(project)
    target_dir = root / STAGE_DIRS[stage] / asset_id / version_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists():
        raise FileExistsError(f"Managed payload already exists: {target}")

    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(prefix=".place-", dir=str(target_dir))
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                out.write(chunk)
                size += len(chunk)
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
    hex_digest = digest.hexdigest()
    if known_sha256 is not None and known_sha256 != hex_digest:
        # Honest checksum: never silently adopt a caller-provided digest that
        # does not match the bytes actually placed.
        try:
            target.unlink()
        except OSError:
            pass
        raise CatalogError(
            f"Checksum mismatch for {source}: caller reported {known_sha256},"
            f" actual {hex_digest}"
        )
    _make_readonly(target)
    if register_blob:
        place_blob(project, target, hex_digest)
    if not keep_source:
        try:
            source.unlink()
        except OSError:
            pass
    project_dir = _project_dir(project)
    return target.relative_to(project_dir).as_posix(), size, hex_digest


def create_working_copy(project_path: Path, version_path: Path, version_id: str) -> Path:
    """Copy a committed payload into ``working/`` as a mutable file.

    Always a full copy (never a hardlink) so edits cannot touch the managed
    original. The copy is left writable regardless of the source's read-only bit.
    """
    version_path = Path(version_path)
    target_dir = working_dir_for(Path(project_path)) / version_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / version_path.name
    if target.exists():
        _make_writable(target)
        target.unlink()
    shutil.copyfile(version_path, target)
    _make_writable(target)
    fsync_dir(target_dir)
    return target
