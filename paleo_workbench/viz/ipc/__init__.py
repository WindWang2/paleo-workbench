"""Shared Memory IPC module for zero-copy array transfers."""
from .shared_memory_handle import SharedMemoryArrayHandle, SharedArrayMetadata
from .process_bridge import QProcessFutureBridge

__all__ = [
    "SharedMemoryArrayHandle",
    "SharedArrayMetadata",
    "QProcessFutureBridge",
]
