"""Interactive tools must follow the active layer (#523)."""
from __future__ import annotations

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage


def _page_with_authoring(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    document = PaleoMapDocument(id="map-tools", name="Tools Map", linked_target_horizon="H1")
    page.update_state([document], project_crs="EPSG:3857")
    assert page._authoring_document is not None
    return page


def test_layer_switch_rebinds_select_tool_to_new_layer(qtbot):
    page = _page_with_authoring(qtbot)
    authoring = page._authoring_document
    facies_layer = authoring.layer("facies")
    well_layer = authoring.layer("well")

    authoring.set_active_kind("facies")
    page._on_action_tool_requested("select")
    tool = page._map_tools.active_tool
    assert tool is not None and tool.layer is facies_layer

    # User picks a different layer in the tree: the tool must follow.
    page._on_native_active_layer(well_layer.id)
    rebound = page._map_tools.active_tool
    assert rebound is not None and rebound is not tool
    assert rebound.layer is well_layer


def test_layer_switch_deactivates_kind_bound_add_tool(qtbot):
    """add_point forces the well kind; switching to the facies layer must
    deactivate it instead of silently editing the OLD well layer (#523)."""
    page = _page_with_authoring(qtbot)
    authoring = page._authoring_document

    authoring.set_active_kind("well")
    authoring.start_editing()  # add tools need an open session to install
    page._on_action_tool_requested("add_point")
    assert page._map_tools.active_tool is not None
    assert page._map_tools.active_tool.tool_id == "add_point"

    facies_id = authoring.layer("facies").id
    page._on_native_active_layer(facies_id)
    assert page._map_tools.active_tool.tool_id == "pan"


def test_layer_switch_keeps_kind_bound_tool_on_matching_layer(qtbot):
    """Re-selecting the tool's own kind (e.g. another well sub-layer id)
    keeps the tool active — re-requested, not deactivated."""
    page = _page_with_authoring(qtbot)
    authoring = page._authoring_document

    authoring.set_active_kind("well")
    authoring.start_editing()  # add tools need an open session to install
    page._on_action_tool_requested("add_point")
    tool = page._map_tools.active_tool
    assert tool is not None

    well_id = authoring.layer("well").id
    page._on_native_active_layer(well_id)
    assert page._map_tools.active_tool is not None
    assert page._map_tools.active_tool.tool_id == "add_point"


def test_pan_tool_survives_layer_switch(qtbot):
    page = _page_with_authoring(qtbot)
    authoring = page._authoring_document
    page._on_action_tool_requested("pan")
    page._on_native_active_layer(authoring.layer("well").id)
    assert page._map_tools.active_tool.tool_id == "pan"
