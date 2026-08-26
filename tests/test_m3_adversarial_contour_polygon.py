"""Adversarial Stress Test Suite for Milestone 3 (Marching Squares & Facies Polygonization).

Covers:
1. 100% NaN grids and partially masked NaN grids.
2. Uniform flat grids (vmin == vmax).
3. Degenerate dimensions: 1x1, 1xN, Nx1 grids.
4. Extreme aspect ratio grids (1000:1 and 1:1000).
5. Checkerboard saddle patterns and saddle disambiguation.
6. Isolated single-pixel peaks, pits, and NaN anomalies.
7. 2-level concentric nested rings (donuts, islands in lakes).
8. 3-level nested rings and multi-tier hole area conservation.
9. Polygon topology verification (CCW outer, CW inner, Shapely is_valid, no self-intersections).
10. Exact Shoelace area conservation (sum of facies areas == valid domain area).
11. Line simplification (Douglas-Peucker) and corner-cutting (Chaikin) on degenerate/closed loops.
12. Extreme numerical spans (very large 1e12, very small 1e-8, negative ranges).
"""

import math
import numpy as np
import pytest
from shapely.geometry import shape

from paleo_workbench.mapping.geological_pipeline.contouring import (
    _marching_squares_pure_python,
    _stitch_segments,
    calculate_nice_contour_levels,
    calculate_polyline_length,
    calculate_quantile_contour_levels,
    chaikin_smooth,
    douglas_peucker_2d,
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    _compute_geometry_area,
    _point_in_ring,
    _polygonize_raster_boundaries,
    calculate_shoelace_area,
    calculate_signed_area,
    generate_facies_polygon_layer,
    simplify_collinear_ring,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def make_grid_result(
    grid_z: np.ndarray,
    extent: tuple[float, float, float, float] = (0.0, 0.0, 100.0, 100.0),
    factor_name: str = "porosity",
) -> FactorGridResult:
    h, w = grid_z.shape
    xmin, ymin, xmax, ymax = extent
    gx = np.linspace(xmin, xmax, w)
    gy = np.linspace(ymin, ymax, h)
    return FactorGridResult(
        grid_z=grid_z,
        grid_x=gx,
        grid_y=gy,
        factor_name=factor_name,
        algorithm_id="kriging",
        unit="%",
        crs="EPSG:3857",
    )


# ==============================================================================
# 1. 100% NaN Grids and Partially Masked Grids
# ==============================================================================

def test_100_percent_nan_grids():
    """Verify 100% NaN grids in contouring and polygonization gracefully produce empty layers."""
    for shape_tuple in [(10, 10), (1, 1), (1, 100), (100, 1), (50, 2)]:
        z = np.full(shape_tuple, np.nan)
        res = make_grid_result(z)

        # Contouring
        c_layer = generate_contour_layer(res)
        assert len(c_layer.features) == 0
        assert len(c_layer.levels) == 0

        # Polygonization
        p_layer = generate_facies_polygon_layer(res)
        assert len(p_layer.features) == 0


def test_partial_nan_grids_shoelace_conservation():
    """Verify that when cells are NaN, Shoelace area matches exactly finite cell count area."""
    h, w = 20, 20
    z = np.full((h, w), 10.0)
    # Mask 50 cells out of 400 as NaN
    z[:5, :10] = np.nan

    extent = (0.0, 0.0, 200.0, 200.0)
    res = make_grid_result(z, extent=extent)

    p_layer = generate_facies_polygon_layer(res, thresholds=[5.0], facies_names=["有效带"])
    assert len(p_layer.features) == 1
    feature = p_layer.features[0]

    geom = feature["geometry"]
    s_geom = shape(geom)
    assert s_geom.is_valid

    # Domain area = 200 * 200 = 40000
    # Total cells = 400. Masked cells = 50. Valid cells = 350.
    # Expected area = 40000 * (350 / 400) = 35000.0
    cell_area = (200.0 / w) * (200.0 / h)
    expected_valid_area = 350 * cell_area
    assert math.isclose(feature["properties"]["area"], expected_valid_area, rel_tol=1e-5)
    assert math.isclose(feature["properties"]["area_percent"], (350.0 / 400.0) * 100.0, rel_tol=1e-5)


# ==============================================================================
# 2. Uniform Flat Grids (vmin == vmax)
# ==============================================================================

def test_uniform_flat_grid():
    """Verify flat grids produce 0 contours and 1 full-extent valid facies polygon."""
    z = np.full((15, 15), 25.5)
    extent = (1000.0, 2000.0, 1500.0, 3000.0)
    expected_total_area = (1500.0 - 1000.0) * (3000.0 - 2000.0)  # 500 * 1000 = 500,000

    res = make_grid_result(z, extent=extent)

    # Contours should be empty
    c_layer = generate_contour_layer(res)
    assert len(c_layer.features) == 0

    # Polygon should cover the full domain
    p_layer = generate_facies_polygon_layer(res)
    assert len(p_layer.features) == 1
    feat = p_layer.features[0]
    assert feat["properties"]["facies_name"] == "均一相带"
    assert math.isclose(feat["properties"]["area"], expected_total_area, rel_tol=1e-5)
    assert math.isclose(feat["properties"]["area_percent"], 100.0, rel_tol=1e-5)

    s_geom = shape(feat["geometry"])
    assert s_geom.is_valid
    assert math.isclose(s_geom.area, expected_total_area, rel_tol=1e-5)


# ==============================================================================
# 3. Degenerate Dimension Grids (1x1, 1xN, Nx1)
# ==============================================================================

def test_degenerate_1x1_and_strips():
    """Verify single cell and 1D strip grids do not crash and handle degenerates safely."""
    # 1x1 grid
    z_1x1 = np.array([[12.0]])
    res_1x1 = make_grid_result(z_1x1, extent=(0.0, 0.0, 50.0, 50.0))
    c_1x1 = generate_contour_layer(res_1x1)
    assert len(c_1x1.features) == 0
    p_1x1 = generate_facies_polygon_layer(res_1x1)
    assert len(p_1x1.features) == 0  # Single point extent has dx=0, dy=0

    # 1x10 strip (1D grid with height=0 in 2D space)
    z_1x10 = np.array([[float(i) for i in range(10)]])
    res_1x10 = make_grid_result(z_1x10, extent=(0.0, 0.0, 100.0, 10.0))
    c_1x10 = generate_contour_layer(res_1x10)
    assert len(c_1x10.features) == 0  # Marching squares requires at least 2x2
    p_1x10 = generate_facies_polygon_layer(res_1x10, thresholds=[3.0, 7.0])
    assert len(p_1x10.features) == 0  # 1D line has zero 2D planar area


# ==============================================================================
# 4. Extreme Aspect Ratio Grids (1000:1 and 1:1000)
# ==============================================================================

def test_extreme_aspect_ratio_1000_to_1():
    """Verify Marching Squares and Polygonization with 1000:1 aspect ratios."""
    # 1000 rows, 4 cols
    h, w = 1000, 4
    y_grad = np.linspace(0, 100, h)[:, None]
    z = np.repeat(y_grad, w, axis=1)
    extent = (0.0, 0.0, 10.0, 10000.0)
    res = make_grid_result(z, extent=extent)

    # Contours across 1000 rows
    c_layer = generate_contour_layer(res, interval=10.0)
    assert len(c_layer.features) > 0
    for feat in c_layer.features:
        coords = feat["geometry"]["coordinates"]
        assert len(coords) >= 2
        # Isoline should span horizontal x range 0 to 10
        assert math.isclose(coords[0][0], 0.0, abs_tol=1e-3)
        assert math.isclose(coords[-1][0], 10.0, abs_tol=1e-3)

    # Facies polygonization with collinear simplification on 1000 rows
    p_layer = generate_facies_polygon_layer(res, thresholds=[30.0, 70.0], facies_names=["Bottom", "Middle", "Top"])
    assert len(p_layer.features) == 3
    total_area = sum(f["properties"]["area"] for f in p_layer.features)
    assert math.isclose(total_area, 10.0 * 10000.0, rel_tol=1e-4)

    # Check collinear simplification worked: vertices should be compact (<= 10 vertices), not thousands
    for f in p_layer.features:
        s_geom = shape(f["geometry"])
        assert s_geom.is_valid
        poly_coords = f["geometry"]["coordinates"][0]
        assert len(poly_coords) <= 10  # Rectangles simplified to 5 points (4 corners + closing point)


# ==============================================================================
# 5. Checkerboard Saddle Patterns & Saddle Disambiguation
# ==============================================================================

def test_checkerboard_saddle_marching_squares_and_polygonization():
    """Verify Marching Squares center-average saddle disambiguation on alternating 8x8 checkerboard."""
    h, w = 8, 8
    z = np.zeros((h, w))
    for i in range(h):
        for j in range(w):
            z[i, j] = 10.0 if (i + j) % 2 == 0 else 0.0

    extent = (0.0, 0.0, 80.0, 80.0)
    res = make_grid_result(z, extent=extent)

    # Level exactly at saddle average 5.0
    c_layer = generate_contour_layer(res, levels=[5.0])
    assert len(c_layer.features) > 0
    for feat in c_layer.features:
        assert feat["geometry"]["type"] == "LineString"
        assert len(feat["geometry"]["coordinates"]) >= 2

    # Facies polygonization on checkerboard
    p_layer = generate_facies_polygon_layer(res, thresholds=[5.0], facies_names=["Low", "High"])
    assert len(p_layer.features) > 0

    total_area = sum(f["properties"]["area"] for f in p_layer.features)
    assert math.isclose(total_area, 80.0 * 80.0, rel_tol=1e-4)

    for feat in p_layer.features:
        s_geom = shape(feat["geometry"])
        assert s_geom.is_valid


def test_marching_squares_saddle_cases_5_and_10_explicit():
    """Explicit test of saddle resolution cases 5 and 10."""
    z = np.array([
        [10.0, 0.0],
        [0.0, 10.0]
    ])
    gx = np.array([0.0, 10.0])
    gy = np.array([0.0, 10.0])

    # Level 4.0 (center >= level)
    lines_4 = _marching_squares_pure_python(z, gx, gy, level=4.0)
    assert len(lines_4) == 2

    # Level 6.0 (center < level)
    lines_6 = _marching_squares_pure_python(z, gx, gy, level=6.0)
    assert len(lines_6) == 2

    # Case 10: z00=0, z10=10, z11=0, z01=10 -> center=5
    z10 = np.array([
        [0.0, 10.0],
        [10.0, 0.0]
    ])
    lines_10_4 = _marching_squares_pure_python(z10, gx, gy, level=4.0)
    assert len(lines_10_4) == 2
    lines_10_6 = _marching_squares_pure_python(z10, gx, gy, level=6.0)
    assert len(lines_10_6) == 2


# ==============================================================================
# 6. Isolated Single-Pixel Anomalies
# ==============================================================================

def test_isolated_single_pixel_peak_and_pit():
    """Verify single-pixel spike in the middle of a flat plane."""
    # Peak
    z_peak = np.zeros((7, 7))
    z_peak[3, 3] = 100.0
    res_peak = make_grid_result(z_peak, extent=(0.0, 0.0, 70.0, 70.0))

    c_layer = generate_contour_layer(res_peak, levels=[50.0])
    assert len(c_layer.features) == 1
    assert c_layer.features[0]["properties"]["is_closed"] is True

    p_layer = generate_facies_polygon_layer(res_peak, thresholds=[50.0], facies_names=["Background", "Spike"])
    assert len(p_layer.features) == 2  # Background with 1 hole, and Spike polygon
    total_area = sum(f["properties"]["area"] for f in p_layer.features)
    assert math.isclose(total_area, 70.0 * 70.0, rel_tol=1e-4)

    # Spike area should be exactly 1 cell area: 10 * 10 = 100
    spike_feat = next(f for f in p_layer.features if f["properties"]["facies_name"] == "Spike")
    assert math.isclose(spike_feat["properties"]["area"], 100.0, rel_tol=1e-4)

    bg_feat = next(f for f in p_layer.features if f["properties"]["facies_name"] == "Background")
    assert math.isclose(bg_feat["properties"]["area"], 4800.0, rel_tol=1e-4)

    for f in p_layer.features:
        assert shape(f["geometry"]).is_valid


# ==============================================================================
# 7. Concentric Nested Rings and Holes (2-level: Donut & Island)
# ==============================================================================

def test_concentric_nested_rings_facies_polygonization():
    """Verify 2-level nesting: Outer High -> Middle Low (Donut) -> Inner High (Island)."""
    # 15x15 grid
    # Radius from center (7, 7)
    y, x = np.ogrid[:15, :15]
    dist_sq = (x - 7) ** 2 + (y - 7) ** 2

    # Center (r <= 2): High (10)
    # Ring (2 < r <= 5): Low (2)
    # Outer (r > 5): High (10)
    z = np.where(dist_sq <= 4, 10.0, np.where(dist_sq <= 25, 2.0, 10.0))
    res = make_grid_result(z, extent=(0.0, 0.0, 150.0, 150.0))

    p_layer = generate_facies_polygon_layer(res, thresholds=[5.0], facies_names=["Low_Ring", "High_Zone"])

    total_area = sum(f["properties"]["area"] for f in p_layer.features)
    assert math.isclose(total_area, 150.0 * 150.0, rel_tol=1e-4)

    for feat in p_layer.features:
        geom = feat["geometry"]
        s_geom = shape(geom)
        assert s_geom.is_valid


# ==============================================================================
# 8. Multi-Level Nested Holes Area Conservation (3-Level: Continent->Lake->Island->Pond)
# ==============================================================================

def test_multi_level_nested_holes_area_conservation():
    """Adversarial stress test for 3-level nested topology: Continent -> Lake -> Island -> Pond.

    Tests that innermost holes are assigned to innermost containing polygons rather than
    outermost polygons, preserving exact domain area conservation.
    """
    y, x = np.ogrid[:31, :31]
    r_sq = (x - 15) ** 2 + (y - 15) ** 2

    # Pond (r <= 2): High (10)
    # Island (2 < r <= 6): Low (0)
    # Lake (6 < r <= 10): High (10)
    # Continent (r > 10): Low (0)
    z = np.zeros((31, 31), dtype=np.float32)
    z[r_sq <= 100] = 10.0  # Lake (High)
    z[r_sq <= 36] = 0.0    # Island (Low)
    z[r_sq <= 4] = 10.0    # Pond (High)

    domain_extent = (0.0, 0.0, 310.0, 310.0)
    expected_domain_area = 310.0 * 310.0  # 96,100

    res = make_grid_result(z, extent=domain_extent)
    p_layer = generate_facies_polygon_layer(res, thresholds=[5.0], facies_names=["Low_Facies", "High_Facies"])

    total_area = sum(f["properties"]["area"] for f in p_layer.features)
    assert math.isclose(total_area, expected_domain_area, rel_tol=1e-4), (
        f"Multi-level nested holes area overcounted: got {total_area}, expected {expected_domain_area}"
    )


# ==============================================================================
# 9. Polygon Topology & GeoJSON Ring Orientation Invariants
# ==============================================================================

def test_polygon_topology_and_orientation_invariants():
    """Verify all generated polygons strictly satisfy GeoJSON CCW exterior / CW interior invariants."""
    np.random.seed(12345)
    z = np.random.uniform(0, 100, size=(25, 25))
    res = make_grid_result(z, extent=(100.0, 200.0, 600.0, 700.0))

    p_layer = generate_facies_polygon_layer(
        res,
        thresholds=[25.0, 50.0, 75.0],
        facies_names=["F1", "F2", "F3", "F4"],
    )

    for feat in p_layer.features:
        geom = feat["geometry"]
        s_geom = shape(geom)
        assert s_geom.is_valid

        if geom["type"] == "Polygon":
            polys = [geom["coordinates"]]
        else:
            polys = geom["coordinates"]

        for poly_coords in polys:
            ext = poly_coords[0]
            # Exterior ring: CCW -> signed area > 0
            assert calculate_signed_area(ext) > 0, "Exterior ring must be oriented CCW"
            # Holes: CW -> signed area < 0
            for hole in poly_coords[1:]:
                assert calculate_signed_area(hole) < 0, "Interior hole must be oriented CW"


# ==============================================================================
# 10. Exact Shoelace Area Conservation on Complex Surfaces
# ==============================================================================

def test_shoelace_area_exact_conservation():
    """Verify exact Shoelace area conservation: sum(facies_area) == domain_area across continuous surfaces."""
    extent = (1200.0, 3400.0, 2200.0, 4900.0)
    domain_area = (2200.0 - 1200.0) * (4900.0 - 3400.0)  # 1000 * 1500 = 1,500,000

    # Gaussian hill pattern
    x = np.linspace(-3, 3, 30)
    y = np.linspace(-3, 3, 40)
    xx, yy = np.meshgrid(x, y)
    z = 100.0 * np.exp(-(xx**2 + yy**2) / 2.0)

    res = make_grid_result(z, extent=extent)
    p_layer = generate_facies_polygon_layer(
        res,
        thresholds=[10.0, 30.0, 60.0, 85.0],
        facies_names=["Zone1", "Zone2", "Zone3", "Zone4", "Zone5"],
    )

    sum_areas = sum(f["properties"]["area"] for f in p_layer.features)
    sum_pct = sum(f["properties"]["area_percent"] for f in p_layer.features)

    assert math.isclose(sum_areas, domain_area, rel_tol=1e-5)
    assert math.isclose(sum_pct, 100.0, rel_tol=1e-5)


# ==============================================================================
# 11. Douglas-Peucker & Chaikin Corner-Cutting Edge Cases
# ==============================================================================

def test_douglas_peucker_and_chaikin_edge_cases():
    """Verify simplification and smoothing on closed loops and degenerate lines."""
    # Degenerate 1-point and 2-point polylines
    assert douglas_peucker_2d([], 1.0) == []
    assert douglas_peucker_2d([[0.0, 0.0]], 1.0) == [[0.0, 0.0]]
    assert douglas_peucker_2d([[0.0, 0.0], [1.0, 1.0]], 1.0) == [[0.0, 0.0], [1.0, 1.0]]

    # Closed square polyline
    sq = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    # Chaikin smooth 2 iterations
    smoothed = chaikin_smooth(sq, iterations=2)
    assert len(smoothed) > len(sq)
    # Must remain closed
    assert math.isclose(smoothed[0][0], smoothed[-1][0], abs_tol=1e-5)
    assert math.isclose(smoothed[0][1], smoothed[-1][1], abs_tol=1e-5)

    # Open line smoothing
    line = [[0.0, 0.0], [5.0, 10.0], [10.0, 0.0]]
    sm_line = chaikin_smooth(line, iterations=1)
    assert len(sm_line) == 6
    assert sm_line[0] == [0.0, 0.0]
    assert sm_line[-1] == [10.0, 0.0]


# ==============================================================================
# 12. Extreme Numerical Ranges
# ==============================================================================

def test_extreme_numerical_ranges():
    """Verify nice levels and contouring under micro (1e-6) and astronomical (1e9) scales."""
    # Micro scale
    z_micro = np.array([
        [1.0e-6, 2.0e-6, 3.0e-6],
        [2.0e-6, 4.0e-6, 2.0e-6],
        [3.0e-6, 2.0e-6, 1.0e-6]
    ])
    res_micro = make_grid_result(z_micro)
    c_micro = generate_contour_layer(res_micro)
    assert len(c_micro.levels) > 0

    # Macro scale
    z_macro = np.array([
        [1.0e8, 2.0e8, 3.0e8],
        [2.0e8, 5.0e8, 2.0e8],
        [3.0e8, 2.0e8, 1.0e8]
    ])
    res_macro = make_grid_result(z_macro)
    c_macro = generate_contour_layer(res_macro)
    assert len(c_macro.levels) > 0

    # Negative scale
    z_neg = np.array([
        [-500.0, -300.0, -100.0],
        [-400.0, -200.0, -50.0],
        [-300.0, -100.0, 0.0]
    ])
    res_neg = make_grid_result(z_neg)
    c_neg = generate_contour_layer(res_neg)
    assert len(c_neg.levels) > 0
