import math
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal


@dataclass
class BinGridGeometry:
    """Bin-grid geometry for mapping inline/crossline to world coordinates."""

    x_origin: float = 500000.0
    y_origin: float = 3000000.0
    il_azimuth_deg: float = 0.0
    il_spacing_m: float = 25.0
    xl_spacing_m: float = 25.0

    def xy_to_il_xl(self, x: float, y: float) -> tuple[float, float]:
        dx = x - self.x_origin
        dy = y - self.y_origin
        az = math.radians(self.il_azimuth_deg)
        cos_a, sin_a = math.cos(az), math.sin(az)
        il_frac = (-dx * sin_a + dy * cos_a) / self.il_spacing_m
        xl_frac = (dx * cos_a + dy * sin_a) / self.xl_spacing_m
        return il_frac, xl_frac

    def il_xl_to_xy(self, il_frac: float, xl_frac: float) -> tuple[float, float]:
        az = math.radians(self.il_azimuth_deg)
        cos_a, sin_a = math.cos(az), math.sin(az)
        x = self.x_origin - il_frac * self.il_spacing_m * sin_a + xl_frac * self.xl_spacing_m * cos_a
        y = self.y_origin + il_frac * self.il_spacing_m * cos_a + xl_frac * self.xl_spacing_m * sin_a
        return x, y


class SeismicVolumeState(QObject):
    """Event-driven state observer for seismic volume slice coordinates and spatial coordinate mappings.

    Signals:
        slice_changed (int, int, int): Emitted when (inline, crossline, sample) changes.
        horizon_selected (str): Emitted when a target horizon selection changes.
    """

    slice_changed = Signal(int, int, int)
    horizon_selected = Signal(str)

    def __init__(
        self,
        inline_range: tuple[int, int] = (0, 1000),
        crossline_range: tuple[int, int] = (0, 1000),
        sample_range: tuple[int, int] = (0, 1000),
        geometry: BinGridGeometry | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.inline_min, self.inline_max = inline_range
        self.crossline_min, self.crossline_max = crossline_range
        self.sample_min, self.sample_max = sample_range

        self._inline_idx: int = self.inline_min
        self._crossline_idx: int = self.crossline_min
        self._sample_idx: int = self.sample_min
        self._active_horizon: str | None = None

        self.geometry: BinGridGeometry = geometry or BinGridGeometry(
            x_origin=500000.0,
            y_origin=3000000.0,
            il_azimuth_deg=0.0,
            il_spacing_m=25.0,
            xl_spacing_m=25.0,
        )

    @property
    def inline_idx(self) -> int:
        return self._inline_idx

    @property
    def crossline_idx(self) -> int:
        return self._crossline_idx

    @property
    def sample_idx(self) -> int:
        return self._sample_idx

    @property
    def t_slice_idx(self) -> int:
        """Alias for sample_idx to align with domain model vocabulary."""
        return self._sample_idx

    @property
    def active_horizon(self) -> str | None:
        return self._active_horizon

    def set_slice(
        self,
        inline: int | None = None,
        crossline: int | None = None,
        sample: int | None = None,
    ) -> None:
        """Update slice indices and emit slice_changed signal if modified."""
        changed = False

        if inline is not None:
            clamped_il = max(self.inline_min, min(self.inline_max, int(inline)))
            if clamped_il != self._inline_idx:
                self._inline_idx = clamped_il
                changed = True

        if crossline is not None:
            clamped_xl = max(self.crossline_min, min(self.crossline_max, int(crossline)))
            if clamped_xl != self._crossline_idx:
                self._crossline_idx = clamped_xl
                changed = True

        if sample is not None:
            clamped_s = max(self.sample_min, min(self.sample_max, int(sample)))
            if clamped_s != self._sample_idx:
                self._sample_idx = clamped_s
                changed = True

        if changed:
            self.slice_changed.emit(self._inline_idx, self._crossline_idx, self._sample_idx)

    def select_horizon(self, horizon_id: str) -> None:
        """Select active horizon and emit horizon_selected signal."""
        if horizon_id != self._active_horizon:
            self._active_horizon = horizon_id
            self.horizon_selected.emit(horizon_id)

    def grid_to_geographic(self, il: float, xl: float) -> tuple[float, float]:
        """Convert grid (inline, crossline) to geographic (easting, northing)."""
        return self.geometry.il_xl_to_xy(il, xl)

    def geographic_to_grid(self, easting: float, northing: float) -> tuple[float, float]:
        """Convert geographic (easting, northing) to grid (inline, crossline)."""
        return self.geometry.xy_to_il_xl(easting, northing)
