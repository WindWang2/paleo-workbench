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
    # Workstation V3 Light named layouts (design-qa P3). Coexist with the
    # mapping/well presets above; shell applies them via QMainWindow docks.
    WORKSTATION_COMPOSITE = "workstation_composite"
    WORKSTATION_INTERPRETATION = "workstation_interpretation"


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
    """Manages dockable panel configurations and workspace layout presets.

    Also owns the panel-id registry: the canonical id → title vocabulary the
    :class:`~paleo_workbench.ui.panel_float_controller.FloatController`
    consults when it needs a floating window title. Register a page's panels
    here either bare (``"layer_tree"``) or namespaced
    (``"mapping:layer_tree"``); :meth:`panel_title` tries the exact key first,
    then the suffix after the last ``':'``.
    """

    def __init__(self) -> None:
        self._layouts: dict[WorkspacePreset, WorkspaceLayout] = {}
        self._panels: dict[str, DockPanelConfig] = {}
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
        # Workstation V3 Light presets — mirror layout_presets visibility.
        self._layouts[WorkspacePreset.WORKSTATION_COMPOSITE] = WorkspaceLayout(
            preset=WorkspacePreset.WORKSTATION_COMPOSITE,
            name="默认综合编修",
            docks=[
                DockPanelConfig("workstation:explorer", "资源管理器", visible=True, area="left"),
                DockPanelConfig("workstation:inspector", "检查器", visible=True, area="right"),
                DockPanelConfig("workstation:process", "Agent", visible=False, area="bottom"),
                DockPanelConfig("workstation:tasks", "任务中心", visible=False, area="bottom"),
                DockPanelConfig(
                    "workstation:composite_layer", "图层管理", visible=True, area="right"
                ),
                DockPanelConfig(
                    "workstation:composite_input", "输入与结果", visible=False, area="left"
                ),
                DockPanelConfig(
                    "workstation:composite_linked", "联动视图", visible=False, area="bottom"
                ),
            ],
        )
        self._layouts[WorkspacePreset.WORKSTATION_INTERPRETATION] = WorkspaceLayout(
            preset=WorkspacePreset.WORKSTATION_INTERPRETATION,
            name="解释工作区",
            docks=[
                DockPanelConfig("workstation:explorer", "资源管理器", visible=True, area="left"),
                DockPanelConfig("workstation:inspector", "检查器", visible=True, area="right"),
                DockPanelConfig("workstation:process", "Agent", visible=True, area="bottom"),
                DockPanelConfig("workstation:tasks", "任务中心", visible=True, area="bottom"),
                DockPanelConfig(
                    "workstation:composite_layer", "图层管理", visible=False, area="right"
                ),
                DockPanelConfig(
                    "workstation:composite_input", "输入与结果", visible=False, area="left"
                ),
                DockPanelConfig(
                    "workstation:composite_linked", "联动视图", visible=False, area="bottom"
                ),
            ],
        )
        # The preset docks seed the panel-id registry: ids are unique across
        # presets (first registration wins on collision).
        for layout in self._layouts.values():
            for dock in layout.docks:
                self._panels.setdefault(dock.id, dock)

        # Keep layout_presets panel vocabulary in sync (no-op if already seeded).
        try:
            from paleo_workbench.ui.layout_presets import (
                register_with_dock_manager,
            )

            register_with_dock_manager(self)
        except Exception:
            pass

    def get_layout(self, preset: WorkspacePreset) -> WorkspaceLayout | None:
        return self._layouts.get(preset)

    def set_active_preset(self, preset: WorkspacePreset) -> None:
        if preset in self._layouts:
            self._active_preset = preset

    @property
    def active_layout(self) -> WorkspaceLayout:
        return self._layouts[self._active_preset]

    # --- panel-id registry (FloatController vocabulary) ----------------

    def register_panel(
        self,
        panel_id: str,
        title: str,
        *,
        area: str = "left",
        visible: bool = True,
    ) -> DockPanelConfig:
        """Register (or retitle) a panel id and return its config.

        Existing ids are aliased, not replaced: the returned config is the
        stored instance (for preset-seeded ids, the preset's own
        ``DockPanelConfig``), so a retitle propagates to the preset layout —
        and ``area``/``visible`` are silently ignored for existing ids.
        """
        existing = self._panels.get(panel_id)
        if existing is not None:
            if title:
                existing.title = title
            return existing
        config = DockPanelConfig(
            id=panel_id, title=title, visible=visible, area=area
        )
        self._panels[panel_id] = config
        return config

    def panel_title(self, panel_id: str) -> str | None:
        """Resolve a panel title by exact id, then by ``':'`` suffix."""
        config = self._panels.get(panel_id)
        if config is None:
            suffix = panel_id.rpartition(":")[2]
            if suffix and suffix != panel_id:
                config = self._panels.get(suffix)
        return config.title if config is not None else None

    def has_panel(self, panel_id: str) -> bool:
        return panel_id in self._panels

    def panel_ids(self) -> tuple[str, ...]:
        return tuple(self._panels)


dock_manager = DockManager()
