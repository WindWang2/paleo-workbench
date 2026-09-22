"""L5 paleo side — calibrated well-trace overlays + fail-closed depth slice.

Unit tests for the projection (registered well + calibration + bin grid),
the panel wiring contract (stubbed engine view), and the depth-slice
refusal: a TWT-domain volume must NEVER offer a depth slice silently.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QWidget

from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
from paleo_workbench.viz.coordinate_hub import (
    CoordinateTransformHub,
    TimeDepthCalibration,
)
from paleo_workbench.viz.well_section_overlay import (
    compute_well_section_overlays,
)


@pytest.fixture()
def hub() -> CoordinateTransformHub:
    hub = CoordinateTransformHub()
    hub.configure_seismic_grid(
        origin=(0.0, 0.0),
        il_step=(25.0, 0.0),
        xl_step=(0.0, 25.0),
        il_min=100,
        xl_min=200,
    )
    hub.register_well("W1", x=0.0, y=0.0, elevation=30.0, total_depth_m=1000.0)
    hub.set_time_depth_calibration(
        TimeDepthCalibration.from_pairs(
            "W1", [(0.0, 100.0), (1000.0, 1100.0)], provenance="test:checkshot"
        )
    )
    return hub


class TestProjection:
    def test_vertical_well_projects_on_both_sections(self, hub):
        overlays, reason = compute_well_section_overlays(
            hub, "W1", inline_value=100, crossline_value=200
        )
        assert reason is None
        inline = overlays["inline"]
        # The well sits exactly at IL 100 / XL 200: h constant, TWT increasing.
        assert set(inline.h_values) == {200.0}
        twts = np.asarray(inline.v_values_twt_ms)
        assert twts[0] == pytest.approx(100.0)
        assert twts[-1] == pytest.approx(1100.0)
        assert np.all(np.diff(twts) > 0)
        crossline = overlays["crossline"]
        assert set(crossline.h_values) == {100.0}

    def test_deviated_well_only_on_crossed_sections(self, hub):
        hub.register_well(
            "WDEV",
            x=0.0,
            y=0.0,
            total_depth_m=1000.0,
            stations=[(0.0, 0.0, 0.0), (1000.0, 90.0, 90.0)],  # walks east/+x/+inline
        )
        hub.set_time_depth_calibration(
            TimeDepthCalibration.from_pairs(
                "WDEV", [(0.0, 0.0), (1000.0, 1000.0)], provenance="test"
            )
        )
        overlays, reason = compute_well_section_overlays(
            hub, "WDEV", inline_value=100, crossline_value=200
        )
        # IL 100 covers only the early (near-surface) part of the walk; the
        # crossline XL 200 section holds the whole trajectory.
        assert reason is None
        assert "crossline" in overlays
        crossline = overlays["crossline"]
        ils = np.asarray(crossline.h_values)
        assert ils.max() > 100.0  # the trajectory leaves IL 100

    def test_fail_closed_reasons(self, hub):
        _, reason = compute_well_section_overlays(
            hub, "NOPE", inline_value=100, crossline_value=200
        )
        assert reason == "well-not-registered:NOPE"

        hub2 = CoordinateTransformHub()
        hub2.configure_seismic_grid(origin=(0.0, 0.0), il_step=(25.0, 0.0),
                                    xl_step=(0.0, 25.0), il_min=100, xl_min=200)
        hub2.register_well("NOCAL", x=0.0, y=0.0)
        _, reason = compute_well_section_overlays(
            hub2, "NOCAL", inline_value=100, crossline_value=200
        )
        assert reason == "no-calibration:NOCAL"

        # Sections nowhere near the well refuse instead of painting a fake
        # trace on someone else's section.
        _, reason = compute_well_section_overlays(
            hub, "W1", inline_value=140, crossline_value=240
        )
        assert reason == "well-outside-section-window"


class _StubProfile:
    def __init__(self):
        self.paths: list | None = None
        self.cleared = 0

    def set_path_overlays(self, paths):
        self.paths = list(paths)

    def clear_path_overlays(self):
        self.cleared += 1
        self.paths = None


class _StubView(QWidget):
    """Minimal engine-view surface the panel touches for overlays."""

    def __init__(self, il=100.0, xl=200.0):
        super().__init__(None)
        self._meta = type("M", (), {"vertical_domain": None})()
        self._profile_il = _StubProfile()
        self._profile_xl = _StubProfile()
        self._il_val, self._xl_val = il, xl

    def is_ready(self) -> bool:
        return True

    def _install(self, panel) -> None:
        """Swap into the panel's stack so is_view_ready() is honestly True."""
        panel.stack.addWidget(self)
        panel.stack.setCurrentWidget(self)

    def _current_il_xl_t(self):
        return 0, 0, 0

    def _preview_to_survey_coords(self, slice_type, position):
        return self._il_val, self._xl_val, 0.0


class TestPanelWiring:
    @pytest.fixture()
    def panel(self, qtbot):
        QApplication.instance() or QApplication([])
        panel = SeismicViewPanel()
        qtbot.addWidget(panel)
        return panel

    def test_overlay_without_hub_reports_reason(self, panel):
        panel.view = _StubView()
        panel.view._install(panel)
        panel._coordination = None
        assert panel.set_well_overlay("W1") is False
        assert panel.well_overlay_unavailable_reason() == "no-coordination-hub"

    def test_overlay_pushes_paths_to_section_panels(self, panel, hub):
        panel.view = _StubView()
        panel.view._install(panel)
        panel._coordination = type("C", (), {"coordinate_hub": hub})()
        assert panel.set_well_overlay("W1") is True
        assert panel.well_overlay_unavailable_reason() is None
        assert panel.view._profile_il.paths, "inline section got the trace"
        assert panel.view._profile_il.paths[0]["label"] == "W1"
        assert panel.view._profile_xl.paths, "crossline section got the trace"

    def test_overlay_clear_removes_paths(self, panel, hub):
        panel.view = _StubView()
        panel.view._install(panel)
        panel._coordination = type("C", (), {"coordinate_hub": hub})()
        panel.set_well_overlay("W1")
        panel.set_well_overlay(None)
        assert panel.view._profile_il.paths is None
        assert panel.view._profile_il.cleared == 1

    def test_overlay_without_calibration_is_fail_closed(self, panel):
        bare_hub = CoordinateTransformHub()
        panel.view = _StubView()
        panel.view._install(panel)
        panel._coordination = type("C", (), {"coordinate_hub": bare_hub})()
        assert panel.set_well_overlay("GHOST") is False
        assert panel.well_overlay_unavailable_reason() == "well-not-registered:GHOST"

    def test_depth_slice_refused_for_twt_volume(self, panel):
        panel.view = _StubView()
        panel.view._install(panel)
        assert panel.depth_slice_unavailable_reason() == "twt-domain-volume"

    def test_depth_slice_refused_without_volume(self, panel):
        assert panel.depth_slice_unavailable_reason() == "no-volume"
