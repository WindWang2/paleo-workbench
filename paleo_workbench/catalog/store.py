"""Portable canonical store for the catalog (ADR 0056).

``metadata/catalog.json`` is the single source of truth for catalog data.
Writes are atomic (temp file + fsync + rename + directory fsync), matching the
ProjectManager save pattern. The SQLite database is only a rebuildable index
over this document — see ``db.py``.
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


class CatalogStore:
    """Load/save the canonical CatalogDocument for one project."""

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)

    def load(self) -> CatalogDocument:
        """Load the canonical document; an absent catalog means an empty one."""
        path = catalog_file_for(self.project_path)
        if not path.is_file():
            return CatalogDocument()
        data = json.loads(path.read_text(encoding="utf-8"))
        return CatalogDocument.model_validate(data)

    def save(self, document: CatalogDocument) -> None:
        """Atomically persist the canonical document."""
        ensure_catalog_layout(self.project_path)
        path = catalog_file_for(self.project_path)
        payload = json.dumps(
            document.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
            fsync_dir(path.parent)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
