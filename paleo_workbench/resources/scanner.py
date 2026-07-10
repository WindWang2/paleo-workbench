from __future__ import annotations

import hashlib
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import relativize_path
from paleo_workbench.resources.classifier import classify_path


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_resources(
    root: Path,
    project_path: Path | None = None,
    *,
    skip_checksum_over_bytes: int | None = None,
) -> list[ResourceItem]:
    resources: list[ResourceItem] = []

    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path.name.startswith("._"):
            continue

        resource_type, resource_format, status = classify_path(path)
        resolved_path = path.resolve()
        stored_path = resolved_path.as_posix()
        external = False

        if project_path is not None:
            stored_path, external = relativize_path(str(path), project_path)

        size_bytes = resolved_path.stat().st_size
        summary: dict = {"size_bytes": size_bytes}
        checksum: str | None
        if (
            skip_checksum_over_bytes is not None
            and size_bytes > skip_checksum_over_bytes
        ):
            checksum = None
            summary["checksum_skipped"] = True
        else:
            try:
                checksum = _checksum(path)
            except OSError:
                checksum = None
                summary["checksum_error"] = True

        resources.append(
            ResourceItem(
                name=path.name,
                path=stored_path,
                type=resource_type,
                format=resource_format,
                status=status,
                source="scan",
                parsed_summary=summary,
                checksum=checksum,
                external=external,
            )
        )

    return resources
