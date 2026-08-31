"""SelectionContext: Cross-View Selection and Multi-View Coordination State (Feature F16).

Provides an immutable snapshot dataclass (SelectionState) and a thread-safe QObject
selection bus (SelectionContext) for synchronizing selections, depth ranges, and
seismic coordinates across Map Canvas, Well Log Workstation, and Seismic 3D views.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from PySide6.QtCore import QObject, Signal

_UNSET: Any = object()


@dataclass(frozen=True)
class SelectionState:
    """Immutable snapshot of the multi-view selection state.

    The geological slots (``active_horizon_id`` / ``active_fault_id`` /
    ``active_interpretation_id``) carry STABLE domain identities — the same
    ``DomainEntity``/interpretation ids the project store and the catalog
    versions use — never display names, so every view resolves one object
    through one key (scenario D). ``spatial_cursor`` is a map-space (x, y)
    position; ``depth_cursor`` is ``(well_id, md_m)`` from the well-log side.
    """

    active_well_id: str | None = None
    selected_well_ids: tuple[str, ...] = ()
    depth_range: tuple[float, float] | None = None
    seismic_cursor: tuple[int, int, float] | None = None
    active_horizon_id: str | None = None
    active_fault_id: str | None = None
    active_interpretation_id: str | None = None
    spatial_cursor: tuple[float, float] | None = None
    depth_cursor: tuple[str, float] | None = None
    active_layer_id: str | None = None
    map_extent: tuple[float, float, float, float] | None = None
    source_widget_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    custom_attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_depth_range(self) -> tuple[float, float] | None:
        """Return (min_depth, max_depth) regardless of display orientation, or None."""
        if self.depth_range is None:
            return None
        return (min(self.depth_range), max(self.depth_range))


class SelectionContext(QObject):
    """Thread-safe state bus coordinating selection across multi-view workstation widgets."""

    selection_changed = Signal(object)

    def __init__(
        self,
        active_well_id: str | None = None,
        selected_well_ids: Sequence[str] | None = None,
        depth_range: tuple[float, float] | None = None,
        seismic_cursor: tuple[int, int, float] | None = None,
        source_widget_id: str | None = None,
        timestamp: float | None = None,
        custom_attributes: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._lock = threading.RLock()
        self.active_well_id: str | None = active_well_id
        self.selected_well_ids: list[str] = (
            list(selected_well_ids) if selected_well_ids is not None else []
        )
        self.depth_range: tuple[float, float] | None = depth_range
        self.seismic_cursor: tuple[int, int, float] | None = seismic_cursor
        self.active_horizon_id: str | None = None
        self.active_fault_id: str | None = None
        self.active_interpretation_id: str | None = None
        self.spatial_cursor: tuple[float, float] | None = None
        self.depth_cursor: tuple[str, float] | None = None
        self.active_layer_id: str | None = None
        self.map_extent: tuple[float, float, float, float] | None = None
        self.source_widget_id: str | None = source_widget_id
        self.timestamp: float = (
            float(timestamp) if timestamp is not None else time.time()
        )
        self.custom_attributes: dict[str, Any] = (
            dict(custom_attributes) if custom_attributes is not None else {}
        )

    @property
    def normalized_depth_range(self) -> tuple[float, float] | None:
        """Return (min_depth, max_depth) or None if depth_range is not set."""
        with self._lock:
            if self.depth_range is None:
                return None
            return (min(self.depth_range), max(self.depth_range))

    def update(
        self,
        *,
        active_well_id: str | None = _UNSET,
        selected_well_ids: Sequence[str] | None = _UNSET,
        depth_range: tuple[float, float] | None = _UNSET,
        seismic_cursor: tuple[int, int, float] | None = _UNSET,
        active_horizon_id: str | None = _UNSET,
        active_fault_id: str | None = _UNSET,
        active_interpretation_id: str | None = _UNSET,
        spatial_cursor: tuple[float, float] | None = _UNSET,
        depth_cursor: tuple[str, float] | None = _UNSET,
        active_layer_id: str | None = _UNSET,
        map_extent: tuple[float, float, float, float] | None = _UNSET,
        source_widget_id: str | None = _UNSET,
        custom_attributes: dict[str, Any] | None = _UNSET,
    ) -> None:
        """Update selection state fields and emit selection_changed signal.

        Uses private sentinel _UNSET to support partial updates while allowing
        explicit clearing of attributes by passing None.
        """
        with self._lock:
            if active_well_id is not _UNSET:
                self.active_well_id = active_well_id
            if selected_well_ids is not _UNSET:
                self.selected_well_ids = (
                    list(selected_well_ids) if selected_well_ids is not None else []
                )
            if depth_range is not _UNSET:
                self.depth_range = depth_range
            if seismic_cursor is not _UNSET:
                self.seismic_cursor = seismic_cursor
            if active_horizon_id is not _UNSET:
                self.active_horizon_id = active_horizon_id
            if active_fault_id is not _UNSET:
                self.active_fault_id = active_fault_id
            if active_interpretation_id is not _UNSET:
                self.active_interpretation_id = active_interpretation_id
            if spatial_cursor is not _UNSET:
                self.spatial_cursor = spatial_cursor
            if depth_cursor is not _UNSET:
                self.depth_cursor = depth_cursor
            if active_layer_id is not _UNSET:
                self.active_layer_id = active_layer_id
            if map_extent is not _UNSET:
                self.map_extent = map_extent
            if source_widget_id is not _UNSET:
                self.source_widget_id = source_widget_id
            if custom_attributes is not _UNSET:
                self.custom_attributes = (
                    dict(custom_attributes) if custom_attributes is not None else {}
                )
            self.timestamp = time.time()

        self.selection_changed.emit(self)

    def clear(self, source_widget_id: str | None = None) -> None:
        """Reset all selection parameters to empty/None state."""
        self.update(
            active_well_id=None,
            selected_well_ids=[],
            depth_range=None,
            seismic_cursor=None,
            active_horizon_id=None,
            active_fault_id=None,
            active_interpretation_id=None,
            spatial_cursor=None,
            depth_cursor=None,
            active_layer_id=None,
            map_extent=None,
            source_widget_id=source_widget_id,
            custom_attributes={},
        )

    def snapshot(self) -> SelectionState:
        """Create an immutable SelectionState dataclass representing the current state."""
        with self._lock:
            return SelectionState(
                active_well_id=self.active_well_id,
                selected_well_ids=tuple(self.selected_well_ids),
                depth_range=self.depth_range,
                seismic_cursor=self.seismic_cursor,
                active_horizon_id=self.active_horizon_id,
                active_fault_id=self.active_fault_id,
                active_interpretation_id=self.active_interpretation_id,
                spatial_cursor=self.spatial_cursor,
                depth_cursor=self.depth_cursor,
                active_layer_id=self.active_layer_id,
                map_extent=self.map_extent,
                source_widget_id=self.source_widget_id,
                timestamp=self.timestamp,
                custom_attributes=dict(self.custom_attributes),
            )
