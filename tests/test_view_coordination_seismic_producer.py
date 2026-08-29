"""#1029 final closure — seismic cursor producer + well registry lifecycle.

All objects under test are PRODUCTION objects:

* :class:`CoordinateTransformHub` unit math (nearest well, MD/TVD conversion,
  unregister/clear semantics);
* :class:`ViewCoordinationController` project lifecycle (``bind_project`` /
  ``clear_project``) against real ``ProjectDocument`` entities — including
  cross-project residue checks and seismic bin-grid configuration;
* integration: controller + real ``SelectionContext`` + hub — a published
  seismic cursor routes to the well-log page, duplicate publishes are
  dropped by differential routing, and an empty registry degrades to a
  debug log instead of a crash;
* producer: :class:`SeismicCursorGate` debounce logic, the panel's public
  ``notify_cursor`` surface, and the engine's real ``cursor_moved_3d``
  signal funneled end-to-end through an ``AppShell``.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.domain import SeismicSurveyEntity, WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_view_panel import (
    SeismicCursorGate,
    SeismicViewPanel,
)
from paleo_workbench.ui.view_coordination import ViewCoordinationController
from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
from paleo_workbench.viz.selection_context import SelectionContext


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """Deterministic monotonic clock (seconds)."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, ms: float) -> None:
        self.now += ms / 1000.0


class StubWellLogPage:
    """Minimal well-log page double: only the routed surface is exercised."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def set_selected_well(self, well_id: str) -> bool:
        self.calls.append(str(well_id))
        return True


class StubController:
    """Records publish_seismic_cursor calls (panel debounce unit tests)."""

    def __init__(self) -> None:
        self.published: list[tuple[int, int, float]] = []

    def publish_seismic_cursor(self, il: int, xl: int, twt: float) -> None:
        self.published.append((int(il), int(xl), float(twt)))


@pytest.fixture()
def hub() -> CoordinateTransformHub:
    return CoordinateTransformHub()


@pytest.fixture()
def controller() -> ViewCoordinationController:
    ctx = SelectionContext()
    ctl = ViewCoordinationController(ctx, CoordinateTransformHub())
    ctl.attach_well_log_page(StubWellLogPage())
    return ctl


def _project_with_wells(names_xy, *, surveys=None):
    doc = ProjectDocument.new("Test Project")
    doc.wells = [
        WellEntity(name=name, project_x=x, project_y=y, kb=10.0, td=3000.0)
        for name, (x, y) in names_xy
    ]
    if surveys:
        doc.seismic_surveys = surveys
    return doc


# ---------------------------------------------------------------------------
# Hub unit — nearest well, MD conversion, unregister/clear
# ---------------------------------------------------------------------------


def test_seismic_to_well_finds_nearest_registered_well(hub):
    # Default grid: inline numbers step 10 m in x, so (il 100, xl 200) maps
    # to map (100, 200); nearest-well search is by wellhead distance (hub math).
    hub.register_well("W-NEAR", x=100.0, y=200.0, total_depth_m=3000.0)
    hub.register_well("W-FAR", x=110.0, y=200.0, total_depth_m=3000.0)

    well_id, md = hub.seismic_to_well(100, 200, 1000.0)

    assert well_id == "W-NEAR"
    assert md == pytest.approx(1000.0)  # vertical well: MD == TVD == z


def test_seismic_cursor_to_md_vertical_well_matches_depth(hub):
    # Default grid: (il 100, xl 200) -> map (100, 200); z = twt/2000*v = twt
    hub.register_well(
        "W-VERT", x=100.0, y=200.0, elevation=25.0, total_depth_m=3000.0
    )

    well_id, md = hub.seismic_to_well(100, 200, 1500.0)

    assert well_id == "W-VERT"
    assert md == pytest.approx(1500.0)
    # TVDSS datum conversion: KB - TVD
    assert hub.well_depth_to_tvdss("W-VERT", md) == pytest.approx(25.0 - 1500.0)


def test_seismic_cursor_to_md_deviated_well_roundtrip(hub):
    # 1 survey number == 1 m on both axes -> IL/XL ints are exact meters.
    hub.configure_seismic_grid(
        origin=(0.0, 0.0), il_step=(1.0, 0.0), xl_step=(0.0, 1.0), il_min=0, xl_min=0
    )
    hub.register_well(
        "W-DEV",
        x=100.0,
        y=100.0,
        total_depth_m=4000.0,
        stations=[(0.0, 0.0, 0.0), (2000.0, 45.0, 30.0), (4000.0, 45.0, 30.0)],
    )

    # Nearest-well search is by WELLHEAD distance: a cursor at the wellhead
    # (twt 1500 ms -> z 1500 m at the default 2000 m/s) must resolve onto the
    # deviated trajectory as the MD whose TVD is 1500 m.
    well_id, md = hub.seismic_to_well(100, 100, 1500.0)

    assert well_id == "W-DEV"
    assert hub.well_depth_to_map("W-DEV", md)[2] == pytest.approx(1500.0)
    assert 0.0 < md < 4000.0  # deviated: MD exceeds TVD on the build segment


def test_unregister_well_then_queries_fail_or_none(hub):
    hub.register_well("W-GONE", x=100.0, y=200.0, total_depth_m=1000.0)

    assert hub.unregister_well("W-GONE") is True
    assert hub.unregister_well("W-GONE") is False

    # nearest-well query degrades to (None, 0.0) — no crash, no fabricated well
    assert hub.seismic_to_well(100, 200, 1000.0) == (None, 0.0)
    # direct depth transform raises KeyError for an unregistered well
    with pytest.raises(KeyError):
        hub.well_depth_to_map("W-GONE", 100.0)


def test_clear_all_wells_empties_registry(hub):
    hub.register_well("W-1", x=0.0, y=0.0)
    hub.register_well("W-2", x=10.0, y=10.0)
    assert hub.registered_well_ids() == ("W-1", "W-2")

    removed = hub.clear_all_wells()

    assert removed == 2
    assert hub.registered_well_ids() == ()
    assert hub.clear_all_wells() == 0
    assert hub.seismic_to_well(0, 0, 0.0) == (None, 0.0)


# ---------------------------------------------------------------------------
# Controller project lifecycle (bind_project / clear_project)
# ---------------------------------------------------------------------------


def test_bind_project_registers_every_located_well(controller):
    controller.bind_project(
        _project_with_wells([("W-A", (100.0, 200.0)), ("W-B", (500.0, 200.0))])
    )

    registered = set(controller.coordinate_hub.registered_well_ids())
    assert registered == {"W-A", "W-B"}


def test_bind_project_skips_wells_without_coordinates(controller):
    doc = ProjectDocument.new("Coord-less")
    doc.wells = [
        WellEntity(name="W-OK", project_x=1.0, project_y=2.0),
        WellEntity(name="W-NOXY"),  # no project/source coordinates at all
        WellEntity(name="W-HALF", project_x=3.0, project_y=None),
    ]

    controller.bind_project(doc)

    assert controller.coordinate_hub.registered_well_ids() == ("W-OK",)


def test_bind_project_prefers_project_crs_coordinates(controller):
    doc = ProjectDocument.new("CRS")
    doc.wells = [
        WellEntity(
            name="W-PROJ",
            surface_x=0.0,
            surface_y=0.0,
            project_x=100.0,
            project_y=200.0,
        )
    ]

    controller.bind_project(doc)

    # (il 100, xl 200) maps to (100, 200) on the default grid: the registry
    # entry must be the PROJECTED pair, not the raw source pair.
    well_id, _md = controller.coordinate_hub.seismic_to_well(100, 200, 1000.0)
    assert well_id == "W-PROJ"


def test_bind_project_registers_deviated_trajectory_from_metadata(controller):
    doc = ProjectDocument.new("Deviated")
    doc.wells = [
        WellEntity(
            name="W-DEV",
            project_x=100.0,
            project_y=200.0,
            td=4000.0,
            metadata={
                # build to 90 deg, then hold — a lateral well
                "survey_stations": [(0.0, 0.0, 0.0), (2000.0, 90.0, 0.0), (4000.0, 90.0, 0.0)],
            },
        )
    ]

    controller.bind_project(doc)
    hub = controller.coordinate_hub

    # Lateral hold: TVD stops growing while MD keeps growing…
    x_lateral, y_lateral, tvd_hold = hub.well_depth_to_map("W-DEV", 4000.0)
    assert hub.well_depth_to_map("W-DEV", 2500.0)[2] == pytest.approx(
        tvd_hold, abs=1e-6
    )
    # …and the well physically walked away from its wellhead.
    assert (x_lateral, y_lateral) != (100.0, 200.0)
    # First MD crossing of the hold TVD is the lateral entry (~2000 m).
    assert hub.map_to_well_depth("W-DEV", tvd_hold) == pytest.approx(2000.0, abs=1e-6)


def test_clear_project_empties_registry_and_resets_grid(controller):
    controller.bind_project(
        _project_with_wells([("W-A", (100.0, 200.0))])
    )
    assert controller.coordinate_hub.registered_well_ids() == ("W-A",)

    controller.clear_project()

    assert controller.coordinate_hub.registered_well_ids() == ()
    # grid restored to hub defaults: (il 100, xl 200) is the map origin
    x, y, _z = controller.coordinate_hub.seismic_to_map(100, 200, 0.0)
    assert (x, y) == pytest.approx((100.0, 200.0))


def test_rebind_different_project_leaves_no_residue(controller):
    project_a = _project_with_wells([("W-A1", (100.0, 200.0)), ("W-A2", (300.0, 200.0))])
    project_b = _project_with_wells([("W-B1", (100.0, 200.0))])

    controller.bind_project(project_a)
    controller.bind_project(project_b)

    assert controller.coordinate_hub.registered_well_ids() == ("W-B1",)
    # the cursor must resolve to the NEW project's well only
    well_id, _md = controller.coordinate_hub.seismic_to_well(100, 200, 500.0)
    assert well_id == "W-B1"


def test_bind_project_configures_seismic_bin_grid(controller):
    # Corners follow the engine survey_from_corners convention:
    # extent[0]=(il0,xl0) origin, extent[1]=opposite CROSSLINE corner,
    # extent[2]=opposite INLINE corner.
    survey = SeismicSurveyEntity(
        name="SVY-1",
        extent=[[1000.0, 2000.0], [1100.0, 2000.0], [1100.0, 2200.0]],
        inline_range=[10.0, 110.0, 10.0],
        crossline_range=[20.0, 70.0, 5.0],
        dt_ms=4.0,
        n_samples=1500,
    )
    controller.bind_project(_project_with_wells([], surveys=[survey]))
    hub = controller.coordinate_hub

    # origin corner: (il_min, xl_min) -> extent[0]
    x, y, _z = hub.seismic_to_map(10, 20, 0.0)
    assert (x, y) == pytest.approx((1000.0, 2000.0))
    # opposite inline corner: (il_max, xl_max) -> extent[2]
    x, y, _z = hub.seismic_to_map(110, 70, 0.0)
    assert (x, y) == pytest.approx((1100.0, 2200.0))
    # opposite crossline corner: (il_min, xl_max) -> extent[1]
    x, y, _z = hub.seismic_to_map(10, 70, 0.0)
    assert (x, y) == pytest.approx((1100.0, 2000.0))


def test_bind_project_with_degenerate_survey_keeps_grid(controller):
    survey = SeismicSurveyEntity(
        name="SVY-BAD",
        extent=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        inline_range=[1.0, 1.0, 1.0],  # zero span -> unusable
        crossline_range=[0.0, 10.0, 1.0],
    )
    controller.bind_project(_project_with_wells([], surveys=[survey]))

    # grid untouched (hub defaults) instead of corrupted
    x, y, _z = controller.coordinate_hub.seismic_to_map(100, 200, 0.0)
    assert (x, y) == pytest.approx((100.0, 200.0))


# ---------------------------------------------------------------------------
# Integration — SelectionContext routing with real controller + hub
# ---------------------------------------------------------------------------


def test_seismic_cursor_routes_to_well_log_page(controller):
    controller.bind_project(_project_with_wells([("W-CUR", (100.0, 200.0))]))
    page = controller._well_log_page

    controller.publish_seismic_cursor(100, 200, 1000.0)

    assert page.calls == ["W-CUR"]
    attrs = controller.selection_context.snapshot().custom_attributes
    assert attrs.get("seismic_well_id") == "W-CUR"
    assert attrs.get("seismic_well_md") == pytest.approx(1000.0)


def test_duplicate_cursor_publish_is_not_redispatched(controller):
    controller.bind_project(_project_with_wells([("W-DUP", (100.0, 200.0))]))
    page = controller._well_log_page

    controller.publish_seismic_cursor(100, 200, 1000.0)
    controller.publish_seismic_cursor(100, 200, 1000.0)  # identical pick

    assert page.calls == ["W-DUP"], "identical cursor must not re-dispatch"


def test_empty_registry_cursor_does_not_crash_and_logs(controller, caplog):
    page = controller._well_log_page
    caplog.set_level(
        logging.DEBUG, logger="paleo_workbench.ui.view_coordination"
    )

    controller.publish_seismic_cursor(100, 200, 1000.0)

    assert page.calls == []
    assert any("no registered well" in rec.message for rec in caplog.records)


def test_clear_project_stops_seismic_routing(controller):
    controller.bind_project(_project_with_wells([("W-GONE", (100.0, 200.0))]))
    page = controller._well_log_page

    controller.clear_project()
    controller.publish_seismic_cursor(100, 200, 1000.0)

    assert page.calls == []


# ---------------------------------------------------------------------------
# Producer — debounce gate (pure logic)
# ---------------------------------------------------------------------------


def test_cursor_gate_publishes_first_pick_immediately():
    gate = SeismicCursorGate(clock=FakeClock())
    assert gate.should_publish(100.0) is True


def test_cursor_gate_suppresses_within_interval_and_releases_after():
    clock = FakeClock()
    gate = SeismicCursorGate(min_interval_ms=30.0, clock=clock)

    assert gate.should_publish(100.0) is True
    assert gate.should_publish(100.5) is False  # same inline, 0 ms elapsed
    clock.advance_ms(29.9)
    assert gate.should_publish(100.5) is False  # still inside the 30 ms window
    clock.advance_ms(0.2)
    assert gate.should_publish(100.5) is True  # window elapsed


def test_cursor_gate_big_inline_jump_publishes_immediately():
    clock = FakeClock()
    gate = SeismicCursorGate(min_interval_ms=30.0, clock=clock)

    assert gate.should_publish(100.0) is True
    # >1 inline of movement must not wait out the timer
    assert gate.should_publish(102.0) is True
    # ...but a sub-inline wiggle right after still waits
    assert gate.should_publish(102.5) is False


# ---------------------------------------------------------------------------
# Producer — panel public surface + real engine signal
# ---------------------------------------------------------------------------


def test_panel_notify_cursor_without_controller_is_silent(qtbot):
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)

    assert panel.notify_cursor(100.0, 200.0, 1000.0) is False


def test_panel_notify_cursor_debounce_with_fake_clock(qtbot):
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    stub = StubController()
    panel.attach_coordination(stub)
    clock = FakeClock()
    panel._cursor_gate = SeismicCursorGate(min_interval_ms=30.0, clock=clock)

    assert panel.notify_cursor(100.0, 200.0, 1000.0) is True
    assert panel.notify_cursor(100.4, 201.0, 1010.0) is False  # inside window
    clock.advance_ms(31.0)
    assert panel.notify_cursor(100.4, 201.0, 1010.0) is True
    assert panel.notify_cursor(103.0, 201.0, 1010.0) is True  # >1 inline jump

    assert stub.published == [
        (100, 200, 1000.0),
        (100, 201, 1010.0),
        (103, 201, 1010.0),
    ]


def test_panel_notify_cursor_rejects_non_numeric_input(qtbot):
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    panel.attach_coordination(StubController())

    assert panel.notify_cursor(None, 200.0, 1000.0) is False  # type: ignore[arg-type]


def test_panel_emits_cursor_from_real_engine_profile_signal(qtbot, monkeypatch):
    """Engine ``cursor_moved_3d`` (the crosshair-linking signal) feeds the
    producer: logical IL/XL + TWT ms reach the coordination controller."""
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    vd = getattr(getattr(panel.view, "_profile_il", None), "_vd", None)
    if vd is None or not hasattr(vd, "cursor_moved_3d"):
        pytest.skip("engine profile internals moved; producer tap unavailable")

    stub = StubController()
    panel.attach_coordination(stub)
    clock = FakeClock()
    panel._cursor_gate = SeismicCursorGate(clock=clock)
    # Engine cursor moves already arrive in survey units; the panel combines
    # them with the current slider position (no volume -> fallback 0.0).
    monkeypatch.setattr(
        panel.view, "_current_il_xl_t", lambda: (7, 8, 9), raising=False
    )

    vd.cursor_moved_3d.emit(215.0, 512.5, "inline")
    vd.cursor_moved_3d.emit(220.0, 530.0, "crossline")  # >1 IL jump -> passes gate

    # inline panel: h=crossline v=TWT; crossline panel: h=inline v=TWT.
    # With no volume loaded the engine's survey-coords fallback (mirrored
    # from _on_cursor_3d) collapses the slider axes to the IL index, so the
    # crossline slot also arrives as 7 — same behaviour the engine's own
    # crosshair linking shows on an unloaded view.
    assert (7, 215, 512.5) in stub.published
    assert (220, 7, 530.0) in stub.published


def test_app_shell_binds_project_and_wires_producer(qtbot):
    """Full-stack wiring: AppShell binds wells into its hub and hands the
    coordination controller to the seismic view panel."""
    from paleo_workbench.ui.app_shell import AppShell

    survey = SeismicSurveyEntity(
        name="SVY",
        extent=[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0]],
        inline_range=[0.0, 100.0, 1.0],
        crossline_range=[0.0, 100.0, 1.0],
    )
    doc = _project_with_wells([("W-SHELL", (200.0, 0.0))], surveys=[survey])
    shell = AppShell(project=doc)
    qtbot.addWidget(shell)

    assert shell.coordinate_hub.registered_well_ids() == ("W-SHELL",)
    panel = shell.seismic_prediction_page_widget().view_panel
    assert panel._coordination is shell.view_coordination

    # End-to-end: engine signal -> panel producer -> context -> hub -> page.
    page_calls = []
    page = shell.well_log_prediction_page_widget()
    monkey_set = page.set_selected_well
    page.set_selected_well = lambda name: page_calls.append(name) or True
    try:
        clock = FakeClock()
        panel._cursor_gate = SeismicCursorGate(clock=clock)
        vd = getattr(getattr(panel.view, "_profile_il", None), "_vd", None)
        if vd is None or not hasattr(vd, "cursor_moved_3d"):
            pytest.skip("engine profile internals moved; producer tap unavailable")
        # No volume loaded: slider fallback il/xl = 0 -> cursor (IL 0, XL 200)
        # -> map (200, 0) on the project's survey grid -> W-SHELL at 1000 ms.
        vd.cursor_moved_3d.emit(200.0, 1000.0, "inline")
    finally:
        page.set_selected_well = monkey_set

    assert page_calls == ["W-SHELL"]
    cursor = shell.selection_context.snapshot().seismic_cursor
    assert cursor == (0, 200, 1000.0)
