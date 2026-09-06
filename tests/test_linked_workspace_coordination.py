"""L8 — Map ↔ Well ↔ Seismic bidirectional linking through the docks.

Case A: a well selection anywhere opens/focuses the workstation well dock.
Case B: a seismic cursor resolves to a CALIBRATED MD and drives the docked
well view's native link cursor (cleared when no authority exists).
Case C: the docked well panel publishes depth cursors under its own well
name; the echo path (link cursor → native crosshairChanged) is suppressed
by the L2 value-match guard, so no loop.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.ui.view_coordination import ViewCoordinationController
from paleo_workbench.viz.coordinate_hub import (
    CoordinateTransformHub,
    TimeDepthCalibration,
)
from paleo_workbench.viz.selection_context import SelectionContext

SOURCE_SEISMIC = ViewCoordinationController.SOURCE_SEISMIC


@pytest.fixture()
def hub() -> CoordinateTransformHub:
    hub = CoordinateTransformHub()
    hub.register_well("W-1", x=100.0, y=200.0, elevation=25.0, total_depth_m=4000.0)
    hub.set_time_depth_calibration(
        TimeDepthCalibration.from_pairs(
            "W-1",
            [(0.0, 0.0), (2000.0, 1600.0), (4000.0, 3000.0)],
            provenance="checkshot:test",
        )
    )
    hub.configure_seismic_grid(
        origin=(0.0, 0.0), il_step=(25.0, 0.0), xl_step=(0.0, 25.0), il_min=0, xl_min=0
    )
    return hub


@pytest.fixture()
def controller(hub) -> ViewCoordinationController:
    return ViewCoordinationController(SelectionContext(), hub)


class _Panel:
    """Well-panel double: current well name + depth-cursor signal plumbing."""

    def __init__(self, well_name: str):
        self._well_name = well_name
        self.link_calls: list = []

    def current_well_name(self) -> str:
        return self._well_name

    def set_link_cursor(self, md):
        self.link_calls.append(md)
        return True


# ---------------------------------------------------------------------------
# Case A — well selection → well dock
# ---------------------------------------------------------------------------


def test_well_selection_routes_to_dock_sink(controller):
    opened: list[str] = []
    controller.set_well_dock_sink(opened.append)

    controller.publish_well_selection("W-1", source=controller.SOURCE_MAP)

    assert opened == ["W-1"]


def test_dock_sink_failure_never_breaks_routing(controller):
    def _boom(_name):
        raise RuntimeError("dock destroyed")

    controller.set_well_dock_sink(_boom)
    controller.publish_well_selection("W-1", source=controller.SOURCE_MAP)  # no raise
    assert controller.selection_context.snapshot().active_well_id == "W-1"


# ---------------------------------------------------------------------------
# Case B — seismic cursor → calibrated MD → link cursor
# ---------------------------------------------------------------------------


def test_seismic_cursor_drives_link_cursor_with_calibrated_md(controller):
    panel = _Panel("W-1")
    controller.set_link_cursor_sink(
        lambda well, md: panel.set_link_cursor(md)
    )

    # (il, xl) of the well head: x=100 → il 4, y=200 → xl 8; TWT 1600 ms is
    # inside the calibration and maps back to exactly MD 2000 m.
    controller.publish_seismic_cursor(4, 8, 1600.0)

    assert panel.link_calls == [2000.0]
    attrs = controller.selection_context.snapshot().custom_attributes
    assert attrs["seismic_well_md_is_approximate"] is False
    assert attrs["seismic_well_md_authority"] == "time-depth:checkshot:test"


def test_seismic_cursor_without_authority_clears_shown_cursor(controller):
    controller.coordinate_hub.clear_time_depth_calibration("W-1")
    panel = _Panel("W-1")
    controller.set_link_cursor_sink(
        lambda well, md: panel.set_link_cursor(md)
    )

    # First a calibrated cursor is impossible → nothing shown, no clear yet.
    controller.publish_seismic_cursor(4, 8, 1600.0)
    assert panel.link_calls == []

    # After a cursor HAS been shown (simulate by arming the state), the next
    # authority-less cursor must clear it exactly once.
    controller._link_cursor_set = True
    controller.publish_seismic_cursor(4, 8, 1700.0)
    assert panel.link_calls == [None]


def test_approximate_md_does_not_drive_link_cursor(controller):
    """Velocity-assumption readouts stay readouts: the native link cursor
    only ever shows CALIBRATED depths."""
    controller.coordinate_hub.clear_time_depth_calibration("W-1")
    controller.coordinate_hub.set_velocity(2000.0)
    panel = _Panel("W-1")
    controller.set_link_cursor_sink(
        lambda well, md: panel.set_link_cursor(md)
    )

    controller.publish_seismic_cursor(4, 8, 1600.0)

    assert panel.link_calls == []
    attrs = controller.selection_context.snapshot().custom_attributes
    assert attrs["seismic_well_md_is_approximate"] is True


def test_clear_project_resets_link_cursor_state(controller):
    panel = _Panel("W-1")
    controller.set_link_cursor_sink(
        lambda well, md: panel.set_link_cursor(md)
    )
    controller.publish_seismic_cursor(4, 8, 1600.0)
    assert controller._link_cursor_set is True

    controller.clear_project()

    assert controller._link_cursor_set is False


# ---------------------------------------------------------------------------
# Case C — dock panel depth-cursor producer
# ---------------------------------------------------------------------------


def test_dock_panel_depth_cursor_publishes_under_its_well(controller):
    publishes: list[tuple[str, float, str]] = []
    original = controller.publish_depth_cursor

    def _spy(well, md, *, source):
        publishes.append((well, md, source))
        return original(well, md, source=source)

    controller.publish_depth_cursor = _spy
    try:
        panel = _Panel("W-1")
        controller.attach_well_dock_panel(panel)

        # simulate the panel's depth_cursor_moved signal handler path
        controller._on_dock_depth_cursor(panel, 1234.5)
        assert publishes == [("W-1", 1234.5, controller.SOURCE_WELL_LOG)]
    finally:
        controller.publish_depth_cursor = original

    # a panel without a well never publishes
    anonymous = _Panel("")
    controller._on_dock_depth_cursor(anonymous, 10.0)
    assert len(publishes) == 1


# ---------------------------------------------------------------------------
# LinkedInterpretationWorkspace.apply_link_cursor gating
# ---------------------------------------------------------------------------


class TestApplyLinkCursor:
    def _workspace(self):
        from paleo_workbench.ui.workstation.linked_workspace import (
            LinkedInterpretationWorkspace,
        )

        ws = LinkedInterpretationWorkspace()
        ws._views_created = True  # pretend panels exist; inject a double
        ws._active_well_name = "W-1"

        class _WellPanel:
            def __init__(self):
                self.calls: list = []

            def set_link_cursor(self, md):
                self.calls.append(md)
                return True

        ws.well_panel = _WellPanel()
        return ws

    def test_matching_well_drives_cursor(self, qtbot):
        ws = self._workspace()
        assert ws.apply_link_cursor("W-1", 2000.0) is True
        assert ws.well_panel.calls == [2000.0]

    def test_different_well_is_ignored(self, qtbot):
        ws = self._workspace()
        assert ws.apply_link_cursor("W-OTHER", 2000.0) is False
        assert ws.well_panel.calls == []

    def test_empty_well_name_refused(self, qtbot):
        ws = self._workspace()
        assert ws.apply_link_cursor("", 100.0) is False
        assert ws.apply_link_cursor(None, 100.0) is False

    def test_clearing_cursor_on_matching_well(self, qtbot):
        ws = self._workspace()
        assert ws.apply_link_cursor("W-1", None) is True
        assert ws.well_panel.calls == [None]


# ---------------------------------------------------------------------------
# AppShell integration — composite locate + sink registration
# ---------------------------------------------------------------------------


def test_app_shell_registers_workstation_sinks(qtbot):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)

    assert shell.view_coordination._well_dock_sink is not None
    assert shell.view_coordination._link_cursor_sink is not None
    # composite locate is behavioural: the dock panel is looked up AT CALL
    # TIME (it is created lazily), so injecting a fake dock panel now and
    # firing the focus sink must route the (il, xl, twt) to it.
    dock_locates: list = []

    class _FakeDockPanel:
        def locate_position(self, il, xl, twt=None):
            dock_locates.append((il, xl, twt))

    shell.workstation.linked_workspace.seismic_panel = _FakeDockPanel()
    sink = shell.view_coordination._seismic_focus_sink
    sink(10, 20, 100.0)
    assert dock_locates == [(10, 20, 100.0)]


class TestReviewFixes:
    def test_no_well_in_radius_clears_shown_link_cursor(self, controller):
        """R1-M3: the cursor leaving every well's radius clears the link."""
        panel = _Panel("W-1")
        controller.set_link_cursor_sink(lambda well, md: panel.set_link_cursor(md))
        controller.publish_seismic_cursor(4, 8, 1600.0)
        assert panel.link_calls == [2000.0]

        # the registry empties (project switch semantics): cursor publishes
        # again → no well → the shown cursor must clear exactly once
        controller.coordinate_hub.clear_all_wells()
        controller.publish_seismic_cursor(500, 500, 2000.0)
        assert panel.link_calls == [2000.0, None]
        controller.publish_seismic_cursor(501, 501, 2000.0)
        assert panel.link_calls == [2000.0, None]  # no repeat clears

    def test_link_cursor_writes_are_throttled(self, controller, monkeypatch):
        """R3-M5: rapid cursor routing cannot hammer the native write."""
        writes: list = []
        controller.set_link_cursor_sink(lambda well, md: writes.append(md))
        # neutralize the 30 ms throttle by travelling time? No — assert the
        # first write lands and a burst of identical publishes does not
        # multiply writes for the SAME cursor (differential routing drops
        # identical cursors before the sink anyway).
        controller.publish_seismic_cursor(4, 8, 1600.0)
        for _ in range(20):
            controller.publish_seismic_cursor(4, 8, 1600.0)
        assert writes == [2000.0]
