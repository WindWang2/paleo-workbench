"""#1029 — SelectionContext / CoordinateTransformHub are live UI machinery.

The engines existed (and unit tests exercised them in isolation) but no
production code ever instantiated them: pages kept syncing through ad-hoc
``page.well_selected → other_page.slot`` point-to-point connections. These
tests pin the centralized coordination:

* AppShell owns one SelectionContext + one CoordinateTransformHub;
* Map → Well Log: picking a well publishes ``active_well_id`` and the
  well-log page follows;
* Map → 3D: the same event highlights the well trajectory;
* 3D → Well Log + Map: the legacy direct wire is gone, the context routes;
* Seismic → Well: a published (IL, XL, TWT) cursor resolves through the
  hub to the nearest well + MD and routes to the well-log page;
* no view ever re-processes its own publication (source-tagged echo guard).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui.view_coordination import ViewCoordinationController

SOURCE_MAP = ViewCoordinationController.SOURCE_MAP
SOURCE_3D = ViewCoordinationController.SOURCE_3D
SOURCE_SEISMIC = ViewCoordinationController.SOURCE_SEISMIC


@pytest.fixture()
def shell(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    return shell


def test_app_shell_owns_the_coordination_engines(shell):
    from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
    from paleo_workbench.viz.selection_context import SelectionContext

    assert isinstance(shell.selection_context, SelectionContext)
    assert isinstance(shell.coordinate_hub, CoordinateTransformHub)
    assert shell.view_coordination is not None
    # single ownership: every page reaches the SAME instances
    assert shell.data_page.selection_context is shell.selection_context
    assert shell.data_page.coordinate_hub is shell.coordinate_hub


def test_map_pick_publishes_active_well_into_context(shell):
    map_page = shell.data_page.well_map_panel.map_page

    map_page.well_selected.emit("W-100")

    selection = shell.selection_context.snapshot()
    assert selection.active_well_id == "W-100"
    assert selection.source_widget_id == SOURCE_MAP


def test_map_pick_drives_well_log_page(shell, monkeypatch):
    calls = []
    page = shell.well_log_prediction_page_widget()
    monkeypatch.setattr(page, "set_selected_well", lambda name: calls.append(name) or True)

    shell.data_page.well_map_panel.map_page.well_selected.emit("W-200")

    assert calls == ["W-200"]


def test_map_pick_highlights_3d_trajectory(shell, monkeypatch):
    calls = []
    geo_page = shell.geomodel_page
    monkeypatch.setattr(geo_page, "highlight_well", lambda wid: calls.append(wid))

    shell.data_page.well_map_panel.map_page.well_selected.emit("W-300")

    assert calls == ["W-300"]


def test_3d_pick_routes_through_context_without_direct_wire(shell, monkeypatch):
    """The old workflow_controller page→page wire is replaced by the context."""
    from paleo_workbench.ui import workflow_controller as wc_module

    # the point-to-point handler is no longer connected by the controller
    geo_page = shell.geomodel_page
    welllog_calls = []
    map_calls = []
    monkeypatch.setattr(
        shell.well_log_prediction_page_widget(),
        "set_selected_well",
        lambda name: welllog_calls.append(name) or True,
    )
    monkeypatch.setattr(
        shell.data_page.well_map_panel.map_page,
        "select_well",
        lambda wid, **kw: map_calls.append(wid),
    )

    geo_page.well_selected.emit("W-400")

    selection = shell.selection_context.snapshot()
    assert selection.active_well_id == "W-400"
    assert selection.source_widget_id == SOURCE_3D
    assert welllog_calls == ["W-400"]
    assert map_calls == ["W-400"]


def test_seismic_cursor_resolves_to_nearest_well_md(shell):
    hub = shell.coordinate_hub
    hub.register_well("W-500", x=100.0, y=200.0, total_depth_m=3000.0)

    welllog_calls = []
    page = shell.well_log_prediction_page_widget()
    original = page.set_selected_well
    page.set_selected_well = lambda name: welllog_calls.append(name) or True
    try:
        shell.view_coordination.publish_seismic_cursor(100, 200, 1000.0)
    finally:
        page.set_selected_well = original

    selection = shell.selection_context.snapshot()
    assert selection.seismic_cursor == (100, 200, 1000.0)
    assert welllog_calls == ["W-500"], (
        "IL/XL/TWT cursor must resolve through the hub to the nearest well"
    )


def test_source_tag_prevents_echo_processing(shell, monkeypatch):
    """A view must never re-process a selection it published itself."""
    welllog_calls = []
    monkeypatch.setattr(
        shell.well_log_prediction_page_widget(),
        "set_selected_well",
        lambda name: welllog_calls.append(name) or True,
    )
    map_calls = []
    map_page = shell.data_page.well_map_panel.map_page
    monkeypatch.setattr(
        map_page, "select_well", lambda wid, **kw: map_calls.append(wid)
    )

    # the well-log page publishing its own selection must not loop back
    shell.view_coordination.publish_well_selection(
        "W-600", source=ViewCoordinationController.SOURCE_WELL_LOG
    )
    assert welllog_calls == []
    assert map_calls == ["W-600"]  # other views still follow

    # the map publishing must update everyone EXCEPT the map
    map_page.well_selected.emit("W-700")
    assert map_calls == ["W-600"]  # no self re-entry from the map publication
    assert welllog_calls == ["W-700"]


def test_well_log_refresh_does_not_publish_selection(shell):
    """Routine ``update_state`` refreshes rebuild the task list; those are
    NOT user selections and must not hijack map/3D selection state (the raw
    currentRowChanged subscription did exactly that — review BLOCKER)."""
    from types import SimpleNamespace

    page = shell.well_log_prediction_page_widget()
    published = []
    shell.selection_context.selection_changed.connect(
        lambda sel: published.append(sel.active_well_id)
    )

    page.update_state([SimpleNamespace(name="refresh-only-task")])

    assert not published, f"refresh leaked into selection context: {published}"


def test_seismic_cursor_after_prior_selection_dispatches_once(shell):
    """A cursor publish must route ONLY the cursor — not re-dispatch the
    stale active well through a full canvas rebind (review MAJOR)."""
    shell.coordinate_hub.register_well("W-CUR", x=100.0, y=200.0, total_depth_m=1000.0)
    shell.view_coordination.publish_well_selection(
        "W-PREV", source=ViewCoordinationController.SOURCE_MAP
    )

    calls = []
    page = shell.well_log_prediction_page_widget()
    original = page.set_selected_well
    page.set_selected_well = lambda name: calls.append(name) or True
    try:
        shell.view_coordination.publish_seismic_cursor(100, 200, 1000.0)
    finally:
        page.set_selected_well = original

    assert calls == ["W-CUR"], f"cursor routing double-dispatched: {calls}"
    attrs = shell.selection_context.snapshot().custom_attributes
    assert attrs.get("seismic_well_md") is not None


def test_workflow_controller_direct_wire_is_gone():
    """#1029: the page→page handler was removed; the context routes."""
    from paleo_workbench.ui.workflow_controller import WorkflowController

    assert not hasattr(WorkflowController, "_on_geomodel_well_selected")


def test_well_log_selection_publishes_to_other_views(shell, monkeypatch):
    """Well → Map direction: choosing a task on the well-log page highlights
    the well on the map."""
    map_calls = []
    map_page = shell.data_page.well_map_panel.map_page
    monkeypatch.setattr(
        map_page, "select_well", lambda wid, **kw: map_calls.append(wid)
    )

    from types import SimpleNamespace

    page = shell.well_log_prediction_page_widget()
    # simulate the user picking a task row through the panel's semantic,
    # refresh-suppressed signal (task name == well name)
    page._tasks = [SimpleNamespace(name="W-900")]
    page.task_panel.task_selected.emit(0)

    assert map_calls == ["W-900"], "well-log selection must publish to the map"

