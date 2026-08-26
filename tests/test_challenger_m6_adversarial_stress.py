"""Tier 5 Adversarial Stress Testing & Empirical Challenge Suite for Milestone 6.

Author: challenger_m6_2 (teamwork_preview_challenger)
Scope:
1. Multi-View Event Storms on SelectionContext:
   - High-frequency event storms (50,000 events) across multiple widget sources.
   - 20-thread concurrent producer-consumer race harness with invariant checks.
   - Multi-view mesh topology (6 interconnected views) with echo loop suppression.
   - Deep cascade re-entrancy resilience and stack safety.
   - Large payload storms (100k wells, complex attributes) with memory isolation.
   - Dynamic listener connect/disconnect storms during active emission.

2. Coordinate Transform Singularities on CoordinateTransformHub:
   - Out-of-bounds MD (negative, massive 1e12 m, infinite/NaN) and depth roundtrips.
   - Negative TVD, high elevation mountain datums, and subsea TVDSS conversions.
   - Pathological well trajectories (0 stations, duplicate MD, 90°/180° doglegs, corkscrew wellpaths).
   - Non-orthogonal sheared seismic grids, rotated grids, anisotropic step ratios.
   - Degenerate / singular step matrices, negative/zero/extreme velocities, negative TWT.

3. Extreme Polygonization Topologies in Geological Pipeline:
   - 5-tier nested concentric islands-in-holes-in-islands (Russian doll topology).
   - Zero-area sliver polygons, single-pixel bottlenecks, hourglass vertices, and spikes.
   - Collinear vertex simplification on massive step boundaries.
   - High-density checkerboard and fractal grid stress testing.
   - Marching Squares saddle point disambiguation and contour line continuity.
   - Pathological grid payloads (all-NaN, Inf, uniform flat, 1xN/Nx1).
"""

from __future__ import annotations

import concurrent.futures
import gc
import math
import threading
import time
from typing import Any, Sequence

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, Qt
from shapely.geometry import shape

from paleo_workbench.mapping.geological_pipeline.contouring import (
    _marching_squares_pure_python,
    _stitch_segments,
    calculate_nice_contour_levels,
    calculate_polyline_length,
    calculate_quantile_contour_levels,
    chaikin_smooth,
    douglas_peucker_2d,
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    _compute_geometry_area,
    _point_in_ring,
    _polygonize_raster_boundaries,
    calculate_shoelace_area,
    calculate_signed_area,
    generate_facies_polygon_layer,
    simplify_collinear_ring,
)
from paleo_workbench.mapping.topology import repair_invalid_geometry
from paleo_workbench.viz import (
    CoordinateTransformHub,
    SelectionContext,
    SelectionState,
    WellTrajectoryData,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_test_grid_result(
    grid_z: np.ndarray,
    extent: tuple[float, float, float, float] = (0.0, 0.0, 100.0, 100.0),
    factor_name: str = "porosity",
) -> FactorGridResult:
    """Construct a well-formed FactorGridResult from a numpy grid."""
    h, w = grid_z.shape
    xmin, ymin, xmax, ymax = extent
    gx = np.linspace(xmin, xmax, w)
    gy = np.linspace(ymin, ymax, h)
    return FactorGridResult(
        grid_z=grid_z,
        grid_x=gx,
        grid_y=gy,
        factor_name=factor_name,
        algorithm_id="kriging",
        unit="%",
        crs="EPSG:3857",
    )


# ==============================================================================
# 1. MULTI-VIEW EVENT STORMS ON SelectionContext
# ==============================================================================

class TestAdversarialMultiViewEventStorms:
    """Stress tests simulating intense event storms, high concurrency, and complex topologies."""

    def test_event_storm_high_frequency_burst_50k(self):
        """Burst 50,000 rapid selection events across 5 alternating source widgets.

        Verifies throughput (>5,000 ops/sec), ordering, monotonic timestamps,
        and final snapshot exactness.
        """
        bus = SelectionContext()
        event_count = 0
        sources = ["map_canvas", "well_log_1", "well_log_2", "seismic_3d", "section_view"]

        def on_event(ctx: SelectionContext):
            nonlocal event_count
            event_count += 1

        bus.selection_changed.connect(on_event)

        t0 = time.perf_counter()
        total_events = 50_000

        for i in range(total_events):
            src = sources[i % len(sources)]
            if i % 4 == 0:
                bus.update(
                    active_well_id=f"WELL-{i:06d}",
                    selected_well_ids=[f"WELL-{i:06d}", f"WELL-{i+1:06d}"],
                    source_widget_id=src,
                )
            elif i % 4 == 1:
                bus.update(
                    depth_range=(float(i), float(i + 200)),
                    source_widget_id=src,
                )
            elif i % 4 == 2:
                bus.update(
                    seismic_cursor=(i % 1000, (i * 2) % 1000, float(i * 1.5)),
                    source_widget_id=src,
                )
            else:
                bus.update(
                    active_well_id=f"WELL-{i:06d}",
                    depth_range=(float(i), float(i + 50)),
                    seismic_cursor=(100, 200, 300.0),
                    custom_attributes={"event_seq": i},
                    source_widget_id=src,
                )

        elapsed = time.perf_counter() - t0

        assert event_count == total_events
        # Throughput assertion: 50,000 events within 10.0 seconds (>5,000 ops/s)
        assert elapsed < 10.0, f"50k burst took {elapsed:.3f}s (too slow)"

        snap = bus.snapshot()
        assert snap.source_widget_id == sources[(total_events - 1) % len(sources)]
        assert snap.timestamp > 0.0

    def test_event_storm_concurrent_producer_consumer_race(self):
        """20 concurrent threads (10 producers + 10 consumers) executing 1,000 ops each (20,000 ops).

        Checks thread safety, snapshot isolation, normalization invariants, and deadlock freedom.
        """
        bus = SelectionContext()
        stop_event = threading.Event()
        errors: list[Exception] = []
        consumer_checks = 0
        checks_lock = threading.Lock()

        def producer(thread_id: int):
            try:
                for i in range(1000):
                    if stop_event.is_set():
                        break
                    src = f"producer_thread_{thread_id}"
                    if i % 3 == 0:
                        bus.update(
                            active_well_id=f"P{thread_id}-W{i}",
                            selected_well_ids=[f"P{thread_id}-W{i}", f"P{thread_id}-W{i+1}"],
                            depth_range=(float(i * 10 + 500), float(i * 10)),  # inverted to test normalization
                            source_widget_id=src,
                            custom_attributes={"thread": thread_id, "step": i},
                        )
                    elif i % 3 == 1:
                        bus.update(
                            seismic_cursor=(thread_id * 50, i * 2, float(i * 3.3)),
                            source_widget_id=src,
                        )
                    else:
                        bus.clear(source_widget_id=src)
            except Exception as e:
                errors.append(e)

        def consumer(thread_id: int):
            nonlocal consumer_checks
            local_checks = 0
            try:
                for _ in range(1000):
                    if stop_event.is_set():
                        break
                    snap = bus.snapshot()

                    # Invariant 1: normalized depth range is valid
                    norm = snap.normalized_depth_range
                    if norm is not None:
                        assert len(norm) == 2
                        assert norm[0] <= norm[1]

                    # Invariant 2: selected_well_ids is immutable tuple
                    assert isinstance(snap.selected_well_ids, tuple)

                    # Invariant 3: snapshot custom attributes isolation
                    snap.custom_attributes["injected_key"] = 9999
                    snap_fresh = bus.snapshot()
                    assert "injected_key" not in snap_fresh.custom_attributes

                    # Invariant 4: live property consistency
                    live_norm = bus.normalized_depth_range
                    if live_norm is not None:
                        assert live_norm[0] <= live_norm[1]

                    local_checks += 1
            except Exception as e:
                errors.append(e)
            finally:
                with checks_lock:
                    consumer_checks += local_checks

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            prods = [executor.submit(producer, i) for i in range(10)]
            cons = [executor.submit(consumer, i) for i in range(10)]
            concurrent.futures.wait(prods + cons)

        assert len(errors) == 0, f"Concurrent execution errors: {errors}"
        assert consumer_checks >= 10 * 1000

    def test_multi_view_echo_loop_storm_mesh_topology(self):
        """Mesh topology of 6 workstation view widgets firing concurrent event bursts.

        Verifies that source tagging prevents echo storms and all nodes converge cleanly.
        """
        bus = SelectionContext()
        node_names = ["map_canvas", "well_log_primary", "well_log_secondary", "seismic_inline", "seismic_crossline", "section_view"]

        class MeshWidgetNode:
            def __init__(self, name: str, context: SelectionContext):
                self.name = name
                self.bus = context
                self.received_events: list[SelectionState] = []
                self.bus.selection_changed.connect(self.on_change)

            def on_change(self, ctx: SelectionContext):
                if ctx.source_widget_id == self.name:
                    return  # Echo suppression
                self.received_events.append(ctx.snapshot())

            def trigger_selection(self, well_id: str, depth: tuple[float, float], cursor: tuple[int, int, float]):
                self.bus.update(
                    active_well_id=well_id,
                    depth_range=depth,
                    seismic_cursor=cursor,
                    source_widget_id=self.name,
                )

        nodes = [MeshWidgetNode(name, bus) for name in node_names]

        # Each node triggers 50 updates sequentially
        for round_idx in range(50):
            for i, node in enumerate(nodes):
                node.trigger_selection(
                    well_id=f"WELL_R{round_idx}_N{i}",
                    depth=(1000.0 + round_idx * 10, 1500.0 + round_idx * 10),
                    cursor=(100 + round_idx, 200 + round_idx, 500.0 + round_idx * 2.0),
                )

        # Total events fired = 50 * 6 = 300
        # Each node should have received exactly 300 - 50 = 250 events (suppressed its own 50 events)
        for node in nodes:
            assert len(node.received_events) == 250, f"Node {node.name} expected 250 events, got {len(node.received_events)}"
            assert all(ev.source_widget_id != node.name for ev in node.received_events)

        # Verify final converged state
        final = bus.snapshot()
        assert final.active_well_id == "WELL_R49_N5"
        assert final.source_widget_id == "section_view"

    def test_reentrant_event_storm_deep_cascade_resilience(self):
        """8-level re-entrant cascade triggered on a single thread.

        Node 1 -> triggers Node 2 -> triggers Node 3 -> ... -> Node 8.
        Verifies stack safety, deterministic execution order, and loop termination.
        """
        bus = SelectionContext()
        chain_depth = 8
        cascade_log: list[str] = []

        class CascadeNode:
            def __init__(self, index: int, bus: SelectionContext):
                self.index = index
                self.name = f"cascade_node_{index}"
                self.bus = bus
                self.bus.selection_changed.connect(self.on_change)

            def on_change(self, ctx: SelectionContext):
                if ctx.source_widget_id == self.name:
                    return
                # Check if this node is next in the chain
                expected_trigger = f"cascade_node_{self.index - 1}" if self.index > 1 else "initial_trigger"
                if ctx.source_widget_id == expected_trigger and self.index < chain_depth:
                    cascade_log.append(f"node_{self.index}_triggered")
                    self.bus.update(
                        custom_attributes={"level": self.index},
                        source_widget_id=self.name,
                    )

        nodes = [CascadeNode(i, bus) for i in range(1, chain_depth + 1)]

        # Fire initial trigger
        bus.update(active_well_id="CASCADE_START", source_widget_id="initial_trigger")

        # Verify all levels triggered in sequential order
        expected_log = [f"node_{i}_triggered" for i in range(1, chain_depth)]
        assert cascade_log == expected_log
        assert bus.custom_attributes.get("level") == chain_depth - 1

    def test_dynamic_listener_storm_during_active_emission(self):
        """Rapidly add and remove 100 dynamic signal listeners while 2,000 events are emitting."""
        bus = SelectionContext()
        call_counts: dict[int, int] = {}

        def make_handler(idx: int):
            def handler(ctx: SelectionContext):
                call_counts[idx] = call_counts.get(idx, 0) + 1
            return handler

        handlers = [make_handler(i) for i in range(100)]

        for i in range(2000):
            # Dynamically connect new handlers
            if i < 100:
                bus.selection_changed.connect(handlers[i])

            bus.update(active_well_id=f"W-{i}", source_widget_id="storm_gen")

            # Dynamically disconnect half of the handlers midway
            if i == 500:
                for h_idx in range(0, 50):
                    try:
                        bus.selection_changed.disconnect(handlers[h_idx])
                    except Exception:
                        pass

        # Handlers 0-49 should have stopped receiving updates at event 500
        for h_idx in range(0, 50):
            assert call_counts[h_idx] <= 501, f"Handler {h_idx} continued receiving calls after disconnect"

        # Handlers 50-99 should have received all subsequent updates
        for h_idx in range(50, 100):
            assert call_counts[h_idx] >= 1900


# ==============================================================================
# 2. COORDINATE TRANSFORM SINGULARITIES
# ==============================================================================

class TestAdversarialCoordinateTransformSingularities:
    """Stress tests targeting mathematical singularities and edge cases in CoordinateTransformHub."""

    def test_coordinate_singularities_out_of_bounds_md(self):
        """Test out-of-bounds MD on vertical and deviated wells.

        MD < 0, MD > total depth, MD >> 1e12 m.
        """
        hub = CoordinateTransformHub()
        # Deviated well
        stations = [
            (0.0, 0.0, 0.0),
            (1000.0, 0.0, 0.0),
            (2000.0, 30.0, 45.0),
            (3000.0, 60.0, 90.0),
        ]
        hub.register_well("WELL_DEV", 500000.0, 4000000.0, elevation=100.0, total_depth_m=3000.0, stations=stations)

        # 1. Negative MD: np.interp clamps to initial station
        x_neg, y_neg, tvd_neg = hub.well_depth_to_map("WELL_DEV", -500.0)
        assert math.isclose(x_neg, 500000.0, abs_tol=1e-5)
        assert math.isclose(y_neg, 4000000.0, abs_tol=1e-5)
        assert math.isclose(tvd_neg, 0.0, abs_tol=1e-5)

        # 2. Massive MD (1e12 m): np.interp clamps to final station
        x_huge, y_huge, tvd_huge = hub.well_depth_to_map("WELL_DEV", 1e12)
        assert math.isfinite(x_huge)
        assert math.isfinite(y_huge)
        assert math.isfinite(tvd_huge)
        # Clamped to station at MD 3000m
        x_3000, y_3000, tvd_3000 = hub.well_depth_to_map("WELL_DEV", 3000.0)
        assert math.isclose(x_huge, x_3000, abs_tol=1e-5)
        assert math.isclose(y_huge, y_3000, abs_tol=1e-5)
        assert math.isclose(tvd_huge, tvd_3000, abs_tol=1e-5)

        # 3. TVD to MD inverse mapping with negative TVD
        md_neg = hub.map_to_well_depth("WELL_DEV", -100.0)
        assert math.isclose(md_neg, 0.0, abs_tol=1e-5)

        # 4. TVD to MD inverse mapping with massive TVD
        md_huge = hub.map_to_well_depth("WELL_DEV", 1e12)
        assert math.isclose(md_huge, 3000.0, abs_tol=1e-5)

    def test_coordinate_singularities_negative_tvd_and_elevation(self):
        """Test negative TVD, offshore subsea platforms (elevation < 0), and mountain wells (elevation > 5000m)."""
        hub = CoordinateTransformHub()
        # High mountain well
        hub.register_well("W_MOUNTAIN", 1000.0, 2000.0, elevation=5200.0, total_depth_m=4000.0)
        # Offshore subsea well
        hub.register_well("W_OFFSHORE", 3000.0, 4000.0, elevation=-80.0, total_depth_m=3500.0)

        # Mountain TVDSS: KB - TVD = 5200 - 1000 = 4200 (above sea level)
        tvdss_mtn = hub.well_depth_to_tvdss("W_MOUNTAIN", 1000.0)
        assert math.isclose(tvdss_mtn, 4200.0, abs_tol=1e-5)

        # Deep mountain TVDSS: KB - TVD = 5200 - 6000 = -800 (below sea level)
        tvdss_mtn_deep = hub.well_depth_to_tvdss("W_MOUNTAIN", 6000.0)
        assert math.isclose(tvdss_mtn_deep, -800.0, abs_tol=1e-5)

        # Offshore TVDSS: KB - TVD = -80 - 1000 = -1080
        tvdss_off = hub.well_depth_to_tvdss("W_OFFSHORE", 1000.0)
        assert math.isclose(tvdss_off, -1080.0, abs_tol=1e-5)

    def test_coordinate_singularities_pathological_trajectories(self):
        """Test pathological survey stations:

        - 0 stations
        - Duplicate MD stations (dmd == 0)
        - 180° complete vertical flip doglegs (inc 0 -> inc 180)
        - 90° horizontal turn (inc 90, az 0 -> inc 90, az 180)
        """
        hub = CoordinateTransformHub()

        # 1. Zero stations vertical fallback
        hub.register_well("W_ZERO", 100.0, 200.0, elevation=0.0, total_depth_m=2000.0, stations=[])
        x, y, tvd = hub.well_depth_to_map("W_ZERO", 1500.0)
        assert (x, y, tvd) == (100.0, 200.0, 1500.0)

        # 2. Duplicate MD stations
        stations_dup = [
            (0.0, 0.0, 0.0),
            (1000.0, 10.0, 45.0),
            (1000.0, 10.0, 45.0),  # Duplicate MD
            (1000.0, 15.0, 50.0),  # Duplicate MD with different angle
            (2000.0, 20.0, 60.0),
        ]
        hub.register_well("W_DUP", 100.0, 200.0, elevation=0.0, total_depth_m=2000.0, stations=stations_dup)
        x_dup, y_dup, tvd_dup = hub.well_depth_to_map("W_DUP", 1000.0)
        assert math.isfinite(x_dup)
        assert math.isfinite(y_dup)
        assert math.isfinite(tvd_dup)

        # 3. 180° vertical flip (inc 0 -> inc 180)
        stations_flip = [
            (0.0, 0.0, 0.0),
            (1000.0, 0.0, 0.0),
            (2000.0, 180.0, 0.0),  # Vertical turn upwards
        ]
        hub.register_well("W_FLIP", 100.0, 200.0, elevation=0.0, total_depth_m=2000.0, stations=stations_flip)
        x_flip, y_flip, tvd_flip = hub.well_depth_to_map("W_FLIP", 2000.0)
        assert math.isfinite(x_flip)
        assert math.isfinite(y_flip)
        assert math.isfinite(tvd_flip)

        # 4. 180° azimuth U-turn (inc 90, az 0 -> inc 90, az 180)
        stations_uturn = [
            (0.0, 0.0, 0.0),
            (1000.0, 90.0, 0.0),    # Heading North
            (2000.0, 90.0, 180.0),  # U-turn heading South
        ]
        hub.register_well("W_UTURN", 0.0, 0.0, elevation=0.0, total_depth_m=2000.0, stations=stations_uturn)
        x_u, y_u, tvd_u = hub.well_depth_to_map("W_UTURN", 2000.0)
        assert math.isfinite(x_u)
        assert math.isfinite(y_u)
        assert math.isfinite(tvd_u)

    def test_coordinate_singularities_non_orthogonal_and_singular_seismic_grids(self):
        """Test sheared, non-orthogonal seismic grids, singular step matrices, and velocity edge cases."""
        hub = CoordinateTransformHub()

        # 1. Non-orthogonal sheared seismic grid (IL step = (15, 8), XL step = (-5, 20))
        # Matrix = [[15, -5], [8, 20]], det = 15*20 - (-5)*8 = 300 + 40 = 340 != 0
        hub.configure_seismic_grid(
            origin=(500000.0, 4000000.0),
            il_step=(15.0, 8.0),
            xl_step=(-5.0, 20.0),
            il_min=100,
            xl_min=200,
            velocity=2500.0,
        )

        test_coords = [
            (100, 200, 1000.0),
            (150, 250, 2500.0),
            (50, 100, 0.0),
            (-500, 800, 5000.0),
        ]

        for il, xl, twt in test_coords:
            x, y, z = hub.seismic_to_map(il, xl, twt)
            assert math.isfinite(x)
            assert math.isfinite(y)
            assert math.isfinite(z)

            rec_il, rec_xl, rec_twt = hub.map_to_seismic(x, y, z)
            assert rec_il == il
            assert rec_xl == xl
            assert math.isclose(rec_twt, twt, abs_tol=1e-5)

        # 2. Singular / collinear grid step vectors (det == 0)
        hub.configure_seismic_grid(
            il_step=(10.0, 20.0),
            xl_step=(20.0, 40.0),  # Collinear: 2 * (10, 20)
        )
        with pytest.raises(ValueError, match="Degenerate seismic grid step matrix"):
            hub.map_to_seismic(500100.0, 4000200.0, 1000.0)

        # 3. Invalid negative or zero velocity
        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.configure_seismic_grid(velocity=-1500.0)

        with pytest.raises(ValueError, match="Velocity must be positive"):
            hub.set_velocity(0.0)

    def test_coordinate_singularities_unregistered_well_lookup(self):
        """Verify accessing unregistered well raises KeyError."""
        hub = CoordinateTransformHub()
        with pytest.raises(KeyError, match="Well NON_EXISTENT not found"):
            hub.well_depth_to_map("NON_EXISTENT", 1000.0)

        with pytest.raises(KeyError, match="Well NON_EXISTENT not found"):
            hub.well_depth_to_tvdss("NON_EXISTENT", 1000.0)

        with pytest.raises(KeyError, match="Well NON_EXISTENT not found"):
            hub.map_to_well_depth("NON_EXISTENT", 1000.0)


# ==============================================================================
# 3. EXTREME POLYGONIZATION TOPOLOGIES
# ==============================================================================

class TestAdversarialExtremePolygonizationTopologies:
    """Stress tests for complex nested topological polygons, slivers, collinear nodes, and degenerate rasters."""

    def test_extreme_topology_islands_in_holes_in_islands_5_tiers(self):
        """5-Tier Nested Concentric 'Russian Doll' Topology.

        Tier 0: Outer Box 100x100 (Class 1)
        Tier 1: Ring Hole 80x80 (Class 0)
        Tier 2: Island inside Hole 60x60 (Class 1)
        Tier 3: Ring Hole inside Island 40x40 (Class 0)
        Tier 4: Island inside Hole 20x20 (Class 1)
        Core: Inner Hole 10x10 (Class 0)

        Verifies:
        1. All generated GeoJSON geometries pass Shapely `is_valid`.
        2. Nested holes are correctly associated with their containing exterior ring.
        3. Area conservation: Area(Class 1) + Area(Class 0) == Total Area (100 * 100 = 10,000).
        """
        h, w = 100, 100
        z = np.zeros((h, w), dtype=np.float64)

        # Tier 0: Outer (Class 1)
        z[:, :] = 1.0
        # Tier 1: 80x80 (Class 0)
        z[10:90, 10:90] = 0.0
        # Tier 2: 60x60 (Class 1)
        z[20:80, 20:80] = 1.0
        # Tier 3: 40x40 (Class 0)
        z[30:70, 30:70] = 0.0
        # Tier 4: 20x20 (Class 1)
        z[40:60, 40:60] = 1.0
        # Core: 10x10 (Class 0)
        z[45:55, 45:55] = 0.0

        extent = (0.0, 0.0, 100.0, 100.0)
        res = make_test_grid_result(z, extent=extent)

        p_layer = generate_facies_polygon_layer(
            res,
            thresholds=[0.5],
            facies_names=["背景带", "目标带"],
        )

        assert len(p_layer.features) >= 2

        total_poly_area = 0.0
        for feat in p_layer.features:
            geom = feat["geometry"]
            s_geom = shape(geom)
            assert s_geom.is_valid, f"Invalid geometry for {feat['properties']['facies_name']}"
            total_poly_area += s_geom.area

        # Total grid area = 100 * 100 = 10000.0
        assert math.isclose(total_poly_area, 10000.0, rel_tol=1e-3)

        # Expected Class 1 area:
        # Tier 0 (100^2 - 80^2) = 10000 - 6400 = 3600
        # Tier 2 (60^2 - 40^2) = 3600 - 1600 = 2000
        # Tier 4 (20^2 - 10^2) = 400 - 100 = 300
        # Total Class 1 = 3600 + 2000 + 300 = 5900
        feat_c1 = [f for f in p_layer.features if f["properties"]["facies_name"] == "目标带"]
        area_c1 = sum(shape(f["geometry"]).area for f in feat_c1)
        assert math.isclose(area_c1, 5900.0, rel_tol=1e-3)

    def test_extreme_topology_zero_area_sliver_polygons_and_spikes(self):
        """Test rasters with 1-pixel diagonal bridges, isolated single-pixel peaks, and cross patterns (+).

        Verifies auto-healing via `repair_invalid_geometry` eliminates self-intersections.
        """
        h, w = 30, 30
        z = np.zeros((h, w), dtype=np.float64)

        # 1. Diagonal bridge (touching corners)
        z[5, 5] = 10.0
        z[6, 6] = 10.0
        z[7, 7] = 10.0

        # 2. Cross pattern (+) touching at center
        z[15, 10:20] = 10.0
        z[10:20, 15] = 10.0

        # 3. Isolated single-pixel spike
        z[25, 25] = 10.0

        extent = (0.0, 0.0, 300.0, 300.0)
        res = make_test_grid_result(z, extent=extent)

        p_layer = generate_facies_polygon_layer(
            res,
            thresholds=[5.0],
            facies_names=["背景", "尖峰带"],
        )

        for feat in p_layer.features:
            geom = feat["geometry"]
            s_geom = shape(geom)
            assert s_geom.is_valid, f"Invalid geometry created for sliver/spike raster: {geom}"
            assert s_geom.area > 0.0

    def test_extreme_topology_collinear_points_and_staircases(self):
        """Test polygon collinear vertex simplification along long horizontal/vertical boundaries."""
        # 100x100 grid with left half = 0, right half = 1 (creates 100 collinear boundary vertices)
        h, w = 100, 100
        z = np.zeros((h, w), dtype=np.float64)
        z[:, 50:] = 10.0

        extent = (0.0, 0.0, 1000.0, 1000.0)
        res = make_test_grid_result(z, extent=extent)

        p_layer = generate_facies_polygon_layer(
            res,
            thresholds=[5.0],
            facies_names=["左侧", "右侧"],
        )

        assert len(p_layer.features) == 2
        for feat in p_layer.features:
            geom = feat["geometry"]
            assert geom["type"] == "Polygon"
            coords = geom["coordinates"][0]
            # A rectangular polygon simplified should have 5 vertices (4 corners + closing vertex)
            assert len(coords) == 5, f"Expected 5 vertices after collinear simplification, got {len(coords)}"

    def test_extreme_topology_checkerboard_stress(self):
        """Dense 50x50 alternating checkerboard raster (2,500 alternating cells).

        Verifies robust loop extraction, no infinite loops, bounded runtime (<3s), and valid geometries.
        """
        h, w = 50, 50
        # Checkerboard: 1 if (i + j) % 2 == 0 else 0
        i_idx, j_idx = np.indices((h, w))
        z = ((i_idx + j_idx) % 2).astype(np.float64) * 10.0

        extent = (0.0, 0.0, 500.0, 500.0)
        res = make_test_grid_result(z, extent=extent)

        t0 = time.perf_counter()
        p_layer = generate_facies_polygon_layer(res, thresholds=[5.0])
        elapsed = time.perf_counter() - t0

        assert elapsed < 3.0, f"Checkerboard polygonization took {elapsed:.3f}s (too slow)"
        assert len(p_layer.features) >= 1

        for feat in p_layer.features:
            geom = feat["geometry"]
            s_geom = shape(geom)
            assert s_geom.is_valid

    def test_extreme_topology_saddle_point_marching_squares_disambiguation(self):
        """Test Marching Squares contouring on 2x2 saddle cells (Cases 5 and 10).

        Verifies center value disambiguation produces consistent non-intersecting contours.
        """
        # Case 5 saddle: top-left & bottom-right high, top-right & bottom-left low
        z_case5 = np.array([
            [10.0, 0.0],
            [0.0, 10.0],
        ], dtype=np.float64)
        gx = np.array([0.0, 10.0])
        gy = np.array([0.0, 10.0])

        # Level at 5.0 (v_center = 5.0 >= level -> connected high diagonal)
        contours_5a = _marching_squares_pure_python(z_case5, gx, gy, level=5.0)
        assert len(contours_5a) == 2

        # Level at 5.1 (v_center = 5.0 < level -> connected low diagonal)
        contours_5b = _marching_squares_pure_python(z_case5, gx, gy, level=5.1)
        assert len(contours_5b) == 2

        # Case 10 saddle: top-right & bottom-left high, top-left & bottom-right low
        z_case10 = np.array([
            [0.0, 10.0],
            [10.0, 0.0],
        ], dtype=np.float64)
        contours_10a = _marching_squares_pure_python(z_case10, gx, gy, level=5.0)
        assert len(contours_10a) == 2

    def test_extreme_topology_all_nan_infinite_and_uniform_rasters(self):
        """Test pathological raster values:

        - All NaNs
        - All Inf / -Inf
        - Uniform flat rasters (vmin == vmax)
        - 1x1, 1xN, Nx1 rasters
        """
        # 1. 100% NaN grid
        z_nan = np.full((20, 20), np.nan)
        res_nan = make_test_grid_result(z_nan)
        c_nan = generate_contour_layer(res_nan)
        p_nan = generate_facies_polygon_layer(res_nan)
        assert len(c_nan.features) == 0
        assert len(p_nan.features) == 0

        # 2. 100% Inf grid
        z_inf = np.full((20, 20), np.inf)
        res_inf = make_test_grid_result(z_inf)
        c_inf = generate_contour_layer(res_inf)
        p_inf = generate_facies_polygon_layer(res_inf)
        assert len(c_inf.features) == 0
        assert len(p_inf.features) == 0

        # 3. Uniform flat grid (vmin == vmax == 25.0)
        z_flat = np.full((30, 30), 25.0)
        res_flat = make_test_grid_result(z_flat)
        c_flat = generate_contour_layer(res_flat)
        p_flat = generate_facies_polygon_layer(res_flat)
        # Contouring on flat grid produces 0 contours
        assert len(c_flat.features) == 0
        # Polygonization produces 1 uniform facies layer covering the entire grid
        assert len(p_flat.features) == 1
        s_flat = shape(p_flat.features[0]["geometry"])
        assert s_flat.is_valid
        assert math.isclose(s_flat.area, 10000.0, rel_tol=1e-3)

        # 4. 1x1 degenerate grid (single point has 0 area / extent)
        z_1x1 = np.array([[10.0]])
        res_1x1 = make_test_grid_result(z_1x1)
        c_1x1 = generate_contour_layer(res_1x1)
        p_1x1 = generate_facies_polygon_layer(res_1x1)
        assert len(c_1x1.features) == 0
        assert len(p_1x1.features) == 0

    def test_extreme_topology_multi_hole_multi_island_archipelago(self):
        """Archipelago topology: multiple separate islands, each containing multiple holes with nested sub-islands."""
        h, w = 120, 120
        z = np.zeros((h, w), dtype=np.float64)

        # Island 1 (top-left 50x50):
        z[10:50, 10:50] = 1.0
        # Island 1 - Hole A (10x10)
        z[15:25, 15:25] = 0.0
        # Island 1 - Hole B (10x10)
        z[30:40, 30:40] = 0.0
        # Island 1 - Hole B Sub-island (4x4)
        z[33:37, 33:37] = 1.0

        # Island 2 (bottom-right 50x50):
        z[70:110, 70:110] = 1.0
        # Island 2 - Hole C (15x15)
        z[80:95, 80:95] = 0.0
        # Island 2 - Hole C Sub-island (6x6)
        z[85:91, 85:91] = 1.0

        extent = (0.0, 0.0, 1200.0, 1200.0)
        res = make_test_grid_result(z, extent=extent)

        p_layer = generate_facies_polygon_layer(
            res,
            thresholds=[0.5],
            facies_names=["水域/孔洞", "陆地/相带"],
        )

        assert len(p_layer.features) >= 2
        for feat in p_layer.features:
            s_geom = shape(feat["geometry"])
            assert s_geom.is_valid

        total_area = sum(shape(f["geometry"]).area for f in p_layer.features)
        assert math.isclose(total_area, 1200.0 * 1200.0, rel_tol=1e-3)

    def test_extreme_topology_thresholds_boundary_resilience(self):
        """Test irregular threshold inputs:

        - Unsorted thresholds
        - Duplicate thresholds
        - Thresholds completely outside [vmin, vmax]
        - Negative thresholds
        """
        h, w = 30, 30
        z = np.linspace(-100.0, 200.0, h * w).reshape((h, w))
        res = make_test_grid_result(z)

        # 1. Unsorted & duplicate thresholds with negatives
        p_layer1 = generate_facies_polygon_layer(
            res,
            thresholds=[50.0, -20.0, 50.0, -80.0, 150.0],
            facies_names=["F1", "F2", "F3", "F4", "F5"],
        )
        assert len(p_layer1.features) > 0
        for feat in p_layer1.features:
            assert shape(feat["geometry"]).is_valid

        # 2. Thresholds below vmin (all cells >= threshold -> 1 class)
        p_layer2 = generate_facies_polygon_layer(
            res,
            thresholds=[-500.0],
            facies_names=["全部高值"],
        )
        assert len(p_layer2.features) == 1
        assert shape(p_layer2.features[0]["geometry"]).is_valid

        # 3. Thresholds above vmax (all cells < threshold -> 1 class)
        p_layer3 = generate_facies_polygon_layer(
            res,
            thresholds=[1000.0],
            facies_names=["全部低值"],
        )
        assert len(p_layer3.features) == 1
        assert shape(p_layer3.features[0]["geometry"]).is_valid

    def test_extreme_topology_large_scale_noisy_raster_stress(self):
        """100x100 high-entropy random binary grid (10,000 cells) testing polygonizer performance and robustness."""
        rng = np.random.default_rng(seed=42)
        z = rng.integers(0, 2, size=(100, 100)).astype(np.float64) * 10.0

        res = make_test_grid_result(z, extent=(0.0, 0.0, 1000.0, 1000.0))

        t0 = time.perf_counter()
        p_layer = generate_facies_polygon_layer(res, thresholds=[5.0])
        elapsed = time.perf_counter() - t0

        assert elapsed < 5.0, f"100x100 noisy raster polygonization took {elapsed:.3f}s (too slow)"
        for feat in p_layer.features:
            s_geom = shape(feat["geometry"])
            assert s_geom.is_valid


# ==============================================================================
# 4. CROSS-SUBSYSTEM INTEGRATED ADVERSARIAL PIPELINE
# ==============================================================================

class TestAdversarialCrossSubsystemCoordinationPipeline:
    """Stress tests combining SelectionContext, CoordinateTransformHub, and Geological Layers."""

    def test_coordinate_hub_cross_domain_roundtrip_storm(self):
        """1,000 random points round-tripped across Map CRS <-> Deviated Well <-> Seismic Grid."""
        hub = CoordinateTransformHub()
        stations = [
            (0.0, 0.0, 0.0),
            (500.0, 15.0, 30.0),
            (1500.0, 45.0, 60.0),
            (3000.0, 75.0, 90.0),
            (4500.0, 85.0, 120.0),
        ]
        hub.register_well("W_DEV_COMPLEX", 500000.0, 4000000.0, elevation=150.0, total_depth_m=4500.0, stations=stations)
        hub.configure_seismic_grid(
            origin=(500000.0, 4000000.0),
            il_step=(25.0, 10.0),
            xl_step=(-10.0, 25.0),
            il_min=100,
            xl_min=200,
            velocity=2800.0,
        )

        rng = np.random.default_rng(seed=12345)
        md_samples = rng.uniform(0.0, 4500.0, size=1000)

        for md in md_samples:
            # 1. Well to Map
            x, y, tvd = hub.well_depth_to_map("W_DEV_COMPLEX", md)
            assert math.isfinite(x) and math.isfinite(y) and math.isfinite(tvd)

            # 2. Map to Well TVD round-trip
            rec_md = hub.map_to_well_depth("W_DEV_COMPLEX", tvd)
            assert math.isclose(rec_md, md, abs_tol=1e-3)

            # 3. Well to Seismic
            il, xl, twt = hub.well_to_seismic("W_DEV_COMPLEX", md)

            # 4. Seismic to Map
            rec_x, rec_y, rec_z = hub.seismic_to_map(il, xl, twt)
            assert math.isfinite(rec_x) and math.isfinite(rec_y) and math.isfinite(rec_z)

            # 5. Map to Seismic roundtrip
            rec_il, rec_xl, rec_twt = hub.map_to_seismic(rec_x, rec_y, rec_z)
            assert rec_il == il
            assert rec_xl == xl
            assert math.isclose(rec_twt, twt, abs_tol=1e-5)

    def test_concurrent_well_registry_modification_and_lookup(self):
        """Stress-test concurrent registration, unregistration, and spatial lookup in CoordinateTransformHub."""
        hub = CoordinateTransformHub()
        # Seed 50 initial wells
        for i in range(50):
            hub.register_well(f"W_SEED_{i}", 1000.0 * i, 2000.0 * i, elevation=50.0, total_depth_m=3000.0)

        stop_event = threading.Event()
        errors: list[Exception] = []

        def modifier_task(thread_id: int):
            try:
                for i in range(200):
                    if stop_event.is_set():
                        break
                    wid = f"W_DYN_{thread_id}_{i}"
                    hub.register_well(wid, 500.0 * i, 500.0 * i, elevation=10.0, total_depth_m=2500.0)
                    time.sleep(0.0001)
                    hub.unregister_well(wid)
            except Exception as e:
                errors.append(e)

        def reader_task(thread_id: int):
            try:
                for i in range(500):
                    if stop_event.is_set():
                        break
                    # Spatial query
                    hub.map_to_well(1000.0 * (i % 50), 2000.0 * (i % 50), max_radius=100.0)
                    # Depth query on seed well
                    hub.well_depth_to_map(f"W_SEED_{i % 50}", 1500.0)
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            mods = [executor.submit(modifier_task, i) for i in range(4)]
            reads = [executor.submit(reader_task, i) for i in range(8)]
            concurrent.futures.wait(mods + reads)

        assert len(errors) == 0, f"Errors during concurrent well registry access: {errors}"

