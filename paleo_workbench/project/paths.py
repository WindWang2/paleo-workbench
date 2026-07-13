from __future__ import annotations

from pathlib import Path


def artifact_dir_for(project_path: Path) -> Path:
    project_name = project_path.name.removesuffix(".paleo.json")
    return project_path.with_name(f"{project_name}.artifacts")


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


def relativize_path(path: str, project_path: Path) -> tuple[str, bool]:
    project_dir = project_path.parent.resolve()
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
    """Resolve a path stored in a project document for runtime file access."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve().as_posix()
    return (project_path.parent / candidate).resolve().as_posix()
