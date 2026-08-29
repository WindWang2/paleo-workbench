"""Conservative garbage collection for the catalog artifacts tree (P4).

``plan_gc`` classifies orphaned files with ZERO deletion; ``sweep_gc`` deletes
only the safe classes; ``cleanup_working_copies`` is the explicit working-copy
hook. Invariants:

- A reachable committed ``DataVersion`` payload is NEVER deleted: referenced
  paths are computed from the document before any sweep.
- External source files are never touched (they live outside ``.artifacts/``).
- Trashed payloads are only swept when their version record is gone (i.e. the
  trash entry has no version id anymore).
- Blobs are swept by reachability (the keep-set is every managed version's
  recorded digest — see ``dedup.py``).
- Working copies are treated as user work: only dirs whose version id does
  not exist at all are considered abandoned, and even those require the
  explicit ``cleanup_working_copies`` hook (never swept automatically).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paleo_workbench.catalog.storage import (
    STAGE_DIRS,
    blob_dir_for,
    catalog_dir_for,
    trash_dir_for,
    working_dir_for,
)
from paleo_workbench.catalog import dedup

# Orphan classes (report only; deletion policy lives in sweep_gc).
STAGE_ORPHAN = "stage_orphan"
WORKING_ORPHAN = "working_orphan"
TEMP_ORPHAN = "temp_orphan"
TRASH_ORPHAN = "trash_orphan"
BLOB_ORPHAN = "blob_orphan"
EMPTY_DIR = "empty_dir"

_TEMP_PREFIXES = (".place-", ".blob-", ".catalog.json.")
_TEMP_SUFFIX = ".tmp"


@dataclass
class GcItem:
    """One orphaned file/dir candidate."""

    kind: str
    path: Path
    size: int = 0


@dataclass
class GcReport:
    """Dry-run classification result (nothing is deleted by planning)."""

    items: list[GcItem] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[GcItem]:
        return [item for item in self.items if item.kind == kind]

    def count(self, kind: str | None = None) -> int:
        if kind is None:
            return len(self.items)
        return len(self.by_kind(kind))

    def bytes_for(self, kind: str) -> int:
        return sum(item.size for item in self.by_kind(kind))

    def total_bytes(self) -> int:
        return sum(item.size for item in self.items)

    def kinds(self) -> list[str]:
        return sorted({item.kind for item in self.items})


def _is_temp_name(name: str) -> bool:
    return name.endswith(_TEMP_SUFFIX) or name.startswith(_TEMP_PREFIXES)


def _walk_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [p for p in directory.rglob("*") if p.is_file()]


def _temp_scan_roots(project_path: Path) -> tuple[tuple[Path, Path]]:
    """Directory roots the temp-name scan must NOT descend into.

    ``working/`` holds the only mutable copy of uncommitted user edits —
    even a temp-named working copy is user work and may only be removed via
    the explicit ``cleanup_working_copies`` hook (module invariant).
    ``trash/`` payloads are recoverable by design and are governed by
    step-3 version reachability instead.
    """
    return (working_dir_for(project_path), trash_dir_for(project_path))


def _in_roots(path: Path, roots) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _plan_auto_gc(service) -> GcReport:
    """Open-time plan: temp leftovers and empty dirs only (no full-tree orphan scan)."""
    report = GcReport()
    project_path = service.project_path
    document = service.document
    referenced = {v.path for v in document.versions if v.managed}
    stage_root = catalog_dir_for(project_path).parent
    skip_roots = _temp_scan_roots(project_path)
    for path in _walk_files(stage_root):
        if not _is_temp_name(path.name):
            continue
        if _in_roots(path, skip_roots):
            continue
        try:
            rel = path.relative_to(stage_root.parent).as_posix()
        except ValueError:
            rel = ""
        if rel not in referenced:
            report.items.append(GcItem(TEMP_ORPHAN, path, _safe_size(path)))
    for directory in _empty_dirs(stage_root):
        report.items.append(GcItem(EMPTY_DIR, directory, 0))
    return report


def plan_gc(service, *, explicit: bool = True) -> GcReport:
    """Classify orphans in the artifacts tree (never deletes anything).

    ``explicit=False`` (open-time auto sweep) only classifies TEMP_ORPHAN and
    EMPTY_DIR so project open does not pay three full artifacts-tree walks.
    """
    if not explicit:
        return _plan_auto_gc(service)
    report = GcReport()
    project_path = service.project_path
    document = service.document

    # 1. Stage payloads not referenced by any managed version path.
    referenced = {v.path for v in document.versions if v.managed}
    stage_root = catalog_dir_for(project_path).parent
    for stage_name in STAGE_DIRS.values():
        for path in _walk_files(stage_root / stage_name):
            try:
                # Version paths are stored relative to the PROJECT dir and
                # include the ``<project>.artifacts/`` prefix.
                rel = path.relative_to(stage_root.parent).as_posix()
            except ValueError:
                continue
            if rel not in referenced:
                report.items.append(
                    GcItem(STAGE_ORPHAN, path, _safe_size(path))
                )

    # 2. Abandoned working copies: dirs/files whose version id is unknown.
    known_version_ids = {v.id for v in document.versions}
    working_root = working_dir_for(project_path)
    if working_root.is_dir():
        for path in _walk_files(working_root):
            try:
                version_id = path.relative_to(working_root).parts[0]
            except (ValueError, IndexError):
                version_id = ""
            if version_id not in known_version_ids:
                report.items.append(
                    GcItem(WORKING_ORPHAN, path, _safe_size(path))
                )

    # 3. Unreferenced trash payloads: trash/{version_id}/file where the
    #    version record is gone.
    trash_root = trash_dir_for(project_path)
    if trash_root.is_dir():
        for path in _walk_files(trash_root):
            try:
                version_id = path.relative_to(trash_root).parts[0]
            except (ValueError, IndexError):
                version_id = ""
            if version_id not in known_version_ids:
                report.items.append(
                    GcItem(TRASH_ORPHAN, path, _safe_size(path))
                )

    # 4. Stale temp files anywhere in the artifacts tree. A file whose name
    #    matches the temp pattern is only an orphan when NO managed version
    #    references it — an imported payload may legitimately be named
    #    ``data.tmp`` / ``.blob-x`` (review finding: auto-sweep deleted
    #    referenced payloads on open). Referenced files are NEVER classified
    #    here (same referenced set as step 1). The working/ and trash/
    #    subtrees are skipped: temp-named working copies are uncommitted user
    #    work (only ``cleanup_working_copies`` may touch them) and trash is
    #    governed by step-3 reachability (#889).
    referenced = {v.path for v in document.versions if v.managed}
    skip_roots = _temp_scan_roots(project_path)
    for path in _walk_files(stage_root):
        if not _is_temp_name(path.name):
            continue
        if _in_roots(path, skip_roots):
            continue
        try:
            rel = path.relative_to(stage_root.parent).as_posix()
        except ValueError:
            rel = ""
        if rel not in referenced:
            report.items.append(GcItem(TEMP_ORPHAN, path, _safe_size(path)))

    # 5. Unreferenced blobs (reachability GC on the content store).
    for digest in dedup.plan_blob_gc(project_path, document):
        blob_path = blob_dir_for(project_path) / digest[:2] / digest
        report.items.append(GcItem(BLOB_ORPHAN, blob_path, _safe_size(blob_path)))

    # 6. Empty directories under the payload dirs (crash leftovers).
    for directory in _empty_dirs(stage_root):
        report.items.append(GcItem(EMPTY_DIR, directory, 0))
    return report


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _empty_dirs(stage_root: Path) -> list[Path]:
    """Empty directories below the stage/working/trash trees (deepest first)."""
    empties: list[Path] = []
    for root_name in [*STAGE_DIRS.values(), "working", "trash"]:
        root = stage_root / root_name
        if not root.is_dir():
            continue
        for directory in sorted(
            (p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)
        ):
            try:
                if not any(directory.iterdir()):
                    empties.append(directory)
            except OSError:
                continue
    return empties


# Classes the default sweep deletes (conservative). Working copies and trash
# payloads with a live version record are never swept.
_AUTO_SWEEPABLE = {TEMP_ORPHAN, EMPTY_DIR}
_EXPLICIT_SWEEPABLE = {
    STAGE_ORPHAN,
    TEMP_ORPHAN,
    TRASH_ORPHAN,
    BLOB_ORPHAN,
    EMPTY_DIR,
}


def sweep_gc(service, *, dry_run: bool = True, explicit: bool = False) -> GcReport:
    """Plan (dry_run=True) or perform a GC sweep.

    With ``explicit=False`` (the conservative sweep used on open) only stale
    temp files and empty directories are removed. With ``explicit=True`` the
    full safe set is swept: stage orphans, trash orphans and unreferenced
    blobs too. Working copies are never swept here (see
    :func:`cleanup_working_copies`).
    """
    report = plan_gc(service, explicit=explicit)
    sweepable = _EXPLICIT_SWEEPABLE if explicit else _AUTO_SWEEPABLE
    removed: list[GcItem] = []
    for item in report.items:
        if item.kind not in sweepable:
            continue
        if dry_run:
            removed.append(item)
            continue
        try:
            if item.path.is_dir():
                item.path.rmdir()
            else:
                item.path.unlink()
            removed.append(item)
        except PermissionError:
            # Read-only payload (blobs are content-addressed and immutable
            # by contract): Windows refuses to unlink read-only files —
            # clear the bit and retry once.
            try:
                item.path.chmod(item.path.stat().st_mode | stat.S_IWUSR)
                if item.path.is_dir():
                    item.path.rmdir()
                else:
                    item.path.unlink()
                removed.append(item)
            except OSError:
                continue
        except OSError:
            continue
    return GcReport(removed)


def cleanup_working_copies(service) -> GcReport:
    """Remove abandoned working-copy payloads (explicit user action).

    A working copy is abandoned when its directory's version id does not exist
    in the document at all (the version was purged, or the copy was created
    and the version never committed). Live versions' working copies are never
    touched — they may hold uncommitted user edits.
    """
    report = GcReport()
    known_version_ids = {v.id for v in service.document.versions}
    working_root = working_dir_for(service.project_path)
    if not working_root.is_dir():
        return report
    for path in _walk_files(working_root):
        try:
            version_id = path.relative_to(working_root).parts[0]
        except (ValueError, IndexError):
            version_id = ""
        if version_id not in known_version_ids:
            try:
                path.unlink()
                report.items.append(GcItem(WORKING_ORPHAN, path, 0))
            except OSError:
                continue
    # Prune now-empty working subdirs (deepest first).
    for directory in sorted(
        (p for p in working_root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)
    ):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue
    return report
