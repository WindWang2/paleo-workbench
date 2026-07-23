"""SeismicVolumeState: Centralized observer module for 2D/3D slice coordinates & coordinate transforms."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_seismic.models import BinGridGeometry


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
