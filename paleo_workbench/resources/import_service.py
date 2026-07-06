from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.scanner import scan_resources


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


def _existing_checksums(existing: list[ResourceItem]) -> set[str]:
    return {resource.checksum for resource in existing if resource.checksum}


def _filter_new(
    candidates: list[ResourceItem],
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    report = ImportReport()
    path_keys = _existing_path_keys(existing, project_path)
    checksums = _existing_checksums(existing)

    for resource in candidates:
        candidate_path = Path(resource.path)
        resolved = _path_key(candidate_path, project_path)
        if resolved in path_keys:
            report.skipped_path.append(candidate_path)
            continue
        if resource.checksum and resource.checksum in checksums:
            report.skipped_checksum.append(candidate_path)
            continue
        report.added.append(resource)
        path_keys.add(resolved)
        if resource.checksum:
            checksums.add(resource.checksum)

    return report


def import_files(
    paths: list[Path],
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    candidates: list[ResourceItem] = []
    warnings: list[str] = []

    for path in paths:
        try:
            candidates.extend(scan_resources(path.parent, project_path=project_path))
        except OSError as exc:
            warnings.append(f"{path}: {exc}")

    requested = {_path_key(path, project_path) for path in paths}
    candidates = [
        resource
        for resource in candidates
        if _path_key(resource.path, project_path) in requested
    ]

    report = _filter_new(candidates, existing, project_path)
    report.warnings.extend(warnings)
    return report


def import_folder(
    root: Path,
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    try:
        candidates = scan_resources(root, project_path=project_path)
    except OSError as exc:
        return ImportReport(warnings=[f"{root}: {exc}"])
    return _filter_new(candidates, existing, project_path)
