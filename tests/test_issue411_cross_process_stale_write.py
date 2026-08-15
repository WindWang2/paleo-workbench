"""Regression tests for issue #411: cross-process project/catalog writes.

``*.paleo.json`` and ``metadata/catalog.json`` are whole-document rewrites
guarded only by an in-process RLock; two application instances on the same
project silently overwrite each other (last-writer-wins).  Save-time stale
detection (mtime baseline captured at open / last save) now refuses an
overwrite when the file advanced on disk since this session last looked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import CatalogStaleWriteError, DataCatalogService
from paleo_workbench.project.manager import (
    ProjectManager,
    ProjectStaleWriteError,
)
from paleo_workbench.project.models import ProjectDocument, ResourceItem


def _project_file(tmp_path: Path, name: str = "tarim.paleo.json") -> Path:
    """Create a valid on-disk project document."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ProjectDocument.new(name.removesuffix(".paleo.json"))
    ProjectManager(path).save(doc)
    return path


def test_project_save_refuses_overwrite_after_external_modification(tmp_path: Path):
    """A save whose file advanced on disk must raise, keeping the other write."""
    project_file = _project_file(tmp_path)
    project = ProjectManager(project_file).load()
    project.resources.append(
        ResourceItem(name="a.las", path="a.las", type="well_log", format="las")
    )
    assert ProjectManager(project_file).save(project) is True

    # Another process modifies the project file (e.g. imports from-B + save).
    external = project_file.read_text(encoding="utf-8")
    project_file.write_text(external + "\n", encoding="utf-8")
    os.utime(project_file, ns=(project_file.stat().st_mtime_ns + 2,) * 2)

    project.resources.append(
        ResourceItem(name="a-late.las", path="a-late.las", type="well_log", format="las")
    )
    with pytest.raises(ProjectStaleWriteError):
        ProjectManager(project_file).save(project)
    # The external write is preserved on disk.
    assert "a-late.las" not in project_file.read_text(encoding="utf-8")


def test_project_sequential_saves_still_work(tmp_path: Path):
    """Single-instance behavior: repeated saves on the same session succeed."""
    project_file = _project_file(tmp_path)
    project = ProjectManager(project_file).load()
    manager = ProjectManager(project_file)
    for i in range(3):
        project.resources.append(
            ResourceItem(name=f"w{i}.las", path=f"w{i}.las", type="well_log", format="las")
        )
        assert manager.save(project) is True
    assert "w2.las" in project_file.read_text(encoding="utf-8")


def test_catalog_second_instance_save_refused_first_commit_survives(tmp_path: Path):
    """Two services on one project: the stale writer is blocked, A's asset stays."""
    project = _project_file(tmp_path)
    src_a = tmp_path / "incoming" / "from-A.bin"
    src_a.parent.mkdir(parents=True, exist_ok=True)
    src_a.write_bytes(b"AAA")
    src_b = tmp_path / "incoming" / "from-B.bin"
    src_b.write_bytes(b"BBB")

    svc_a = DataCatalogService.open(project)
    svc_b = DataCatalogService.open(project)  # same baseline as svc_a
    try:
        svc_a.import_raw(src_a)
        asset_a = svc_a.document.assets[-1].id
        with pytest.raises(CatalogStaleWriteError):
            svc_b.import_raw(src_b)
    finally:
        svc_a.close()
        svc_b.close()

    # A fresh reader sees A's commit; B's was refused and never persisted.
    reader = DataCatalogService.open(project)
    try:
        assert any(a.id == asset_a for a in reader.document.assets)
        assert not any("from-B" in (a.metadata or {}).get("source_name", "") for a in reader.document.assets)
    finally:
        reader.close()


def test_catalog_sequential_saves_on_one_service_still_work(tmp_path: Path):
    """Single-instance behavior: the singleton may keep saving without conflicts."""
    project = _project_file(tmp_path)
    svc = DataCatalogService.open(project)
    try:
        for i in range(3):
            src = tmp_path / "incoming" / f"w{i}.bin"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(b"x")
            svc.import_raw(src)
        assert len(svc.document.assets) == 3
    finally:
        svc.close()
    assert len(DataCatalogService.open(project).document.assets) == 3
