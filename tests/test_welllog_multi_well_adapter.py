"""Parity tests for multi-well WellLogEngine dual-path (#170)."""

from __future__ import annotations

import numpy as np
import pytest

from geoviz import CurveData, LithologyInterval, WellLogData

from paleo_workbench.viz import welllog_multi_well_adapter as multi


def _well(name: str, gr0: float, gr1: float, top: float = 1000.0) -> WellLogData:
    return WellLogData(
        well_name=name,
        top_depth=top,
        bottom_depth=top + 2.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[top, top + 1.0, top + 2.0],
                values=[gr0, gr1, gr0],
                display_range=(0.0, 150.0),
            )
        ],
        lithology=[
            LithologyInterval(top=top, bottom=top + 1.0, lithology="H1"),
            LithologyInterval(top=top + 1.0, bottom=top + 2.0, lithology="H2"),
        ],
    )


def test_stable_entity_ids_across_reload_and_rename_display():
    logs = [_well("A", 10, 20), _well("B", 30, 40)]
    rids = ["res-a", "res-b"]
    p1 = multi.adapt_multi_well_section(
        logs, ["Display A", "Display B"], resource_ids=rids
    )
    # Rename display labels, same resource ids → same document/marker ids.
    p2 = multi.adapt_multi_well_section(
        logs, ["A-renamed", "B-renamed"], resource_ids=rids
    )
    assert p1.document_ids == p2.document_ids
    assert p1.wells[0].curve_id == p2.wells[0].curve_id
    assert p1.wells[0].markers[0].marker_id == p2.wells[0].markers[0].marker_id


def test_reorder_changes_left_but_not_document_identity():
    logs = [_well("A", 10, 20), _well("B", 30, 40)]
    rids = ["res-a", "res-b"]
    p_ab = multi.adapt_multi_well_section(
        logs, ["A", "B"], resource_ids=rids, gap_mm=5.0, track_width_mm=30.0
    )
    p_ba = multi.adapt_multi_well_section(
        [logs[1], logs[0]],
        ["B", "A"],
        resource_ids=["res-b", "res-a"],
        gap_mm=5.0,
        track_width_mm=30.0,
    )
    id_a = p_ab.wells[0].document_id
    id_b = p_ab.wells[1].document_id
    assert {w.document_id for w in p_ba.wells} == {id_a, id_b}
    # Order index and left follow layout order.
    assert p_ab.wells[0].left_mm == 0.0
    assert p_ab.wells[1].left_mm == pytest.approx(35.0)
    assert p_ba.wells[0].resource_id == "res-b"
    assert p_ba.wells[0].left_mm == 0.0


def test_horizon_datum_shift_and_transform_points():
    logs = [_well("A", 10, 20, top=1000.0), _well("B", 30, 40, top=1050.0)]
    tops = {
        "A": [("H1", 1000.0), ("H2", 1002.0)],
        "B": [("H1", 1050.0), ("H2", 1052.0)],
    }
    plan = multi.adapt_multi_well_section(
        logs,
        ["A", "B"],
        resource_ids=["a", "b"],
        tops_by_well=tops,
        datum_mode="horizon",
        target_horizon="H1",
    )
    # Horizon flatten: shift = -marker depth
    assert plan.wells[0].depth_shift == pytest.approx(-1000.0)
    assert plan.wells[1].depth_shift == pytest.approx(-1050.0)
    assert plan.wells[0].transform_points
    assert plan.wells[1].transform_points
    # Shared display window after shift should include ~0
    assert plan.shared_display_top <= 0.0
    assert plan.shared_display_bottom >= 0.0


def test_overlays_horizon_and_band_reference_stable_ids():
    logs = [_well("A", 10, 20), _well("B", 30, 40)]
    tops = {
        "A": [("H1", 1000.0), ("H2", 1001.5)],
        "B": [("H1", 1000.5), ("H2", 1001.8)],
    }
    plan = multi.adapt_multi_well_section(
        logs, ["A", "B"], resource_ids=["a", "b"], tops_by_well=tops
    )
    kinds = {o.kind for o in plan.overlays}
    assert "horizon_line" in kinds
    assert "correlation_band" in kinds
    for o in plan.overlays:
        assert o.left_document_id == plan.wells[0].document_id
        assert o.right_document_id == plan.wells[1].document_id
        assert o.left_marker_id
        assert o.right_marker_id
        if o.kind == "correlation_band":
            assert o.left_bottom_marker_id
            assert o.right_bottom_marker_id


def test_parity_snapshot_spacing_and_links():
    logs = [_well("A", 10, 20), _well("B", 30, 40), _well("C", 50, 60)]
    tops = {
        "A": [("H1", 1000.0), ("H2", 1002.0)],
        "B": [("H1", 1000.0), ("H2", 1002.0)],
        "C": [("H1", 1000.0), ("H2", 1002.0)],
    }
    plan = multi.adapt_multi_well_section(
        logs,
        ["A", "B", "C"],
        resource_ids=["a", "b", "c"],
        tops_by_well=tops,
        spacing_px=180,
        gap_mm=8.0,
    )
    snap = multi.multi_well_parity_snapshot(plan)
    assert snap["well_count"] == 3
    assert snap["well_spacing_px"] == 180
    assert snap["gap_mm"] == 8.0
    assert snap["lefts_mm"][0] == 0.0
    assert snap["lefts_mm"][1] == pytest.approx(38.0)
    assert len(snap["overlays"]) >= 2  # horizons between pairs
    # Payload for native submit is serializable without engine.
    payload = multi.plan_to_submit_payload(plan)
    assert len(payload["wells"]) == 3
    assert payload["wells"][0]["depth"].flags.writeable is False
    assert payload["shared_top"] < payload["shared_bottom"]
    assert isinstance(payload["overlays"], list)


def test_submit_multi_well_plan_calls_native_api():
    logs = [_well("A", 10, 20), _well("B", 30, 40)]
    plan = multi.adapt_multi_well_section(
        logs, ["A", "B"], resource_ids=["a", "b"]
    )
    calls: list[dict] = []

    class FakeView:
        def submit_multi_well_section(self, payload):
            calls.append(payload)
            return {"well_count": len(payload["wells"]), "render_prepared": True}

    result = multi.submit_multi_well_plan(FakeView(), plan)
    assert len(calls) == 1
    assert result["well_count"] == 2
    assert result["overlay_count"] == len(plan.overlays)
    assert calls[0]["wells"][0]["document_id"] == plan.wells[0].document_id


def test_submit_without_bridge_raises():
    plan = multi.adapt_multi_well_section([_well("A", 1, 2)], ["A"])
    with pytest.raises(RuntimeError):
        multi.submit_multi_well_plan(object(), plan)


def test_md_mode_zero_shift():
    plan = multi.adapt_multi_well_section(
        [_well("A", 1, 2)],
        ["A"],
        resource_ids=["a"],
        datum_mode="md",
        tops_by_well={"A": [("H1", 1000.0)]},
    )
    assert plan.wells[0].depth_shift == 0.0
    assert plan.wells[0].transform_points == ()
