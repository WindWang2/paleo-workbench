"""Adversarial stress test suite for CoordinateTransformHub (Milestone 4).

Tests boundary conditions, numerical stability, degenerate geometries,
tortuous wellpaths, extreme coordinate magnitudes, velocity edge cases,
and concurrent multi-threaded execution.
"""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pytest

from paleo_workbench.viz import CoordinateTransformHub, WellTrajectoryData


class TestExtremeCoordinates:
    """Stress tests for extreme coordinate magnitudes (-10^9 to 10^9) and numerical precision."""

    def test_extreme_magnitude_seismic_bidirectional_roundtrip(self):
        """Verify round-trip precision for seismic mapping with coordinates up to 10^9."""
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(
            origin=(1e8, -1e8),
            il_step=(25.0, 10.0),
            xl_step=(-10.0, 25.0),
            il_min=-1000000,
            xl_min=1000000,
            velocity=3000.0,
        )

        test_cases = [
            (1000000, 2000000, 10000.0),
            (-5000000, -3000000, 50000.0),
            (0, 0, 0.0),
            (10000000, -10000000, 100000.0),
        ]

        for il, xl, twt in test_cases:
            x, y, z = hub.seismic_to_map(il, xl, twt)
            # Ensure no overflow/NaN
            assert math.isfinite(x)
            assert math.isfinite(y)
            assert math.isfinite(z)

            rec_il, rec_xl, rec_twt = hub.map_to_seismic(x, y, z)
            assert rec_il == il
            assert rec_xl == xl
            assert math.isclose(rec_twt, twt, abs_tol=1e-5)

    def test_extreme_coordinate_well_spatial_search(self):
        """Verify spatial nearest-neighbor search at coordinate bounds around +/- 10^9."""
        hub = CoordinateTransformHub()
        hub.register_well("W-FAR-POS", 1e9, 1e9, elevation=100.0, total_depth_m=5000.0)
        hub.register_well("W-FAR-NEG", -1e9, -1e9, elevation=50.0, total_depth_m=5000.0)

        # Exact match
        assert hub.map_to_well(1e9, 1e9, max_radius=1.0) == "W-FAR-POS"
        assert hub.map_to_well(-1e9, -1e9, max_radius=1.0) == "W-FAR-NEG"

        # Within 20m tolerance at 1e9 magnitude (tests float64 precision of hypot)
        assert hub.map_to_well(1e9 + 10.0, 1e9 + 10.0, max_radius=20.0) == "W-FAR-POS"
        assert hub.map_to_well(-1e9 - 10.0, -1e9 - 10.0, max_radius=20.0) == "W-FAR-NEG"

        # Outside tolerance
        assert hub.map_to_well(1e9 + 30.0, 1e9 + 30.0, max_radius=20.0) is None

    def test_extreme_depth_well_mapping(self):
        """Verify well trajectory mapping with extreme MD and TVD depths (10^7 m)."""
        hub = CoordinateTransformHub()
        stations = [
            (0.0, 0.0, 0.0),
            (1e6, 0.0, 0.0),
            (5e6, 45.0, 90.0),
            (1e7, 45.0, 90.0),
        ]
        hub.register_well("W-DEEP", 500000.0, 4000000.0, elevation=2500.0, total_depth_m=1e7, stations=stations)

        x, y, tvd = hub.well_depth_to_map("W-DEEP", 8e6)
        assert math.isfinite(x)
        assert math.isfinite(y)
        assert math.isfinite(tvd)
        assert tvd < 8e6  # Deviated section reduces TVD

        tvdss = hub.well_depth_to_tvdss("W-DEEP", 8e6)
        assert math.isclose(tvdss, 2500.0 - tvd, abs_tol=1e-5)


class TestDegenerateSeismicGrids:
    """Stress tests for singular matrices, degenerate step vectors, and boundary grids."""

    def test_singular_zero_step_vectors_raises(self):
        """Verify that zero step vectors raise ValueError during inversion."""
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(il_step=(0.0, 0.0), xl_step=(0.0, 0.0))
        with pytest.raises(ValueError, match="Degenerate seismic grid step matrix"):
            hub.map_to_seismic(100.0, 200.0, 1000.0)

    def test_collinear_step_vectors_raises(self):
        """Verify that collinear step vectors (det = 0) raise ValueError."""
        hub = CoordinateTransformHub()
        # Collinear: xl_step is 2 * il_step -> det(M) = 25*50 - 50*25 = 0
        hub.configure_seismic_grid(il_step=(25.0, 25.0), xl_step=(50.0, 50.0))
        with pytest.raises(ValueError, match="Degenerate seismic grid step matrix"):
            hub.map_to_seismic(500.0, 600.0, 1000.0)

    def test_nearly_singular_step_vectors_raises(self):
        """Verify that nearly singular matrices (|det| < 1e-12) raise ValueError."""
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(il_step=(1.0, 0.0), xl_step=(1.0, 1e-13))
        with pytest.raises(ValueError, match="Degenerate seismic grid step matrix"):
            hub.map_to_seismic(100.0, 100.0, 0.0)

    def test_highly_sheared_oblique_grid(self):
        """Verify bidirectional mapping on non-orthogonal, highly sheared seismic grid (angle = 30 deg)."""
        hub = CoordinateTransformHub()
        # IL along X axis, XL at 30 deg to IL axis
        hub.configure_seismic_grid(
            origin=(5000.0, 5000.0),
            il_step=(25.0, 0.0),
            xl_step=(25.0 * math.cos(math.radians(30)), 25.0 * math.sin(math.radians(30))),
            il_min=1,
            xl_min=1,
            velocity=2200.0,
        )

        test_il, test_xl, test_twt = 120, 350, 1850.0
        mx, my, mz = hub.seismic_to_map(test_il, test_xl, test_twt)
        rec_il, rec_xl, rec_twt = hub.map_to_seismic(mx, my, mz)

        assert rec_il == test_il
        assert rec_xl == test_xl
        assert math.isclose(rec_twt, test_twt, abs_tol=1e-4)

    def test_negative_step_grid(self):
        """Verify grid with negative coordinate steps (e.g. inverted Y or inverted X survey)."""
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(
            origin=(10000.0, 20000.0),
            il_step=(-20.0, 0.0),
            xl_step=(0.0, -25.0),
            il_min=500,
            xl_min=500,
            velocity=2500.0,
        )

        mx, my, mz = hub.seismic_to_map(550, 520, 1200.0)
        # dil = 50 -> x = 10000 - 50*20 = 9000
        # dxl = 20 -> y = 20000 - 20*25 = 19500
        assert math.isclose(mx, 9000.0, abs_tol=1e-5)
        assert math.isclose(my, 19500.0, abs_tol=1e-5)

        rec_il, rec_xl, rec_twt = hub.map_to_seismic(mx, my, mz)
        assert rec_il == 550
        assert rec_xl == 520
        assert math.isclose(rec_twt, 1200.0, abs_tol=1e-4)


class TestTortuousWellTrajectories:
    """Stress tests for tortuous wellpaths, unsorted survey stations, duplicate MDs, and azimuth wraps."""

    def test_unsorted_and_duplicate_md_stations(self):
        """Verify well registration handles unsorted stations and duplicate MDs gracefully."""
        hub = CoordinateTransformHub()
        stations = [
            (2000.0, 45.0, 90.0),
            (1000.0, 20.0, 45.0),
            (1000.0, 20.0, 45.0),  # Duplicate MD
            (500.0, 10.0, 0.0),
            (0.0, 0.0, 0.0),
        ]
        hub.register_well("W-UNSORTED", 1000.0, 2000.0, elevation=50.0, stations=stations)

        x, y, tvd = hub.well_depth_to_map("W-UNSORTED", 1500.0)
        assert math.isfinite(x)
        assert math.isfinite(y)
        assert math.isfinite(tvd)
        assert 1000.0 <= x
        assert tvd < 1500.0

    def test_azimuth_360_wrap_around(self):
        """Verify dogleg calculation when azimuth wraps across North (359 deg -> 1 deg)."""
        hub = CoordinateTransformHub()
        # Well heading roughly North, oscillating between 359 deg and 1 deg (2 deg delta)
        stations = [
            (0.0, 30.0, 359.0),
            (100.0, 30.0, 1.0),
            (200.0, 30.0, 359.0),
            (300.0, 30.0, 1.0),
        ]
        hub.register_well("W-AZ-WRAP", 0.0, 0.0, elevation=0.0, stations=stations)

        x300, y300, tvd300 = hub.well_depth_to_map("W-AZ-WRAP", 300.0)
        # Displacement should be primarily North (positive Y), with East displacement near 0
        assert y300 > 100.0
        assert math.isclose(x300, 0.0, abs_tol=10.0)
        assert math.isfinite(tvd300)

    def test_corkscrew_spiral_well(self):
        """Verify continuous 360-degree rotation corkscrew wellpath."""
        hub = CoordinateTransformHub()
        stations = []
        for i in range(20):
            md = i * 100.0
            inc = 30.0
            az = (i * 45.0) % 360.0  # complete rotations
            stations.append((md, inc, az))

        hub.register_well("W-SPIRAL", 5000.0, 5000.0, stations=stations)

        # Interpolate at various points along the spiral
        for md_test in [50.0, 250.0, 750.0, 1450.0, 1900.0]:
            x, y, tvd = hub.well_depth_to_map("W-SPIRAL", md_test)
            assert math.isfinite(x)
            assert math.isfinite(y)
            assert math.isfinite(tvd)
            assert tvd < md_test

    def test_hairpin_180_degree_turn(self):
        """Verify sudden 180-degree reversal in azimuth (drilling North then turning South)."""
        hub = CoordinateTransformHub()
        stations = [
            (0.0, 0.0, 0.0),
            (500.0, 45.0, 0.0),    # Drilling North
            (1000.0, 45.0, 180.0), # Turn to South
            (1500.0, 45.0, 180.0), # Continuing South
        ]
        hub.register_well("W-HAIRPIN", 1000.0, 1000.0, stations=stations)

        # At MD 500m, Y should be north of surface (> 1000)
        x500, y500, _ = hub.well_depth_to_map("W-HAIRPIN", 500.0)
        assert y500 > 1000.0

        # At MD 1500m, Y should have turned back South
        x1500, y1500, _ = hub.well_depth_to_map("W-HAIRPIN", 1500.0)
        assert y1500 < y500


class TestVelocityEdgeCases:
    """Stress tests for zero, negative, extreme, and invalid velocity values."""

    def test_zero_and_negative_velocities_rejected(self):
        """Verify zero, negative, and invalid velocities raise ValueError across all entrypoints."""
        hub = CoordinateTransformHub()

        # Zero velocity
        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.set_velocity(0.0)
        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.configure_seismic_grid(velocity=0.0)

        # Negative velocity
        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.set_velocity(-2000.0)
        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.configure_seismic_grid(velocity=-500.0)

    def test_extreme_high_and_low_velocities(self):
        """Verify extreme but positive velocities perform conversions correctly."""
        hub = CoordinateTransformHub()

        # Near-zero velocity (0.1 m/s)
        hub.set_velocity(0.1)
        _, _, z_slow = hub.seismic_to_map(100, 200, 2000.0)
        assert math.isclose(z_slow, 0.1, abs_tol=1e-6)

        # High velocity (300,000 km/s - speed of light)
        hub.set_velocity(3e8)
        _, _, z_fast = hub.seismic_to_map(100, 200, 2000.0)
        assert math.isclose(z_fast, 3e8, rel_tol=1e-6)
        _, _, twt_fast = hub.map_to_seismic(100.0, 200.0, 3e8)
        assert math.isclose(twt_fast, 2000.0, rel_tol=1e-6)


class TestHighAngleHorizontalWells:
    """Stress tests for 90-degree horizontal wells and undulating/upward trajectories."""

    def test_horizontal_well_extended_reach(self):
        """Verify 90-degree inclination horizontal well with 3000m lateral reach."""
        hub = CoordinateTransformHub()
        stations = [
            (0.0, 0.0, 0.0),
            (1000.0, 0.0, 0.0),      # Vertical kickoff
            (1500.0, 90.0, 90.0),    # Build to 90 deg horizontal heading East
            (4500.0, 90.0, 90.0),    # 3000m horizontal lateral
        ]
        hub.register_well("W-HORIZ", 5000.0, 5000.0, elevation=200.0, total_depth_m=4500.0, stations=stations)

        # At MD 1500m (heel)
        x_heel, y_heel, tvd_heel = hub.well_depth_to_map("W-HORIZ", 1500.0)
        # At MD 4500m (toe)
        x_toe, y_toe, tvd_toe = hub.well_depth_to_map("W-HORIZ", 4500.0)

        # Horizontal lateral: TVD stays constant, X increases by 3000m
        assert math.isclose(tvd_toe, tvd_heel, abs_tol=1e-3)
        assert math.isclose(x_toe - x_heel, 3000.0, abs_tol=1e-2)
        assert math.isclose(y_toe, y_heel, abs_tol=1e-2)

        # TVDSS subsea datum
        tvdss_toe = hub.well_depth_to_tvdss("W-HORIZ", 4500.0)
        assert math.isclose(tvdss_toe, 200.0 - tvd_toe, abs_tol=1e-5)

    def test_upward_undulating_well_trajectory(self):
        """Verify well drilled upwards (inclination > 90 deg) where TVD decreases along lateral."""
        hub = CoordinateTransformHub()
        stations = [
            (0.0, 0.0, 0.0),
            (1000.0, 90.0, 90.0),     # Horizontal at 1000m
            (1500.0, 100.0, 90.0),    # Inclination 100 deg (drilling upwards)
        ]
        hub.register_well("W-UPWARD", 0.0, 0.0, stations=stations)

        x1000, y1000, tvd1000 = hub.well_depth_to_map("W-UPWARD", 1000.0)
        x1500, y1500, tvd1500 = hub.well_depth_to_map("W-UPWARD", 1500.0)

        # Drilling upwards causes TVD to decrease
        assert tvd1500 < tvd1000
        assert x1500 > x1000


class TestConcurrentCoordinateLookups:
    """Stress tests for multi-threaded concurrent access to CoordinateTransformHub."""

    def test_multithreaded_read_concurrency(self):
        """Verify 50 concurrent threads executing 10,000 coordinate transforms without race conditions."""
        hub = CoordinateTransformHub()
        hub.configure_seismic_grid(
            origin=(1000.0, 2000.0),
            il_step=(25.0, 0.0),
            xl_step=(0.0, 25.0),
            il_min=1,
            xl_min=1,
            velocity=2500.0,
        )

        for i in range(10):
            hub.register_well(
                f"WELL-{i}",
                x=1000.0 + i * 50.0,
                y=2000.0 + i * 50.0,
                elevation=20.0,
                total_depth_m=3000.0,
            )

        errors = []

        def worker_task(thread_id: int):
            try:
                for step in range(200):
                    # Seismic to map & inverse
                    il = 10 + (thread_id * 3 + step) % 100
                    xl = 20 + (thread_id * 5 + step) % 100
                    twt = 500.0 + step * 5.0
                    x, y, z = hub.seismic_to_map(il, xl, twt)
                    rec_il, rec_xl, rec_twt = hub.map_to_seismic(x, y, z)
                    if rec_il != il or rec_xl != xl or not math.isclose(rec_twt, twt, abs_tol=1e-4):
                        raise ValueError(f"Seismic mismatch in thread {thread_id}")

                    # Well depth to map
                    target_well = f"WELL-{thread_id % 10}"
                    wx, wy, tvd = hub.well_depth_to_map(target_well, 1000.0 + step)
                    assert math.isfinite(wx) and math.isfinite(wy) and math.isfinite(tvd)

                    # Nearest well
                    nearest = hub.map_to_well(wx, wy, max_radius=10.0)
                    if nearest != target_well:
                        raise ValueError(f"Nearest well mismatch in thread {thread_id}: expected {target_well}, got {nearest}")
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(worker_task, tid) for tid in range(50)]
            for future in as_completed(futures):
                future.result()

        assert len(errors) == 0, f"Thread errors encountered: {errors}"

    def test_concurrent_registration_and_lookup(self):
        """Verify thread-safe reads while wells are dynamically registered and unregistered."""
        hub = CoordinateTransformHub()
        hub.register_well("BASE-WELL", 500.0, 500.0, elevation=10.0, total_depth_m=2000.0)

        stop_event = threading.Event()
        errors = []

        def reader_loop():
            try:
                while not stop_event.is_set():
                    # BASE-WELL is always present
                    x, y, tvd = hub.well_depth_to_map("BASE-WELL", 500.0)
                    assert x == 500.0 and y == 500.0 and tvd == 500.0
                    _ = hub.map_to_well(500.0, 500.0, max_radius=10.0)
            except Exception as exc:
                errors.append(exc)

        def writer_loop():
            try:
                for i in range(100):
                    wname = f"TEMP-{threading.get_ident()}-{i}"
                    hub.register_well(wname, 1000.0 + i, 1000.0 + i)
                    _ = hub.well_depth_to_map(wname, 100.0)
                    hub.unregister_well(wname)
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=16) as executor:
            readers = [executor.submit(reader_loop) for _ in range(8)]
            writers = [executor.submit(writer_loop) for _ in range(8)]

            # Wait for writers to complete
            for w in writers:
                w.result()

            stop_event.set()
            for r in readers:
                r.result()

        assert len(errors) == 0, f"Concurrent registration errors: {errors}"
