from __future__ import annotations

from pathlib import Path


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


def relocate_artifacts(old_project_path: Path, new_project_path: Path) -> bool:
    """Re-home ``<old>.artifacts/`` to the save-as location; True when moved.

    Fixes the orphan-on-save-as hazard: previously ``save_project_as`` wrote
    the project file to the new path and opened a FRESH catalog there, leaving
    the old ``.artifacts/`` (payloads + catalog + index + working copies +
    trash) stranded and forcing a full re-import at the new location.

    Rules (conservative, never destroys data):

    - Same artifacts location (or no source artifacts) → no-op.
    - Target artifacts dir absent → rename the whole tree (same filesystem);
      cross-device falls back to a recursive copy then removes the source.
    - Target artifacts dir already present → merge only the subdirectories the
      target lacks; conflicting subdirectories are left untouched (both sides
      hold data that must not be overwritten).

    Returns True when anything was moved/merged, False otherwise. Raises on
    unrecoverable IO errors (callers decide whether saving may still proceed).
    """
    old = Path(old_project_path)
    new = Path(new_project_path)
    source = artifact_dir_for(old)
    target = artifact_dir_for(new)
    if source == target or not source.is_dir():
        return False
    moved = False
    if not target.exists():
        try:
            source.rename(target)
            return True
        except OSError:
            pass
        # Cross-device: copy the tree, then remove the source.
        import shutil

        shutil.copytree(source, target, dirs_exist_ok=True)
        shutil.rmtree(source, ignore_errors=True)
        return True
    # Target exists: merge only missing subdirectories (never overwrite).
    for child in source.iterdir():
        dest = target / child.name
        if not dest.exists():
            child.rename(dest)
            moved = True
    if moved:
        try:
            source.rmdir()
        except OSError:
            pass
    return moved


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


def relativize_path(path: str, project_path: Path) -> tuple[str, bool]:
    project_dir = project_dir_for(project_path)
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


def resolve_project_path(path: str, project_path: Path) -> str:
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
    project_dir = project_dir_for(project_path)

    if candidate.is_absolute():
        return candidate.resolve().as_posix()

    # Relative paths are project-local by contract (portability). Constrain
    # them so a crafted ``../../etc/passwd`` entry cannot leave the tree.
    resolved = (project_dir / candidate).resolve()
    if not is_within_directory(resolved, project_dir):
        raise ProjectPathError(
            f"Relative path escapes project directory: {raw!r} "
            f"(project_dir={project_dir.as_posix()})"
        )
    return resolved.as_posix()
