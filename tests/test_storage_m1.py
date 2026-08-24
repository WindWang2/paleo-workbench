"""Tests for storage safe_unlink and atomic working copy (Issue #972)."""

from pathlib import Path
import stat
from paleo_workbench.catalog.storage import (
    safe_unlink,
    create_working_copy,
    purge_trashed_payload,
    _make_readonly,
)


def test_safe_unlink_handles_readonly_file(tmp_path: Path):
    """safe_unlink must remove read-only files on Windows NTFS without raising PermissionError."""
    target = tmp_path / "readonly_file.txt"
    target.write_text("read-only payload", encoding="utf-8")
    _make_readonly(target)

    # Should safely unlink without PermissionError
    safe_unlink(target)
    assert not target.exists()


def test_safe_unlink_missing_file_is_noop(tmp_path: Path):
    """safe_unlink on non-existent file should be a silent no-op."""
    missing = tmp_path / "does_not_exist.bin"
    safe_unlink(missing)  # No exception raised


def test_create_working_copy_atomically_overwrites_existing_readonly(tmp_path: Path):
    """create_working_copy must atomically overwrite existing file even if read-only."""
    version_id = "v-test-123"
    version_file = tmp_path / "source_payload.bin"
    version_file.write_bytes(b"version-data-bytes" * 50)
    _make_readonly(version_file)

    # Create working copy first time
    working_path = create_working_copy(tmp_path, version_file, version_id)
    assert working_path.is_file()
    assert working_path.read_bytes() == b"version-data-bytes" * 50

    # Mark working copy read-only as if it was locked
    _make_readonly(working_path)

    # Update version file with new content
    version_file_2 = tmp_path / "source_payload.bin"
    # Make writable to update
    version_file_2.chmod(stat.S_IWRITE | stat.S_IREAD)
    version_file_2.write_bytes(b"updated-data-bytes" * 50)
    _make_readonly(version_file_2)

    # Overwrite working copy atomically
    working_path_2 = create_working_copy(tmp_path, version_file_2, version_id)
    assert working_path_2 == working_path
    assert working_path_2.read_bytes() == b"updated-data-bytes" * 50


def test_purge_trashed_payload_removes_readonly_trashed_file(tmp_path: Path):
    """purge_trashed_payload must remove read-only trashed files cleanly."""
    trash_file = tmp_path / "trashed_version.bin"
    trash_file.write_bytes(b"trashed-content")
    _make_readonly(trash_file)

    purge_trashed_payload(tmp_path, trash_file)
    assert not trash_file.exists()
