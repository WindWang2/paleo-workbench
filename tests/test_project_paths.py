"""Unit tests for project path relativize / resolve confinement."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.project.paths import (
    ProjectPathError,
    is_within_directory,
    project_dir_for,
    relativize_path,
    resolve_project_path,
)


def test_project_dir_for_is_parent_of_paleo_file(tmp_path: Path):
    project = tmp_path / "nested" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    assert project_dir_for(project) == (tmp_path / "nested").resolve()


def test_resolve_relative_path_inside_project(tmp_path: Path):
    project = tmp_path / "demo.paleo.json"
    data = tmp_path / "wells" / "a.las"
    data.parent.mkdir()
    data.write_text("~V\n", encoding="utf-8")

    resolved = resolve_project_path("wells/a.las", project)
    assert Path(resolved) == data.resolve()


def test_resolve_allows_normalized_dotdot_inside_project(tmp_path: Path):
    """``data/../data/a.las`` stays inside project_dir after resolve."""
    project = tmp_path / "demo.paleo.json"
    data = tmp_path / "data" / "a.las"
    data.parent.mkdir()
    data.write_text("~V\n", encoding="utf-8")

    resolved = resolve_project_path("data/../data/a.las", project)
    assert Path(resolved) == data.resolve()
    assert is_within_directory(Path(resolved), tmp_path)


def test_resolve_blocks_parent_escape(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project = project_dir / "demo.paleo.json"
    secret = tmp_path / "secret.txt"
    secret.write_text("nope", encoding="utf-8")

    with pytest.raises(ProjectPathError, match="escapes project directory"):
        resolve_project_path("../secret.txt", project)

    with pytest.raises(ProjectPathError, match="escapes project directory"):
        resolve_project_path("data/../../secret.txt", project)

    with pytest.raises(ProjectPathError, match="escapes project directory"):
        resolve_project_path("../../secret.txt", project)


def test_resolve_blocks_empty_path(tmp_path: Path):
    project = tmp_path / "demo.paleo.json"
    with pytest.raises(ProjectPathError, match="Empty path"):
        resolve_project_path("", project)
    with pytest.raises(ProjectPathError, match="Empty path"):
        resolve_project_path("   ", project)


def test_resolve_absolute_external_still_allowed(tmp_path: Path):
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir()
    external = tmp_path / "shared" / "regional.las"
    external.parent.mkdir()
    external.write_text("~V\n", encoding="utf-8")

    resolved = resolve_project_path(str(external), project)
    assert Path(resolved) == external.resolve()


def test_relativize_marks_outside_as_external(tmp_path: Path):
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir()
    external = tmp_path / "outside.las"
    external.write_text("x", encoding="utf-8")

    stored, external_flag = relativize_path(str(external), project)
    assert external_flag is True
    assert Path(stored).is_absolute()


def test_load_rejects_project_with_escaped_relative_resource(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project_path = project_dir / "demo.paleo.json"
    secret = tmp_path / "secret.las"
    secret.write_text("~V\n", encoding="utf-8")

    # Craft a project JSON with a relative path that escapes on resolve.
    import json

    payload = ProjectDocument.new("Bad").model_dump()
    payload["resources"] = [
        {
            "id": "r1",
            "name": "secret.las",
            "path": "../secret.las",
            "type": "well_log",
            "format": "las",
            "status": "indexed",
            "external": False,
            "checksum": None,
            "parsed_summary": {},
            "artifact_role": "",
            "tags": [],
        }
    ]
    project_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProjectPathError):
        ProjectManager(project_path).load()


def test_open_project_path_reports_escape_error(qtbot, tmp_path: Path):
    from paleo_workbench.app import PaleoWorkbenchWindow
    import json

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project_path = project_dir / "demo.paleo.json"
    payload = ProjectDocument.new("Bad").model_dump()
    payload["resources"] = [
        ResourceItem(
            name="x.las",
            path="../escape.las",
            type="well_log",
            format="las",
        ).model_dump()
    ]
    project_path.write_text(json.dumps(payload), encoding="utf-8")

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    ok = window.open_project_path(project_path)
    assert ok is False
    assert window._last_open_error is not None
    assert "逃出" in window._last_open_error or "非法" in window._last_open_error


# ------------------------------------------------- #1190 safe_rmtree observability


def test_safe_rmtree_raises_and_logs_on_failure(tmp_path: Path, monkeypatch, caplog):
    """A failed removal is observable: logged AND re-raised (#1190)."""
    import logging
    import shutil as shutil_module
    from paleo_workbench.project import paths as paths_module

    target = tmp_path / "tree"
    target.mkdir()
    (target / "f.txt").write_text("x", encoding="utf-8")

    def _boom(path, *args, **kwargs):
        raise OSError("simulated rmtree failure")

    monkeypatch.setattr(shutil_module, "rmtree", _boom)
    with caplog.at_level(logging.WARNING, logger="paleo_workbench.project.paths"):
        with pytest.raises(OSError):
            paths_module.safe_rmtree(target)
    assert any("safe_rmtree" in record.message for record in caplog.records)


def test_safe_rmtree_succeeds_silently(tmp_path: Path):
    from paleo_workbench.project.paths import safe_rmtree

    target = tmp_path / "tree"
    target.mkdir()
    (target / "f.txt").write_text("x", encoding="utf-8")
    safe_rmtree(target)
    assert not target.exists()


def test_safe_rmtree_missing_path_is_noop(tmp_path: Path):
    from paleo_workbench.project.paths import safe_rmtree

    safe_rmtree(tmp_path / "not-there")  # must not raise


def test_relocation_commit_propagates_rmtree_failure(tmp_path: Path, monkeypatch):
    """StagedArtifactRelocation.commit lets a source-cleanup failure abort
    the Save As finishing step instead of half-finishing silently."""
    import shutil as shutil_module
    from paleo_workbench.project.paths import StagedArtifactRelocation

    source = tmp_path / "old.artifacts"
    target = tmp_path / "new.artifacts"
    source.mkdir()
    (source / "payload.bin").write_bytes(b"p")
    shutil_module.copytree(source, target)

    staged = StagedArtifactRelocation(
        source=source, target=target, preserved_source=True
    )

    def _boom(path, *args, **kwargs):
        raise OSError("cannot remove source")

    monkeypatch.setattr(shutil_module, "rmtree", _boom)
    with pytest.raises(OSError):
        staged.commit()


def test_relocation_rollback_stays_best_effort_on_rmtree_failure(
    tmp_path: Path, monkeypatch
):
    """rollback() is best-effort BY DESIGN (an undo must never mask the
    original failure) — it catches the OSError; the log inside safe_rmtree
    keeps it attributable."""
    import shutil as shutil_module
    from paleo_workbench.project.paths import StagedArtifactRelocation

    source = tmp_path / "old.artifacts"
    target = tmp_path / "new.artifacts"
    source.mkdir()
    target.mkdir()
    (target / "junk.bin").write_bytes(b"j")

    staged = StagedArtifactRelocation(
        source=source, target=target, copied_root=True
    )

    def _boom(path, *args, **kwargs):
        raise OSError("cannot remove target")

    monkeypatch.setattr(shutil_module, "rmtree", _boom)
    staged.rollback()  # must not raise
