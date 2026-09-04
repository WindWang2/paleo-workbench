"""Named workstation layout presets (V3 Light design-qa P3).

Pure data + visibility matrices — no Qt widgets. ``WorkstationFrame`` (workstation shell) applies
these through ``QMainWindow`` dock show/hide and optional ``saveState``
snapshots. Existing ``WorkspacePreset`` values (MAP_AUTHORING, etc.) stay
untouched; workstation ids live beside them via :func:`register_with_dock_manager`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


#: Deprecated document-tab keys (Task 2 removes shell usages, then delete).
TAB_COMPOSITE = "composite"
TAB_JOINT = "joint"


@dataclass(frozen=True)
class DockVisibilityMatrix:
    """Visibility flags for the top-level workstation dock set.

    Composite docks only matter when the composite document is active; the
    shell still applies the flags so switching back to 编图 restores them.
    """

    nav: bool = True
    inspector: bool = True
    process: bool = False
    tasks: bool = False
    composite_layer: bool = True
    composite_input: bool = False
    composite_linked: bool = False
    explorer_expanded: bool = True
    well: bool = False
    seismic: bool = False
    hub: bool = False


@dataclass(frozen=True)
class WorkstationLayoutPreset:
    id: str
    label: str
    description: str
    visibility: DockVisibilityMatrix
    #: When True, float every currently-visible shell dock (low-risk affordance).
    float_visible: bool = False


#: Canonical registry — order is menu order.
WORKSTATION_LAYOUT_PRESETS: tuple[WorkstationLayoutPreset, ...] = (
    WorkstationLayoutPreset(
        id="composite_default",
        label="默认编图",
        description="Variant C full-bleed map; only the layer dock open among composite panels.",
        visibility=DockVisibilityMatrix(
            nav=True,
            inspector=True,
            process=False,
            tasks=False,
            composite_layer=True,
            composite_input=False,
            composite_linked=False,
            explorer_expanded=True,
            well=False,
            seismic=False,
            hub=False,
        ),
    ),
    WorkstationLayoutPreset(
        id="interpretation",
        label="解释工作区",
        description="Explorer + inspector + tasks open for linked interpretation.",
        visibility=DockVisibilityMatrix(
            nav=True,
            inspector=True,
            process=True,
            tasks=True,
            composite_layer=True,
            composite_input=False,
            composite_linked=False,
            explorer_expanded=True,
            well=True,
            seismic=True,
            hub=False,
        ),
    ),
)

#: Alias used by the 面板 menu "恢复默认布局" action.
RESET_LAYOUT_PRESET_ID = "composite_default"


def list_presets() -> tuple[WorkstationLayoutPreset, ...]:
    return WORKSTATION_LAYOUT_PRESETS


def get_preset(preset_id: str) -> WorkstationLayoutPreset | None:
    for preset in WORKSTATION_LAYOUT_PRESETS:
        if preset.id == preset_id:
            return preset
    return None


def preset_labels() -> tuple[tuple[str, str], ...]:
    """``(id, label)`` pairs for UI menus."""
    return tuple((p.id, p.label) for p in WORKSTATION_LAYOUT_PRESETS)


def visibility_dict(matrix: DockVisibilityMatrix) -> dict[str, bool]:
    """Flat dock-key → visible map (stable keys for tests / persistence notes)."""
    return {
        "nav": matrix.nav,
        "inspector": matrix.inspector,
        "process": matrix.process,
        "tasks": matrix.tasks,
        "composite_layer": matrix.composite_layer,
        "composite_input": matrix.composite_input,
        "composite_linked": matrix.composite_linked,
        "explorer_expanded": matrix.explorer_expanded,
        "well": matrix.well,
        "seismic": matrix.seismic,
        "hub": matrix.hub,
    }


def register_with_dock_manager(dock_manager) -> None:
    """Register workstation panel titles into the shared DockManager vocabulary.

    Does not replace existing MAP_AUTHORING / WELL_LOG presets; only seeds
    panel ids used by the V3 shell and FloatController title lookup.
    """
    panels: Iterable[tuple[str, str, str]] = (
        ("workstation:explorer", "资源管理器", "left"),
        ("workstation:inspector", "检查器", "right"),
        ("workstation:process", "Agent", "bottom"),
        ("workstation:tasks", "任务中心", "bottom"),
        ("workstation:composite_layer", "图层管理", "right"),
        ("workstation:composite_input", "输入与结果", "left"),
        ("workstation:composite_linked", "联动视图", "bottom"),
        ("workstation:well", "测井轨道", "bottom"),
        ("workstation:seismic", "地震剖面", "bottom"),
        ("workstation:hub", "功能页", "right"),
    )
    for panel_id, title, area in panels:
        dock_manager.register_panel(panel_id, title, area=area)
