"""V6 §8 — the coordinate hub must not answer from a fabricated default grid.

Before any survey is bound, the hub's bin-grid geometry is UNKNOWN: answering
map↔seismic conversions from the (100,200)-origin / 25 m-bin defaults made
cursor routing look authoritative on invented geometry (audit P1-6).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub


class TestGridConfiguredGate:
    def test_fresh_hub_refuses_map_to_seismic(self):
        hub = CoordinateTransformHub()
        with pytest.raises(ValueError, match="no seismic grid"):
            hub.map_to_seismic_xy(150.0, 250.0)

    def test_fresh_hub_refuses_seismic_to_map(self):
        hub = CoordinateTransformHub()
        with pytest.raises(ValueError, match="no seismic grid"):
            hub.seismic_to_map_xy(105, 205)

    def test_grid_configured_property(self):
        hub = CoordinateTransformHub()
        assert hub.grid_configured is False
        hub.configure_seismic_grid(
            origin=(100.0, 200.0),
            il_step=(10.0, 0.0),
            xl_step=(0.0, 10.0),
            il_min=100,
            xl_min=200,
        )
        assert hub.grid_configured is True
        assert hub.map_to_seismic_xy(150.0, 250.0) == (105, 205)
        assert hub.seismic_to_map_xy(105, 205) == (150.0, 250.0)

    def test_no_arg_configure_resets_to_unconfigured(self):
        """clear_project's reset must restore UNKNOWN geometry, not defaults."""
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(origin=(0.0, 0.0), il_min=1, xl_min=1)
        assert hub.grid_configured is True
        hub.configure_seismic_grid()  # reset call (view_coordination.py)
        assert hub.grid_configured is False
        with pytest.raises(ValueError, match="no seismic grid"):
            hub.seismic_to_map_xy(1, 1)

    def test_well_md_to_seismic_cursor_refuses_without_grid(self):
        """No calibration → already None; with calibration but no grid the
        (IL, XL) part must also be refused, never fabricated."""
        from paleo_workbench.viz.coordinate_hub import TimeDepthCalibration

        hub = CoordinateTransformHub()
        hub.register_well("well-a", x=150.0, y=250.0)
        hub.set_time_depth_calibration(
            TimeDepthCalibration(
                well_id="well-a",
                pairs=[(0.0, 0.0), (1000.0, 1000.0)],
                provenance="checkshot:test",
            )
        )
        assert hub.well_md_to_twt("well-a", 500.0) is not None
        cursor = hub.well_md_to_seismic_cursor("well-a", 500.0)
        assert cursor is None, "unconfigured grid must not fabricate (IL, XL)"


class TestDomainCoordsNoGrid:
    def test_typed_layer_reports_no_grid(self):
        from paleo_workbench.viz.domain_coords import (
            DomainCoordinationService,
            MapPoint,
        )

        svc = DomainCoordinationService(CoordinateTransformHub())
        out = svc.map_to_seismic_xy(MapPoint(150.0, 250.0))
        assert not out.ok
        assert out.reason is not None and out.detail
