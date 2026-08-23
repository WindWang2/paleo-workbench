"""Workspace and Dock Panel Layout Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkspacePreset(str, Enum):
    DATA_MANAGEMENT = "data_management"
    WELL_LOG_INTERPRETATION = "well_log"
    SEISMIC_ANALYSIS = "seismic"
    SINGLE_FACTOR_MAPPING = "single_factor"
    MAP_AUTHORING = "map_authoring"
    GEOMODEL_3D = "geomodel_3d"


@dataclass
class DockPanelConfig:
    id: str
    title: str
    visible: bool = True
    floating: bool = False
    area: str = "left"  # left, right, top, bottom


@dataclass
class WorkspaceLayout:
    preset: WorkspacePreset
    name: str
    docks: list[DockPanelConfig] = field(default_factory=list)


class DockManager:
    """Manages dockable panel configurations and workspace layout presets."""

    def __init__(self) -> None:
        self._layouts: dict[WorkspacePreset, WorkspaceLayout] = {}
        self._active_preset: WorkspacePreset = WorkspacePreset.MAP_AUTHORING
        self._register_default_presets()

    def _register_default_presets(self) -> None:
        self._layouts[WorkspacePreset.MAP_AUTHORING] = WorkspaceLayout(
            preset=WorkspacePreset.MAP_AUTHORING,
            name="古地理综合编图工作区",
            docks=[
                DockPanelConfig("layer_tree", "图层管理树", visible=True, area="left"),
                DockPanelConfig("map_tools", "制图工具箱", visible=True, area="left"),
                DockPanelConfig("property_inspector", "图斑属性检查器", visible=True, area="right"),
                DockPanelConfig("history_panel", "拓扑操作历史", visible=True, area="right"),
                DockPanelConfig("qa_audit", "合规质检报告", visible=False, area="bottom"),
            ],
        )
        self._layouts[WorkspacePreset.WELL_LOG_INTERPRETATION] = WorkspaceLayout(
            preset=WorkspacePreset.WELL_LOG_INTERPRETATION,
            name="测井解释与地层对比工作区",
            docks=[
                DockPanelConfig("well_tree", "井目录与道模板", visible=True, area="left"),
                DockPanelConfig("correlation_panel", "井间对比与拉平", visible=True, area="right"),
                DockPanelConfig("crossplot", "岩性交会图", visible=True, area="bottom"),
            ],
        )

    def get_layout(self, preset: WorkspacePreset) -> WorkspaceLayout | None:
        return self._layouts.get(preset)

    def set_active_preset(self, preset: WorkspacePreset) -> None:
        if preset in self._layouts:
            self._active_preset = preset

    @property
    def active_layout(self) -> WorkspaceLayout:
        return self._layouts[self._active_preset]


dock_manager = DockManager()
