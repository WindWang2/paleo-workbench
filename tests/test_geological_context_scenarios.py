"""P0-C — unified geological context: the four cross-view scenarios.

Scenario A: map well click → well page switches, SEISMIC locates the well, 3D highlights.
Scenario B: seismic inline/crossline click → map shows the spatial position, 3D slice syncs.
Scenario C: well-log depth move → seismic time cursor syncs ONLY through a valid
            time-depth calibration; without one the route refuses (no depth==time guess).
Scenario D: horizon selection → one stable identity reaches seismic, map, 3D, inspector.
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

SOURCE_MAP = ViewCoordinationController.SOURCE_MAP
SOURCE_SEISMIC = ViewCoordinationController.SOURCE_SEISMIC
SOURCE_WELL_LOG = ViewCoordinationController.SOURCE_WELL_LOG


@pytest.fixture()
def hub() -> CoordinateTransformHub:
    hub = CoordinateTransformHub()
    # A seismic grid matching the hub defaults so IL/XL ↔ XY is identity-ish:
    hub.configure_seismic_grid(
        origin=(0.0, 0.0),
        il_step=(25.0, 0.0),
        xl_step=(0.0, 25.0),
        il_min=100,
        xl_min=200,
    )
    hub.register_well("W-A", x=50.0, y=75.0, total_depth_m=3000.0)
    return hub


@pytest.fixture()
def controller(hub) -> ViewCoordinationController:
    return ViewCoordinationController(SelectionContext(), hub)


# ---------------------------------------------------------------------------
# TimeDepthCalibration unit contract
# ---------------------------------------------------------------------------


class TestTimeDepthCalibration:
    def test_piecewise_linear_roundtrip(self):
        cal = TimeDepthCalibration.from_pairs(
            "W-A", [(0.0, 0.0), (1000.0, 1000.0), (2000.0, 2100.0)], provenance="checkshot:test"
        )
        assert cal.md_to_twt(500.0) == pytest.approx(500.0)
        assert cal.md_to_twt(1500.0) == pytest.approx(1550.0)
        assert cal.twt_to_md(1550.0) == pytest.approx(1500.0)

    def test_out_of_range_is_none_not_extrapolated(self):
        cal = TimeDepthCalibration.from_pairs(
            "W-A", [(100.0, 120.0), (1000.0, 1100.0)], provenance="checkshot:test"
        )
        assert cal.md_to_twt(50.0) is None
        assert cal.md_to_twt(2000.0) is None
        assert cal.twt_to_md(50.0) is None

    def test_rejects_non_monotonic_pairs(self):
        with pytest.raises(ValueError):
            # TWT decreases while MD increases
            TimeDepthCalibration.from_pairs(
                "W-A", [(0.0, 0.0), (1000.0, -900.0)], provenance="checkshot:test"
            )
        with pytest.raises(ValueError):
            # duplicate MD
            TimeDepthCalibration.from_pairs(
                "W-A", [(0.0, 0.0), (0.0, 100.0)], provenance="checkshot:test"
            )

    def test_rejects_fewer_than_two_pairs(self):
        with pytest.raises(ValueError):
            TimeDepthCalibration.from_pairs("W-A", [(0.0, 0.0)], provenance="x")

    def test_provenance_is_carried(self):
        cal = TimeDepthCalibration.from_pairs(
            "W-A", [(0.0, 0.0), (1000.0, 1000.0)], provenance="td-table:smi.dat"
        )
        assert cal.provenance == "td-table:smi.dat"


class TestHubCalibrationGate:
    def test_md_to_twt_fail_closed_without_calibration(self, hub):
        assert hub.well_md_to_twt("W-A", 1500.0) is None

    def test_md_to_twt_uses_calibration_when_present(self, hub):
        hub.set_time_depth_calibration(
            TimeDepthCalibration.from_pairs(
                "W-A", [(0.0, 0.0), (2000.0, 2400.0)], provenance="checkshot:test"
            )
        )
        assert hub.well_md_to_twt("W-A", 1000.0) == pytest.approx(1200.0)

    def test_md_to_seismic_cursor_requires_calibration(self, hub):
        # x/y geometry is known, but without calibration the time coordinate
        # must not be invented from a constant velocity.
        assert hub.well_md_to_seismic_cursor("W-A", 1000.0) is None
        hub.set_time_depth_calibration(
            TimeDepthCalibration.from_pairs(
                "W-A", [(0.0, 0.0), (2000.0, 2400.0)], provenance="checkshot:test"
            )
        )
        il, xl, twt = hub.well_md_to_seismic_cursor("W-A", 1000.0)
        assert (il, xl) == (102, 203)  # (50/25+100, 75/25+200)
        assert twt == pytest.approx(1200.0)

    def test_unknown_well_is_none_not_crash(self, hub):
        assert hub.well_md_to_twt("W-MISSING", 10.0) is None

    def test_calibration_registryLifecycle(self, hub):
        cal = TimeDepthCalibration.from_pairs(
            "W-A", [(0.0, 0.0), (1000.0, 1000.0)], provenance="x"
        )
        hub.set_time_depth_calibration(cal)
        assert hub.time_depth_calibration("W-A") is cal
        assert hub.clear_time_depth_calibration("W-A") is True
        assert hub.time_depth_calibration("W-A") is None
        assert hub.clear_time_depth_calibration("W-A") is False


# ---------------------------------------------------------------------------
# Selection state slots (backward compatible)
# ---------------------------------------------------------------------------


class TestSelectionStateSlots:
    def test_new_slots_default_none(self):
        state = SelectionContext().snapshot()
        assert state.active_horizon_id is None
        assert state.active_fault_id is None
        assert state.active_interpretation_id is None
        assert state.spatial_cursor is None
        assert state.depth_cursor is None
        assert state.active_layer_id is None
        assert state.map_extent is None

    def test_partial_update_of_geological_slots(self):
        ctx = SelectionContext()
        ctx.update(active_horizon_id="horizon/H1", source_widget_id="src")
        snap = ctx.snapshot()
        assert snap.active_horizon_id == "horizon/H1"
        assert snap.active_well_id is None  # untouched

    def test_clear_resets_geological_slots(self):
        ctx = SelectionContext()
        ctx.update(
            active_horizon_id="h",
            active_fault_id="f",
            spatial_cursor=(1.0, 2.0),
            depth_cursor=("W-A", 1500.0),
        )
        ctx.clear()
        snap = ctx.snapshot()
        assert snap.active_horizon_id is None
        assert snap.spatial_cursor is None
        assert snap.depth_cursor is None


# ---------------------------------------------------------------------------
# Scenario wiring through the controller
# ---------------------------------------------------------------------------


class TestScenarioASeismicLocatesWell:
    def test_well_selection_routes_to_seismic_locator(self, controller):
        calls: list[tuple[int, int, float | None]] = []
        controller.set_seismic_sink(
            lambda il, xl, twt=None: calls.append((il, xl, twt))
        )
        controller.publish_well_selection("W-A", source=SOURCE_MAP)
        # W-A at (50, 75) on the 25 m grid → IL 102 / XL 203, no invented TWT
        assert calls == [(102, 203, None)]

    def test_unknown_well_does_not_crash_routing(self, controller):
        calls: list[tuple] = []
        controller.set_seismic_sink(lambda *a: calls.append(a))
        controller.publish_well_selection("W-MISSING", source=SOURCE_MAP)
        assert calls == []


class TestScenarioBSeismicCursorToMapAnd3D:
    def test_cursor_publish_includes_spatial_position(self, controller):
        controller.publish_seismic_cursor(102, 203, 1200.0)
        snap = controller.selection_context.snapshot()
        assert snap.seismic_cursor == (102, 203, 1200.0)
        assert snap.spatial_cursor == (50.0, 75.0)

    def test_cursor_routes_to_map_marker(self, controller):
        received: list[tuple[float, float]] = []
        controller.set_spatial_cursor_sink(lambda x, y: received.append((x, y)))
        controller.publish_seismic_cursor(102, 203, 1200.0)
        assert received == [(50.0, 75.0)]

    def test_cursor_routes_to_3d_slice_focus(self, controller):
        received: list[tuple[int, int, float]] = []
        controller.set_seismic_focus_sink(lambda il, xl, twt: received.append((il, xl, twt)))
        controller.publish_seismic_cursor(102, 203, 1200.0)
        assert received == [(102, 203, 1200.0)]


class TestScenarioCDepthTimeGate:
    def test_depth_cursor_without_calibration_does_not_touch_seismic(self, controller):
        seismic: list[tuple] = []
        controller.set_seismic_focus_sink(lambda *a: seismic.append(a))
        controller.publish_depth_cursor("W-A", 1500.0, source=SOURCE_WELL_LOG)
        snap = controller.selection_context.snapshot()
        assert snap.depth_cursor == ("W-A", 1500.0)
        assert snap.seismic_cursor is None  # refused: no calibration
        assert seismic == []

    def test_depth_cursor_with_calibration_updates_seismic_time(self, controller):
        controller.coordinate_hub.set_time_depth_calibration(
            TimeDepthCalibration.from_pairs(
                "W-A", [(0.0, 0.0), (2000.0, 2400.0)], provenance="checkshot:test"
            )
        )
        seismic: list[tuple] = []
        controller.set_seismic_focus_sink(lambda *a: seismic.append(a))
        controller.publish_depth_cursor("W-A", 1000.0, source=SOURCE_WELL_LOG)
        snap = controller.selection_context.snapshot()
        # The route must NOT rewrite the seismic_cursor slot from the depth
        # side (that slot belongs to the seismic picker); it navigates the
        # seismic view only.
        assert snap.seismic_cursor is None
        assert seismic == [(102, 203, 1200.0)]

    def test_depth_cursor_out_of_calibrated_range_refuses(self, controller):
        controller.coordinate_hub.set_time_depth_calibration(
            TimeDepthCalibration.from_pairs(
                "W-A", [(0.0, 0.0), (1000.0, 1200.0)], provenance="checkshot:test"
            )
        )
        seismic: list[tuple] = []
        controller.set_seismic_focus_sink(lambda *a: seismic.append(a))
        controller.publish_depth_cursor("W-A", 5000.0, source=SOURCE_WELL_LOG)
        assert seismic == []


class TestScenarioDHorizonIdentity:
    def test_horizon_selection_publishes_and_routes(self, controller):
        received: list[str] = []
        controller.set_horizon_sink(lambda hid: received.append(hid))
        controller.publish_horizon_selection("horizon/H7", source="seismic_view")
        snap = controller.selection_context.snapshot()
        assert snap.active_horizon_id == "horizon/H7"
        assert snap.active_interpretation_id is None
        assert received == ["horizon/H7"]

    def test_fault_selection_slot(self, controller):
        controller.publish_fault_selection("fault/F1", source="map")
        assert controller.selection_context.snapshot().active_fault_id == "fault/F1"


class TestEchoAndBleed:
    def test_same_publication_not_re_routed(self, controller):
        received: list[str] = []
        controller.set_horizon_sink(lambda hid: received.append(hid))
        controller.publish_horizon_selection("horizon/H1", source="seismic_view")
        controller.publish_horizon_selection("horizon/H1", source="seismic_view")
        assert received == ["horizon/H1"]

    def test_clear_project_resets_geological_slots(self, controller):
        controller.publish_horizon_selection("horizon/H1", source="map")
        controller.clear_project()
        snap = controller.selection_context.snapshot()
        assert snap.active_horizon_id is None


# ---------------------------------------------------------------------------
# Page-level sink implementations
# ---------------------------------------------------------------------------


class TestPageSinks:
    def test_well_map_page_spatial_cursor_series(self, qtbot):
        from paleo_workbench.ui.pages.project_well_map_page import ProjectWellMapPage

        page = ProjectWellMapPage()
        qtbot.addWidget(page)
        if page.plot is None:
            pytest.skip("geo-viz engine plot unavailable")
        page.show_spatial_cursor(123.0, 456.0)
        assert page.spatial_cursor_position() == (123.0, 456.0)
        page.clear_spatial_cursor()
        assert page.spatial_cursor_position() is None

    def test_seismic_view_panel_locate_position_noop_safely(self, qtbot):
        from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel

        panel = SeismicViewPanel()
        qtbot.addWidget(panel)
        # No volume loaded: locating must be a safe no-op, not a crash.
        assert panel.locate_position(102, 203, 1200.0) is False

    def test_well_log_panel_depth_at_pixel(self, qtbot):
        from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel

        panel = WellLogCanvasPanel()
        qtbot.addWidget(panel)

        class _Track:
            depth_top = 1000.0
            depth_bottom = 2000.0
            header_height = 56

        class _Canvas:
            tracks = [_Track()]

            @staticmethod
            def height() -> int:
                return 456  # 56 header + 400 content

        panel.canvas = _Canvas()  # type: ignore[assignment]
        assert panel.depth_at_pixel(56.0) == pytest.approx(1000.0)
        assert panel.depth_at_pixel(256.0) == pytest.approx(1500.0)
        assert panel.depth_at_pixel(10.0) is None  # inside the header
        panel.canvas = type("_EmptyCanvas", (), {"tracks": []})()
        assert panel.depth_at_pixel(100.0) is None
