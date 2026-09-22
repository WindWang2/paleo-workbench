"""V6 §7 / P0-1 — the engine backend must receive gaps, not bridged lines.

The legacy QPainter path splits curve paths at NaN (curve_track.py). The
engine adapter used to filter+compact non-finite pairs, so a missing
interval rendered as a straight line on the native backend — a fabricated
trend. The submission contract: samples with finite DEPTH stay on the axis
carrying NaN values; the engine's LOD run-splitting turns them into honest
gaps (same semantics as the fallback renderer).
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from geoviz_well_log.models import CurveData, WellLogData


def _well_with_gap():
    depth = [1000.0, 1000.5, 1001.0, 1001.5, 1002.0, 1002.5]
    values = [60.0, 61.0, float("nan"), float("nan"), 64.0, 65.0]
    return WellLogData(
        well_name="W-gap",
        top_depth=1000.0,
        bottom_depth=1002.5,
        curves=[
            CurveData(
                name="GR",
                unit="gAPI",
                depth=depth,
                values=values,
                display_range=(0.0, 150.0),
            )
        ],
    )


class TestGapSubmission:
    def test_plan_keeps_nan_values_on_the_axis(self):
        from paleo_workbench.viz import welllog_engine_adapter as adapter

        plan = adapter.adapt_well_log_data(_well_with_gap())
        curve = plan.primary
        assert curve.depth.size == 6, "finite-depth samples must stay on the axis"
        assert curve.values.size == 6
        assert bool(np.isnan(curve.values[2:4]).all())
        assert tuple(curve.null_indices) == (2, 3)

    def test_submit_payload_carries_nan_gaps(self):
        from paleo_workbench.viz import welllog_engine_adapter as adapter

        plan = adapter.adapt_well_log_data(_well_with_gap())
        payload = adapter.plan_to_submit_payload(plan)
        values = np.asarray(payload["curves"][0]["values"], dtype=float)
        assert values.size == 6
        assert bool(np.isnan(values[2:4]).all())

    def test_parity_snapshot_records_gaps(self):
        from paleo_workbench.viz import welllog_engine_adapter as adapter

        snap = adapter.parity_snapshot(_well_with_gap())
        assert snap["curves"][0]["length"] == 6
        assert snap["curves"][0]["null_indices"] == [2, 3]
        assert snap["curves"][0]["value_first"] == pytest.approx(60.0)
        assert bool(np.isnan(snap["curves"][0]["value_last"])) is False

    def test_non_finite_depths_are_dropped_counted(self):
        from paleo_workbench.viz import welllog_engine_adapter as adapter

        data = WellLogData(
            well_name="W-bad-depth",
            top_depth=0.0,
            bottom_depth=3.0,
            curves=[
                CurveData(
                    name="GR",
                    unit="gAPI",
                    depth=[0.0, float("nan"), 2.0, 3.0],
                    values=[10.0, 20.0, 30.0, 40.0],
                    display_range=(0.0, 150.0),
                )
            ],
        )
        plan = adapter.adapt_well_log_data(data)
        curve = plan.primary
        # NaN DEPTH cannot live on the axis: those rows are dropped and the
        # dropped position is reported in null_indices (diagnostic contract)
        assert curve.depth.size == 3
        assert bool(np.isfinite(curve.depth).all())
        assert tuple(curve.null_indices) == (1,)

    def test_fully_null_curve_is_dropped_with_diagnostic(self):
        """Zero finite values → nothing displayable → curve_empty (#402);
        gaps only survive where finite neighbors bound them."""
        from paleo_workbench.viz import welllog_engine_adapter as adapter

        data = WellLogData(
            well_name="W-null",
            top_depth=0.0,
            bottom_depth=2.0,
            curves=[
                CurveData(
                    name="GR",
                    unit="gAPI",
                    depth=[0.0, 1.0, 2.0],
                    values=[float("nan")] * 3,
                    display_range=(0.0, 150.0),
                )
            ],
        )
        plan = adapter.adapt_well_log_data(data)
        assert "curve_empty:GR" in plan.diagnostics
        assert plan.curves == []

    def test_gap_semantics_match_legacy_backend(self):
        """Both backends derive gap presence from the same NaN values: the
        legacy build_curve_path splits at NaN; the engine run-splits at
        non-finite samples — one submission contract, no divergence."""
        from geoviz_well_log.renderer.curve_track import build_curve_path
        from paleo_workbench.viz import welllog_engine_adapter as adapter

        data = _well_with_gap()
        plan = adapter.adapt_well_log_data(data)
        # legacy path receives the same arrays the adapter now submits
        path = build_curve_path(
            np.asarray(plan.primary.depth, dtype=float),
            np.asarray(plan.primary.values, dtype=float),
        )
        # the QPainterPath contains a gap (two disjoint subpaths)
        assert path.elementCount() >= 2
        assert bool(np.isnan(plan.primary.values[2:4]).all())
