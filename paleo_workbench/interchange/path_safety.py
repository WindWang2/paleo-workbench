"""Path-safety primitives for package extraction and manifest resolution.

Everything that turns a *manifest string* or an *archive entry name* into a
filesystem path must go through this module. The policy is fail-closed:
suspicious input is rejected with :class:`UnsafePathError`, never sanitized
silently, so callers cannot accidentally "skip" a malicious entry and continue
with a half-open package.

Defended cases:

- ``../`` traversal and absolute-path injection (POSIX and Windows forms)
- symlinks (and other non-regular members) escaping the package root
- duplicate names after Unicode NFC normalization
- case-insensitive collisions (macOS/Windows filesystems)
- Windows reserved device names (CON, NUL, COM1, ...)
- overlong paths / path components
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PurePosixPath


class UnsafePathError(ValueError):
    """Raised when an entry name must be rejected (fail-closed)."""


MAX_COMPONENT_LEN = 200
MAX_RELATIVE_LEN = 900

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Control characters and Windows-independent troublemakers in component names.
_BAD_CHARS_RE = re.compile(r"[<>:\"|?*\x00-\x1f]")


def safe_relative_path(name: str, *, what: str = "entry") -> PurePosixPath:
    """Validate a package-relative POSIX path and return it.

    Raises :class:`UnsafePathError` for anything that is not a clean,
    traversal-free, collision-safe relative path.
    """
    if not name or not name.strip():
        raise UnsafePathError(f"{what}: empty path")
    if "\x00" in name:
        raise UnsafePathError(f"{what}: NUL byte in {name!r}")

    normalized = unicodedata.normalize("NFC", name)
    if normalized != name:
        # Reject rather than rewrite: two manifest entries must never differ
        # only by Unicode normalization form (silent duplicate names).
        raise UnsafePathError(f"{what}: non-NFC path {name!r}")

    pure = PurePosixPath(normalized.replace("\\", "/"))
    if pure.is_absolute() or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise UnsafePathError(f"{what}: absolute path not allowed: {name!r}")

    parts = pure.parts
    if not parts:
        raise UnsafePathError(f"{what}: no components in {name!r}")
    for part in parts:
        if part in (".", ".."):
            raise UnsafePathError(f"{what}: traversal component in {name!r}")
        if not part.strip():
            raise UnsafePathError(f"{what}: blank path component in {name!r}")
        if part != part.rstrip(" ."):
            # NTFS/FAT strip trailing dots/spaces: "file.txt." would silently
            # overwrite "file.txt" and "com1 " would target the COM1 device.
            raise UnsafePathError(f"{what}: trailing dot/space in {part!r}")
        if len(part) > MAX_COMPONENT_LEN:
            raise UnsafePathError(f"{what}: path component too long in {name!r}")
        stem = part.split(".")[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise UnsafePathError(f"{what}: Windows reserved name {part!r}")
        if _BAD_CHARS_RE.search(part):
            raise UnsafePathError(f"{what}: reserved character in {part!r}")

    rel = "/".join(parts)
    if len(rel) > MAX_RELATIVE_LEN:
        raise UnsafePathError(f"{what}: path too long: {name!r}")
    return pure


def check_collision(name: PurePosixPath, seen_casefold: set[str], seen_nfc: set[str]) -> None:
    """Track a validated name; raise on NFC-duplicate or case-insensitive clash."""
    key = str(name)
    if key in seen_nfc:
        raise UnsafePathError(f"duplicate entry after normalization: {key!r}")
    folded = key.casefold()
    if folded in seen_casefold:
        raise UnsafePathError(f"case-insensitive collision: {key!r}")
    seen_nfc.add(key)
    seen_casefold.add(folded)


def ensure_within_root(root: Path, candidate: Path) -> Path:
    """Resolve *candidate* under *root* and fail-closed on escape or symlink.

    Returns the resolved path. Rejects when any resolved component stops
    being inside *root* (covers both ``..`` survivors and symlinked dirs).
    """
    root = root.resolve()
    candidate = Path(candidate)
    if candidate.is_symlink():
        raise UnsafePathError(f"symlink rejected: {candidate}")
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise UnsafePathError(f"path escapes package root: {candidate}")
    return resolved


def safe_members(archive, *, what: str = "archive") -> list[str]:
    """Return validated member names of a :class:`zipfile.ZipFile`.

    Every name goes through :func:`safe_relative_path` plus a casefold/NFC
    collision pass. Any failure raises :class:`UnsafePathError` — callers must
    abort the whole extraction, not skip the entry.
    """
    # Imported lazily so this module stays usable without zipfile consumers.
    from zipfile import ZipInfo

    seen_casefold: set[str] = set()
    seen_nfc: set[str] = set()
    names: list[str] = []
    for info in archive.infolist():
        if isinstance(info, ZipInfo) and (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise UnsafePathError(f"{what}: symlink entry rejected: {info.filename!r}")
        pure = safe_relative_path(info.filename, what=what)
        check_collision(pure, seen_casefold, seen_nfc)
        names.append(str(pure))
    return names


def extract_archive(archive, dest_root: Path, *, what: str = "package") -> list[Path]:
    """Extract a validated zip archive into *dest_root*, fail-closed.

    Files only; directories are created implicitly. Any unsafe entry aborts
    the whole extraction *before* any file is written (validation first,
    writes second — a partially extracted malicious package is never left
    behind on failure).
    """
    import zipfile

    if not isinstance(archive, zipfile.ZipFile):
        raise TypeError("extract_archive expects an opened zipfile.ZipFile")
    names = safe_members(archive, what=what)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for info, name in zip(archive.infolist(), names):
        target = ensure_within_root(dest_root, dest_root / name)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, open(target, "wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
        written.append(target)
    return written


def sanitize_filename(stem: str, fallback: str = "export") -> str:
    """Make an arbitrary string safe to use as a single file name."""
    cleaned = unicodedata.normalize("NFC", stem)
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f/\\]', "_", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.split(".")[0].upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:MAX_COMPONENT_LEN]


def is_reserved_or_unsafe(name: str) -> bool:
    """True when *name* would be rejected as a path component."""
    try:
        safe_relative_path(name)
        return False
    except UnsafePathError:
        return True


def os_replace_atomic(temp_path: Path, target_path: Path) -> None:
    """os.replace with a directory fsync so renames survive power loss."""
    os.replace(temp_path, target_path)
    fd = os.open(str(target_path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
