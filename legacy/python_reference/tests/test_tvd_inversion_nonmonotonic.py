"""#1037 — non-monotonic TVD → MD inversion.

``map_to_well_depth`` used ``np.interp(tvd, well.tvd, well.md)``, which
requires strictly increasing ``xp``: for horizontal / undulating trajectories
(incidence > 90°) NumPy silently returned garbage from its binary search on
unsorted data. These tests pin the piecewise trajectory-segment inversion
with explicitly defined multi-crossing semantics.
"""

from __future__ import annotations

import math

import pytest

from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub


def _hub_with_horizontal_well() -> CoordinateTransformHub:
    """Build then hold: vertical to 1000 m TVD, build to 90°, lateral, then
    a falling section (incidence 95°) that makes TVD non-monotonic."""
    hub = CoordinateTransformHub()
    stations = [
        (0.0, 0.0, 0.0),
        (500.0, 0.0, 0.0),      # vertical
        (1500.0, 90.0, 10.0),   # build to horizontal
        (2500.0, 90.0, 10.0),   # lateral (TVD ~constant)
        (3500.0, 95.0, 10.0),   # dropping section — TVD DECREASES
    ]
    hub.register_well("H-1", x=0.0, y=0.0, stations=stations)
    return hub


def test_horizontal_well_tvd_is_non_monotonic():
    hub = _hub_with_horizontal_well()
    well = hub._wells["H-1"]
    diffs = well.tvd[1:] - well.tvd[:-1]
    assert (diffs > 0).any() and (diffs <= 0).any(), (
        "fixture must produce a genuinely non-monotonic TVD log"
    )


def test_roundtrip_md_to_tvd_to_md_on_rising_sections():
    hub = _hub_with_horizontal_well()
    for md in (100.0, 900.0, 1200.0):
        _, _, tvd = hub.well_depth_to_map("H-1", md)
        back = hub.map_to_well_depth("H-1", tvd)
        assert back == pytest.approx(md, abs=1.0), f"md={md} tvd={tvd} back={back}"


def test_multi_crossing_tvd_returns_first_md_then_all():
    hub = _hub_with_horizontal_well()
    well = hub._wells["H-1"]
    # pick a TVD that occurs on BOTH the build section and the dropping
    # section (TVD rises past it, then falls back through it)
    peak = float(well.tvd.max())
    target = peak - 5.0  # crossed rising before the peak, falling after

    crossings = hub.map_to_well_depth_all("H-1", target)
    assert len(crossings) >= 2, (
        f"TVD {target} must cross multiple times on this trajectory: {crossings}"
    )

    first = hub.map_to_well_depth("H-1", target)
    assert first == pytest.approx(crossings[0], abs=0.5)
    assert first == pytest.approx(min(crossings), abs=0.5)
    # every crossing inverts to a trajectory point whose TVD matches target
    for md in crossings:
        _, _, tvd = hub.well_depth_to_map("H-1", md)
        assert tvd == pytest.approx(target, abs=0.05)


def test_monotonic_deviated_well_matches_legacy_interp():
    hub = CoordinateTransformHub()
    stations = [(0.0, 0.0, 0.0), (1000.0, 30.0, 5.0), (2000.0, 60.0, 5.0)]
    hub.register_well("D-1", x=0.0, y=0.0, stations=stations)
    for tvd in (100.0, 500.0, 1000.0):
        md = hub.map_to_well_depth("D-1", tvd)
        _, _, tvd_back = hub.well_depth_to_map("D-1", md)
        assert tvd_back == pytest.approx(tvd, abs=0.5)


def test_out_of_range_tvd_clamps_to_endpoints():
    hub = _hub_with_horizontal_well()
    well = hub._wells["H-1"]
    md_min = hub.map_to_well_depth("H-1", -100.0)
    assert md_min == pytest.approx(float(well.md[0]), abs=0.5)
    # above the maximum reached TVD: the deepest crossing of that TVD level
    # is the point where TVD peaks; out-of-range-high clamps onto the peak MD
    md_high = hub.map_to_well_depth("H-1", float(well.tvd.max()) + 500.0)
    peak_index = int(well.tvd.argmax())
    assert md_high == pytest.approx(float(well.md[peak_index]), abs=1.0)


def test_lateral_section_tvd_maps_into_lateral_md_range():
    hub = _hub_with_horizontal_well()
    well = hub._wells["H-1"]
    lateral_tvd = float((well.tvd[2] + well.tvd[3]) / 2.0)
    md = hub.map_to_well_depth("H-1", lateral_tvd)
    assert 1400.0 <= md <= 2600.0, (
        f"lateral TVD {lateral_tvd} must map inside the lateral, got MD {md}"
    )


def test_vertical_well_identity_mapping_unchanged():
    hub = CoordinateTransformHub()
    hub.register_well("V-1", x=1.0, y=2.0, total_depth_m=3000.0)
    assert hub.map_to_well_depth("V-1", 1234.5) == pytest.approx(1234.5)


def test_unknown_well_raises_keyerror():
    hub = CoordinateTransformHub()
    with pytest.raises(KeyError):
        hub.map_to_well_depth("nope", 100.0)
    with pytest.raises(KeyError):
        hub.map_to_well_depth_all("nope", 100.0)
