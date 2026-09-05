from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
import shutil

logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)


class ProjectPathError(ValueError):
    """Raised when a stored path is invalid or escapes the project directory."""


def safe_file_stat(path: Path) -> tuple[int, int] | None:
    """Return ``(size, mtime_ns)`` for cache keys, or None if the path is unreadable.

    Canonical stat helper shared by preview parsers, the in-memory preview cache,
    and the disk preview cache. ``OSError`` (missing file / permission) → None
    so callers can treat unreadable paths as cache misses.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def artifact_dir_for(project_path: Path) -> Path:
    project_name = project_path.name.removesuffix(".paleo.json")
    return project_path.with_name(f"{project_name}.artifacts")


import os
import stat
import sys


def _handle_remove_readonly(func, path, exc_info=None):
    """Clear readonly bit and reattempt removal on Windows NTFS.

    A failure here propagates: swallowing it inside the handler made
    ``shutil.rmtree`` report success while entries were left behind (#1190).
    """
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    func(path)


def safe_rmtree(path: Path | str) -> bool:
    """Safely remove a directory tree, clearing Windows read-only flags on demand.

    #1190: returns True when the tree is gone (or never existed) so
    transaction layers can tell "cleared" from "still there" instead of
    guessing through a swallowed error. Never raises for removal failures.
    """
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return True
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(
                p, onexc=lambda func, path, exc: _handle_remove_readonly(func, path, exc)
            )
        else:
            shutil.rmtree(p, onerror=_handle_remove_readonly)
    except Exception:
        pass
    if p.exists() or p.is_symlink():
        try:
            shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass
    gone = not p.exists() and not p.is_symlink()
    if not gone:
        logger.warning("safe_rmtree could not remove %s", p)
    return gone


@dataclass
class StagedArtifactRelocation:
    """A reversible Save As artifact move/copy transaction.

    It stages only the project-managed artifact tree.  ``commit`` is called
    only after the target project JSON has landed atomically; ``rollback`` is
    used when target metadata persistence fails.  This keeps the old portable
    project usable instead of leaving it pointing at a tree already moved.
    """

    source: Path
    target: Path
    moved_root: bool = False
    copied_root: bool = False
    preserved_source: bool = False
    moved_children: list[tuple[Path, Path]] = field(default_factory=list)

    @property
    def staged(self) -> bool:
        return (
            self.moved_root
            or self.copied_root
            or self.preserved_source
            or bool(self.moved_children)
        )

    def commit(self) -> bool:
        """Finalize a source-preserving copy only after target metadata is durable.

        Returns True when nothing remains to clean. A False return means the
        target is durable but source debris is still present (safe direction —
        the old project stays usable); the caller decides whether to surface it.
        """
        if not (self.copied_root or self.preserved_source):
            return True
        return safe_rmtree(self.source)

    def rollback(self) -> bool:
        """Best-effort reversal limited to entries this transaction owns.

        Returns True when every owned entry was restored/removed; False
        leaves the transaction state inspectable for diagnostics.
        """
        ok = True
        if self.moved_root and self.target.exists() and not self.source.exists():
            try:
                self.target.rename(self.source)
            except OSError:
                ok = False
        elif (self.copied_root or self.preserved_source) and self.target.exists():
            if not safe_rmtree(self.target):
                ok = False
        for source, target in reversed(self.moved_children):
            if target.exists() and not source.exists():
                try:
                    target.rename(source)
                except OSError:
                    ok = False
        if self.moved_children:
            try:
                self.target.rmdir()
            except OSError:
                pass
        return ok


def stage_artifact_relocation(
    old_project_path: Path, new_project_path: Path
) -> StagedArtifactRelocation:
    """Stage a reversible artifact relocation for a Save As transaction.

    Fresh targets are copied while retaining the old tree until
    :meth:`StagedArtifactRelocation.commit`, so a failed or interrupted target
    save cannot orphan the source project.  Existing target roots only receive
    missing direct children and are also reversible.
    """

    source = artifact_dir_for(Path(old_project_path))
    target = artifact_dir_for(Path(new_project_path))
    staged = StagedArtifactRelocation(source=source, target=target)
    if source == target or not source.is_dir():
        return staged
    if not target.exists():
        try:
            shutil.copytree(source, target)
            staged.preserved_source = True
            return staged
        except Exception:
            if target.exists() and not safe_rmtree(target):
                logger.warning("staged relocation cleanup failed for %s", target)
            raise
    try:
        for child in source.iterdir():
            destination = target / child.name
            if not destination.exists():
                child.rename(destination)
                staged.moved_children.append((child, destination))
    except Exception:
        staged.rollback()
        raise
    return staged


def relocate_artifacts(old_project_path: Path, new_project_path: Path) -> bool:
    """Re-home ``<old>.artifacts/`` to the save-as location; True when moved.

    Fixes the orphan-on-save-as hazard: previously ``save_project_as`` wrote
    the project file to the new path and opened a FRESH catalog there, leaving
    the old ``.artifacts/`` (payloads + catalog + index + working copies +
    trash) stranded and forcing a full re-import at the new location.

    Rules (conservative, never destroys data):

    - Same artifacts location (or no source artifacts) → no-op.
    - Target artifacts dir absent → recursively copy then remove the source
      after the standalone relocation commits.  Transactional Save As uses
      :func:`stage_artifact_relocation` and preserves the source until target
      metadata is durable.
    - Target artifacts dir already present → merge only the subdirectories the
      target lacks; conflicting subdirectories are left untouched (both sides
      hold data that must not be overwritten).

    Returns True when anything was moved/merged, False otherwise. Raises on
    unrecoverable IO errors (callers decide whether saving may still proceed).
    """
    staged = stage_artifact_relocation(old_project_path, new_project_path)
    staged.commit()
    return staged.staged


def ensure_artifact_layout(project_path: Path) -> Path:
    root = artifact_dir_for(project_path)
    for name in [
        "cache",
        "factor_maps",
        "predictions",
        "paleomaps",
        "qc",
        "exports",
        "thumbnails",
    ]:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def rebase_owned_artifact_path(
    raw: str,
    *,
    old_root: Path,
    new_root: Path,
    project_dir: Path | None = None,
) -> str | None:
    """Rewrite a project-owned artifact path after Save As relocation.

    Tries resolve-against-old-root first, then a ``<name>.artifacts/`` prefix
    rewrite so relative refs that resolve against CWD still move with the
    project. Returns None when the path is external / unrelated.
    """
    if not raw:
        return None
    candidates = [Path(raw)]
    if project_dir is not None and not Path(raw).is_absolute():
        candidates.append(Path(project_dir) / raw)
    for candidate in candidates:
        try:
            relative = candidate.resolve().relative_to(old_root)
        except ValueError:
            continue
        return (new_root / relative).as_posix()
    posix = Path(raw).as_posix()
    old_name = old_root.name
    new_name = new_root.name
    prefix = f"{old_name}/"
    if posix.startswith(prefix) and old_name.endswith(".artifacts"):
        return f"{new_name}/{posix[len(prefix):]}"
    return None


def project_dir_for(project_path: Path) -> Path:
    """Return the resolved directory that contains the ``.paleo.json`` file."""
    return Path(project_path).expanduser().resolve().parent


def is_within_directory(path: Path, directory: Path) -> bool:
    """True if *path* is *directory* or a descendant (after resolve)."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except (ValueError, OSError):
        return False


def relativize_path(
    path: str,
    project_path: Path,
    *,
    project_dir: Path | None = None,
) -> tuple[str, bool]:
    """Return a portable path, optionally reusing a resolved project root.

    ``project_dir`` is an internal batch-save optimization.  It must be the
    resolved parent for ``project_path``; accepting it does not relax path or
    symlink semantics because each candidate still goes through ``resolve``.
    """
    project_dir = project_dir or project_dir_for(project_path)
    candidate = Path(path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (project_dir / candidate).resolve()
    )
    try:
        return resolved.relative_to(project_dir).as_posix(), False
    except ValueError:
        return resolved.as_posix(), True


def resolve_project_path(
    path: str,
    project_path: Path,
    *,
    project_dir: Path | None = None,
) -> str:
    """Resolve a path stored in a project document for runtime file access.

    - Absolute paths are allowed (external assets flagged on save).
    - Relative paths are joined to the project directory and **must** stay
      inside that directory after normalization. ``..`` segments that escape
      the project root raise :class:`ProjectPathError`.
    """
    raw = str(path if path is not None else "").strip()
    if not raw:
        raise ProjectPathError("Empty path cannot be resolved against a project")

    candidate = Path(raw).expanduser()
    project_dir = project_dir or project_dir_for(project_path)

    if candidate.is_absolute():
        return candidate.resolve().as_posix()

    # Relative paths are project-local by contract (portability). Constrain
    # them so a crafted ``../../etc/passwd`` entry cannot leave the tree.
    resolved = (project_dir / candidate).resolve()
    try:
        resolved.relative_to(project_dir)
    except ValueError:
        raise ProjectPathError(
            f"Relative path escapes project directory: {raw!r} "
            f"(project_dir={project_dir.as_posix()})"
        )
    return resolved.as_posix()
