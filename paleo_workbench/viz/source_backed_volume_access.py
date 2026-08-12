"""Source-backed :class:`~geoviz.VolumeAccess` adapter over SeismicVolumeSource.

Bridges Stage-6 lazy SEGY access into the joint 3D scene protocol without
requiring a dense full-cube materialisation for slicing / fences.

Optional ``display_data`` is a dense LOD brick used only by the GL renderer
(``load_volume``). Scene registration / orthogonal indices always use the
logical ``shape`` (native survey dimensions by default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from paleo_workbench.viz.seismic_volume_source import SeismicVolumeSource


class SourceBackedVolumeAccess:
    """VolumeAccess implementation backed by :class:`SeismicVolumeSource`."""

    def __init__(
        self,
        source: "SeismicVolumeSource",
        *,
        shape: tuple[int, int, int] | None = None,
    ) -> None:
        meta = source.metadata()
        native = (int(meta.n_inlines), int(meta.n_crosslines), int(meta.n_samples))
        if any(d < 1 for d in native) and shape is None:
            raise ValueError("source metadata has empty shape")
        self._source = source
        self._native_shape = native if all(d >= 1 for d in native) else (1, 1, 1)
        self._shape = tuple(int(x) for x in (shape or self._native_shape))
        self._display: np.ndarray | None = None
        self._lod_level: int = -1
        self._source_id = meta.source_id

    # ------------------------------------------------------------------ identity
    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def lod_level(self) -> int:
        return int(self._lod_level)

    @property
    def source(self) -> "SeismicVolumeSource":
        return self._source

    # ------------------------------------------------------------------ VolumeAccess
    @property
    def shape(self) -> tuple[int, int, int]:
        """Logical (n_inline, n_crossline, n_sample) for registration / UI."""
        return self._shape

    def slice_inline(self, il_index: int) -> np.ndarray:
        ii = self._clamp(il_index, 0)
        # Prefer dense display when it matches logical shape (fast scrub).
        if self._display is not None and self._display.shape == self._shape:
            return np.asarray(self._display[ii, :, :], dtype=np.float32)
        native_i = self._map_index(ii, axis=0)
        return np.asarray(self._source.read_inline(native_i), dtype=np.float32)

    def slice_crossline(self, xl_index: int) -> np.ndarray:
        xi = self._clamp(xl_index, 1)
        if self._display is not None and self._display.shape == self._shape:
            return np.asarray(self._display[:, xi, :], dtype=np.float32)
        native_x = self._map_index(xi, axis=1)
        return np.asarray(self._source.read_crossline(native_x), dtype=np.float32)

    def slice_time(self, sample_index: int) -> np.ndarray:
        ti = self._clamp(sample_index, 2)
        if self._display is not None and self._display.shape == self._shape:
            return np.asarray(self._display[:, :, ti], dtype=np.float32)
        native_t = self._map_index(ti, axis=2)
        return np.asarray(self._source.read_timeslice(native_t), dtype=np.float32)

    # ------------------------------------------------------------------ GL display LOD
    @property
    def data(self) -> np.ndarray | None:
        """Optional dense brick for GL ``load_volume`` (may be None before L0)."""
        return self._display

    def set_display_data(
        self,
        volume: np.ndarray | None,
        *,
        lod_level: int = 0,
        adopt_shape: bool = True,
    ) -> None:
        """Attach / replace progressive dense LOD for the renderer.

        When *adopt_shape* is True and volume is not None, logical ``shape``
        becomes the display shape so registration matches GL indices (preview
        mode). Slices still fall back to the source when display is missing.
        """
        if volume is None:
            self._display = None
            self._lod_level = -1
            return
        arr = np.ascontiguousarray(volume, dtype=np.float32)
        if arr.ndim != 3:
            raise ValueError("display volume must be 3-D")
        self._display = arr
        self._lod_level = int(lod_level)
        if adopt_shape:
            self._shape = (int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2]))

    # ------------------------------------------------------------------ helpers
    def _clamp(self, index: int, axis: int) -> int:
        n = self._shape[axis]
        if n <= 0:
            return 0
        return int(max(0, min(n - 1, int(index))))

    def _map_index(self, logical_index: int, *, axis: int) -> int:
        """Map logical/display index into native source index space."""
        n_log = max(1, self._shape[axis])
        n_nat = max(1, self._native_shape[axis])
        if n_log == n_nat:
            return int(max(0, min(n_nat - 1, logical_index)))
        # Uniform downsample mapping used by preview strides.
        scale = n_nat / n_log
        return int(max(0, min(n_nat - 1, round(logical_index * scale))))

    def sample_trace(self, il_index: int, xl_index: int) -> np.ndarray:
        """Return one vertical trace for fence extraction (nt,)."""
        ii = self._clamp(il_index, 0)
        xi = self._clamp(xl_index, 1)
        if self._display is not None and self._display.shape == self._shape:
            return np.asarray(self._display[ii, xi, :], dtype=np.float32)
        line = self.slice_inline(ii)
        # line shape (n_xl, n_sample)
        xi2 = min(xi, max(0, line.shape[0] - 1))
        return np.asarray(line[xi2, :], dtype=np.float32)
