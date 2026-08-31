from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import relativize_path
from paleo_workbench.resources.classifier import classify_path


def _checksum(path: Path) -> str:
    # Unified implementation lives in paleo_workbench.catalog.checksum so
    # scanner/import/catalog hashing can never diverge (ADR 0056).
    return sha256_file(path)


def _process_file(
    path: Path,
    project_path: Path | None,
    skip_checksum_over_bytes: int | None,
    classify=classify_path,
) -> ResourceItem | None:
    """Process a single file: classify, stat, checksum, build ResourceItem.

    Returns None if the file vanished (stat OSError) — caller filters it.
    Thread-safe: uses only local state and stateless helpers.
    """
    resource_type, resource_format, status = classify(path)
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
    classify=classify_path,
) -> list[ResourceItem]:
    candidates = sorted(
        c for c in root.rglob("*") if c.is_file() and not c.name.startswith("._")
    )
    if not candidates:
        return []
    if max_workers:
        workers = max_workers
    else:
        # P2-A: background scanning shares the governor's IO-slot budget
        # instead of opening cpu_count+4 threads that fight interactive
        # slice reads for the disk.
        try:
            from paleo_workbench.runtime.resource_governor import get_governor

            workers = max(2, min(32, int(get_governor().io_slots()) + 2))
        except Exception:
            workers = min(32, (os.cpu_count() or 1) + 4)
        workers = max(workers, 2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processed = list(
            pool.map(
                lambda p: _process_file(
                    p, project_path, skip_checksum_over_bytes, classify
                ),
                candidates,
            )
        )
    return [r for r in processed if r is not None]
