"""ISS-VIZ-01: WellTieHost thin shell over engine WellTieCanvas."""

from __future__ import annotations

import numpy as np
from geoviz import CurveData, WellLogData, WellTieCanvas

from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel
from paleo_workbench.viz.hosts.well_tie_host import WellTieHost, build_tie_arrays
from paleo_workbench.viz.models import VizPayload


def _well_with_dt_rhob() -> WellLogData:
    depths = [1000.0 + i * 10.0 for i in range(20)]
    return WellLogData(
        well_name="TIE-1",
        top_depth=1000.0,
        bottom_depth=1190.0,
        curves=[
            CurveData(
                name="DT",
                unit="us/m",
                depth=depths,
                values=[260.0 - i for i in range(20)],
                display_range=(200.0, 300.0),
            ),
            CurveData(
                name="RHOB",
                unit="g/cm3",
                depth=depths,
                values=[2.2 + i * 0.01 for i in range(20)],
                display_range=(2.0, 2.6),
            ),
            CurveData(
                name="GR",
                unit="gapi",
                depth=depths,
                values=[40.0 + i for i in range(20)],
                display_range=(0.0, 150.0),
            ),
        ],
    )


def test_well_tie_host_creates_engine_canvas(qtbot):
    host = WellTieHost()
    qtbot.addWidget(host.widget)
    assert isinstance(host.widget, WellTieCanvas)
    assert host.tab_title == "井震标定"


def test_build_tie_arrays_uses_dt_rhob_curves():
    data = _well_with_dt_rhob()
    arrays = build_tie_arrays(data, None)
    assert arrays is not None
    depths, twt, sonic, density, seismic = arrays
    assert len(depths) == 20
    assert len(twt) == 20
    assert float(twt[-1]) > float(twt[0])
    assert np.allclose(sonic[0], 260.0)
    assert np.allclose(density[0], 2.2)
    assert len(seismic) == 20


def test_build_tie_arrays_synthetic_proxy_without_dt_rhob():
    data = WellLogData(
        well_name="GR-only",
        top_depth=0.0,
        bottom_depth=100.0,
        curves=[
            CurveData(
                name="GR",
                unit="gapi",
                depth=[0.0, 50.0, 100.0],
                values=[10.0, 50.0, 90.0],
            )
        ],
    )
    arrays = build_tie_arrays(data, None)
    assert arrays is not None
    depths, twt, sonic, density, _seismic = arrays
    assert len(depths) == 3
    assert sonic.size == 3
    assert density.size == 3
    assert float(twt[-1]) >= 0.0


def test_build_tie_arrays_seismic_only():
    vol = np.random.default_rng(1).standard_normal((4, 5, 40)).astype(np.float32)
    arrays = build_tie_arrays(None, vol, n_fallback=50)
    assert arrays is not None
    _d, _t, _s, _rho, seismic = arrays
    assert len(seismic) == 50


def test_build_tie_arrays_none_without_inputs():
    assert build_tie_arrays(None, None) is None


def test_well_tie_host_apply_and_clear(qtbot):
    host = WellTieHost()
    qtbot.addWidget(host.widget)
    payload = VizPayload(kind="well_log", label="TIE-1", well_log=_well_with_dt_rhob())
    assert host.apply(payload) is True
    assert host.widget._depths is not None
    assert host.widget._synthetic is not None
    host.clear()
    assert host.widget._depths is None
    assert host.widget._synthetic is None


def test_composite_loads_well_tie_from_well_log_payload(qtbot):
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)
    payload = VizPayload(kind="well_log", label="TIE-1", well_log=_well_with_dt_rhob())
    panel.load_payload(payload)
    assert panel.well_tie_canvas._depths is not None
    assert "井震标定" in panel.status_label.text()
    # Primary tab remains 测井 for well_log kind.
    assert panel.tabs.tabText(panel.tabs.currentIndex()) == "测井"


# ---------------------------------------------------------------------------
# #403 — a foot depth axis must not be integrated as meters in _twt_from_sonic
# (TWT would otherwise come out 0.3048x too small).
# ---------------------------------------------------------------------------

def test_twt_from_sonic_feet_axis_matches_meter_integration():
    from paleo_workbench.viz.hosts.well_tie_host import _twt_from_sonic

    depths_ft = np.linspace(6000.0, 6400.0, 41)
    sonic = np.linspace(250.0, 220.0, 41)  # µs/m (already normalized)
    twt_ft = _twt_from_sonic(depths_ft, sonic, depth_unit="ft")
    twt_m = _twt_from_sonic(depths_ft * 0.3048, sonic, depth_unit="m")
    np.testing.assert_allclose(twt_ft, twt_m)
    # Foot integration must be smaller than the old (wrong) meter assumption.
    wrong = _twt_from_sonic(depths_ft, sonic, depth_unit="m")
    assert abs(float(twt_ft[-1]) - float(wrong[-1]) * 0.3048) < 1e-9


def test_build_tie_arrays_feet_well_uses_foot_depths():
    from paleo_workbench.viz.well_log_load import WellLogDataWithDepthUnit

    data = _well_with_dt_rhob()
    ft_data = WellLogDataWithDepthUnit(data, "ft")
    arrays = build_tie_arrays(ft_data, None)
    assert arrays is not None
    _depths, twt, sonic, _density, _seismic = arrays
    # The same (meter) depths labeled "ft" must integrate 0.3048x smaller:
    # the old code treated them as meters and produced a 3.28x-too-large TWT.
    expected = build_tie_arrays(WellLogDataWithDepthUnit(data, "m"), None)
    np.testing.assert_allclose(twt, expected[1] * 0.3048)
    assert float(twt[-1]) > 0.0


# #406 — sonic unit conversion must trust curve.unit metadata; the numeric
# fallback stays only for curves whose ~CURVE block carried no unit.
def test_sonic_unit_metadata_beats_numeric_heuristic():
    import numpy as np

    from paleo_workbench.viz.hosts.well_tie_host import _sonic_to_us_per_m

    # Dense carbonate at 145 us/m: the old median<150 heuristic reclassified
    # it as us/ft and multiplied by 3.28084 (TWT inflated ~3.3x).
    fast_m = np.full(50, 145.0)
    assert np.allclose(_sonic_to_us_per_m(fast_m, "US/M"), fast_m)

    # us/ft metadata converts exactly once.
    usft = np.full(50, 44.0)
    assert np.allclose(_sonic_to_us_per_m(usft, "US/F"), usft * 3.28084)

    # Missing metadata keeps the numeric fallback.
    assert np.allclose(_sonic_to_us_per_m(usft, ""), usft * 3.28084)
    assert np.allclose(_sonic_to_us_per_m(fast_m, ""), fast_m * 3.28084)


def test_twt_from_sonic_survives_null_samples():
    """#534: a single LAS null (NaN) in the sonic curve used to NaN every
    TWT sample at and below the gap via the trapezoid + cumsum; gaps are
    now bridged from the nearest finite samples."""
    from paleo_workbench.viz.hosts.well_tie_host import _twt_from_sonic

    depths = np.array([1000.0, 1001.0, 1002.0, 1003.0, 1004.0])
    clean = np.full(5, 100.0)  # 100 us/m flat
    twt_clean = _twt_from_sonic(depths, clean)
    # 2 * 100us * 1m / 1000 per meter-step, cumulative.
    np.testing.assert_allclose(twt_clean, [0.0, 0.2, 0.4, 0.6, 0.8])

    gapped = clean.copy()
    gapped[2] = np.nan  # one missing sample mid-well
    twt_gapped = _twt_from_sonic(depths, gapped)
    np.testing.assert_allclose(twt_gapped, twt_clean)
    assert np.isfinite(twt_gapped).all()

    # Nulls at the edges extend the nearest finite value, not NaN.
    edged = clean.copy()
    edged[0] = np.nan
    edged[-1] = np.nan
    twt_edged = _twt_from_sonic(depths, edged)
    assert np.isfinite(twt_edged).all()
    np.testing.assert_allclose(twt_edged, twt_clean)

    # An entirely-null curve integrates to zeros (no NaN cascade).
    all_nan = np.full(5, np.nan)
    np.testing.assert_allclose(
        _twt_from_sonic(depths, all_nan), np.zeros(5)
    )
