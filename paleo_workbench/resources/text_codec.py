"""Shared text decoding for user-supplied data files.

Chinese well data (LAS headers, formation tops CSVs, SMI well heads)
frequently arrives GBK/GB18030-encoded; decoding it as UTF-8 with
``errors="replace"`` silently corrupts every Chinese character (#1004,
ISSUE-010). The canonical fallback chain lives here so every parser uses
the same order: UTF-8-sig, then GB18030 (GBK superset), then replace.
"""

from __future__ import annotations


def decode_text_with_fallback(raw_bytes: bytes) -> str:
    """Decode bytes attempting UTF-8-sig, then GB18030/GBK, then replace (#1004)."""
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return raw_bytes.decode("gb18030")
    except UnicodeDecodeError:
        pass
    return raw_bytes.decode("utf-8-sig", errors="replace")


def read_text_with_fallback(path) -> str:
    """Read a whole file as text using the shared fallback chain."""
    from pathlib import Path

    return decode_text_with_fallback(Path(path).read_bytes())
