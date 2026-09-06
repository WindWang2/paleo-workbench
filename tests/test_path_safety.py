"""I17 — path safety / security: fail-closed validation of untrusted names."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from paleo_workbench.interchange.path_safety import (
    UnsafePathError,
    ensure_within_root,
    extract_archive,
    is_reserved_or_unsafe,
    safe_members,
    safe_relative_path,
    sanitize_filename,
)


class TestSafeRelativePath:
    @pytest.mark.parametrize("name", [
        "../evil.txt",
        "a/../../evil.txt",
        "/absolute/path.txt",
        "C:\\windows\\path.txt",
        "C:/windows/path.txt",
        "..",
        ".",
        "",
        "   ",
        "CON",
        "con.txt",
        "NUL.txt",
        "COM1",
        "bad<name>.txt",
        'bad"quote.txt',
        "pipe|file.txt",
        "ctrl\x01char.txt",
    ])
    def test_rejects_unsafe_names(self, name):
        with pytest.raises(UnsafePathError):
            safe_relative_path(name)

    def test_dot_components_are_normalized_away(self):
        # PurePosixPath drops "." components, so "a/./b.txt" is equivalent to
        # "a/b.txt" — no traversal, therefore acceptable.
        assert safe_relative_path("a/./b.txt").as_posix() == "a/b.txt"

    def test_rejects_nfc_duplicates(self):
        # decomposed 形 (NFD) 必须被拒绝而不是悄悄归一 —— 否则两个 manifest
        # 条目可能解包成同一个文件名（静默覆盖）。
        nfd = "cafe\u0301.txt"
        with pytest.raises(UnsafePathError):
            safe_relative_path(nfd)

    def test_rejects_overlong(self):
        with pytest.raises(UnsafePathError):
            safe_relative_path("a/" + "x" * 300)
        with pytest.raises(UnsafePathError):
            safe_relative_path("/".join(["dir"] * 400))

    def test_accepts_unicode_paths(self):
        pure = safe_relative_path("数据/测井/W-001.las")
        assert pure.as_posix() == "数据/测井/W-001.las"

    def test_accepts_normal_relative(self):
        assert safe_relative_path("artifacts/raw/a/b/file.las").name == "file.las"

    def test_reserved_check_helper(self):
        assert is_reserved_or_unsafe("../x")
        assert is_reserved_or_unsafe("CON")
        assert not is_reserved_or_unsafe("data/file.bin")


class TestZipExtraction:
    def _zip_with(self, tmp_path: Path, entries: dict[str, bytes]) -> Path:
        archive_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive_path, "w") as bundle:
            for name, payload in entries.items():
                bundle.writestr(name, payload)
        return archive_path

    def test_rejects_traversal_entry_before_writing(self, tmp_path):
        archive = self._zip_with(tmp_path, {"good.txt": b"ok", "../evil.txt": b"boom"})
        dest = tmp_path / "out"
        with zipfile.ZipFile(archive) as bundle:
            with pytest.raises(UnsafePathError):
                extract_archive(bundle, dest)
        # fail-closed: NOTHING was written, not even the good entry
        assert not dest.exists() or not any(dest.rglob("*"))

    def test_rejects_absolute_entry(self, tmp_path):
        archive = self._zip_with(tmp_path, {"/etc/passwd": b"boom"})
        with zipfile.ZipFile(archive) as bundle, pytest.raises(UnsafePathError):
            extract_archive(bundle, tmp_path / "out")

    def test_rejects_casefold_collision(self, tmp_path):
        archive = self._zip_with(tmp_path, {"Data/file.txt": b"a", "data/file.txt": b"b"})
        with zipfile.ZipFile(archive) as bundle, pytest.raises(UnsafePathError):
            extract_archive(bundle, tmp_path / "out")

    def test_rejects_reserved_names(self, tmp_path):
        archive = self._zip_with(tmp_path, {"CON": b"a"})
        with zipfile.ZipFile(archive) as bundle, pytest.raises(UnsafePathError):
            extract_archive(bundle, tmp_path / "out")

    def test_rejects_symlink_entries(self, tmp_path):
        archive_path = tmp_path / "link.zip"
        with zipfile.ZipFile(archive_path, "w") as bundle:
            info = zipfile.ZipInfo("link.txt")
            info.external_attr = 0o120777 << 16  # S_IFLNK
            bundle.writestr(info, "/etc/passwd")
        with zipfile.ZipFile(archive_path) as bundle:
            with pytest.raises(UnsafePathError):
                safe_members(bundle)

    def test_extracts_clean_archive(self, tmp_path):
        archive = self._zip_with(tmp_path, {
            "a/b.txt": b"hello",
            "数据/c.las": "数据".encode("utf-8"),
        })
        dest = tmp_path / "out"
        with zipfile.ZipFile(archive) as bundle:
            written = extract_archive(bundle, dest)
        assert len(written) == 2
        assert (dest / "a" / "b.txt").read_bytes() == b"hello"
        assert (dest / "数据" / "c.las").exists()


class TestWithinRoot:
    def test_allows_inside(self, tmp_path):
        root = tmp_path / "pkg"
        root.mkdir()
        candidate = root / "sub" / "f.txt"
        candidate.parent.mkdir()
        candidate.write_text("x")
        assert ensure_within_root(root, candidate) == candidate.resolve()

    def test_rejects_escape(self, tmp_path):
        root = tmp_path / "pkg"
        root.mkdir()
        outsider = tmp_path / "outside.txt"
        outsider.write_text("x")
        with pytest.raises(UnsafePathError):
            ensure_within_root(root, outsider)

    def test_rejects_symlink_escape(self, tmp_path):
        root = tmp_path / "pkg"
        root.mkdir()
        outsider = tmp_path / "outside.txt"
        outsider.write_text("x")
        link = root / "link.txt"
        try:
            link.symlink_to(outsider)
        except OSError:
            pytest.skip("symlink 不可用")
        with pytest.raises(UnsafePathError):
            ensure_within_root(root, link)


def test_sanitize_filename():
    assert sanitize_filename("a/b<c") == "a_b_c"
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("") == "export"
    assert sanitize_filename("  . ") == "export"
    assert len(sanitize_filename("x" * 500)) <= 200
