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


class ChecksumCancelled(Exception):
    """Raised by :func:`sha256_file` when its cancel callback fires mid-hash.

    The digest is deliberately NOT returned partial — callers surface an
    honest "cancelled" state instead of a wrong checksum."""


def sha256_file(
    path: Path,
    *,
    chunk_size: int = CHUNK_SIZE,
    cancel: "callable[[], bool] | None" = None,
) -> str:
    """Return the hex SHA-256 digest of *path*, read in chunks.

    ``cancel`` (v6 #1224): polled once per chunk; hashing a multi-GB payload
    is interruptible at MiB granularity instead of blocking until completion.
    Raises :class:`ChecksumCancelled` — never a partial digest.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            if cancel is not None and cancel():
                raise ChecksumCancelled(f"hash cancelled: {path}")
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file_or_none(path: str | Path) -> str | None:
    """Like :func:`sha256_file` but return None when unreadable (missing/permissions)."""
    try:
        return sha256_file(Path(path))
    except OSError:
        return None


def sha256_text(text: str) -> str:
    """Return hex SHA-256 digest of text normalized to LF line endings (#998)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
