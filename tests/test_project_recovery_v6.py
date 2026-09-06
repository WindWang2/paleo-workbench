"""Project load-time recovery decision table (#1229, foundation v6 §7).

Pins, per failure class:
- TRANSIENT unreadable (PermissionError) → typed ProjectUnreadableError, main
  and .bak untouched, no recovery record — never a silent downgrade;
- CORRUPT main → .bak restored, corrupt bytes quarantined (forensics), the
  recovery recorded on meta (persisted by the next save), stale-save baseline
  taken from the file that actually backs the session;
- MISSING main (interrupted save) → .bak restored;
- corrupt main + unusable .bak → open fails with the original error;
- benign external mtime touch (identical content) → save proceeds;
- real external content change → save raises ProjectStaleWriteError.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from paleo_workbench.project.manager import (
    ProjectManager,
    ProjectStaleWriteError,
    ProjectUnreadableError,
)
from paleo_workbench.project.models import ProjectDocument


def _project(tmp_path: Path, name: str = "demo") -> Path:
    path = tmp_path / f"{name}.paleo.json"
    ProjectManager(path).save(ProjectDocument.new(name))
    return path


def _backup_of(path: Path) -> Path:
    return path.with_name(f"{path.name}.bak")


def test_transient_unreadable_never_falls_back(tmp_path, monkeypatch):
    path = _project(tmp_path)
    # Make a NEWER main (a second save rotates .bak = older revision).
    manager = ProjectManager(path)
    doc = manager.load()
    doc.meta.region = "newer"
    manager.save(doc)
    backup_bytes = _backup_of(path).read_bytes()

    real_read_text = Path.read_text

    def locked_read(self, *args, **kwargs):
        if Path(self) == path:
            raise PermissionError(13, "locked by AV scanner")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", locked_read)
    with pytest.raises(ProjectUnreadableError):
        ProjectManager(path).load()
    monkeypatch.undo()

    # Nothing was touched: main still newer content, backup intact.
    assert "newer" in path.read_text(encoding="utf-8")
    assert _backup_of(path).read_bytes() == backup_bytes


def test_corrupt_main_quarantined_and_recorded(tmp_path):
    path = _project(tmp_path)
    good_bytes = path.read_bytes()
    # A second save seeds a valid .bak, then corrupt the main.
    manager = ProjectManager(path)
    doc = manager.load()
    doc.meta.region = "second"
    manager.save(doc)
    path.write_text("{ this is not json", encoding="utf-8")

    recovered_manager = ProjectManager(path)
    loaded = recovered_manager.load()
    # .bak holds the PREVIOUS revision (save 1 — region still default); the
    # corrupted save-2 bytes were quarantined, not lost silently.
    assert loaded.meta.region == ""
    assert loaded.meta.last_recovery is not None
    record = loaded.meta.last_recovery
    assert record["source"] == "backup-corrupt-main"
    assert record["quarantined"]
    quarantine = Path(record["quarantined"])
    assert quarantine.is_file()
    assert quarantine.read_text(encoding="utf-8") == "{ this is not json"

    # The recovery record persists on the next save and the save succeeds
    # (stale baseline correctly points at the recovered file).
    recovered_manager.save(loaded)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["meta"]["last_recovery"]["source"] == "backup-corrupt-main"

    # Reopening keeps the record until the next explicit save changes it.
    reopened = ProjectManager(path).load()
    assert reopened.meta.last_recovery is not None


def test_missing_main_restored_from_backup(tmp_path):
    path = _project(tmp_path)
    manager = ProjectManager(path)
    doc = manager.load()
    doc.meta.region = "saved"
    manager.save(doc)  # .bak now holds revision 1
    path.unlink()  # interrupted after main→bak, before tmp→main

    loaded = ProjectManager(path).load()
    assert loaded.meta.name == "demo"
    assert loaded.meta.last_recovery is not None
    assert loaded.meta.last_recovery["source"] == "backup-interrupted-save"
    assert path.is_file()  # restored


def test_corrupt_main_and_backup_fails_honestly(tmp_path):
    path = _project(tmp_path)
    path.write_text("]]] broken", encoding="utf-8")
    with pytest.raises((ValueError, Exception)) as excinfo:
        ProjectManager(path).load()
    assert not isinstance(excinfo.value, ProjectUnreadableError)


def test_benign_mtime_touch_allows_save(tmp_path):
    path = _project(tmp_path)
    manager = ProjectManager(path)
    doc = manager.load()
    doc.meta.region = "local-edit"

    # External sync tool: same bytes, new mtime.
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns + 1_000_000_000, st.st_mtime_ns + 1_000_000_000))

    manager.save(doc)  # must NOT raise ProjectStaleWriteError
    assert "local-edit" in path.read_text(encoding="utf-8")


def test_real_foreign_write_still_refuses(tmp_path):
    path = _project(tmp_path)
    manager = ProjectManager(path)
    doc = manager.load()
    doc.meta.region = "local-edit"

    foreign = json.loads(path.read_text(encoding="utf-8"))
    foreign["meta"]["region"] = "foreign-edit"
    path.write_text(json.dumps(foreign), encoding="utf-8")

    with pytest.raises(ProjectStaleWriteError):
        manager.save(doc)
    assert "foreign-edit" in path.read_text(encoding="utf-8")
