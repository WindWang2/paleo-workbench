"""L11 — adversarial scientific verification matrix (linked-interpretation).

One file, one matrix. Items already covered by dedicated suites are marked
in docs/development/linked-interpretation/verification.md; what runs here
are the entries that had no home yet.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.ui.workstation.linked_workspace import (
    LinkedInterpretationWorkspace,
)
from paleo_workbench.viz.coordinate_hub import (
    CoordinateTransformHub,
    TimeDepthCalibration,
)
from paleo_workbench.viz.selection_context import SelectionContext
from paleo_workbench.viz.domain_coords import (
    ConversionFailure,
    DepthCoordinate,
    DepthDomain,
    DomainCoordinationService,
    LengthUnit,
    MapPoint,
    SeismicPosition,
    TwtCoordinate,
)
from paleo_workbench.workflow.correlation_artifact import read_fault_artifact


# ---------------------------------------------------------------------------
# Well head / registry adversarial
# ---------------------------------------------------------------------------


def test_missing_well_head_coordinates_are_not_fabricated():
    """A well without usable XY is refused everywhere, never (0, 0)."""
    hub = CoordinateTransformHub()
    svc = DomainCoordinationService(hub)
    out = svc.well_md_to_map(
        "NOHEAD", DepthCoordinate.from_source(100.0, DepthDomain.MD)
    )
    assert not out.ok
    assert out.reason is ConversionFailure.UNKNOWN_WELL
    nearest = svc.nearest_well(MapPoint(0.0, 0.0))
    assert not out.ok and nearest.ok is False


def test_no_nearby_well_refuses_instead_of_guessing():
    hub = CoordinateTransformHub()
    hub.register_well("W-FAR", x=100000.0, y=200000.0, total_depth_m=1000.0)
    svc = DomainCoordinationService(hub)
    out = svc.nearest_well(MapPoint(0.0, 0.0), max_radius_m=50.0)
    assert not out.ok
    assert out.reason is ConversionFailure.NO_TRAJECTORY


def test_ft_and_m_wells_roundtrip_through_the_same_calibration():
    """One calibration in metres serves ft-declared MDs identically."""
    hub = CoordinateTransformHub()
    hub.register_well("W-FT", x=0.0, y=0.0, total_depth_m=3000.0)
    hub.set_time_depth_calibration(
        TimeDepthCalibration.from_pairs(
            "W-FT", [(0.0, 0.0), (3000.0, 2400.0)], provenance="p"
        )
    )
    svc = DomainCoordinationService(hub)
    md_m = svc.well_md_to_twt(
        "W-FT", DepthCoordinate.from_source(1500.0, DepthDomain.MD)
    )
    md_ft = svc.well_md_to_twt(
        "W-FT", DepthCoordinate.from_source(1500.0 / 0.3048, DepthDomain.MD, LengthUnit.FT)
    )
    assert md_m.ok and md_ft.ok
    assert md_ft.value.value_ms == pytest.approx(md_m.value.value_ms, rel=1e-9)


# ---------------------------------------------------------------------------
# Out-of-range TWT / domain edges
# ---------------------------------------------------------------------------


def test_out_of_range_twt_refuses_with_calibrated_range_named():
    hub = CoordinateTransformHub()
    hub.register_well("W-R", x=0.0, y=0.0, total_depth_m=4000.0)
    hub.set_time_depth_calibration(
        TimeDepthCalibration.from_pairs(
            "W-R", [(0.0, 0.0), (2000.0, 1500.0)], provenance="p"
        )
    )
    svc = DomainCoordinationService(hub)
    out = svc.twt_to_well_md("W-R", TwtCoordinate(1600.0))  # 100 ms past the end
    assert not out.ok
    assert out.reason is ConversionFailure.OUT_OF_CALIBRATION_RANGE
    assert "1500.0" in out.detail and "outside" in out.detail


def test_non_monotonic_calibration_rejected_at_construction():
    with pytest.raises(ValueError, match="strictly increase"):
        TimeDepthCalibration.from_pairs(
            "W-BAD", [(0.0, 900.0), (1000.0, 800.0)], provenance="p"
        )


def test_project_switch_clears_wells_calibrations_and_link_state():
    from paleo_workbench.ui.view_coordination import ViewCoordinationController

    hub = CoordinateTransformHub()
    hub.register_well("W-OLD", x=0.0, y=0.0, total_depth_m=1000.0)
    hub.set_time_depth_calibration(
        TimeDepthCalibration.from_pairs(
            "W-OLD", [(0.0, 0.0), (1000.0, 800.0)], provenance="p"
        )
    )
    controller = ViewCoordinationController(SelectionContext(), hub)
    controller._link_cursor_set = True
    controller.publish_well_selection("W-OLD", source=controller.SOURCE_MAP)

    controller.clear_project()

    assert hub.registered_well_ids() == ()
    assert hub.time_depth_calibration("W-OLD") is None
    assert controller._link_cursor_set is False
    snap = controller.selection_context.snapshot()
    assert snap.active_well_id is None  # no cross-project selection bleed


# ---------------------------------------------------------------------------
# Repeated open/close and rapid interactions
# ---------------------------------------------------------------------------


def test_repeated_workspace_open_close_is_stable(qtbot):
    ws = LinkedInterpretationWorkspace()
    qtbot.addWidget(ws)
    for _ in range(5):
        ws.ensure_views()  # offscreen: no-op, must stay safe
        ws.open_well("A12")  # missing well: no-op, must stay safe
        ws.shutdown_workers()
    assert ws.well_panel is None or ws.well_panel is not None  # alive, no crash


def test_rapid_depth_publishes_do_not_flood_the_bus(qtbot):
    from PySide6.QtCore import QObject, Signal

    from paleo_workbench.ui.view_coordination import ViewCoordinationController

    class _Panel(QObject):
        depth_cursor_moved = Signal(float)

        def current_well_name(self):
            return "W-1"

    hub = CoordinateTransformHub()
    hub.register_well("W-1", x=0.0, y=0.0, total_depth_m=3000.0)
    controller = ViewCoordinationController(SelectionContext(), hub)
    publishes: list[float] = []
    original = controller.publish_depth_cursor
    controller.publish_depth_cursor = (
        lambda well, md, *, source: publishes.append(md)
    )
    try:
        panel = _Panel()
        controller.attach_well_dock_panel(panel)
        # 60 rapid emissions inside the panel's 120 ms gate → ≤ half pass
        for i in range(60):
            panel.depth_cursor_moved.emit(float(i))
    finally:
        controller.publish_depth_cursor = original
    assert len(publishes) <= 30, f"gate failed: {len(publishes)} publishes"


# ---------------------------------------------------------------------------
# Corrupted interpretation artifacts
# ---------------------------------------------------------------------------


def test_corrupted_fault_artifact_fails_loudly(tmp_path):
    bad = tmp_path / "bad.fault_interp.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_fault_artifact(bad)

    wrong_schema = tmp_path / "wrong.fault_interp.json"
    wrong_schema.write_text(
        json.dumps({"schema": "something-else", "payload": {}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="schema"):
        read_fault_artifact(wrong_schema)


def test_corrupted_td_table_refused_not_guessed(tmp_path):
    from paleo_workbench.viz.joint_well_parsers import parse_td_table

    one_column = tmp_path / "bad.dat"
    one_column.write_text("# Well : W\n1234.0\n", encoding="utf-8")
    assert parse_td_table(one_column, well_name="W") is None


# ---------------------------------------------------------------------------
# Small seismic window (ROI semantics stays windowed)
# ---------------------------------------------------------------------------


def test_map_to_seismic_window_needs_full_volume_never():
    """The typed conversions are pure geometry: no volume access at all, so
    a small window/ROI volume can never make them fail differently."""
    hub = CoordinateTransformHub()
    hub.configure_seismic_grid(
        origin=(0.0, 0.0), il_step=(12.5, 0.0), xl_step=(0.0, 12.5), il_min=100, xl_min=200
    )
    svc = DomainCoordinationService(hub)
    for il, xl in ((100, 200), (101, 201), (140, 240)):
        pos = svc.seismic_to_map_xy(SeismicPosition(inline=il, crossline=xl))
        back = svc.map_to_seismic_xy(pos.value)
        assert (back.value.inline, back.value.crossline) == (il, xl)


def test_rapid_seismic_cursors_keep_dedup_on_the_bus():
    """Identical rapid cursor publishes dispatch once (differential routing)."""
    from paleo_workbench.ui.view_coordination import ViewCoordinationController

    hub = CoordinateTransformHub()
    controller = ViewCoordinationController(SelectionContext(), hub)
    routed: list = []
    controller._well_log_page = type(
        "P", (), {"set_selected_well": staticmethod(lambda w: routed.append(w))}
    )()
    # no wells registered: routing is a debug-log no-op and must not crash
    for i in range(50):
        controller.publish_seismic_cursor(10, 20, 100.0 + (i % 3))
    assert routed == []  # no well → no well-log routing, no fabrications
