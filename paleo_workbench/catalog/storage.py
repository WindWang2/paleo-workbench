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
import tempfile
from pathlib import Path

from paleo_workbench.catalog.checksum import CHUNK_SIZE
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.project.paths import artifact_dir_for

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


def fsync_dir(directory: Path) -> None:
    """Best-effort fsync of a directory so rename metadata survives a crash."""
    try:
        fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
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
) -> tuple[str, int, str]:
    """Copy *source* into managed storage atomically, hashing in one pass.

    Reads the source exactly once: streams it to a temp file in the target
    directory while accumulating SHA-256, then fsync + rename into place and
    marks the committed payload read-only.

    Returns ``(relative_path, size_bytes, sha256)``. On failure the temp file
    is removed and no partial payload is left behind.

    ``keep_source=False`` moves instead of copying (used when committing a
    working copy that is being promoted to immutable).
    """
    source = Path(source)
    root = ensure_catalog_layout(Path(project_path))
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
    _make_readonly(target)
    if not keep_source:
        try:
            source.unlink()
        except OSError:
            pass
    project_dir = Path(project_path).expanduser().resolve().parent
    return target.relative_to(project_dir).as_posix(), size, digest.hexdigest()


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
