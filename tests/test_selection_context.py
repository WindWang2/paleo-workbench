"""Unit tests for SelectionContext and SelectionState (Feature F16)."""

from __future__ import annotations

import concurrent.futures
import time
import pytest
from PySide6.QtCore import QObject

from paleo_workbench.viz import SelectionContext, SelectionState


class TestSelectionState:
    """Test suite for the immutable SelectionState dataclass."""

    def test_default_values(self):
        state = SelectionState()
        assert state.active_well_id is None
        assert state.selected_well_ids == ()
        assert state.depth_range is None
        assert state.normalized_depth_range is None
        assert state.seismic_cursor is None
        assert state.source_widget_id is None
        assert isinstance(state.timestamp, float)
        assert state.custom_attributes == {}

    def test_immutability(self):
        state = SelectionState(
            active_well_id="W-01",
            selected_well_ids=("W-01", "W-02"),
            depth_range=(1000.0, 2000.0),
            seismic_cursor=(100, 200, 300.0),
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            state.active_well_id = "W-02"  # type: ignore

    def test_normalized_depth_range(self):
        state_none = SelectionState(depth_range=None)
        assert state_none.normalized_depth_range is None

        state_normal = SelectionState(depth_range=(1000.0, 2500.0))
        assert state_normal.normalized_depth_range == (1000.0, 2500.0)

        state_inverted = SelectionState(depth_range=(3000.0, 1500.0))
        assert state_inverted.normalized_depth_range == (1500.0, 3000.0)


class TestSelectionContext:
    """Test suite for SelectionContext state bus and Qt signaling."""

    def test_initial_state(self):
        ctx = SelectionContext()
        assert ctx.active_well_id is None
        assert ctx.selected_well_ids == []
        assert ctx.depth_range is None
        assert ctx.normalized_depth_range is None
        assert ctx.seismic_cursor is None
        assert ctx.source_widget_id is None
        assert isinstance(ctx.timestamp, float)
        assert ctx.custom_attributes == {}

    def test_partial_updates(self):
        ctx = SelectionContext()

        # Update only active_well_id
        ctx.update(active_well_id="WELL-A")
        assert ctx.active_well_id == "WELL-A"
        assert ctx.selected_well_ids == []
        assert ctx.depth_range is None

        # Update depth_range and source_widget_id without overwriting active_well_id
        ctx.update(depth_range=(500.0, 1200.0), source_widget_id="map_canvas")
        assert ctx.active_well_id == "WELL-A"
        assert ctx.depth_range == (500.0, 1200.0)
        assert ctx.source_widget_id == "map_canvas"

        # Update seismic_cursor
        ctx.update(seismic_cursor=(105, 215, 450.0))
        assert ctx.active_well_id == "WELL-A"
        assert ctx.depth_range == (500.0, 1200.0)
        assert ctx.seismic_cursor == (105, 215, 450.0)

    def test_explicit_none_clearing_via_sentinel(self):
        """Verify that passing None explicitly clears fields instead of skipping them."""
        ctx = SelectionContext(
            active_well_id="WELL-A",
            selected_well_ids=["WELL-A", "WELL-B"],
            depth_range=(100.0, 500.0),
            seismic_cursor=(10, 20, 30.0),
            source_widget_id="test_widget",
            custom_attributes={"key": "val"},
        )

        # Clear active_well_id by passing None
        ctx.update(active_well_id=None)
        assert ctx.active_well_id is None
        assert ctx.selected_well_ids == ["WELL-A", "WELL-B"]
        assert ctx.depth_range == (100.0, 500.0)

        # Clear depth_range by passing None
        ctx.update(depth_range=None)
        assert ctx.depth_range is None
        assert ctx.normalized_depth_range is None
        assert ctx.seismic_cursor == (10, 20, 30.0)

        # Clear seismic_cursor by passing None
        ctx.update(seismic_cursor=None)
        assert ctx.seismic_cursor is None

        # Clear selected_well_ids by passing empty list or None
        ctx.update(selected_well_ids=None)
        assert ctx.selected_well_ids == []

        # Clear custom attributes
        ctx.update(custom_attributes=None)
        assert ctx.custom_attributes == {}

    def test_clear_method(self):
        ctx = SelectionContext(
            active_well_id="W-1",
            selected_well_ids=["W-1", "W-2"],
            depth_range=(1000.0, 2000.0),
            seismic_cursor=(1, 2, 3.0),
            source_widget_id="view_1",
            custom_attributes={"prop": 42},
        )
        ctx.clear(source_widget_id="reset_button")

        assert ctx.active_well_id is None
        assert ctx.selected_well_ids == []
        assert ctx.depth_range is None
        assert ctx.seismic_cursor is None
        assert ctx.source_widget_id == "reset_button"
        assert ctx.custom_attributes == {}

    def test_snapshot_returns_independent_immutable_state(self):
        ctx = SelectionContext(
            active_well_id="W-01",
            selected_well_ids=["W-01", "W-02"],
            depth_range=(2000.0, 1000.0),
            seismic_cursor=(10, 20, 30.0),
            source_widget_id="widget_a",
            custom_attributes={"layer": "wells"},
        )
        snap = ctx.snapshot()

        assert isinstance(snap, SelectionState)
        assert snap.active_well_id == "W-01"
        assert snap.selected_well_ids == ("W-01", "W-02")
        assert snap.depth_range == (2000.0, 1000.0)
        assert snap.normalized_depth_range == (1000.0, 2000.0)
        assert snap.seismic_cursor == (10, 20, 30.0)
        assert snap.source_widget_id == "widget_a"
        assert snap.custom_attributes == {"layer": "wells"}

        # Modifying ctx does not alter previous snapshot
        ctx.update(active_well_id="W-99", depth_range=(50.0, 100.0))
        assert snap.active_well_id == "W-01"
        assert snap.depth_range == (2000.0, 1000.0)

    def test_multi_listener_echo_suppression(self):
        ctx = SelectionContext()
        events_view_a: list[str | None] = []
        events_view_b: list[str | None] = []
        events_view_c: list[str | None] = []

        def on_view_a(c: SelectionContext):
            if c.source_widget_id != "view_a":
                events_view_a.append(c.active_well_id)

        def on_view_b(c: SelectionContext):
            if c.source_widget_id != "view_b":
                events_view_b.append(c.active_well_id)

        def on_view_c(c: SelectionContext):
            if c.source_widget_id != "view_c":
                events_view_c.append(c.active_well_id)

        ctx.selection_changed.connect(on_view_a)
        ctx.selection_changed.connect(on_view_b)
        ctx.selection_changed.connect(on_view_c)

        # Trigger from view_a
        ctx.update(active_well_id="WELL_1", source_widget_id="view_a")
        assert events_view_a == []
        assert events_view_b == ["WELL_1"]
        assert events_view_c == ["WELL_1"]

        # Trigger from view_b
        ctx.update(active_well_id="WELL_2", source_widget_id="view_b")
        assert events_view_a == ["WELL_2"]
        assert events_view_b == ["WELL_1"]  # unchanged
        assert events_view_c == ["WELL_1", "WELL_2"]

        # Global event (None source)
        ctx.update(active_well_id="GLOBAL", source_widget_id=None)
        assert events_view_a == ["WELL_2", "GLOBAL"]
        assert events_view_b == ["WELL_1", "GLOBAL"]
        assert events_view_c == ["WELL_1", "WELL_2", "GLOBAL"]

    def test_concurrent_multithreaded_updates(self):
        ctx = SelectionContext()
        errors: list[Exception] = []

        def worker_task(thread_id: int):
            try:
                for i in range(100):
                    ctx.update(
                        active_well_id=f"T{thread_id}-W{i}",
                        depth_range=(float(i * 10), float(i * 10 + 50)),
                        source_widget_id=f"thread_{thread_id}",
                    )
                    snap = ctx.snapshot()
                    assert snap.timestamp > 0
            except Exception as exc:
                errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_task, tid) for tid in range(8)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0
        final_snap = ctx.snapshot()
        assert final_snap.active_well_id is not None
        assert final_snap.depth_range is not None
