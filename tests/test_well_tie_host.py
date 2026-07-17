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
