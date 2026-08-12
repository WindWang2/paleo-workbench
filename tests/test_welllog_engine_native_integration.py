"""Focused Workbench ↔ built WellLogEngine retained-session coverage."""

from __future__ import annotations

import numpy as np
import pytest

from geoviz import CurveData, FaciesInterval, LithologyInterval, WellLogData

from paleo_workbench.viz import welllog_engine_adapter as adapter


def _well() -> WellLogData:
    depth = [1000.0, 1001.0, 1002.0, 1003.0]
    return WellLogData(
        well_name="native-session",
        top_depth=1000.0,
        bottom_depth=1003.0,
        curves=[
            CurveData(
                name="GR", unit="API", depth=list(depth),
                values=[20.0, 30.0, 40.0, 50.0], display_range=(0.0, 150.0),
            ),
            CurveData(
                name="RT", unit="ohm.m", depth=list(depth),
                values=[2.0, 3.0, 4.0, 5.0], display_range=(0.2, 2000.0),
            ),
        ],
        lithology=[LithologyInterval(top=1000.0, bottom=1002.0, lithology="砂")],
        facies=[FaciesInterval(top=1002.0, bottom=1003.0, facies="三角洲")],
    )


def test_workbench_plan_uses_native_multitrack_append_and_patch(qtbot):
    _, view_class, _ = adapter.try_import_welllog()
    if view_class is None:
        pytest.skip("built WellLogEngine binding is not on PYTHONPATH")
    view = view_class()
    qtbot.addWidget(view)

    first = adapter.adapt_well_log_data(_well())
    loaded = adapter.submit_plan_to_view(view, first)
    assert loaded["curve_count"] == 2
    assert loaded["lithology_count"] == 1
    assert loaded["facies_count"] == 1
    assert loaded["track_count"] == 4

    changed = _well()
    for curve in changed.curves:
        curve.depth.extend([1004.0, 1005.0])
        curve.values.extend([curve.values[-1] + 1.0, curve.values[-1] + 2.0])
    changed.lithology[0].bottom = 1002.5
    second = adapter.adapt_well_log_data(changed)
    update = adapter.update_plan_to_view(view, second, first)
    assert update["update_kind"] == "append"

    unchanged = adapter.update_plan_to_view(view, second, second)
    assert unchanged["update_kind"] == "unchanged"

    metrics = view.document_metrics(second.document_id)
    assert metrics["curve_lengths"] == [6, 6]
    assert metrics["revision"] >= 3  # append plus interval patch
    assert metrics["lod_points_avg"] >= 0

    # Retained buffers were normalized to typed, read-only arrays.  The native
    # document, not this test's temporary payload dict, owns their lifetime.
    assert all(not curve.depth.flags.writeable for curve in second.curves)
    assert all(not curve.values.flags.writeable for curve in second.curves)
    assert np.isfinite(second.primary.depth).all()
