"""Well log API façade delegating to native_backend."""
from __future__ import annotations

import numpy as np

from paleo_workbench.native_backend import native_backend

__all__ = [
    "HAS_CPP_WELL_LOG",
    "fast_las_parse_data",
    "minmax_downsample",
]

# For backwards compatibility with direct imports & mock patches
HAS_CPP_WELL_LOG = native_backend.has_cpp("well_log")


def minmax_downsample(
    depth: np.ndarray,
    values: np.ndarray,
    target_pixels: int = 1000,
) -> tuple[np.ndarray, np.ndarray]:
    """Perform Min-Max 4-Point LOD downsampling for 60 FPS well log rendering."""
    return native_backend.dispatch("minmax_downsample", depth, values, target_pixels)


def fast_las_parse_data(
    content: str, null_value: float = -999.0
) -> tuple[tuple[str, ...], np.ndarray]:
    """Parse ASCII LAS data section (~A block) into headers and 2D float64 numpy array."""
    return native_backend.dispatch("fast_las_parse_data", content, null_value)
