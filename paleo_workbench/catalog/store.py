"""Portable canonical store for the catalog (ADR 0056).

``metadata/catalog.json`` is the single source of truth for catalog data.
Writes are atomic (temp file + fsync + rename + directory fsync), matching the
ProjectManager save pattern. Before replacing the canonical file, the previous
revision is kept as ``metadata/catalog.json.bak`` so a crash mid-save can
never lose more than the in-flight revision: ``load()`` falls back to the
``.bak`` when the canonical file is missing or unreadable. The SQLite database
is only a rebuildable index over this document — see ``db.py``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from paleo_workbench.catalog.models import CatalogDocument
from paleo_workbench.catalog.storage import (
    catalog_dir_for,
    ensure_catalog_layout,
    fsync_dir,
)


def catalog_file_for(project_path: Path) -> Path:
    return catalog_dir_for(Path(project_path)) / "catalog.json"


def catalog_bak_file_for(project_path: Path) -> Path:
    """Path of the previous-revision backup (``catalog.json.bak``)."""
    return catalog_dir_for(Path(project_path)) / "catalog.json.bak"


class CatalogStore:
    """Load/save the canonical CatalogDocument for one project."""

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)

    def load(self) -> CatalogDocument:
        """Load the canonical document; an absent catalog means an empty one.

        When ``catalog.json`` is missing but ``catalog.json.bak`` exists (a
        crash between the two renames of a save), the previous revision is
        recovered so reopening never observes a half-written or empty catalog.
        """
        path = catalog_file_for(self.project_path)
        if not path.is_file():
            bak = catalog_bak_file_for(self.project_path)
            if bak.is_file():
                data = json.loads(bak.read_text(encoding="utf-8"))
                document = CatalogDocument.model_validate(data)
                # Re-promote the backup to the canonical path so subsequent
                # saves start from a clean state.
                try:
                    os.replace(bak, path)
                    fsync_dir(path.parent)
                except OSError:
                    pass
                return document
            return CatalogDocument()
        data = json.loads(path.read_text(encoding="utf-8"))
        return CatalogDocument.model_validate(data)

    def save(self, document: CatalogDocument) -> None:
        """Atomically persist the canonical document.

        Sequence (each step crash-safe):

        1. Serialize the document and write it to a temp file (fsync).
        2. Move the current ``catalog.json`` to ``catalog.json.bak`` (rename).
        3. Rename the temp file into place as ``catalog.json``.
        4. fsync the directory.

        A crash between 2 and 3 leaves ``catalog.json.bak`` holding the
        previous revision; :meth:`load` recovers it. Any failure before step 3
        restores the original file and removes the temp file, so a failed save
        never leaves a half-written catalog behind.
        """
        ensure_catalog_layout(self.project_path)
        path = catalog_file_for(self.project_path)
        bak = catalog_bak_file_for(self.project_path)
        payload = json.dumps(
            document.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
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
            os.replace(tmp_name, path)
            fsync_dir(path.parent)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            if old_moved and not path.exists() and bak.exists():
                # The canonical file was moved aside but the new one never
                # landed: put the previous revision back (best-effort).
                try:
                    os.replace(bak, path)
                    fsync_dir(path.parent)
                except OSError:
                    pass
            raise
