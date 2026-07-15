from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import relativize_path
from paleo_workbench.resources.classifier import classify_path


@dataclass
class ImportReport:
    added: list[ResourceItem] = field(default_factory=list)
    skipped_path: list[Path] = field(default_factory=list)
    skipped_checksum: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_path) + len(self.skipped_checksum)


def _path_key(path: str | Path, project_path: Path | None = None) -> str:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve().as_posix()
    if project_path is not None:
        return (project_path.parent / candidate).resolve().as_posix()
    return candidate.resolve().as_posix()


def _existing_path_keys(
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> set[str]:
    return {
        _path_key(resource.path, project_path)
        for resource in existing
        if resource.path
    }


def _filter_new(
    candidates: list[ResourceItem],
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    report = ImportReport()
    path_keys = _existing_path_keys(existing, project_path)

    for resource in candidates:
        candidate_path = Path(resource.path)
        resolved = _path_key(candidate_path, project_path)
        if resolved in path_keys:
            report.skipped_path.append(candidate_path)
            continue
        report.added.append(resource)
        path_keys.add(resolved)

    return report


def _collect_resource(
    path: Path,
    project_path: Path | None = None,
) -> ResourceItem:
    resource_type, resource_format, status = classify_path(path)
    resolved_path = path.resolve()
    size_bytes = resolved_path.stat().st_size
    stored_path = resolved_path.as_posix()
    external = False
    if project_path is not None:
        stored_path, external = relativize_path(str(path), project_path)
    return ResourceItem(
        name=path.name,
        path=stored_path,
        type=resource_type,
        format=resource_format,
        status=status,
        source="import",
        parsed_summary={"size_bytes": size_bytes},
        checksum=None,
        external=external,
    )


def _collect_folder(
    root: Path,
    project_path: Path | None = None,
) -> tuple[list[ResourceItem], list[str]]:
    try:
        paths = sorted(root.rglob("*"))
    except OSError as exc:
        return [], [f"{root}: {exc}"]

    candidates: list[ResourceItem] = []
    warnings: list[str] = []
    for path in paths:
        try:
            if path.is_file() and not path.name.startswith("._"):
                candidates.append(_collect_resource(path, project_path))
        except OSError as exc:
            warnings.append(f"{path}: {exc}")
    return candidates, warnings


def import_files(
    paths: list[Path],
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    candidates: list[ResourceItem] = []
    warnings: list[str] = []

    for path in paths:
        try:
            candidates.append(_collect_resource(path, project_path))
        except OSError as exc:
            warnings.append(f"{path}: {exc}")

    report = _filter_new(candidates, existing, project_path)
    report.warnings.extend(warnings)
    return report


def import_folder(
    root: Path,
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    candidates, warnings = _collect_folder(root, project_path)
    report = _filter_new(candidates, existing, project_path)
    report.warnings.extend(warnings)
    return report
