"""Portable manifest writer for the catalog (ADR 0056, amended by #1027).

``metadata/catalog.json`` is a checkpoint/export MANIFEST of the catalog:
``catalog.sqlite`` (see ``db.py``) is the canonical store, and this file is
written on close / explicit export so the project stays openable by older app
versions and remains a human-readable, diffable export artifact. Writes are
atomic (temp file + fsync + rename + directory fsync), matching the
ProjectManager save pattern. Before replacing the manifest, the previous
revision is kept as ``metadata/catalog.json.bak`` so a crash mid-save can
never lose more than the in-flight checkpoint: ``load()`` falls back to the
``.bak`` when the manifest is missing or unreadable.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from paleo_workbench.catalog.models import CatalogDocument, CatalogError
from paleo_workbench.catalog.storage import (
    catalog_dir_for,
    ensure_catalog_layout,
    fsync_dir,
    safe_unlink,
)


def catalog_file_for(project_path: Path) -> Path:
    return catalog_dir_for(Path(project_path)) / "catalog.json"


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def catalog_bak_file_for(project_path: Path) -> Path:
    """Path of the previous-revision backup (``catalog.json.bak``)."""
    return catalog_dir_for(Path(project_path)) / "catalog.json.bak"


def _isolate_corrupt_file(path: Path) -> Path:
    """Move a corrupt canonical file aside, preserving its bytes for
    forensics, so a later save cannot silently overwrite them.

    Best-effort: if the rename fails the corrupt file stays in place (bytes
    still preserved) and the caller still surfaces the failure.
    """
    isolated = path.with_name(
        f"{path.name}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    )
    try:
        os.replace(path, isolated)
        fsync_dir(path.parent)
        return isolated
    except OSError:
        return path


def _seed_initial_backup(bak: Path, payload: str) -> None:
    """Atomically write the initial ``.bak`` before the first canonical save.

    The backup holds the same revision as the first canonical file, so a
    once-saved catalog always has a recoverable fallback (issue #372 / C14).
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{bak.name}.", suffix=".tmp", dir=str(bak.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, bak)
        fsync_dir(bak.parent)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class CatalogStore:
    """Load/save the canonical CatalogDocument for one project."""

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        # #1183: (payload sha256, manifest mtime_ns) of the last write THIS
        # instance performed. close/export used to re-serialize and rewrite
        # the full manifest even when the document had not changed; an
        # unchanged payload with an untouched on-disk file skips the write
        # entirely. The mtime guard makes the skip safe against external
        # deletion/modification of the manifest between our writes.
        self._last_write: tuple[str, int] | None = None

    def load(self) -> CatalogDocument:
        """Load the canonical document; an absent catalog means an empty one.

        When ``catalog.json`` is missing OR corrupt but ``catalog.json.bak``
        exists (a crash between the two renames of a save, or a torn/partial
        write), the previous revision is recovered so reopening never
        observes a half-written or unreadable catalog (review finding M3).

        A corrupt canonical file with NO recoverable backup is isolated to
        ``catalog.json.corrupt-<timestamp>`` (original bytes preserved) and
        raises :class:`CatalogError`, so callers surface the failure loudly
        instead of silently substituting an empty catalog that the next save
        would atomically overwrite the corrupt bytes with (issue #372 / C14).
        """
        path = catalog_file_for(self.project_path)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return CatalogDocument.model_validate(data)
            except (OSError, ValueError, TypeError) as error:
                # Corrupt canonical file — fall through to the backup below,
                # unless there is nothing to recover from.
                if not catalog_bak_file_for(self.project_path).is_file():
                    _isolate_corrupt_file(path)
                    raise CatalogError(
                        f"Catalog file is corrupt and no backup is available: "
                        f"{path} ({error})"
                    ) from error
        bak = catalog_bak_file_for(self.project_path)
        if bak.is_file():
            try:
                data = json.loads(bak.read_text(encoding="utf-8"))
                document = CatalogDocument.model_validate(data)
            except (OSError, ValueError, TypeError) as error:
                # Both the canonical file AND the backup are unreadable:
                # isolate the canonical bytes for forensics and raise a typed
                # CatalogError instead of leaking a raw JSONDecodeError while
                # leaving the corrupt files in place (audit #848).
                _isolate_corrupt_file(path)
                _isolate_corrupt_file(bak)
                raise CatalogError(
                    f"Catalog file and its backup are both corrupt: {path} "
                    f"(backup error: {error})"
                ) from error
            # Re-promote the backup to the canonical path so subsequent
            # saves start from a clean state.
            try:
                os.replace(bak, path)
                fsync_dir(path.parent)
            except OSError:
                pass
            return document
        return CatalogDocument()

    def save(self, document: CatalogDocument) -> None:
        """Atomically persist the canonical document.

        Sequence (each step crash-safe):

        1. Serialize the document; when the payload is byte-identical to the
           last one this instance wrote AND the manifest still carries that
           write's mtime, return without touching the disk (#1183) — repeated
           close/export checkpoints of an unchanged catalog no longer pay
           serialize + fsync + double rename.
        2. Write the payload to a temp file (fsync).
        3. Move the current ``catalog.json`` to ``catalog.json.bak`` (rename).
           On the FIRST save (no canonical yet) the backup is instead seeded
           with the identical revision, so a once-saved catalog never sits in
           a no-backup window (issue #372 / C14).
        4. Rename the temp file into place as ``catalog.json``.
        5. fsync the directory.

        A crash between 3 and 4 leaves ``catalog.json.bak`` holding the
        previous revision; :meth:`load` recovers it. Any failure before step 4
        restores the original file and removes the temp file, so a failed save
        never leaves a half-written catalog behind.
        """
        ensure_catalog_layout(self.project_path)
        path = catalog_file_for(self.project_path)
        bak = catalog_bak_file_for(self.project_path)
        payload = json.dumps(
            document.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if self._last_write is not None:
            last_digest, last_mtime = self._last_write
            if last_digest == digest:
                current_mtime = _mtime_ns(path)
                if current_mtime is not None and current_mtime == last_mtime:
                    return  # unchanged since our own last write
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        old_moved = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                os.replace(path, bak)
                old_moved = True
            else:
                _seed_initial_backup(bak, payload)
            os.replace(tmp_name, path)
            fsync_dir(path.parent)
        except Exception:
            safe_unlink(tmp_name)
            if old_moved and not path.exists() and bak.exists():
                # The canonical file was moved aside but the new one never
                # landed: put the previous revision back (best-effort).
                try:
                    os.replace(bak, path)
                    fsync_dir(path.parent)
                except OSError:
                    pass
            raise
        written_mtime = _mtime_ns(path)
        if written_mtime is not None:
            self._last_write = (digest, written_mtime)
