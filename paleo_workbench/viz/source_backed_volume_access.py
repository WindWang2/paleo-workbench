"""Source-backed :class:`~geoviz.VolumeAccess` adapter over SeismicVolumeSource.

Bridges Stage-6 lazy SEGY access into the joint 3D scene protocol without
requiring a dense full-cube materialisation for slicing / fences.

Optional ``display_data`` is a dense LOD brick used only by the GL renderer
(``load_volume``). Scene registration / orthogonal indices always use the
logical ``shape``, which follows the display brick while one is attached.

Coordinate contract
-------------------
The preview brick is produced by strided sampling ``native[::si, ::sx, ::st]``
(``SeismicLoader.get_volume_downsampled``), so logical/preview index *p*
corresponds **exactly** to native index ``p * stride``. The per-axis stride
is carried explicitly (never re-derived from a shape ratio, which drifts by
one sample on odd sizes) and shared with the engine's
:class:`~geoviz.VolumeRegistration` via the ``strides`` property.
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
        strides: tuple[int, int, int] = (1, 1, 1),
    ) -> None:
        meta = source.metadata()
        native = (int(meta.n_inlines), int(meta.n_crosslines), int(meta.n_samples))
        if any(d < 1 for d in native) and shape is None:
            raise ValueError("source metadata has empty shape")
        self._source = source
        self._native_shape = native if all(d >= 1 for d in native) else (1, 1, 1)
        self._shape = tuple(int(x) for x in (shape or self._native_shape))
        self._strides = self._validated_strides(strides)
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

    @property
    def native_shape(self) -> tuple[int, int, int]:
        return self._native_shape

    @property
    def strides(self) -> tuple[int, int, int]:
        """Per-axis (inline, crossline, sample) preview stride over native."""
        return self._strides

    def _validated_strides(
        self, strides: tuple[int, int, int]
    ) -> tuple[int, int, int]:
        s = tuple(max(1, int(x)) for x in strides)
        if len(s) != 3:
            raise ValueError(f"strides must have exactly 3 elements: {strides}")
        for axis, stride in enumerate(s):
            implied = -(-self._native_shape[axis] // stride)  # ceil division
            if implied != self._shape[axis]:
                raise ValueError(
                    f"axis {axis}: stride {stride} implies {implied} samples "
                    f"but logical shape is {self._shape[axis]} (native "
                    f"{self._native_shape[axis]})"
                )
        return s

    # ------------------------------------------------------------------ index mapping
    def logical_to_native(self, axis: int, index: int) -> int:
        """Exact native index for a logical/preview index on *axis*."""
        native_n = self._native_shape[axis]
        return int(max(0, min(native_n - 1, int(index) * self._strides[axis])))

    def native_to_logical(self, axis: int, native_index: float) -> float:
        """Fractional logical index for a native index on *axis*."""
        return float(native_index) / self._strides[axis]

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
        native_i = self.logical_to_native(0, ii)
        return np.asarray(self._source.read_inline(native_i), dtype=np.float32)

    def slice_crossline(self, xl_index: int) -> np.ndarray:
        xi = self._clamp(xl_index, 1)
        if self._display is not None and self._display.shape == self._shape:
            return np.asarray(self._display[:, xi, :], dtype=np.float32)
        native_x = self.logical_to_native(1, xi)
        return np.asarray(self._source.read_crossline(native_x), dtype=np.float32)

    def slice_time(self, sample_index: int) -> np.ndarray:
        ti = self._clamp(sample_index, 2)
        if self._display is not None and self._display.shape == self._shape:
            return np.asarray(self._display[:, :, ti], dtype=np.float32)
        native_t = self.logical_to_native(2, ti)
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
        strides: tuple[int, int, int] | None = None,
    ) -> None:
        """Attach / replace progressive dense LOD for the renderer.

        *strides* must be the per-axis downsample stride the brick was
        produced with (fail-closed validation — an unstrided mismatch is a
        coordinate bug, not something to approximate away).

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
        if strides is not None:
            self._strides = self._validated_strides(strides)
        else:
            # Legacy caller without stride info: infer the stride the shape
            # implies so the mapping stays exact for stride-built previews.
            self._strides = tuple(
                -(-self._native_shape[axis] // self._shape[axis])
                for axis in range(3)
            )

    # ------------------------------------------------------------------ helpers
    def _clamp(self, index: int, axis: int) -> int:
        n = self._shape[axis]
        if n <= 0:
            return 0
        return int(max(0, min(n - 1, int(index))))

    def sample_trace(self, il_index: int, xl_index: int) -> np.ndarray:
        """Return one vertical trace for fence extraction (nt,)."""
        ii = self._clamp(il_index, 0)
        xi = self._clamp(xl_index, 1)
        if self._display is not None and self._display.shape == self._shape:
            return np.asarray(self._display[ii, xi, :], dtype=np.float32)
        read_trace = getattr(self._source, "read_trace", None)
        if callable(read_trace):
            native_i = self.logical_to_native(0, ii)
            native_x = self.logical_to_native(1, xi)
            # SeismicVolumeSource.read_trace takes zero-based il/xl indices
            # and converts to survey line numbers itself.
            return np.asarray(
                read_trace(native_i, native_x), dtype=np.float32
            )
        line = self.slice_inline(ii)
        # line shape (n_xl, n_sample) at NATIVE resolution: the crossline
        # index must be mapped into native space too, never reused as-is.
        native_x = self.logical_to_native(1, xi)
        xi2 = min(native_x, max(0, line.shape[0] - 1))
        return np.asarray(line[xi2, :], dtype=np.float32)
