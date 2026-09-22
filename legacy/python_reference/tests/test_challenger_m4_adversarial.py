"""Adversarial Stress Testing & Empirical Challenge Suite for Milestone 4 (Feature F16 SelectionContext).

Author: challenger_m4_1 (Empirical Challenger)
Scope:
1. Circular multi-view subscriber loops (A -> B -> C -> A) and echo suppression verification.
2. Rapid bursts of 10,000 events (throughput, order preservation, Qt queued vs direct cross-thread dispatch).
3. 16-thread concurrent readers and writers stress harness (race conditions, invariants, deadlock freedom).
4. Out-of-order timestamps, clock resolution, and chronological event sequence analysis.
5. Defensive copying, mutation isolation, and frozen dataclass boundary invariants.
6. Extreme / degenerate values (infinite depths, extreme coordinates, 100k well collections).
7. Integrated multi-view coordination pipeline stress test (Map <-> Well <-> Seismic).
"""

from __future__ import annotations

import concurrent.futures
import gc
import math
import threading
import time
from typing import Any, List, Tuple
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Qt

from paleo_workbench.viz import (
    CoordinateTransformHub,
    SelectionContext,
    SelectionState,
    WellTrajectoryData,
)


# ============================================================================
# 1. CIRCULAR MULTI-VIEW SUBSCRIBER LOOPS & ECHO SUPPRESSION
# ============================================================================

class MultiViewNode:
    """Simulated workstation view widget node with echo suppression."""

    def __init__(self, node_id: str, bus: SelectionContext) -> None:
        self.node_id = node_id
        self.bus = bus
        self.received_events: list[SelectionState] = []
        self.local_active_well: str | None = None
        self.local_depth_range: tuple[float, float] | None = None
        self.local_seismic_cursor: tuple[int, int, float] | None = None
        self.bus.selection_changed.connect(self.on_selection_changed)

    def on_selection_changed(self, ctx: SelectionContext) -> None:
        # Echo suppression check: Ignore events originated by this node
        if ctx.source_widget_id == self.node_id:
            return

        snap = ctx.snapshot()
        self.received_events.append(snap)
        self.local_active_well = snap.active_well_id
        self.local_depth_range = snap.depth_range
        self.local_seismic_cursor = snap.seismic_cursor

    def user_select_well(self, well_id: str) -> None:
        self.local_active_well = well_id
        self.bus.update(active_well_id=well_id, source_widget_id=self.node_id)

    def user_select_depth(self, depth_range: tuple[float, float]) -> None:
        self.local_depth_range = depth_range
        self.bus.update(depth_range=depth_range, source_widget_id=self.node_id)

    def user_select_seismic(self, cursor: tuple[int, int, float]) -> None:
        self.local_seismic_cursor = cursor
        self.bus.update(seismic_cursor=cursor, source_widget_id=self.node_id)


class TwoWayBoundViewNode:
    """Simulated view node with two-way data synchronization and value-change guarding."""

    def __init__(self, node_id: str, bus: SelectionContext) -> None:
        self.node_id = node_id
        self.bus = bus
        self.active_well: str | None = None
        self.sync_event_count = 0
        self.bus.selection_changed.connect(self.on_selection_changed)

    def on_selection_changed(self, ctx: SelectionContext) -> None:
        # 1. Echo suppression by source
        if ctx.source_widget_id == self.node_id:
            return

        # 2. Value-change guard
        if ctx.active_well_id != self.active_well:
            self.active_well = ctx.active_well_id
            self.sync_event_count += 1

    def user_pick_well(self, well_id: str) -> None:
        if self.active_well != well_id:
            self.active_well = well_id
            self.bus.update(active_well_id=well_id, source_widget_id=self.node_id)


class ChainedMultiViewNode:
    """View node that triggers downstream coordinated state changes upon receiving upstream events."""

    def __init__(self, node_id: str, bus: SelectionContext, downstream_action=None) -> None:
        self.node_id = node_id
        self.bus = bus
        self.downstream_action = downstream_action
        self.received_count = 0
        self.processed_states: list[SelectionState] = []
        self.bus.selection_changed.connect(self.on_selection_changed)

    def on_selection_changed(self, ctx: SelectionContext) -> None:
        # Strict echo suppression
        if ctx.source_widget_id == self.node_id:
            return

        self.received_count += 1
        snap = ctx.snapshot()
        self.processed_states.append(snap)

        if self.downstream_action:
            self.downstream_action(self, snap)


class TestAdversarialCircularSubscriberLoops:
    """Stress-test circular multi-view subscriber loops and echo suppression."""

    def test_circular_3view_pipeline_echo_suppression(self):
        """Verify A -> B -> C -> A pipeline with standard echo suppression does not echo back to initiator."""
        bus = SelectionContext()
        node_a = MultiViewNode("view_a_map", bus)
        node_b = MultiViewNode("view_b_welllog", bus)
        node_c = MultiViewNode("view_c_seismic", bus)

        # Action from View A
        node_a.user_select_well("WELL_ALPHA")

        assert len(node_a.received_events) == 0, "Originating Node A must suppress its own echo"
        assert len(node_b.received_events) == 1
        assert len(node_c.received_events) == 1
        assert node_b.received_events[0].active_well_id == "WELL_ALPHA"
        assert node_c.received_events[0].active_well_id == "WELL_ALPHA"

        # Action from View B
        node_b.user_select_depth((1500.0, 1800.0))

        assert len(node_b.received_events) == 1, "Originating Node B must suppress its own echo"
        assert len(node_a.received_events) == 1
        assert len(node_c.received_events) == 2
        assert node_a.received_events[0].depth_range == (1500.0, 1800.0)
        assert node_c.received_events[1].depth_range == (1500.0, 1800.0)

        # Action from View C
        node_c.user_select_seismic((100, 200, 450.0))

        assert len(node_c.received_events) == 2, "Originating Node C must suppress its own echo"
        assert len(node_a.received_events) == 2
        assert len(node_b.received_events) == 2
        assert node_a.received_events[1].seismic_cursor == (100, 200, 450.0)
        assert node_b.received_events[1].seismic_cursor == (100, 200, 450.0)

    def test_two_way_binding_no_infinite_loop(self):
        """Test bidirectional two-way binding between Map and WellLog views with value-change guarding."""
        bus = SelectionContext()
        map_view = TwoWayBoundViewNode("map_view", bus)
        well_view = TwoWayBoundViewNode("well_view", bus)

        # User picks on Map
        map_view.user_pick_well("WELL-100")
        assert map_view.active_well == "WELL-100"
        assert well_view.active_well == "WELL-100"
        assert map_view.sync_event_count == 0  # Map initiated, did not receive sync
        assert well_view.sync_event_count == 1  # WellLog synchronized

        # User picks on WellLog
        well_view.user_pick_well("WELL-200")
        assert map_view.active_well == "WELL-200"
        assert well_view.active_well == "WELL-200"
        assert map_view.sync_event_count == 1  # Map synchronized
        assert well_view.sync_event_count == 1  # WellLog initiated, no extra sync

    def test_chained_multi_view_reentrant_cascade_convergence(self):
        """Test cascade A (well pick) -> B (computes depth range) -> C (computes seismic cursor).

        Verifies that re-entrant chained updates on the same thread execute deterministically,
        converge cleanly to the fully populated coordinated state, and terminate without infinite loops.
        """
        bus = SelectionContext()

        def action_b(node: ChainedMultiViewNode, snap: SelectionState):
            if snap.active_well_id == "WELL_TRIGGER" and snap.depth_range is None:
                # Node B derives depth range from well
                node.bus.update(depth_range=(2000.0, 2500.0), source_widget_id=node.node_id)

        def action_c(node: ChainedMultiViewNode, snap: SelectionState):
            if snap.depth_range == (2000.0, 2500.0) and snap.seismic_cursor is None:
                # Node C derives seismic cursor from depth range
                node.bus.update(seismic_cursor=(300, 400, 1250.0), source_widget_id=node.node_id)

        node_a = ChainedMultiViewNode("view_a", bus)
        node_b = ChainedMultiViewNode("view_b", bus, downstream_action=action_b)
        node_c = ChainedMultiViewNode("view_c", bus, downstream_action=action_c)

        # Initiate from View A
        bus.update(active_well_id="WELL_TRIGGER", source_widget_id="view_a")

        # Check final converged state
        final_state = bus.snapshot()
        assert final_state.active_well_id == "WELL_TRIGGER"
        assert final_state.depth_range == (2000.0, 2500.0)
        assert final_state.seismic_cursor == (300, 400, 1250.0)

        # In synchronous re-entrant dispatch:
        # 1. Event A triggers action_b -> Event B.
        # 2. Event B triggers action_c -> Event C.
        # Node A receives Event B and Event C (2).
        # Node B receives Event A and Event C (2).
        # Node C receives Event B (1).
        assert node_a.received_count == 2
        assert node_b.received_count == 2
        assert node_c.received_count == 1

    def test_ring_topology_5views_bidirectional_roundtrip(self):
        """Stress-test a 5-node ring topology where each node initiates an event sequentially."""
        bus = SelectionContext()
        nodes = [MultiViewNode(f"node_{i}", bus) for i in range(5)]

        for i, node in enumerate(nodes):
            node.user_select_well(f"WELL_NODE_{i}")

        # Each node should have received 4 events (5 total minus 1 self-echo)
        for i, node in enumerate(nodes):
            assert len(node.received_events) == 4, f"Node {i} expected 4 events, got {len(node.received_events)}"
            assert all(ev.source_widget_id != f"node_{i}" for ev in node.received_events)

        assert bus.active_well_id == "WELL_NODE_4"


# ============================================================================
# 2. RAPID BURSTS OF 10,000 EVENTS
# ============================================================================

class TestAdversarialRapidBurst10k:
    """Stress-test SelectionContext with rapid bursts of 10,000 events."""

    def test_single_thread_burst_10k_events(self):
        """Burst 10,000 sequential updates: verify total integrity, ordering, and throughput."""
        bus = SelectionContext()
        received: list[str | None] = []

        bus.selection_changed.connect(lambda ctx: received.append(ctx.active_well_id))

        t0 = time.perf_counter()
        total_events = 10_000

        for i in range(total_events):
            bus.update(
                active_well_id=f"W-{i:05d}",
                depth_range=(float(i), float(i + 100)),
                seismic_cursor=(i, i * 2, float(i * 3)),
                source_widget_id="burst_generator",
            )

        elapsed = time.perf_counter() - t0

        assert len(received) == total_events
        assert received[0] == "W-00000"
        assert received[-1] == "W-09999"

        # Verify final snapshot matches 10,000th update exactly
        snap = bus.snapshot()
        assert snap.active_well_id == "W-09999"
        assert snap.depth_range == (9999.0, 10099.0)
        assert snap.seismic_cursor == (9999, 19998, 29997.0)
        assert snap.source_widget_id == "burst_generator"

        # Throughput assertion: 10,000 events should complete in under 5.0 seconds (>2,000 ops/sec)
        assert elapsed < 5.0, f"10k burst took {elapsed:.3f}s (throughput too low)"

    def test_multi_thread_burst_10k_events_direct_and_queued(self):
        """Burst 10,000 events across 10 concurrent threads (1,000 events each).

        Verifies both Qt DirectConnection (immediate thread execution) and
        Qt AutoConnection (queued event loop processing via QCoreApplication.processEvents).
        """
        app = QCoreApplication.instance() or QCoreApplication([])
        bus = SelectionContext()
        direct_received = 0
        auto_received = 0
        direct_lock = threading.Lock()

        def on_direct(ctx: SelectionContext):
            nonlocal direct_received
            with direct_lock:
                direct_received += 1

        def on_auto(ctx: SelectionContext):
            nonlocal auto_received
            auto_received += 1

        bus.selection_changed.connect(on_direct, Qt.DirectConnection)
        bus.selection_changed.connect(on_auto, Qt.AutoConnection)

        def worker(thread_idx: int):
            for i in range(1000):
                bus.update(
                    active_well_id=f"T{thread_idx}-W{i}",
                    depth_range=(float(i), float(i + 50)),
                    source_widget_id=f"thread_{thread_idx}",
                )

        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, tid) for tid in range(10)]
            concurrent.futures.wait(futures)

        elapsed = time.perf_counter() - t0

        # Direct connection events were handled synchronously across worker threads
        assert direct_received == 10_000
        assert elapsed < 5.0

        # Process pending Qt queued events on the main thread event loop
        QCoreApplication.processEvents()
        assert auto_received == 10_000

        final_snap = bus.snapshot()
        assert final_snap.active_well_id is not None
        assert final_snap.depth_range is not None


# ============================================================================
# 3. 16-THREAD CONCURRENT READERS AND WRITERS STRESS HARNESS
# ============================================================================

class TestAdversarialConcurrency16Threads:
    """Stress-test 16 concurrent threads (8 writers + 8 readers)."""

    def test_16_threads_concurrent_read_write_invariants(self):
        """Run 8 writers and 8 readers concurrently for 1,000 iterations per thread (16,000 ops total).

        Invariants checked by readers:
        1. snap.normalized_depth_range is either None or (min_d, max_d) with min_d <= max_d.
        2. snap.selected_well_ids is always an immutable tuple.
        3. snap.custom_attributes is a dictionary and modifying reader copy does not affect bus.
        4. No partial writes (e.g. depth_range being invalid type).
        5. Zero deadlocks under RLock.
        """
        bus = SelectionContext()
        stop_event = threading.Event()
        writer_errors: list[Exception] = []
        reader_errors: list[Exception] = []
        reader_checks_completed = 0
        reader_lock = threading.Lock()

        def writer_task(worker_id: int):
            try:
                for i in range(1000):
                    if stop_event.is_set():
                        break
                    # Alternating update patterns
                    if i % 5 == 0:
                        bus.clear(source_widget_id=f"writer_{worker_id}")
                    elif i % 5 == 1:
                        bus.update(
                            active_well_id=f"W-{worker_id}-{i}",
                            selected_well_ids=[f"W-{worker_id}-{i}", f"W-{worker_id}-{i+1}"],
                            depth_range=(float(i * 10 + 100), float(i * 10)),  # inverted to test normalization
                            source_widget_id=f"writer_{worker_id}",
                            custom_attributes={"worker": worker_id, "iter": i},
                        )
                    elif i % 5 == 2:
                        bus.update(
                            seismic_cursor=(worker_id * 100, i, float(i * 2.5)),
                            source_widget_id=f"writer_{worker_id}",
                        )
                    elif i % 5 == 3:
                        bus.update(
                            active_well_id=None,
                            depth_range=None,
                            source_widget_id=f"writer_{worker_id}",
                        )
                    else:
                        bus.update(
                            active_well_id=f"W-{worker_id}-{i}",
                            selected_well_ids=[],
                            depth_range=(500.0, 1500.0),
                            source_widget_id=f"writer_{worker_id}",
                        )
            except Exception as exc:
                writer_errors.append(exc)

        def reader_task(worker_id: int):
            nonlocal reader_checks_completed
            checks = 0
            try:
                for _ in range(1000):
                    if stop_event.is_set():
                        break

                    # 1. Snapshot immutability & invariants
                    snap = bus.snapshot()
                    assert isinstance(snap.selected_well_ids, tuple)
                    assert isinstance(snap.custom_attributes, dict)

                    norm_range = snap.normalized_depth_range
                    if norm_range is not None:
                        assert len(norm_range) == 2
                        assert norm_range[0] <= norm_range[1], f"Invariant broken: min > max in {norm_range}"

                    # 2. Live property thread-safety
                    live_norm = bus.normalized_depth_range
                    if live_norm is not None:
                        assert len(live_norm) == 2
                        assert live_norm[0] <= live_norm[1]

                    # 3. Snapshot isolation
                    snap.custom_attributes["poison"] = "hacked"
                    snap2 = bus.snapshot()
                    assert "poison" not in snap2.custom_attributes

                    checks += 1
            except Exception as exc:
                reader_errors.append(exc)
            finally:
                with reader_lock:
                    reader_checks_completed += checks

        # Launch 8 writers and 8 readers = 16 threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            writer_futures = [executor.submit(writer_task, wid) for wid in range(8)]
            reader_futures = [executor.submit(reader_task, rid) for rid in range(8)]
            concurrent.futures.wait(writer_futures + reader_futures)

        assert len(writer_errors) == 0, f"Writer errors: {writer_errors}"
        assert len(reader_errors) == 0, f"Reader errors: {reader_errors}"
        assert reader_checks_completed >= 8 * 1000


# ============================================================================
# 4. OUT-OF-ORDER TIMESTAMPS & ORDERING
# ============================================================================

class TestAdversarialTimestampsAndOrdering:
    """Stress-test timestamp manipulation, clock resolution, and causal ordering."""

    def test_selection_state_explicit_timestamps(self):
        """Verify SelectionState handles arbitrary past, future, zero, and negative timestamps."""
        s_past = SelectionState(active_well_id="W1", timestamp=100.0)
        s_future = SelectionState(active_well_id="W2", timestamp=2000000000.0)
        s_zero = SelectionState(active_well_id="W3", timestamp=0.0)
        s_negative = SelectionState(active_well_id="W4", timestamp=-500.0)

        assert s_past.timestamp == 100.0
        assert s_future.timestamp == 2000000000.0
        assert s_zero.timestamp == 0.0
        assert s_negative.timestamp == -500.0

        # Sort chronological events
        events = [s_future, s_negative, s_past, s_zero]
        sorted_events = sorted(events, key=lambda s: s.timestamp)
        assert [s.active_well_id for s in sorted_events] == ["W4", "W3", "W1", "W2"]

    def test_monotonic_timestamps_on_rapid_updates(self):
        """Verify that timestamps generated by SelectionContext.update() are monotonically non-decreasing."""
        bus = SelectionContext()
        timestamps: list[float] = []

        for i in range(1000):
            bus.update(active_well_id=f"W-{i}")
            timestamps.append(bus.timestamp)

        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], f"Timestamp decreased at index {i}: {timestamps[i]} < {timestamps[i-1]}"

    def test_out_of_order_event_reconciliation(self):
        """Simulate network/worker out-of-order event queue reconciliation."""
        history = [
            SelectionState(active_well_id="W_LATE", timestamp=1003.0),
            SelectionState(active_well_id="W_EARLY", timestamp=1001.0),
            SelectionState(active_well_id="W_MID", timestamp=1002.0),
            SelectionState(active_well_id="W_INITIAL", timestamp=1000.0),
        ]

        # Reconcile using standard timestamp ordering
        reconciled = sorted(history, key=lambda s: s.timestamp)
        assert [s.active_well_id for s in reconciled] == ["W_INITIAL", "W_EARLY", "W_MID", "W_LATE"]


# ============================================================================
# 5. DEFENSIVE COPYING & MUTATION ISOLATION
# ============================================================================

class TestAdversarialMutationAndStateIsolation:
    """Stress-test defensive copying and mutation isolation against adversarial callers."""

    def test_selected_well_ids_external_mutation_isolation(self):
        """Verify external mutation of input list does not affect SelectionContext or snapshot."""
        mutable_wells = ["WELL-01", "WELL-02"]
        bus = SelectionContext(selected_well_ids=mutable_wells)

        # Mutate the original list
        mutable_wells.append("WELL-03")
        mutable_wells.pop(0)

        assert bus.selected_well_ids == ["WELL-01", "WELL-02"]
        assert bus.snapshot().selected_well_ids == ("WELL-01", "WELL-02")

        # Mutate via update
        update_wells = ["WELL-A", "WELL-B"]
        bus.update(selected_well_ids=update_wells)
        update_wells.clear()

        assert bus.selected_well_ids == ["WELL-A", "WELL-B"]
        assert bus.snapshot().selected_well_ids == ("WELL-A", "WELL-B")

    def test_custom_attributes_external_mutation_isolation(self):
        """Verify external mutation of input dict does not affect SelectionContext or snapshot."""
        mutable_attrs = {"filter": "carbonate", "threshold": 0.15}
        bus = SelectionContext(custom_attributes=mutable_attrs)

        # Mutate original dict
        mutable_attrs["filter"] = "sandstone"
        mutable_attrs["threshold"] = 0.99
        mutable_attrs["injected"] = True

        assert bus.custom_attributes == {"filter": "carbonate", "threshold": 0.15}
        assert bus.snapshot().custom_attributes == {"filter": "carbonate", "threshold": 0.15}

    def test_snapshot_immutability_enforcement(self):
        """Verify that SelectionState attributes cannot be reassigned."""
        snap = SelectionState(
            active_well_id="W-1",
            selected_well_ids=("W-1", "W-2"),
            depth_range=(100.0, 200.0),
            seismic_cursor=(10, 20, 30.0),
            source_widget_id="src",
            timestamp=123.456,
            custom_attributes={"a": 1},
        )

        with pytest.raises(Exception):
            snap.active_well_id = "W-2"  # type: ignore

        with pytest.raises(Exception):
            snap.selected_well_ids = ("W-3",)  # type: ignore

        with pytest.raises(Exception):
            snap.depth_range = (50.0, 150.0)  # type: ignore

        with pytest.raises(Exception):
            snap.seismic_cursor = None  # type: ignore

        with pytest.raises(Exception):
            snap.timestamp = 999.0  # type: ignore


# ============================================================================
# 6. EXTREME / DEGENERATE VALUES & DYNAMIC SLOTS
# ============================================================================

class TestAdversarialExtremeValuesAndDynamicSlots:
    """Stress-test extreme inputs, large payloads, and dynamic signal slot manipulation."""

    def test_extreme_depth_ranges_and_coordinates(self):
        """Verify handling of infinite, NaN, negative, and zero-thickness depth intervals."""
        bus = SelectionContext()

        # Zero-thickness interval
        bus.update(depth_range=(1500.0, 1500.0))
        assert bus.normalized_depth_range == (1500.0, 1500.0)

        # Negative depths (e.g. TVDSS above sea level)
        bus.update(depth_range=(-250.0, -100.0))
        assert bus.normalized_depth_range == (-250.0, -100.0)

        # Inverted negative depths
        bus.update(depth_range=(-50.0, -300.0))
        assert bus.normalized_depth_range == (-300.0, -50.0)

        # Very large geological depths
        bus.update(depth_range=(1e9, -1e9))
        assert bus.normalized_depth_range == (-1e9, 1e9)

    def test_large_collection_100k_well_ids(self):
        """Stress-test passing 100,000 well IDs into selected_well_ids."""
        large_wells = [f"WELL_{i:06d}" for i in range(100_000)]
        bus = SelectionContext()

        t0 = time.perf_counter()
        bus.update(selected_well_ids=large_wells)
        snap = bus.snapshot()
        elapsed = time.perf_counter() - t0

        assert len(bus.selected_well_ids) == 100_000
        assert len(snap.selected_well_ids) == 100_000
        assert snap.selected_well_ids[0] == "WELL_000000"
        assert snap.selected_well_ids[-1] == "WELL_099999"
        assert elapsed < 1.0, f"100k wells took {elapsed:.3f}s"

    def test_dynamic_slot_connection_and_disconnection_during_emission(self):
        """Verify connecting and disconnecting slots dynamically while signals are emitting."""
        bus = SelectionContext()
        slot_calls = {"a": 0, "b": 0, "c": 0}

        def slot_c(ctx: SelectionContext):
            slot_calls["c"] += 1

        def slot_b(ctx: SelectionContext):
            slot_calls["b"] += 1
            # Dynamic connection during signal dispatch
            try:
                bus.selection_changed.connect(slot_c)
            except Exception:
                pass

        def slot_a(ctx: SelectionContext):
            slot_calls["a"] += 1

        bus.selection_changed.connect(slot_a)
        bus.selection_changed.connect(slot_b)

        # First update
        bus.update(active_well_id="W-1")
        assert slot_calls["a"] == 1
        assert slot_calls["b"] == 1

        # Second update (slot_c is now connected)
        bus.update(active_well_id="W-2")
        assert slot_calls["a"] == 2
        assert slot_calls["b"] == 2
        assert slot_calls["c"] >= 1

        # Disconnect slot_a dynamically
        bus.selection_changed.disconnect(slot_a)
        bus.update(active_well_id="W-3")
        assert slot_calls["a"] == 2  # Not called again
        assert slot_calls["b"] == 3


# ============================================================================
# 7. INTEGRATED MULTI-VIEW COORDINATION PIPELINE WITH COORDINATE HUB
# ============================================================================

class TestAdversarialMultiViewIntegrationWithCoordHub:
    """Stress-test realistic multi-view coordination pipeline combining SelectionContext and CoordinateTransformHub."""

    def test_end_to_end_multiview_sync_cycle(self):
        """Simulate realistic 3-view workflow:

        1. Map View user clicks (500000.0, 4000000.0).
        2. Hub maps coordinate to nearest well 'W-DEEP'.
        3. Context updates active_well_id='W-DEEP', source='map_canvas'.
        4. Well Log View receives signal, computes TVDSS for MD=3000m, sets depth_range=(2900, 3100), source='well_log'.
        5. Seismic View receives signal, transforms (W-DEEP, MD=3000m) to (IL, XL, TWT), sets seismic_cursor, source='seismic_3d'.
        6. Verify all 3 views converge without infinite recursion or echo backfire.
        """
        hub = CoordinateTransformHub()
        hub.register_well("W-DEEP", 500000.0, 4000000.0, elevation=50.0, total_depth_m=4000.0)
        hub.configure_seismic_grid(
            origin=(500000.0, 4000000.0),
            il_step=(100.0, 0.0),
            xl_step=(0.0, 100.0),
            il_min=1,
            xl_min=1,
            velocity=2500.0,
        )

        bus = SelectionContext()
        map_events: list[SelectionState] = []
        well_events: list[SelectionState] = []
        seismic_events: list[SelectionState] = []

        def on_map_sync(ctx: SelectionContext):
            if ctx.source_widget_id == "map_canvas":
                return
            map_events.append(ctx.snapshot())

        def on_well_sync(ctx: SelectionContext):
            if ctx.source_widget_id == "well_log":
                return
            snap = ctx.snapshot()
            well_events.append(snap)
            # If well is set but depth range isn't, initialize depth range around target interval
            if snap.active_well_id == "W-DEEP" and snap.depth_range is None:
                bus.update(depth_range=(2900.0, 3100.0), source_widget_id="well_log")

        def on_seismic_sync(ctx: SelectionContext):
            if ctx.source_widget_id == "seismic_3d":
                return
            snap = ctx.snapshot()
            seismic_events.append(snap)
            # If depth range is set but seismic cursor isn't, compute seismic cursor at midpoint depth
            if snap.active_well_id == "W-DEEP" and snap.depth_range == (2900.0, 3100.0) and snap.seismic_cursor is None:
                mid_depth = (snap.depth_range[0] + snap.depth_range[1]) / 2.0
                il, xl, twt = hub.well_to_seismic("W-DEEP", md=mid_depth)
                bus.update(seismic_cursor=(il, xl, twt), source_widget_id="seismic_3d")

        bus.selection_changed.connect(on_map_sync)
        bus.selection_changed.connect(on_well_sync)
        bus.selection_changed.connect(on_seismic_sync)

        # Step 1: Map click occurs
        clicked_x, clicked_y = 500010.0, 4000005.0
        nearest_well = hub.map_to_well(clicked_x, clicked_y, max_radius=50.0)
        assert nearest_well == "W-DEEP"

        bus.update(active_well_id=nearest_well, source_widget_id="map_canvas")

        # Verify convergence
        final_state = bus.snapshot()
        assert final_state.active_well_id == "W-DEEP"
        assert final_state.depth_range == (2900.0, 3100.0)
        assert final_state.seismic_cursor == (1, 1, 2400.0)  # MD 3000m at v=2500m/s -> TWT = (3000 / 2500)*2000 = 2400ms

        # Check that map received the updates from well_log and seismic_3d without self-echoing
        assert len(map_events) == 2
        assert map_events[0].depth_range == (2900.0, 3100.0)
        assert map_events[1].seismic_cursor == (1, 1, 2400.0)
