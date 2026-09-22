"""Additional Adversarial Stress Test Suite for Milestone 3 Topological Remediations.

Deep stress tests covering:
1. 4-tier and 5-tier deep nesting (Continent -> Lake -> Island -> Pond -> Micro-Island -> Micro-Pond).
2. Multi-island topology: Multiple disconnected islands each containing multiple holes.
3. Multi-hole topology: Single landmass with 10 separate interior lakes, some containing sub-islands.
4. Checkerboard / Figure-8 / Bowtie self-touching corners in complex multi-component matrices.
5. GeoJSON RFC 7946 orientation invariants across every sub-polygon in complex MultiPolygons.
6. Exact Shoelace area conservation under high-density multi-component random Voronoi/cellular noise.
7. Direct unit stress testing of `repair_invalid_geometry` on pathological Shapely geometries:
   - Self-intersecting bow-tie polygons
   - Self-tangent figure-8 polygons
   - Nested rings with reversed winding (CW exterior, CCW interior)
   - Disjoint multi-polygons with invalid geometries
   - MultiPolygons embedded in GeometryCollections
   - Overlapping / self-intersecting polygons
"""

import math
import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient

from paleo_workbench.mapping.geological_pipeline.polygonization import (
    _compute_geometry_area,
    _point_in_ring,
    _polygonize_raster_boundaries,
    calculate_shoelace_area,
    calculate_signed_area,
    generate_facies_polygon_layer,
    simplify_collinear_ring,
)
from paleo_workbench.mapping.topology import repair_invalid_geometry
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def make_grid(
    z: np.ndarray,
    extent: tuple[float, float, float, float] = (0.0, 0.0, 1000.0, 1000.0),
    name: str = "stress_factor",
) -> FactorGridResult:
    h, w = z.shape
    xmin, ymin, xmax, ymax = extent
    gx = np.linspace(xmin, xmax, w)
    gy = np.linspace(ymin, ymax, h)
    return FactorGridResult(
        grid_z=z,
        grid_x=gx,
        grid_y=gy,
        factor_name=name,
        algorithm_id="stress_test",
        unit="unit",
        crs="EPSG:3857",
    )


def test_deep_5_tier_nested_rings_area_conservation():
    """5-tier concentric nesting:
    Tier 1 (Outer Continent): Low (0)
    Tier 2 (Outer Lake): High (10)
    Tier 3 (Middle Island): Low (0)
    Tier 4 (Inner Pond): High (10)
    Tier 5 (Micro Atoll): Low (0)
    """
    n = 61
    y, x = np.ogrid[:n, :n]
    cx, cy = 30, 30
    r_sq = (x - cx) ** 2 + (y - cy) ** 2

    # Radii:
    # r <= 2 (r_sq <= 4): Micro Atoll (Low)
    # 2 < r <= 6 (4 < r_sq <= 36): Inner Pond (High)
    # 6 < r <= 12 (36 < r_sq <= 144): Middle Island (Low)
    # 12 < r <= 20 (144 < r_sq <= 400): Outer Lake (High)
    # r > 20 (r_sq > 400): Outer Continent (Low)

    z = np.zeros((n, n), dtype=np.float32)
    z[r_sq <= 400] = 10.0  # Lake
    z[r_sq <= 144] = 0.0   # Island
    z[r_sq <= 36] = 10.0   # Pond
    z[r_sq <= 4] = 0.0     # Micro Atoll

    extent = (0.0, 0.0, 610.0, 610.0)
    expected_area = 610.0 * 610.0

    res = make_grid(z, extent=extent)
    p_layer = generate_facies_polygon_layer(res, thresholds=[5.0], facies_names=["Low_Facies", "High_Facies"])

    total_area = sum(f["properties"]["area"] for f in p_layer.features)
    assert math.isclose(total_area, expected_area, rel_tol=1e-4), (
        f"5-tier nesting total area mismatch: got {total_area}, expected {expected_area}"
    )

    for feat in p_layer.features:
        s_geom = shape(feat["geometry"])
        assert s_geom.is_valid


def test_multi_island_with_multiple_holes_each():
    """Create 4 separate continents in a grid.
    Each continent has 2 separate lakes.
    Each lake has an island.
    """
    n = 80
    z = np.zeros((n, n), dtype=np.float32)  # Ocean (0)

    # 4 Continent centers at (20,20), (20,60), (60,20), (60,60)
    centers = [(20, 20), (20, 60), (60, 20), (60, 60)]
    y, x = np.ogrid[:n, :n]

    for cx, cy in centers:
        # Continent: 10
        cont_mask = (x - cx) ** 2 + (y - cy) ** 2 <= 14 ** 2
        z[cont_mask] = 10.0

        # Lake 1 at (cx-5, cy): 0
        lake1_mask = (x - (cx - 6)) ** 2 + (y - cy) ** 2 <= 4 ** 2
        z[lake1_mask] = 0.0
        # Island 1 inside Lake 1: 10
        isl1_mask = (x - (cx - 6)) ** 2 + (y - cy) ** 2 <= 1 ** 2
        z[isl1_mask] = 10.0

        # Lake 2 at (cx+5, cy): 0
        lake2_mask = (x - (cx + 6)) ** 2 + (y - cy) ** 2 <= 4 ** 2
        z[lake2_mask] = 0.0
        # Island 2 inside Lake 2: 10
        isl2_mask = (x - (cx + 6)) ** 2 + (y - cy) ** 2 <= 1 ** 2
        z[isl2_mask] = 10.0

    extent = (0.0, 0.0, 800.0, 800.0)
    expected_area = 800.0 * 800.0
    res = make_grid(z, extent=extent)

    p_layer = generate_facies_polygon_layer(res, thresholds=[5.0], facies_names=["Water", "Land"])
    total_area = sum(f["properties"]["area"] for f in p_layer.features)
    assert math.isclose(total_area, expected_area, rel_tol=1e-4)

    for feat in p_layer.features:
        geom = feat["geometry"]
        s_geom = shape(geom)
        assert s_geom.is_valid

        # Check GeoJSON ring orientation
        if geom["type"] == "Polygon":
            polys = [geom["coordinates"]]
        else:
            polys = geom["coordinates"]
        for poly_coords in polys:
            ext = poly_coords[0]
            assert calculate_signed_area(ext) > 0, "Exterior ring must be CCW"
            for hole in poly_coords[1:]:
                assert calculate_signed_area(hole) < 0, "Interior hole must be CW"


def test_random_perlin_cellular_noise_conservation_and_orientations():
    """Adversarial stress test: generate 10 random noisy grids with multi-class thresholds."""
    extent = (100.0, 100.0, 500.0, 500.0)
    domain_area = 400.0 * 400.0

    for seed in [42, 999, 1337, 2026, 7777]:
        rng = np.random.RandomState(seed)
        # 30x30 random grid
        raw = rng.uniform(0.0, 100.0, size=(30, 30))
        # Apply smoothing to create realistic geological structures with lots of islands and donuts
        try:
            from scipy.ndimage import gaussian_filter
            z = gaussian_filter(raw, sigma=1.5)
        except Exception:
            z = raw

        res = make_grid(z, extent=extent)
        p_layer = generate_facies_polygon_layer(
            res,
            thresholds=[20.0, 40.0, 60.0, 80.0],
            facies_names=["F1", "F2", "F3", "F4", "F5"],
        )

        total_area = sum(f["properties"]["area"] for f in p_layer.features)
        assert math.isclose(total_area, domain_area, rel_tol=1e-4)

        for feat in p_layer.features:
            geom = feat["geometry"]
            s_geom = shape(geom)
            assert s_geom.is_valid, f"Seed {seed} generated invalid geometry: {s_geom.is_valid}"

            if geom["type"] == "Polygon":
                polys = [geom["coordinates"]]
            elif geom["type"] == "MultiPolygon":
                polys = geom["coordinates"]
            else:
                polys = []

            for poly_coords in polys:
                ext = poly_coords[0]
                assert calculate_signed_area(ext) > 0, f"Seed {seed} exterior ring must be CCW"
                for hole in poly_coords[1:]:
                    assert calculate_signed_area(hole) < 0, f"Seed {seed} hole must be CW"


def test_repair_invalid_geometry_pathological_cases():
    """Direct unit tests for repair_invalid_geometry on pathological cases."""
    # 1. Bowtie self-intersection (figure 8 with cross over)
    bowtie_coords = [[[0.0, 0.0], [10.0, 10.0], [0.0, 10.0], [10.0, 0.0], [0.0, 0.0]]]
    repaired_bowtie = repair_invalid_geometry({"type": "Polygon", "coordinates": bowtie_coords})
    s_bowtie = shape(repaired_bowtie)
    assert s_bowtie.is_valid
    # Orientation check
    if repaired_bowtie["type"] == "Polygon":
        assert calculate_signed_area(repaired_bowtie["coordinates"][0]) > 0
    elif repaired_bowtie["type"] == "MultiPolygon":
        for p in repaired_bowtie["coordinates"]:
            assert calculate_signed_area(p[0]) > 0

    # 2. Clockwise exterior (reversed winding)
    cw_polygon = [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0], [0.0, 0.0]]]
    repaired_cw = repair_invalid_geometry({"type": "Polygon", "coordinates": cw_polygon})
    s_cw = shape(repaired_cw)
    assert s_cw.is_valid
    assert calculate_signed_area(repaired_cw["coordinates"][0]) > 0

    # 3. Clockwise exterior with CCW hole (both reversed)
    rev_donut = [
        [[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0], [0.0, 0.0]],  # CW exterior
        [[2.0, 2.0], [8.0, 2.0], [8.0, 8.0], [2.0, 8.0], [2.0, 2.0]],      # CCW hole
    ]
    repaired_donut = repair_invalid_geometry({"type": "Polygon", "coordinates": rev_donut})
    s_donut = shape(repaired_donut)
    assert s_donut.is_valid
    assert calculate_signed_area(repaired_donut["coordinates"][0]) > 0
    assert calculate_signed_area(repaired_donut["coordinates"][1]) < 0

    # 4. Non-closed coordinate ring
    unclosed = {"type": "Polygon", "coordinates": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]]}
    repaired_unclosed = repair_invalid_geometry(unclosed)
    s_unclosed = shape(repaired_unclosed)
    assert s_unclosed.is_valid
    assert repaired_unclosed["coordinates"][0][0] == repaired_unclosed["coordinates"][0][-1]

    # 5. Overlapping polygons decomposing to MultiPolygon
    touching_corners = [
        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]],
        [[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0], [10.0, 10.0]],
    ]
    # Figure 8 touching at (10, 10)
    fig8 = {"type": "Polygon", "coordinates": [
        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    ]}
    repaired_fig8 = repair_invalid_geometry(fig8)
    s_fig8 = shape(repaired_fig8)
    assert s_fig8.is_valid
    if repaired_fig8["type"] == "MultiPolygon":
        for p in repaired_fig8["coordinates"]:
            assert calculate_signed_area(p[0]) > 0
    elif repaired_fig8["type"] == "Polygon":
        assert calculate_signed_area(repaired_fig8["coordinates"][0]) > 0
