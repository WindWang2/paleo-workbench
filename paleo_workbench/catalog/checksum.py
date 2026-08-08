"""Unified SHA-256 checksum helper (ADR 0056).

Single implementation shared by the catalog, the resource scanner, and import
paths so hashing behavior cannot diverge. Streams in fixed-size chunks so
large files (SEGY, rasters) never load fully into memory.

These functions are synchronous and IO-bound by design; callers that need to
keep a UI responsive should wrap them in a worker thread — the functions are
stateless and thread-safe.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MiB, matches the historical scanner behavior


def sha256_file(path: Path, *, chunk_size: int = CHUNK_SIZE) -> str:
    """Return the hex SHA-256 digest of *path*, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file_or_none(path: str | Path) -> str | None:
    """Like :func:`sha256_file` but return None when unreadable (missing/permissions)."""
    try:
        return sha256_file(Path(path))
    except OSError:
        return None
