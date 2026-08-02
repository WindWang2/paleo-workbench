"""Unit tests for the WellLogEngine thin adapter + Feature Flag (#169)."""

from __future__ import annotations

import numpy as np
import pytest

from geoviz import CurveData, FaciesInterval, LithologyInterval, WellLogData

from paleo_workbench.viz import welllog_engine_adapter as adapter


def _sample_well() -> WellLogData:
    return WellLogData(
        well_name="Demo-1",
        top_depth=1000.0,
        bottom_depth=1003.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[1000.0, 1001.0, float("nan"), 1003.0],
                values=[10.0, 20.0, 999.0, 40.0],
                display_range=(0.0, 150.0),
            ),
            CurveData(
                name="RHOB",
                unit="g/cm3",
                depth=[1000.0, 1001.0, 1002.0, 1003.0],
                values=[2.1, 2.2, 2.3, 2.4],
            ),
        ],
        lithology=[
            LithologyInterval(top=1000.0, bottom=1001.5, lithology="砂"),
            LithologyInterval(top=1001.5, bottom=1003.0, lithology="泥"),
        ],
        facies=[FaciesInterval(top=1000.0, bottom=1003.0, facies="三角洲")],
    )


def test_env_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    assert adapter.welllog_engine_env_enabled() is False
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "1")
    assert adapter.welllog_engine_env_enabled() is True
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "yes")
    assert adapter.welllog_engine_env_enabled() is True


def test_adapt_well_log_data_maps_curves_nulls_and_intervals():
    plan = adapter.adapt_well_log_data(_sample_well())
    assert plan.well_name == "Demo-1"
    assert plan.top_depth == 1000.0
    assert plan.bottom_depth == 1003.0
    assert len(plan.curves) == 2
    # Primary is GR
    assert plan.primary is not None
    assert plan.primary.mnemonic == "GR"
    assert plan.primary.value_unit == "GAPI"
    assert plan.primary.depth_unit == "m"
    # Non-finite depth/value pair dropped; null index recorded
    assert plan.primary.depth.size == 3
    assert plan.primary.null_indices == (2,)
    assert float(plan.primary.depth[0]) == 1000.0
    assert float(plan.primary.values[1]) == 20.0
    # Read-only for zero-copy submit contract
    assert plan.primary.depth.flags.writeable is False
    assert plan.primary.values.flags.writeable is False
    # Stable ids across calls
    again = adapter.adapt_well_log_data(_sample_well())
    assert plan.primary.document_id == again.primary.document_id
    assert plan.primary.curve_id == again.primary.curve_id
    # Interval bounds preserved for parity
    assert plan.lithology_bounds[0] == (1000.0, 1001.5, "砂")
    assert plan.facies_bounds[0][2] == "三角洲"


def test_parity_snapshot_matches_legacy_key_fields():
    data = _sample_well()
    snap = adapter.parity_snapshot(data)
    assert snap["well_name"] == "Demo-1"
    assert snap["top_depth"] == 1000.0
    assert snap["bottom_depth"] == 1003.0
    gr = next(c for c in snap["curves"] if c["mnemonic"] == "GR")
    assert gr["unit"] == "GAPI"
    assert gr["depth_unit"] == "m"
    assert gr["length"] == 3
    assert gr["depth_first"] == 1000.0
    assert gr["value_last"] == 40.0
    assert gr["null_indices"] == [2]
    assert snap["lithology_bounds"][0][2] == "砂"


def test_submit_plan_to_view_calls_submit_curve_once():
    plan = adapter.adapt_well_log_data(_sample_well())
    calls: list[tuple] = []

    class FakeView:
        def submit_curve(self, depth, values, doc, axis, curve, mn, du, vu):
            calls.append((depth, values, doc, axis, curve, mn, du, vu))
            return {
                "depth": {"access_mode": "zero_copy"},
                "curve": {"access_mode": "zero_copy"},
                "render_prepared": True,
            }

    result = adapter.submit_plan_to_view(FakeView(), plan)
    assert len(calls) == 1
    depth, values, doc, _axis, curve, mn, du, vu = calls[0]
    assert mn == "GR"
    assert du == "m"
    assert vu == "GAPI"
    assert isinstance(depth, np.ndarray) and depth.flags.writeable is False
    assert result["sample_count"] == 3
    assert result["document_id"] == doc
    assert result["curve_id"] == curve
    assert result["lithology_count"] == 2


def test_submit_plan_without_curves_raises():
    empty = WellLogData(well_name="x", top_depth=0.0, bottom_depth=1.0, curves=[])
    plan = adapter.adapt_well_log_data(empty)
    with pytest.raises(ValueError):
        adapter.submit_plan_to_view(object(), plan)


def test_try_import_welllog_does_not_raise():
    mod, view_cls, _ = adapter.try_import_welllog()
    # Environment may or may not have the binding; both outcomes are valid.
    if mod is None:
        assert view_cls is None
    else:
        assert view_cls is not None
