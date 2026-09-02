"""Pure-logic tests for workstation named layout presets (no display)."""

from __future__ import annotations

from paleo_workbench.ui.dock_manager import WorkspacePreset, DockManager
from paleo_workbench.ui.layout_presets import (
    RESET_LAYOUT_PRESET_ID,
    TAB_COMPOSITE,
    TAB_JOINT,
    get_preset,
    list_presets,
    preset_labels,
    register_with_dock_manager,
    visibility_dict,
)


def test_named_presets_cover_composite_and_interpretation():
    presets = list_presets()
    ids = {p.id for p in presets}
    assert "composite_default" in ids
    assert "interpretation" in ids
    assert RESET_LAYOUT_PRESET_ID == "composite_default"

    composite = get_preset("composite_default")
    assert composite is not None
    assert composite.label == "默认综合编修"
    assert composite.document_tab == TAB_COMPOSITE
    matrix = visibility_dict(composite.visibility)
    assert matrix["composite_layer"] is True
    assert matrix["composite_input"] is False
    assert matrix["composite_linked"] is False
    assert matrix["nav"] is True

    interpretation = get_preset("interpretation")
    assert interpretation is not None
    assert interpretation.label == "解释工作区"
    assert interpretation.document_tab == TAB_JOINT
    im = visibility_dict(interpretation.visibility)
    assert im["inspector"] is True
    assert im["tasks"] is True
    assert im["explorer_expanded"] is True


def test_preset_labels_are_stable_menu_pairs():
    labels = preset_labels()
    assert labels[0] == ("composite_default", "默认综合编修")
    assert ("interpretation", "解释工作区") in labels


def test_dock_manager_keeps_map_authoring_and_adds_workstation_presets():
    mgr = DockManager()
    assert WorkspacePreset.MAP_AUTHORING in mgr._layouts
    assert WorkspacePreset.WELL_LOG_INTERPRETATION in mgr._layouts
    assert WorkspacePreset.WORKSTATION_COMPOSITE in mgr._layouts
    assert WorkspacePreset.WORKSTATION_INTERPRETATION in mgr._layouts

    map_layout = mgr.get_layout(WorkspacePreset.MAP_AUTHORING)
    assert map_layout is not None
    assert map_layout.name == "古地理综合编图工作区"
    assert any(d.id == "layer_tree" for d in map_layout.docks)

    ws = mgr.get_layout(WorkspacePreset.WORKSTATION_COMPOSITE)
    assert ws is not None
    assert ws.name == "默认综合编修"
    assert mgr.panel_title("workstation:inspector") == "检查器"


def test_register_with_dock_manager_is_idempotent():
    mgr = DockManager()
    before = mgr.panel_ids()
    register_with_dock_manager(mgr)
    assert mgr.panel_ids() == before
    assert mgr.panel_title("workstation:composite_layer") == "图层管理"


def test_unknown_preset_returns_none():
    assert get_preset("nope") is None
