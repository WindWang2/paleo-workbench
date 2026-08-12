"""Byte-budgeted shared cache for seismic slices / preview LOD bricks.

Shared by 2D slice consumers and 3D preview readers so the same
``source_id + orientation + index + lod`` payload is not re-read from disk.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np


def _env_bytes(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        text = str(raw).strip().lower()
        mult = 1
        if text.endswith("kb"):
            mult, text = 1024, text[:-2]
        elif text.endswith("mb"):
            mult, text = 1024 * 1024, text[:-2]
        elif text.endswith("gb"):
            mult, text = 1024 * 1024 * 1024, text[:-2]
        elif text.endswith("b"):
            text = text[:-1]
        return max(1024 * 1024, int(float(text) * mult))
    except ValueError:
        return default


# Default ~256 MiB shared seismic payload budget.
DEFAULT_CACHE_MAX_BYTES = _env_bytes(
    "PALEO_SEISMIC_CACHE_MAX_BYTES", 256 * 1024 * 1024
)


@dataclass(frozen=True, slots=True)
class SeismicCacheKey:
    source_id: str
    kind: str  # "inline" | "crossline" | "timeslice" | "preview" | "lod"
    index: int
    lod: int
    attribute: str = "amplitude"

    def as_tuple(self) -> tuple:
        return (
            self.source_id,
            self.kind,
            int(self.index),
            int(self.lod),
            self.attribute,
        )


class SeismicVolumeCache:
    """Thread-safe LRU cache limited by total ndarray nbytes."""

    def __init__(self, max_bytes: int | None = None) -> None:
        self._max_bytes = int(
            max_bytes if max_bytes is not None else DEFAULT_CACHE_MAX_BYTES
        )
        self._lock = threading.RLock()
        self._entries: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._bytes: dict[tuple, int] = {}
        self._total_bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.physical_puts = 0

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return int(self._total_bytes)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes.clear()
            self._total_bytes = 0

    def invalidate_source(self, source_id: str) -> int:
        """Drop all entries for *source_id*. Returns removed count."""
        removed = 0
        with self._lock:
            keys = [k for k in self._entries if k[0] == source_id]
            for key in keys:
                nbytes = self._bytes.pop(key, 0)
                del self._entries[key]
                self._total_bytes = max(0, self._total_bytes - nbytes)
                removed += 1
                self.evictions += 1
        return removed

    def get(self, key: SeismicCacheKey) -> np.ndarray | None:
        tkey = key.as_tuple()
        with self._lock:
            arr = self._entries.get(tkey)
            if arr is None:
                self.misses += 1
                return None
            self._entries.move_to_end(tkey)
            self.hits += 1
            # Return read-only view; consumers that need mutation must copy.
            out = arr
            if out.flags.writeable:
                out = out.view()
                out.setflags(write=False)
            return out

    def put(self, key: SeismicCacheKey, array: np.ndarray) -> np.ndarray:
        arr = np.ascontiguousarray(array, dtype=np.float32)
        if arr.flags.writeable:
            arr.setflags(write=False)
        nbytes = int(arr.nbytes)
        tkey = key.as_tuple()
        with self._lock:
            if tkey in self._entries:
                old = self._bytes.pop(tkey, 0)
                self._total_bytes = max(0, self._total_bytes - old)
                del self._entries[tkey]
            self._evict_until(nbytes)
            self._entries[tkey] = arr
            self._bytes[tkey] = nbytes
            self._total_bytes += nbytes
            self.physical_puts += 1
            return arr

    def _evict_until(self, needed: int) -> None:
        # Allow a single entry larger than budget (store it, keep only it).
        while self._entries and (self._total_bytes + needed) > self._max_bytes:
            old_key, _ = self._entries.popitem(last=False)
            old_n = self._bytes.pop(old_key, 0)
            self._total_bytes = max(0, self._total_bytes - old_n)
            self.evictions += 1

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "total_bytes": self._total_bytes,
                "max_bytes": self._max_bytes,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "physical_puts": self.physical_puts,
            }


# Process-wide default cache shared by all SeismicVolumeSource instances.
_GLOBAL_CACHE: SeismicVolumeCache | None = None
_GLOBAL_LOCK = threading.Lock()


def get_global_seismic_cache() -> SeismicVolumeCache:
    global _GLOBAL_CACHE
    with _GLOBAL_LOCK:
        if _GLOBAL_CACHE is None:
            _GLOBAL_CACHE = SeismicVolumeCache()
        return _GLOBAL_CACHE


def reset_global_seismic_cache() -> None:
    """Test helper: drop the process-wide cache instance."""
    global _GLOBAL_CACHE
    with _GLOBAL_LOCK:
        if _GLOBAL_CACHE is not None:
            _GLOBAL_CACHE.clear()
        _GLOBAL_CACHE = None
