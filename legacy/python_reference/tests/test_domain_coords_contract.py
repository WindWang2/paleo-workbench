"""L1 typed coordinate/domain contract tests (linked-interpretation).

Covers:
* explicit units/domains/CRS on every value;
* fail-closed depth↔time (no calibration, out-of-range, non-monotonic
  calibration rejected at construction);
* the constant-velocity path is explicit-only (VelocityAssumption) and the
  hub refuses z↔TWT without a declared assumption;
* numerical roundtrips map→seismic→map and MD→TWT→MD inside the legal
  domain, with tolerances;
* CRS mismatch refusal.
"""

from __future__ import annotations

import math

import pytest

from paleo_workbench.viz.coordinate_hub import (
    CoordinateTransformHub,
    TimeDepthCalibration,
)
from paleo_workbench.viz.domain_coords import (
    ConversionFailure,
    DepthCoordinate,
    DepthDomain,
    DomainCoordinationService,
    LengthUnit,
    MapPoint,
    SeismicCursorPosition,
    TwtCoordinate,
    VelocityAssumption,
    calibration_identity,
)

# ---------------------------------------------------------------------------
# Unit handling
# ---------------------------------------------------------------------------


def test_depth_coordinate_ft_roundtrips_through_meters():
    md_ft = DepthCoordinate.from_source(1000.0, DepthDomain.MD, LengthUnit.FT)
    assert md_ft.value_m == pytest.approx(304.8)
    assert md_ft.in_unit(LengthUnit.FT) == pytest.approx(1000.0)
    assert md_ft.in_unit(LengthUnit.M) == pytest.approx(304.8)
    assert md_ft.source_unit_value == 1000.0
    assert md_ft.unit is LengthUnit.FT


def test_depth_coordinate_rejects_nonfinite():
    with pytest.raises(ValueError):
        DepthCoordinate.from_source(float("nan"), DepthDomain.MD)
    with pytest.raises(ValueError):
        DepthCoordinate.from_source(float("inf"), DepthDomain.TVDSS)


def test_twt_coordinate_rejects_nonfinite():
    with pytest.raises(ValueError):
        TwtCoordinate(float("nan"))


# ---------------------------------------------------------------------------
# Fail-closed depth↔time
# ---------------------------------------------------------------------------


def _hub_with_well_and_calibration(*, deviated: bool = False):
    hub = CoordinateTransformHub()
    stations = (
        [(0.0, 0.0, 0.0), (2000.0, 45.0, 0.0), (4000.0, 45.0, 0.0)]
        if deviated
        else None
    )
    hub.register_well(
        "W-1", x=1000.0, y=2000.0, elevation=25.0, total_depth_m=4000.0,
        stations=stations,
    )
    hub.set_time_depth_calibration(
        TimeDepthCalibration.from_pairs(
            "W-1", [(0.0, 0.0), (2000.0, 1600.0), (4000.0, 3000.0)],
            provenance="checkshot:test",
        )
    )
    hub.configure_seismic_grid(
        origin=(0.0, 0.0),
        il_step=(25.0, 0.0),
        xl_step=(0.0, 25.0),
        il_min=0,
        xl_min=0,
    )
    return hub


def test_md_to_twt_without_calibration_refuses():
    hub = CoordinateTransformHub()
    hub.register_well("W-NC", x=0.0, y=0.0, total_depth_m=3000.0)
    svc = DomainCoordinationService(hub)
    out = svc.well_md_to_twt("W-NC", DepthCoordinate.from_source(1000.0, DepthDomain.MD))
    assert not out.ok
    assert out.value is None
    assert out.reason is ConversionFailure.NO_CALIBRATION
    assert "refusing" in out.detail


def test_md_to_twt_out_of_calibration_range_refuses():
    svc = DomainCoordinationService(_hub_with_well_and_calibration())
    out = svc.well_md_to_twt("W-1", DepthCoordinate.from_source(4500.0, DepthDomain.MD))
    assert not out.ok
    assert out.reason is ConversionFailure.OUT_OF_CALIBRATION_RANGE
    assert "outside calibrated range" in out.detail


def test_md_twt_roundtrip_inside_calibrated_domain():
    svc = DomainCoordinationService(_hub_with_well_and_calibration())
    for md_m in (0.0, 123.4, 1000.0, 2500.0, 4000.0):
        md = DepthCoordinate.from_source(md_m, DepthDomain.MD)
        twt_out = svc.well_md_to_twt("W-1", md)
        assert twt_out.ok, twt_out.detail
        assert twt_out.authority == "time-depth:checkshot:test"
        back = svc.twt_to_well_md("W-1", twt_out.value)
        assert back.ok, back.detail
        assert back.value.value_m == pytest.approx(md_m, abs=1e-6)
        assert back.value.domain is DepthDomain.MD


def test_ft_well_md_converts_before_calibration_lookup():
    svc = DomainCoordinationService(_hub_with_well_and_calibration())
    # 1000 ft = 304.8 m — inside the calibrated [0, 4000] m range
    out = svc.well_md_to_twt(
        "W-1", DepthCoordinate.from_source(1000.0, DepthDomain.MD, LengthUnit.FT)
    )
    assert out.ok, out.detail
    direct = svc.well_md_to_twt(
        "W-1", DepthCoordinate.from_source(304.8, DepthDomain.MD)
    )
    assert out.value.value_ms == pytest.approx(direct.value.value_ms, abs=1.0)


def test_non_monotonic_calibration_is_rejected_at_construction():
    with pytest.raises(ValueError, match="strictly increase"):
        TimeDepthCalibration.from_pairs(
            "W-BAD",
            [(0.0, 0.0), (2000.0, 1600.0), (1500.0, 2200.0)],
            provenance="bad",
        )
    with pytest.raises(ValueError, match="strictly increase"):
        TimeDepthCalibration.from_pairs(
            "W-BAD",
            [(0.0, 0.0), (2000.0, 1600.0), (3000.0, 1500.0)],
            provenance="bad",
        )


def test_unknown_well_refuses_with_reason():
    svc = DomainCoordinationService(_hub_with_well_and_calibration())
    out = svc.well_md_to_map("NOPE", DepthCoordinate.from_source(10.0, DepthDomain.MD))
    assert not out.ok
    assert out.reason is ConversionFailure.UNKNOWN_WELL


# ---------------------------------------------------------------------------
# Well → seismic cursor (geometry + calibrated time)
# ---------------------------------------------------------------------------


def test_well_md_to_seismatic_cursor_uses_calibration_not_velocity():
    hub = _hub_with_well_and_calibration()
    svc = DomainCoordinationService(hub)
    out = svc.well_md_to_seismic(
        "W-1", DepthCoordinate.from_source(2000.0, DepthDomain.MD)
    )
    assert out.ok, out.detail
    assert out.value.twt.value_ms == pytest.approx(1600.0)
    assert out.value.inline == 40  # x=1000 m / 25 m per inline
    assert out.value.crossline == 80  # y=2000 m / 25 m per crossline
    # no velocity assumption is declared on this hub at all
    assert hub.velocity_assumption() is None


def test_well_md_to_seismic_refuses_without_calibration():
    hub = CoordinateTransformHub()
    hub.register_well("W-1", x=1000.0, y=2000.0, total_depth_m=4000.0)
    hub.configure_seismic_grid(origin=(0.0, 0.0), il_step=(25.0, 0.0),
                               xl_step=(0.0, 25.0), il_min=0, xl_min=0)
    svc = DomainCoordinationService(hub)
    out = svc.well_md_to_seismic(
        "W-1", DepthCoordinate.from_source(1000.0, DepthDomain.MD)
    )
    assert not out.ok
    assert out.reason is ConversionFailure.NO_CALIBRATION


# ---------------------------------------------------------------------------
# Map ↔ seismic roundtrip (pure geometry)
# ---------------------------------------------------------------------------


def test_map_seismic_roundtrip_via_points():
    hub = CoordinateTransformHub()
    hub.configure_seismic_grid(
        origin=(500000.0, 4000000.0),
        il_step=(15.0, 8.0),
        xl_step=(-5.0, 20.0),
        il_min=100,
        xl_min=200,
    )
    svc = DomainCoordinationService(hub, project_crs="EPSG:32650")
    for il, xl in ((100, 200), (137, 246), (250, 300)):
        pos = svc.seismic_to_map_xy(_pos(il, xl))
        assert pos.ok
        back = svc.map_to_seismic_xy(pos.value)
        assert back.ok
        assert (back.value.inline, back.value.crossline) == (il, xl)
        # roundtrip through the point again for numeric stability
        pos2 = svc.seismic_to_map_xy(back.value)
        assert (pos2.value.x, pos2.value.y) == pytest.approx(
            (pos.value.x, pos.value.y), abs=1e-6
        )


def _pos(il: int, xl: int):
    from paleo_workbench.viz.domain_coords import SeismicPosition

    return SeismicPosition(inline=il, crossline=xl)


def test_seismic_cursor_to_map_drops_twt():
    svc = DomainCoordinationService(_hub_with_well_and_calibration())
    cursor = SeismicCursorPosition(inline=10, crossline=20, twt=TwtCoordinate(1500.0))
    out = svc.seismic_cursor_to_map(cursor)
    assert out.ok
    assert out.value.crs is None  # unlabelled project-local
    # the TWT must not appear anywhere in the map result
    assert not hasattr(out.value, "twt")


def test_crs_mismatch_refuses_conversion():
    hub = CoordinateTransformHub()
    hub.configure_seismic_grid(origin=(0.0, 0.0), il_step=(25.0, 0.0),
                               xl_step=(0.0, 25.0), il_min=0, xl_min=0,
                               crs="EPSG:32650")
    svc = DomainCoordinationService(hub, project_crs="EPSG:32650")
    out = svc.map_to_seismic_xy(MapPoint(100.0, 200.0, crs="EPSG:4326"))
    assert not out.ok
    assert out.reason is ConversionFailure.CRS_MISMATCH
    # unlabelled points stay legal (project-local geometry)
    ok = svc.map_to_seismic_xy(MapPoint(100.0, 200.0))
    assert ok.ok


# ---------------------------------------------------------------------------
# Velocity assumption is explicit-only
# ---------------------------------------------------------------------------


def test_velocity_assumption_twt_to_depth_is_marked_approximate():
    assumption = VelocityAssumption(2000.0)
    svc = DomainCoordinationService(CoordinateTransformHub())
    out = svc.seismic_twt_to_depth(
        TwtCoordinate(2000.0), assumption=assumption
    )
    assert out.ok
    assert out.value.value_m == pytest.approx(2000.0)
    assert out.authority == "velocity-assumption:2000 m/s"

    with pytest.raises(ValueError):
        VelocityAssumption(-1.0)
    with pytest.raises(ValueError):
        VelocityAssumption(0.0)
    with pytest.raises(ValueError):
        VelocityAssumption(float("nan"))


def test_hub_refuses_z_twt_without_declared_assumption():
    hub = CoordinateTransformHub()
    # V6 §8: bind grid geometry so this test isolates the VELOCITY gate
    hub.configure_seismic_grid(
        origin=(100.0, 200.0),
        il_step=(10.0, 0.0),
        xl_step=(0.0, 10.0),
        il_min=100,
        xl_min=200,
    )
    with pytest.raises(ValueError, match="no velocity assumption declared"):
        hub.seismic_to_map(100, 200, 1000.0)
    with pytest.raises(ValueError, match="no velocity assumption declared"):
        hub.map_to_seismic(100.0, 200.0, 1000.0)
    hub.set_velocity(2500.0)
    x, y, z = hub.seismic_to_map(100, 200, 1000.0)
    assert z == pytest.approx(1250.0)
    hub.clear_velocity_assumption()
    with pytest.raises(ValueError):
        hub.seismic_to_map(100, 200, 1000.0)


def test_deviated_well_md_tvd_and_tvdss():
    svc = DomainCoordinationService(_hub_with_well_and_calibration(deviated=True))
    md = DepthCoordinate.from_source(2000.0, DepthDomain.MD)
    tvdss = svc.well_md_to_tvdss("W-1", md)
    assert tvdss.ok
    # 2000 m MD at 45° build -> TVD ~ let the hub speak; assert consistency
    # with the hub's own trajectory instead of a hardcoded number.
    _, _, tvd = svc.hub.well_depth_to_map("W-1", 2000.0)
    assert tvdss.value.value_m == pytest.approx(25.0 - tvd)
    assert tvdss.value.domain is DepthDomain.TVDSS


# ---------------------------------------------------------------------------
# Calibration identity (L9 hooks)
# ---------------------------------------------------------------------------


def test_calibration_identity_carries_version():
    cal = TimeDepthCalibration.from_pairs(
        "W-1", [(0.0, 0.0), (2000.0, 1600.0)], provenance="td-table:x.dat",
        version_id="ver_123", fingerprint="abc",
    )
    ident = calibration_identity(cal)
    assert ident.well_id == "W-1"
    assert ident.version_id == "ver_123"
    assert ident.fingerprint == "abc"
    assert ident.provenance == "td-table:x.dat"


def test_calibration_metadata_not_in_equality():
    a = TimeDepthCalibration.from_pairs(
        "W-1", [(0.0, 0.0), (2000.0, 1600.0)], provenance="p",
        metadata={"quality": 0.9},
    )
    b = TimeDepthCalibration.from_pairs(
        "W-1", [(0.0, 0.0), (2000.0, 1600.0)], provenance="p",
    )
    assert a == b
    assert a.metadata == {"quality": 0.9}
