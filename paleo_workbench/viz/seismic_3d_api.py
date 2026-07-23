"""Seismic 3D API façade delegating to native_backend."""
from __future__ import annotations

import numpy as np

from paleo_workbench.native_backend import native_backend

__all__ = [
    "HAS_CPP_SEISMIC",
    "compute_coherence_3d",
    "fast_resample_volume_3d",
    "fast_slice_extract",
    "fast_slice_to_indexed8",
    "marching_cubes_3d",
]

# For backwards compatibility with direct imports & mock patches
HAS_CPP_SEISMIC = native_backend.has_cpp("seismic_3d")


def fast_slice_extract(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    """Extract a 2D slice along axis (0=inline, 1=crossline, 2=time/sample)."""
    return native_backend.dispatch("fast_slice_extract", volume, axis, index)


def fast_slice_to_indexed8(
    volume: np.ndarray, axis: int, index: int
) -> tuple[np.ndarray, float, float]:
    """Extract a 2D slice and normalize it to Indexed8 uint8 in one fast pass."""
    return native_backend.dispatch("fast_slice_to_indexed8", volume, axis, index)


def fast_resample_volume_3d(
    volume: np.ndarray, target_shape: tuple[int, int, int]
) -> np.ndarray:
    """Fast 3D volume downsampling / resampling for LOD visualization."""
    return native_backend.dispatch("fast_resample_volume_3d", volume, target_shape)


def compute_coherence_3d(
    volume: np.ndarray,
    inline_window: int = 3,
    crossline_window: int = 3,
    sample_window: int = 3,
) -> np.ndarray:
    """Compute 3D seismic coherence/similarity volume (per-sample vertical window)."""
    return native_backend.dispatch(
        "compute_coherence_3d",
        volume,
        inline_window=inline_window,
        crossline_window=crossline_window,
        sample_window=sample_window,
    )


def marching_cubes_3d(
    volume: np.ndarray, isovalue: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """3D Isosurface Mesh Extraction via Marching Tetrahedra."""
    return native_backend.dispatch("marching_cubes_3d", volume, isovalue)


class AttributePipeline:
    """High-performance seismic attribute calculation engine delegating to native_backend."""

    def compute_attribute(
        self,
        volume: np.ndarray,
        attribute_type: str = "coherence_3d",
        progress_callback: Any = None,
        cancel_token: Any = None,
        **kwargs: Any,
    ) -> np.ndarray:
        if attribute_type in {"coherence", "coherence_3d"}:
            if progress_callback:
                progress_callback(50.0)
            res = compute_coherence_3d(volume, **kwargs)
            if progress_callback:
                progress_callback(100.0)
            return res.astype(np.float32)

        # Fallback for other spectral or amplitude attributes
        if progress_callback:
            progress_callback(100.0)
        return np.abs(volume).astype(np.float32)


from PySide6.QtCore import QThread, Signal


class AttributeTaskWorker(QThread):
    """Asynchronous worker executing seismic attribute calculations off the UI thread."""

    progress_changed = Signal(float)
    finished = Signal(np.ndarray)
    error = Signal(str)

    def __init__(
        self,
        volume: np.ndarray,
        attribute_type: str = "coherence_3d",
        parent: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)
        self.volume = volume
        self.attribute_type = attribute_type
        self.kwargs = kwargs
        self._is_cancelled = False
        self.pipeline = AttributePipeline()

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            self.progress_changed.emit(10.0)
            if self._is_cancelled:
                return

            def _on_progress(pct: float) -> None:
                self.progress_changed.emit(pct)

            result = self.pipeline.compute_attribute(
                self.volume,
                attribute_type=self.attribute_type,
                progress_callback=_on_progress,
                cancel_token=lambda: self._is_cancelled,
                **self.kwargs,
            )

            if not self._is_cancelled:
                self.progress_changed.emit(100.0)
                self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


__all__.extend(["AttributePipeline", "AttributeTaskWorker"])
