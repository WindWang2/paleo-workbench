from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import relativize_path
from paleo_workbench.resources.classifier import classify_path
from paleo_workbench.resources.io_registry import (
    PREFERRED_IMPORT_EXTENSIONS,
    ROLE_BY_TYPE,
    TYPE_LABELS,
)


@dataclass
class ImportReport:
    added: list[ResourceItem] = field(default_factory=list)
    skipped_path: list[Path] = field(default_factory=list)
    skipped_checksum: list[Path] = field(default_factory=list)
    skipped_filter: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def skipped_count(self) -> int:
        return (
            len(self.skipped_path)
            + len(self.skipped_checksum)
            + len(self.skipped_filter)
        )

    @property
    def by_type(self) -> dict[str, int]:
        return dict(Counter(r.type for r in self.added))

    def summary_text(self) -> str:
        parts = [f"新增 {self.added_count}"]
        if self.skipped_path:
            parts.append(f"路径重复跳过 {len(self.skipped_path)}")
        if self.skipped_filter:
            parts.append(f"过滤跳过 {len(self.skipped_filter)}")
        if self.warnings:
            parts.append(f"警告 {len(self.warnings)}")
        if self.added:
            top = sorted(self.by_type.items(), key=lambda x: -x[1])[:4]
            labels = ", ".join(
                f"{TYPE_LABELS.get(t, t)} {n}" for t, n in top
            )
            parts.append(f"类型: {labels}")
        return " · ".join(parts)


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


def _probe_summary(path: Path, resource_type: str, resource_format: str) -> dict:
    """Lightweight metadata for catalog (never deep-parse large files)."""
    summary: dict = {}
    try:
        stat = path.stat()
        summary["size_bytes"] = int(stat.st_size)
        summary["mtime"] = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        return summary
    summary["extension"] = resource_format
    summary["type_label"] = TYPE_LABELS.get(resource_type, resource_type)

    # Tiny text probes only for small files.
    try:
        if resource_format in {"csv", "txt", "md", "json", "geojson"} and summary.get(
            "size_bytes", 0
        ) < 2_000_000:
            text = path.read_text(encoding="utf-8", errors="replace")
            summary["line_count"] = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
            if resource_format in {"json", "geojson"}:
                import json as _json

                data = _json.loads(text)
                if isinstance(data, dict):
                    summary["json_type"] = data.get("type", "object")
                    if data.get("type") == "FeatureCollection":
                        summary["feature_count"] = len(data.get("features") or [])
                elif isinstance(data, list):
                    summary["json_type"] = "array"
                    summary["row_count"] = len(data)
    except Exception:
        pass
    return summary


def _collect_resource(
    path: Path,
    project_path: Path | None = None,
    *,
    preferred_only: bool = False,
) -> ResourceItem | None:
    if preferred_only:
        ext = path.suffix.lower().lstrip(".")
        if ext and ext not in PREFERRED_IMPORT_EXTENSIONS:
            return None
    resource_type, resource_format, status = classify_path(path)
    resolved_path = path.resolve()
    summary = _probe_summary(resolved_path, resource_type, resource_format)
    stored_path = resolved_path.as_posix()
    external = False
    if project_path is not None:
        stored_path, external = relativize_path(str(path), project_path)
    role = ROLE_BY_TYPE.get(resource_type)
    return ResourceItem(
        name=path.name,
        path=stored_path,
        type=resource_type,
        format=resource_format,
        status=status,
        source="import",
        parsed_summary=summary,
        checksum=None,
        external=external,
        artifact_role=role,
        tags=[role] if role else [],
    )


def _collect_folder(
    root: Path,
    project_path: Path | None = None,
    *,
    preferred_only: bool = False,
) -> tuple[list[ResourceItem], list[str], list[Path]]:
    try:
        paths = sorted(root.rglob("*"))
    except OSError as exc:
        return [], [f"{root}: {exc}"], []

    candidates: list[ResourceItem] = []
    warnings: list[str] = []
    filtered: list[Path] = []
    for path in paths:
        try:
            if not path.is_file() or path.name.startswith("._"):
                continue
            if path.stat().st_size == 0:
                warnings.append(f"{path}: 空文件已跳过")
                filtered.append(path)
                continue
            item = _collect_resource(
                path, project_path, preferred_only=preferred_only
            )
            if item is None:
                filtered.append(path)
                continue
            candidates.append(item)
        except OSError as exc:
            warnings.append(f"{path}: {exc}")
    return candidates, warnings, filtered


def import_files(
    paths: list[Path],
    existing: list[ResourceItem],
    project_path: Path | None = None,
    *,
    preferred_only: bool = False,
) -> ImportReport:
    candidates: list[ResourceItem] = []
    warnings: list[str] = []
    filtered: list[Path] = []

    for path in paths:
        try:
            if not path.is_file():
                warnings.append(f"{path}: 不是文件")
                continue
            if path.stat().st_size == 0:
                warnings.append(f"{path}: 空文件已跳过")
                filtered.append(path)
                continue
            item = _collect_resource(
                path, project_path, preferred_only=preferred_only
            )
            if item is None:
                filtered.append(path)
                continue
            candidates.append(item)
        except OSError as exc:
            warnings.append(f"{path}: {exc}")

    report = _filter_new(candidates, existing, project_path)
    report.warnings.extend(warnings)
    report.skipped_filter.extend(filtered)
    return report


def import_folder(
    root: Path,
    existing: list[ResourceItem],
    project_path: Path | None = None,
    *,
    preferred_only: bool = False,
) -> ImportReport:
    candidates, warnings, filtered = _collect_folder(
        root, project_path, preferred_only=preferred_only
    )
    report = _filter_new(candidates, existing, project_path)
    report.warnings.extend(warnings)
    report.skipped_filter.extend(filtered)
    return report
