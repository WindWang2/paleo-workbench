"""Shared Memory Handle for zero-copy numpy array transfers across processes."""
from __future__ import annotations

from dataclasses import dataclass
import multiprocessing.shared_memory as sm
from typing import Any
import numpy as np


@dataclass(frozen=True)
class SharedArrayMetadata:
    shm_name: str
    shape: tuple[int, ...]
    dtype: str
    size_bytes: int


class SharedMemoryArrayHandle:
    """RAII wrapper for zero-copy numpy array transfers across process boundaries."""

    def __init__(self, shm_name: str, shape: tuple[int, ...], dtype: str | np.dtype, is_owner: bool = False):
        self.shm_name = shm_name
        self.shape = shape
        self.dtype = np.dtype(dtype)
        self.is_owner = is_owner
        self._shm: sm.SharedMemory | None = sm.SharedMemory(name=shm_name, create=False)
        self.array = np.ndarray(self.shape, dtype=self.dtype, buffer=self._shm.buf)

    @classmethod
    def create(cls, shape: tuple[int, ...], dtype: str | np.dtype) -> tuple[SharedMemoryArrayHandle, SharedArrayMetadata]:
        dt = np.dtype(dtype)
        size_bytes = int(np.prod(shape)) * dt.itemsize
        shm = sm.SharedMemory(create=True, size=size_bytes)
        meta = SharedArrayMetadata(
            shm_name=shm.name,
            shape=shape,
            dtype=dt.name,
            size_bytes=size_bytes,
        )
        handle = cls(shm_name=shm.name, shape=shape, dtype=dt, is_owner=True)
        return handle, meta

    def close(self) -> None:
        if getattr(self, "_shm", None) is not None:
            try:
                self._shm.close()
            except (BufferError, AttributeError, OSError):
                pass
            if self.is_owner:
                try:
                    self._shm.unlink()
                except (FileNotFoundError, AttributeError, OSError):
                    pass
            self._shm = None
