"""V8 M1 — mixed m/ft multi-well section unit semantics."""

from __future__ import annotations

import numpy as np
import pytest

from geoviz import CurveData, LithologyInterval, WellLogData

from paleo_workbench.viz import welllog_multi_well_adapter as multi
from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit


def _well(name: str, top: float, unit: str | None) -> WellLogDataWithDepthUnit:
    base = WellLogData(
        well_name=name,
        top_depth=top,
        bottom_depth=top + 2.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[top, top + 1.0, top + 2.0],
                values=[10.0, 20.0, 10.0],
                display_range=(0.0, 150.0),
            )
        ],
        lithology=[
            LithologyInterval(top=top, bottom=top + 1.0, lithology="H1"),
            LithologyInterval(top=top + 1.0, bottom=top + 2.0, lithology="H2"),
        ],
    )
    return WellLogDataWithDepthUnit(base, unit)


def test_mixed_units_converted_to_target_well_unit():
    logs = [_well("A", 1000.0, "m"), _well("B", 3280.84, "ft")]  # B ≈ 1000.26 m
    plan = multi.adapt_multi_well_section(
        logs, ["A", "B"], resource_ids=["a", "b"], target_well_index=0
    )
    assert len(plan.wells) == 2
    assert any("depth_units_mixed" in d for d in plan.diagnostics)
    assert any("depth_unit_converted:B:ft→m" in d for d in plan.diagnostics)
    # B's depth axis (feet numbers) became metre numbers
    depth_b = np.asarray(plan.wells[1].depth, dtype=float)
    assert depth_b[0] == pytest.approx(3280.84 * 0.3048, rel=1e-6)
    assert plan.wells[1].depth_unit == "m"


def test_mixed_units_ft_target_keeps_feet_numbers():
    logs = [_well("A", 1000.0, "m"), _well("B", 3280.0, "ft")]
    plan = multi.adapt_multi_well_section(
        logs, ["A", "B"], resource_ids=["a", "b"], target_well_index=1
    )
    assert plan.wells[0].depth_unit == "ft"
    depth_a = np.asarray(plan.wells[0].depth, dtype=float)
    assert depth_a[0] == pytest.approx(1000.0 / 0.3048, rel=1e-6)


def test_uniform_meters_untouched():
    logs = [_well("A", 1000.0, "m"), _well("B", 1050.0, "m")]
    plan = multi.adapt_multi_well_section(logs, ["A", "B"], resource_ids=["a", "b"])
    assert not any("depth_unit_converted" in d for d in plan.diagnostics)
    assert np.asarray(plan.wells[0].depth)[0] == pytest.approx(1000.0)


def test_unknown_unit_well_refused_on_foot_section():
    logs = [_well("A", 1000.0, "ft"), _well("B", 2000.0, None)]
    plan = multi.adapt_multi_well_section(
        logs, ["A", "B"], resource_ids=["a", "b"], target_well_index=0
    )
    assert len(plan.wells) == 1
    assert any(
        "well_refused_depth_unit_unknown:B" in d for d in plan.diagnostics
    )


def test_unknown_unit_well_kept_on_meter_section_v6_compromise():
    """Undeclared on a meter section keeps the labeled-m compromise (V6)."""
    logs = [_well("A", 1000.0, "m"), _well("B", 2000.0, None)]
    plan = multi.adapt_multi_well_section(logs, ["A", "B"], resource_ids=["a", "b"])
    assert len(plan.wells) == 2
    assert not any("well_refused" in d for d in plan.diagnostics)


def test_external_meter_tops_converted_on_foot_section():
    logs = [_well("A", 3280.0, "ft")]
    tops = {"A": [("H1", 1000.0)]}  # correlation table is metre-domain
    plan = multi.adapt_multi_well_section(
        logs, ["A"], resource_ids=["a"], tops_by_well=tops
    )
    marker = plan.wells[0].markers[0]
    assert marker.reference_depth == pytest.approx(1000.0 / 0.3048, rel=1e-6)


def test_external_meter_tops_untouched_on_meter_section():
    logs = [_well("A", 1000.0, "m")]
    tops = {"A": [("H1", 1000.0)]}
    plan = multi.adapt_multi_well_section(
        logs, ["A"], resource_ids=["a"], tops_by_well=tops
    )
    assert plan.wells[0].markers[0].reference_depth == pytest.approx(1000.0)
