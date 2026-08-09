"""Tests for save-as artifact relocation (P4: fix orphan-on-save-as).

``save_project_as`` previously wrote the project file to the new path and
opened a FRESH catalog there, leaving the old ``<name>.artifacts/`` (payloads,
catalog, index, working copies, trash) stranded and forcing a full re-import.
``relocate_artifacts`` re-homes the tree; these tests pin the move/merge rules
and the end-to-end catalog continuity across save-as.
"""

from __future__ import annotations

from pathlib import Path


from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.paths import artifact_dir_for, relocate_artifacts


def _make_project(tmp_path: Path, name: str = "demo.paleo.json") -> Path:
    project_path = tmp_path / "proj" / name
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


# -------------------------------------------------------------- pure relocation


def test_noop_without_source_artifacts(tmp_path):
    project = _make_project(tmp_path)
    other = _make_project(tmp_path, "other.paleo.json")
    assert relocate_artifacts(project, other) is False
    assert not artifact_dir_for(other).exists()


def test_same_location_is_noop(tmp_path):
    project = _make_project(tmp_path)
    assert relocate_artifacts(project, project) is False


def test_move_whole_tree_to_fresh_target(tmp_path):
    project = _make_project(tmp_path)
    svc = DataCatalogService.open(project)
    svc.import_raw(_source(tmp_path, "a.bin", b"payload"))
    version_id = svc.document.versions[0].id
    svc.close()

    target = _make_project(tmp_path, "renamed.paleo.json")
    assert relocate_artifacts(project, target) is True
    assert not artifact_dir_for(project).exists()

    # The catalog at the NEW location loads the moved document; version paths
    # embed the old artifacts-dir name, so the save-as controller rebases them
    # (mirrored here for the pure-relocation contract).
    reopened = DataCatalogService.open(target)
    try:
        assert reopened.document.catalog_revision >= 1
        assert reopened._rebase_artifact_paths() is True
        version = reopened.get_version(version_id)
        assert reopened.resolve_path(version).is_file()
        assert reopened.verify_integrity(version_id).status_for(version_id) == "verified"
        assert reopened.index_revision() == reopened.document.catalog_revision
        # Idempotent: rebasing again changes nothing.
        assert reopened._rebase_artifact_paths() is False
    finally:
        reopened.close()


def test_merge_only_missing_subdirs_never_overwrites(tmp_path):
    project = _make_project(tmp_path)
    svc = DataCatalogService.open(project)
    svc.import_raw(_source(tmp_path, "a.bin", b"payload"))
    svc.close()

    target = _make_project(tmp_path, "renamed.paleo.json")
    target_artifacts = artifact_dir_for(target)
    target_artifacts.mkdir(parents=True)
    # Simulate an existing target artifacts dir holding its own exports.
    existing_export = target_artifacts / "exports" / "existing.png"
    existing_export.parent.mkdir(parents=True)
    existing_export.write_bytes(b"keep-me")

    assert relocate_artifacts(project, target) is True
    # The existing export was NOT overwritten…
    assert existing_export.read_bytes() == b"keep-me"
    # …and the payload subdirs were merged in.
    assert (target_artifacts / "metadata" / "catalog.json").is_file()


def test_cross_device_fallback_copies_tree(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    (artifact_dir_for(project) / "raw").mkdir(parents=True)
    (artifact_dir_for(project) / "raw" / "keep.bin").write_bytes(b"data")
    target = _make_project(tmp_path, "renamed.paleo.json")

    import os

    real_rename = os.rename
    calls = {"n": 0}

    def _fail_rename(src, dst):
        calls["n"] += 1
        raise OSError("cross-device link")

    monkeypatch.setattr("os.rename", _fail_rename)
    try:
        moved = relocate_artifacts(project, target)
    finally:
        os.rename = real_rename
    assert moved is True
    assert (artifact_dir_for(target) / "raw" / "keep.bin").read_bytes() == b"data"


# ------------------------------------------------------------- end-to-end save-as


def test_save_as_keeps_catalog_continuity(tmp_path, monkeypatch):
    """The controller path: save-as must re-home artifacts so the reopened
    catalog at the new path still serves the committed versions (no orphan,
    no re-import)."""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.project_controller import ProjectController

    project = _make_project(tmp_path, "orig.paleo.json")
    svc = DataCatalogService.open(project)
    svc.import_raw(_source(tmp_path, "a.bin", b"payload"))
    version_id = svc.document.versions[0].id
    svc.close()

    class FakeWindow:
        def __init__(self, project_path: Path):
            self.project_path = project_path
            self.project = ProjectDocument.new("Test Project")

        def _flush_mapping_draft(self):
            return True

        def _flush_joint_analysis_state(self):
            pass

        def _show_project_error(self, title, message):
            raise AssertionError(f"unexpected error dialog: {message}")

    window = FakeWindow(project)
    controller = ProjectController(window)
    target = _make_project(tmp_path, "moved.paleo.json")

    result = controller.save_project_as(target)
    assert result is not None
    assert window.project_path == target
    # Old artifacts no longer stranded.
    assert not artifact_dir_for(project).exists()
    # New catalog serves the same committed version from the moved payload.
    reopened = DataCatalogService.open(target)
    try:
        version = reopened.get_version(version_id)
        assert reopened.resolve_path(version).is_file()
        assert reopened.verify_integrity(version_id).status_for(version_id) == "verified"
    finally:
        reopened.close()
