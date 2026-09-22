"""Measurement and section-geometry tests (G8/G10)."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.builders import build_horizon_from_grid
from paleo_workbench.viz.geomodel.domain import DomainError
from paleo_workbench.viz.geomodel.measurements import (
    distance,
    format_result,
    plane_orientation,
    point_coordinate,
    polyline_length,
    thickness_at,
    vertical_difference,
)
from paleo_workbench.viz.geomodel.section import (
    Plane,
    axis_plane,
    clip_planes_for_box,
    horizon_plane_intersection,
    mesh_plane_intersection,
    well_plane_crossing,
)

CRS = "EPSG:32650"


class TestMeasurements:
    def test_distance_result_and_unit(self):
        m = distance((0, 0, 0), (3, 4, 0), crs=CRS)
        assert m.result == pytest.approx(5.0)
        assert m.unit == "m"
        assert "5.000 m" in format_result(m)
        assert m.object_id.startswith("measure:distance-")

    def test_polyline_and_vertical(self):
        m = polyline_length([(0, 0, 0), (1, 0, 0), (1, 1, 0)], crs=CRS)
        assert m.result == pytest.approx(2.0)
        v = vertical_difference((0, 0, 10), (1, 1, -5), crs=CRS)
        assert v.result == pytest.approx(-15.0)
        assert "vertical" in format_result(v)

    def test_thickness_bilinear_and_hole_failclosed(self):
        g_top = np.zeros((4, 4))
        g_base = np.full((4, 4), 50.0)
        g_base[0, 0] = np.nan
        top = build_horizon_from_grid("T", g_top, origin=(0, 0), spacing=(10, 10), crs=CRS)
        base = build_horizon_from_grid("B", g_base, origin=(0, 0), spacing=(10, 10), crs=CRS)
        m = thickness_at(15.0, 15.0, top, base)
        assert m.result == pytest.approx(50.0)
        assert "thickness" in format_result(m)
        with pytest.raises(DomainError, match="hole"):
            thickness_at(1.0, 1.0, top, base)  # inside the NaN cell

    def test_thickness_requires_matching_domains(self):
        top = build_horizon_from_grid("T", np.zeros((3, 3)), crs=CRS)
        base = build_horizon_from_grid("B", np.ones((3, 3)), crs=CRS, vertical_domain="twt")
        with pytest.raises(DomainError, match="share"):
            thickness_at(0, 0, top, base)

    def test_plane_orientation(self):
        pts = [(0, 0, 0), (10, 0, 0), (0, 10, 1), (10, 10, 1)]
        m = plane_orientation(pts, crs=CRS)
        dip = m.extra["dip_deg"]
        assert 0 < dip < 45
        assert "dip" in format_result(m)

    def test_nonfinite_points_rejected(self):
        with pytest.raises(DomainError):
            distance((0, 0, np.nan), (1, 1, 1), crs=CRS)

    def test_point_record(self):
        m = point_coordinate((5, 6, -100), crs=CRS)
        assert m.measurement_kind == "point"
        assert m.extra["z"] == -100


class TestPlane:
    def test_axis_plane_and_clip_equations(self):
        p = axis_plane("z", -150.0)  # z grows downward; keep everything below -150? no:
        # default keeps n·p <= d -> z <= -150; invert keeps z >= -150
        eq = p.as_clip_equation()
        assert eq == pytest.approx((0.0, 0.0, -1.0, -150.0))
        eq_inv = p.as_clip_equation(invert=True)
        assert eq_inv == pytest.approx((0.0, 0.0, 1.0, 150.0))
        with pytest.raises(ValueError):
            axis_plane("w", 0)

    def test_box_clip_six_planes(self):
        eqs = clip_planes_for_box([(0, 0, 0), (10, 20, 30)])
        assert len(eqs) == 6

    def test_signed_distance(self):
        p = Plane((0, 0, 1), -100.0)
        d = p.signed_distance(np.array([[0, 0, -150.0], [0, 0, -50.0]]))
        assert d[0] < 0 < d[1]


class TestSectionIntersection:
    def test_horizon_z_section_single_curve(self):
        g = np.full((6, 6), -100.0)
        plane = axis_plane("x", 25.0)
        curves = horizon_plane_intersection(
            plane, g, origin=(0, 0), spacing=(10, 10)
        )
        assert len(curves) == 1
        c = curves[0]
        assert np.allclose(c[:, 0], 25.0)
        assert np.allclose(c[:, 2], -100.0)
        assert c[:, 1].min() == pytest.approx(0.0)
        assert c[:, 1].max() == pytest.approx(50.0)

    def test_nan_hole_splits_curve(self):
        g = np.full((6, 6), -100.0)
        g[2:4, 2:4] = np.nan
        plane = axis_plane("x", 25.0)
        curves = horizon_plane_intersection(
            plane, g, origin=(0, 0), spacing=(10, 10)
        )
        assert len(curves) >= 2  # hole splits the section line

    def test_mesh_section(self):
        v = np.array(
            [
                [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
                [0, 0, -10], [10, 0, -10], [10, 10, -10], [0, 10, -10],
            ],
            dtype=float,
        )
        f = np.array(
            [
                [0, 1, 2], [0, 2, 3],  # top
                [4, 6, 5], [4, 7, 6],  # bottom
                [0, 4, 5], [0, 5, 1],  # walls
                [1, 5, 6], [1, 6, 2],
                [2, 6, 7], [2, 7, 3],
                [3, 7, 4], [3, 4, 0],
            ]
        )
        curves = mesh_plane_intersection(axis_plane("x", 5.0), v, f)
        assert curves
        pts = np.vstack(curves)
        assert np.allclose(pts[:, 0], 5.0)

    def test_well_crossing(self):
        traj = np.array([[0, 0, 0], [0, 0, -100], [0, 0, -200]], dtype=float)
        hit = well_plane_crossing(axis_plane("z", -150.0), traj)
        assert hit is not None
        assert hit[2] == pytest.approx(-150.0)
        assert well_plane_crossing(axis_plane("z", -500.0), traj) is None
