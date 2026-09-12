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
    position; ``depth_cursor`` is ``(well_key, md_m)`` from the well-log
    side, where *well_key* is the cross-view well key registered in the
    CoordinateTransformHub (the well's display name today — the established
    #1029 key; unique within one project, and the ONLY key every view
    publishes). ``active_well_id`` follows the same key convention.
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
    # -- V11 UIContext 槽位（goal §6）------------------------------------
    # selected_layer_id：用户在任一图层树里**点选/高亮**的层（注意力焦点）。
    # active_layer_id：工具实际作用的「活动层」（QGIS 语义；编辑控制器权威）。
    # edit_target_layer_id：阶段控制器的**编辑目标**（角色解析结果）。
    # 三者是不同状态，禁止混用（01-ui-audit C3）。
    selected_layer_id: str | None = None
    active_layer_id: str | None = None
    edit_target_layer_id: str | None = None
    # 数据资产 / 版本（catalog 稳定 id；Data 页与 Inspector 权威）
    selected_asset_id: str | None = None
    selected_version_id: str | None = None
    # 地震工区（survey 资源 id）与预测/计算任务 id
    active_survey_id: str | None = None
    active_task_id: str | None = None
    # 工作流阶段（MappingStage.value；发布者：MappingStageController）
    workflow_stage: str | None = None
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
        self.selected_layer_id: str | None = None
        self.active_layer_id: str | None = None
        self.edit_target_layer_id: str | None = None
        self.selected_asset_id: str | None = None
        self.selected_version_id: str | None = None
        self.active_survey_id: str | None = None
        self.active_task_id: str | None = None
        self.workflow_stage: str | None = None
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
        selected_layer_id: str | None = _UNSET,
        active_layer_id: str | None = _UNSET,
        edit_target_layer_id: str | None = _UNSET,
        selected_asset_id: str | None = _UNSET,
        selected_version_id: str | None = _UNSET,
        active_survey_id: str | None = _UNSET,
        active_task_id: str | None = _UNSET,
        workflow_stage: str | None = _UNSET,
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
            if selected_layer_id is not _UNSET:
                self.selected_layer_id = selected_layer_id
            if active_layer_id is not _UNSET:
                self.active_layer_id = active_layer_id
            if edit_target_layer_id is not _UNSET:
                self.edit_target_layer_id = edit_target_layer_id
            if selected_asset_id is not _UNSET:
                self.selected_asset_id = selected_asset_id
            if selected_version_id is not _UNSET:
                self.selected_version_id = selected_version_id
            if active_survey_id is not _UNSET:
                self.active_survey_id = active_survey_id
            if active_task_id is not _UNSET:
                self.active_task_id = active_task_id
            if workflow_stage is not _UNSET:
                self.workflow_stage = workflow_stage
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
            selected_layer_id=None,
            active_layer_id=None,
            edit_target_layer_id=None,
            selected_asset_id=None,
            selected_version_id=None,
            active_survey_id=None,
            active_task_id=None,
            workflow_stage=None,
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
                selected_layer_id=self.selected_layer_id,
                active_layer_id=self.active_layer_id,
                edit_target_layer_id=self.edit_target_layer_id,
                selected_asset_id=self.selected_asset_id,
                selected_version_id=self.selected_version_id,
                active_survey_id=self.active_survey_id,
                active_task_id=self.active_task_id,
                workflow_stage=self.workflow_stage,
                map_extent=self.map_extent,
                source_widget_id=self.source_widget_id,
                timestamp=self.timestamp,
                custom_attributes=dict(self.custom_attributes),
            )
