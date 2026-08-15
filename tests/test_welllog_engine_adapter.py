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


def test_env_flag_defaults_on_and_can_opt_out(monkeypatch):
    # #174: product default is WellLogEngine; Legacy is explicit opt-out.
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    assert adapter.welllog_engine_env_enabled() is True
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "1")
    assert adapter.welllog_engine_env_enabled() is True
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "yes")
    assert adapter.welllog_engine_env_enabled() is True
    for off in ("0", "false", "no", "off", "legacy"):
        monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", off)
        assert adapter.welllog_engine_env_enabled() is False, off


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


def test_submit_plan_to_view_submits_one_complete_multitrack_document():
    plan = adapter.adapt_well_log_data(_sample_well())
    calls: list[dict] = []

    class FakeView:
        def submit_multi_track(self, payload):
            calls.append(payload)
            return {
                "depth": {"access_mode": "zero_copy"},
                "curve_count": len(payload["curves"]),
                "track_count": len(payload["tracks"]),
                "render_prepared": True,
            }

    result = adapter.submit_plan_to_view(FakeView(), plan)
    assert len(calls) == 1
    payload = calls[0]
    assert len(payload["curves"]) == 2
    assert len(payload["tracks"]) == 4  # lithology, facies, GR, RHOB
    assert {item["semantic"] for item in payload["intervals"]} == {
        "lithology", "facies"
    }
    first = payload["curves"][0]
    assert first["mnemonic"] == "GR"
    assert first["value_unit"] == "GAPI"
    assert isinstance(first["depth"], np.ndarray) and first["depth"].flags.writeable is False
    assert result["sample_count"] == 3
    assert result["curve_count"] == 2
    assert result["lithology_count"] == 2


def test_update_prefers_append_then_patch_without_full_resubmit():
    previous = adapter.adapt_well_log_data(_sample_well())
    data = _sample_well()
    for curve in data.curves:
        curve.depth.append(curve.depth[-1] + 1.0)
        curve.values.append(curve.values[-1] + 1.0)
    data.lithology[0].bottom = 1002.0
    current = adapter.adapt_well_log_data(data)
    calls: list[str] = []

    class FakeView:
        def append_curves(self, payload):
            calls.append("append")
            assert len(payload["tails"]) == 2
            return {"incremental": True}

        def patch_document(self, payload):
            calls.append("patch")
            assert "intervals" in payload
            return {"patched": True}

        def submit_multi_track(self, payload):
            calls.append("full")
            return {"curve_count": 2, "track_count": len(payload["tracks"])}

    result = adapter.update_plan_to_view(FakeView(), current, previous)
    assert calls == ["append", "patch"]
    assert result["update_kind"] == "append"


def test_update_marker_change_forces_full_resubmit():
    """Marker edits must reach the native view; patch cannot carry markers."""
    from types import SimpleNamespace

    class WithMarkers:
        """Duck-typed WellLogData carrier exposing a markers list."""

        def __init__(self, data, markers):
            self._data = data
            self.markers = markers

        def __getattr__(self, name):
            return getattr(self._data, name)

    previous = adapter.adapt_well_log_data(_sample_well())
    edited = WithMarkers(
        _sample_well(),
        [SimpleNamespace(depth=1001.0, label="H1", semantic="formation_top")],
    )
    current = adapter.adapt_well_log_data(edited)
    calls: list[str] = []

    class FakeView:
        def append_curves(self, payload):
            calls.append("append")
            return {"incremental": True}

        def patch_document(self, payload):
            calls.append("patch")
            return {"patched": True}

        def submit_multi_track(self, payload):
            calls.append("full")
            assert any(m["label"] == "H1" for m in payload["markers"])
            return {"curve_count": 2, "track_count": len(payload["tracks"])}

    result = adapter.update_plan_to_view(FakeView(), current, previous)
    assert calls == ["full"]
    assert result["update_kind"] == "full_replace"

    # Identical plans — markers included — still collapse to "unchanged".
    calls.clear()
    result = adapter.update_plan_to_view(
        FakeView(), adapter.adapt_well_log_data(_sample_well()), previous
    )
    assert calls == []
    assert result["update_kind"] == "unchanged"


def test_readonly_numpy_input_is_not_list_materialized_or_copied():
    class Curve:
        name = "GR"
        unit = "API"
        display_range = (0.0, 150.0)
        color = "#15803d"
        line_style = "solid"

    class Well:
        well_name = "typed"
        top_depth = 0.0
        bottom_depth = 3.0
        lithology = []
        facies = []
        intervals = None

    curve = Curve()
    curve.depth = np.arange(4.0, dtype=np.float64)
    curve.values = np.arange(4.0, dtype=np.float64)
    curve.depth.flags.writeable = False
    curve.values.flags.writeable = False
    well = Well()
    well.curves = [curve]

    plan = adapter.adapt_well_log_data(well)
    assert np.shares_memory(plan.primary.depth, curve.depth)
    assert np.shares_memory(plan.primary.values, curve.values)


def test_optional_business_markers_reach_the_native_payload():
    class Marker:
        id = "bf03db8b-102f-40cc-a4ce-227b24c6e0c8"
        depth = 1001.0
        label = "H1"
        semantic = "formation_top"

    class MarkerWell:
        well_name = "marker-well"
        top_depth = 1000.0
        bottom_depth = 1002.0
        curves = [
            type(
                "Curve",
                (),
                {
                    "name": "GR",
                    "unit": "API",
                    "depth": [1000.0, 1001.0, 1002.0],
                    "values": [10.0, 20.0, 30.0],
                },
            )()
        ]
        lithology = []
        facies = []
        intervals = None
        markers = [Marker()]

    data = MarkerWell()
    plan = adapter.adapt_well_log_data(data)
    payload = adapter.plan_to_submit_payload(plan)
    assert payload["markers"] == [
        {
            "id": Marker.id,
            "depth": 1001.0,
            "label": "H1",
            "semantic": "formation_top",
        }
    ]


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


# ---------------------------------------------------------------------------
# #403 — the depth-axis unit declared in ~C (DEPT.FT) must reach the engine
# submission payload instead of a hardcoded "m".
# ---------------------------------------------------------------------------

def test_403_adapted_plan_carries_detected_depth_unit():
    from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

    plan = adapter.adapt_well_log_data(
        WellLogDataWithDepthUnit(_sample_well(), "ft")
    )
    assert plan.primary.depth_unit == "ft"
    assert all(curve.depth_unit == "ft" for curve in plan.curves)
    payload = adapter.plan_to_submit_payload(plan)
    assert payload["depth_unit"] == "ft"
    snap = adapter.parity_snapshot(WellLogDataWithDepthUnit(_sample_well(), "ft"))
    assert snap["curves"][0]["depth_unit"] == "ft"


def test_403_default_depth_unit_stays_meter():
    plan = adapter.adapt_well_log_data(_sample_well())
    assert plan.primary.depth_unit == "m"
    payload = adapter.plan_to_submit_payload(plan)
    assert payload["depth_unit"] == "m"


# ---------------------------------------------------------------------------
# #402 — a single non-positive RT/RXO sample must not fail the whole native
# document: log tracks sanitize their minimum (legacy-consistent 1e-10 floor),
# and curves without any positive finite sample fall back to linear.
# ---------------------------------------------------------------------------

def _rt_curve(name="RT", values=None, display_range=(-0.5, 100.0)):
    values = values if values is not None else [10.0] * 19 + [-0.5]
    return CurveData(
        name=name,
        unit="ohm.m",
        depth=[1000.0 + i for i in range(len(values))],
        values=values,
        display_range=display_range,
    )


def _rt_track(payload, plan, mnemonic="RT"):
    curve_id = next(c.curve_id for c in plan.curves if c.mnemonic == mnemonic)
    return next(t for t in payload["tracks"] if t["layers"][0]["curve_id"] == curve_id)


def test_402_negative_rt_sample_sanitizes_log_track_minimum():
    plan = adapter.adapt_well_log_data(
        WellLogData(
            well_name="c47",
            top_depth=1000.0,
            bottom_depth=1019.0,
            curves=[
                CurveData(name="GR", unit="API", depth=[1000.0 + i for i in range(20)],
                          values=[10.0 + i for i in range(20)], display_range=(0.0, 150.0)),
                _rt_curve(),
            ],
        )
    )
    payload = adapter.plan_to_submit_payload(plan)
    track = _rt_track(payload, plan, "RT")
    assert track["scale_mode"] == "log"
    assert track["scale_min"] > 0.0
    assert track["scale_min"] == pytest.approx(1e-10)  # legacy renderer floor
    assert track["scale_max"] == 100.0
    assert "log_scale_fallback" not in " ".join(plan.diagnostics)


def test_402_positive_rt_range_is_unchanged():
    plan = adapter.adapt_well_log_data(
        WellLogData(
            well_name="ok", top_depth=1000.0, bottom_depth=1019.0,
            curves=[_rt_curve(display_range=(0.2, 2000.0))],
        )
    )
    track = _rt_track(adapter.plan_to_submit_payload(plan), plan, "RT")
    assert track["scale_mode"] == "log"
    assert track["scale_min"] == pytest.approx(0.2)


def test_402_all_negative_rt_falls_back_to_linear_with_diagnostic():
    plan = adapter.adapt_well_log_data(
        WellLogData(
            well_name="neg", top_depth=1000.0, bottom_depth=1019.0,
            curves=[_rt_curve(values=[-5.0] * 20, display_range=(-5.0, -1.0))],
        )
    )
    track = _rt_track(adapter.plan_to_submit_payload(plan), plan, "RT")
    assert track["scale_mode"] == "linear"
    assert "log_scale_fallback:RT" in plan.diagnostics


def test_402_null_dominated_rt_is_dropped_before_tracks():
    # A curve with no finite sample never reaches the track payload: it is
    # dropped upstream with a diagnostic, so it cannot submit a bad log track.
    plan = adapter.adapt_well_log_data(
        WellLogData(
            well_name="nulls", top_depth=1000.0, bottom_depth=1019.0,
            curves=[_rt_curve(values=[float("nan")] * 20, display_range=(0.0, 100.0))],
        )
    )
    assert "curve_empty:RT" in plan.diagnostics
    assert not [c for c in plan.curves if c.mnemonic == "RT"]


def test_402_submit_accepts_sanitized_log_payload():
    """Mocked engine validator: log tracks must never carry a non-positive min."""
    plan = adapter.adapt_well_log_data(
        WellLogData(
            well_name="mocked", top_depth=1000.0, bottom_depth=1019.0,
            curves=[_rt_curve()],
        )
    )

    class _StrictView:
        def submit_multi_track(self, payload):
            for track in payload["tracks"]:
                if track["scale_mode"] == "log":
                    assert track["scale_min"] > 0.0, "log track min must be positive"
            return {"track_count": len(payload["tracks"])}

    report = adapter.submit_plan_to_view(_StrictView(), plan)
    assert report["track_count"] == 1
