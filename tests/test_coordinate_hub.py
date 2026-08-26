"""Unit tests for CoordinateTransformHub and WellTrajectoryData (Features F17 & F18)."""

from __future__ import annotations

import math
import numpy as np
import pytest

from paleo_workbench.viz import CoordinateTransformHub, WellTrajectoryData


class TestCoordinateTransformHubWells:
    """Test suite for well registration, unregistration, spatial queries, and trajectory mapping."""

    def test_well_registration_and_unregister(self):
        hub = CoordinateTransformHub()
        hub.register_well("W-01", 100.0, 200.0, elevation=25.0, total_depth_m=3000.0)

        assert hub.map_to_well(100.0, 200.0, max_radius=1.0) == "W-01"
        assert hub.unregister_well("W-01") is True
        assert hub.unregister_well("W-01") is False
        assert hub.map_to_well(100.0, 200.0) is None

    def test_nearest_well_spatial_search(self):
        hub = CoordinateTransformHub()
        hub.register_well("W-NORTH", 1000.0, 2000.0)
        hub.register_well("W-SOUTH", 1000.0, 1000.0)

        # Closer to W-NORTH
        assert hub.map_to_well(1005.0, 2005.0, max_radius=50.0) == "W-NORTH"
        # Closer to W-SOUTH
        assert hub.map_to_well(1002.0, 995.0, max_radius=50.0) == "W-SOUTH"
        # In the middle but outside radius
        assert hub.map_to_well(1000.0, 1500.0, max_radius=100.0) is None

    def test_vertical_well_depth_and_tvdss(self):
        hub = CoordinateTransformHub()
        hub.register_well("VERT-01", 500.0, 600.0, elevation=50.0, total_depth_m=4000.0)

        # Map coords
        x, y, tvd = hub.well_depth_to_map("VERT-01", 1500.0)
        assert x == 500.0
        assert y == 600.0
        assert tvd == 1500.0

        # TVDSS = KB - TVD = 50.0 - 1500.0 = -1450.0
        tvdss = hub.well_depth_to_tvdss("VERT-01", 1500.0)
        assert tvdss == -1450.0

        # Inverse TVD -> MD
        md = hub.map_to_well_depth("VERT-01", 1500.0)
        assert md == 1500.0

    def test_deviated_well_minimum_curvature(self):
        hub = CoordinateTransformHub()
        # Deviated well with survey stations: (MD, Inc_deg, Az_deg)
        # Station 0: Surface (0, 0, 0)
        # Station 1: Kickoff at 1000m (vertical up to 1000m)
        # Station 2: 1500m, Inc 30 deg, Az 90 deg (drilling East)
        # Station 3: 2000m, Inc 60 deg, Az 90 deg (continuing East)
        stations = [
            (0.0, 0.0, 0.0),
            (1000.0, 0.0, 0.0),
            (1500.0, 30.0, 90.0),
            (2000.0, 60.0, 90.0),
        ]
        hub.register_well("DEV-01", 10000.0, 20000.0, elevation=100.0, stations=stations)

        # At MD 500m (vertical section)
        x500, y500, tvd500 = hub.well_depth_to_map("DEV-01", 500.0)
        assert math.isclose(x500, 10000.0, abs_tol=1e-3)
        assert math.isclose(y500, 20000.0, abs_tol=1e-3)
        assert math.isclose(tvd500, 500.0, abs_tol=1e-3)

        # At MD 1500m: well has curved towards East (+X)
        x1500, y1500, tvd1500 = hub.well_depth_to_map("DEV-01", 1500.0)
        assert x1500 > 10000.0  # displaced East
        assert math.isclose(y1500, 20000.0, abs_tol=1e-3)  # Az is 90 deg (pure East)
        assert tvd1500 < 1500.0  # TVD < MD due to deviation

        # Check TVDSS = KB - TVD
        tvdss1500 = hub.well_depth_to_tvdss("DEV-01", 1500.0)
        assert math.isclose(tvdss1500, 100.0 - tvd1500, abs_tol=1e-5)

        # Inverse mapping TVD -> MD
        md_rec = hub.map_to_well_depth("DEV-01", tvd1500)
        assert math.isclose(md_rec, 1500.0, abs_tol=1e-2)

    def test_unregistered_well_raises_key_error(self):
        hub = CoordinateTransformHub()
        with pytest.raises(KeyError, match="not found"):
            hub.well_depth_to_map("UNKNOWN", 100.0)

        with pytest.raises(KeyError, match="not found"):
            hub.well_depth_to_tvdss("UNKNOWN", 100.0)

        with pytest.raises(KeyError, match="not found"):
            hub.map_to_well_depth("UNKNOWN", 100.0)


class TestCoordinateTransformHubSeismic:
    """Test suite for seismic grid mapping, velocity conversion, and matrix inversions."""

    def test_orthogonal_grid_bidirectional_transform(self):
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(
            origin=(500.0, 1000.0),
            il_step=(25.0, 0.0),
            xl_step=(0.0, 12.5),
            il_min=100,
            xl_min=200,
            velocity=2500.0,
        )

        # Forward seismic -> map
        # IL 104 -> dil = 4 -> x = 500 + 4*25 = 600
        # XL 210 -> dxl = 10 -> y = 1000 + 10*12.5 = 1125
        # TWT 1000 ms -> z = (1000/2000)*2500 = 1250 m
        mx, my, mz = hub.seismic_to_map(104, 210, 1000.0)
        assert math.isclose(mx, 600.0, abs_tol=1e-5)
        assert math.isclose(my, 1125.0, abs_tol=1e-5)
        assert math.isclose(mz, 1250.0, abs_tol=1e-5)

        # Inverse map -> seismic
        il, xl, twt = hub.map_to_seismic(600.0, 1125.0, 1250.0)
        assert il == 104
        assert xl == 210
        assert math.isclose(twt, 1000.0, abs_tol=1e-4)

    def test_rotated_grid_bidirectional_transform(self):
        hub = CoordinateTransformHub()
        # Rotated grid: 30 deg rotation, spacing 20m along IL and XL
        # dx_il = 20 * cos(30) = 17.3205, dy_il = 20 * sin(30) = 10.0
        # dx_xl = -20 * sin(30) = -10.0, dy_xl = 20 * cos(30) = 17.3205
        dx_il, dy_il = 20.0 * math.cos(math.radians(30)), 20.0 * math.sin(math.radians(30))
        dx_xl, dy_xl = -20.0 * math.sin(math.radians(30)), 20.0 * math.cos(math.radians(30))

        hub.configure_seismic_grid(
            origin=(1000.0, 2000.0),
            il_step=(dx_il, dy_il),
            xl_step=(dx_xl, dy_xl),
            il_min=1,
            xl_min=1,
            velocity=3000.0,
        )

        test_il, test_xl, test_twt = 42, 88, 1450.0
        mx, my, mz = hub.seismic_to_map(test_il, test_xl, test_twt)
        rec_il, rec_xl, rec_twt = hub.map_to_seismic(mx, my, mz)

        assert rec_il == test_il
        assert rec_xl == test_xl
        assert math.isclose(rec_twt, test_twt, abs_tol=1e-4)

    def test_velocity_guardrails_and_updates(self):
        hub = CoordinateTransformHub()
        hub.set_velocity(3200.0)

        mx, my, mz = hub.seismic_to_map(100, 200, 1000.0)
        # z = (1000 / 2000) * 3200 = 1600.0
        assert math.isclose(mz, 1600.0, abs_tol=1e-5)

        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.set_velocity(0.0)

        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.set_velocity(-1500.0)

        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.configure_seismic_grid(velocity=-100.0)

    def test_degenerate_grid_raises_value_error(self):
        hub = CoordinateTransformHub()
        # Collinear/zero vectors lead to det(M) == 0
        hub.configure_seismic_grid(il_step=(0.0, 0.0), xl_step=(0.0, 0.0))
        with pytest.raises(ValueError, match="Degenerate"):
            hub.map_to_seismic(100.0, 200.0, 0.0)


class TestCoordinateTransformHubCrossDomain:
    """Test suite for cross-domain well <-> seismic transforms."""

    def test_well_to_seismic_and_seismic_to_well(self):
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(
            origin=(0.0, 0.0),
            il_step=(10.0, 0.0),
            xl_step=(0.0, 10.0),
            il_min=0,
            xl_min=0,
            velocity=2000.0,
        )
        hub.register_well("W-ALPHA", 500.0, 800.0, elevation=0.0, total_depth_m=3000.0)

        # Well MD 1000m -> Map (500, 800, 1000) -> Seismic (IL=50, XL=80, TWT=1000ms)
        il, xl, twt = hub.well_to_seismic("W-ALPHA", 1000.0)
        assert il == 50
        assert xl == 80
        assert math.isclose(twt, 1000.0, abs_tol=1e-4)

        # Seismic (50, 80, 1000ms) -> Nearest well "W-ALPHA" and MD 1000.0
        nearest, md = hub.seismic_to_well(50, 80, 1000.0, max_radius=20.0)
        assert nearest == "W-ALPHA"
        assert math.isclose(md, 1000.0, abs_tol=1e-4)

        # Seismic location far from any well
        nearest_far, md_far = hub.seismic_to_well(500, 800, 1000.0, max_radius=20.0)
        assert nearest_far is None
        assert md_far == 0.0
