from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
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


def _process_file(
    path: Path,
    project_path: Path | None,
    skip_checksum_over_bytes: int | None,
) -> ResourceItem | None:
    """Process a single file: classify, stat, checksum, build ResourceItem.

    Returns None if the file vanished (stat OSError) — caller filters it.
    Thread-safe: uses only local state and stateless helpers.
    """
    resource_type, resource_format, status = classify_path(path)
    resolved_path = path.resolve()
    try:
        size_bytes = resolved_path.stat().st_size
    except OSError:
        return None
    stored_path = resolved_path.as_posix()
    external = False
    if project_path is not None:
        stored_path, external = relativize_path(str(path), project_path)
    summary: dict = {"size_bytes": size_bytes}
    if skip_checksum_over_bytes is not None and size_bytes > skip_checksum_over_bytes:
        checksum: str | None = None
        summary["checksum_skipped"] = True
    else:
        try:
            checksum = _checksum(path)
        except OSError:
            checksum = None
            summary["checksum_error"] = True
    return ResourceItem(
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


def scan_resources(
    root: Path,
    project_path: Path | None = None,
    *,
    skip_checksum_over_bytes: int | None = None,
    max_workers: int | None = None,
) -> list[ResourceItem]:
    candidates = sorted(
        c for c in root.rglob("*") if c.is_file() and not c.name.startswith("._")
    )
    if not candidates:
        return []
    workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processed = list(
            pool.map(
                lambda p: _process_file(p, project_path, skip_checksum_over_bytes),
                candidates,
            )
        )
    return [r for r in processed if r is not None]
