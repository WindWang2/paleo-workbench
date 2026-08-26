"""Empirical Adversarial Stress Tests for Milestone 3 (Geological Mapping Pipeline).

Tests extreme edge cases, singular configurations, boundary conditions, and multithreaded
concurrency across Factor Extraction, IDW, Kriging, Marching Squares Contouring, Facies
Polygonization, and FactorGridResult.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import threading
from typing import Any

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline.contouring import (
    calculate_nice_contour_levels,
    calculate_quantile_contour_levels,
    calculate_polyline_length,
    chaikin_smooth,
    douglas_peucker_2d,
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.interpolator import (
    IDWInterpolator,
    KrigingInterpolator,
    _pure_numpy_kriging,
    interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (
    GeologicalMappingPipeline,
    _find_matching_aliases,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    calculate_shoelace_area,
    generate_facies_polygon_layer,
)
from paleo_workbench.workflow.factor_grid_result import (
    FactorGridResult,
    GridStatistics,
    NODATA,
)


# ===========================================================================
# 1. Collinear Sample Points Stress Tests
# ===========================================================================

class TestCollinearSamplePoints:
    """Stress test spatial interpolation when all sample points lie on a straight line."""

    @pytest.mark.parametrize(
        "coords, values",
        [
            # Horizontal line (y = 50)
            ([(10.0, 50.0), (30.0, 50.0), (50.0, 50.0), (70.0, 50.0), (90.0, 50.0)], [10.0, 15.0, 20.0, 25.0, 30.0]),
            # Vertical line (x = 100)
            ([(100.0, 10.0), (100.0, 30.0), (100.0, 50.0), (100.0, 70.0), (100.0, 90.0)], [5.0, 12.0, 18.0, 22.0, 35.0]),
            # Diagonal line (y = 2x - 5)
            ([(0.0, -5.0), (10.0, 15.0), (20.0, 35.0), (30.0, 55.0), (40.0, 75.0)], [1.0, 4.0, 9.0, 16.0, 25.0]),
            # Negative slope line (y = -0.5x + 100)
            ([(0.0, 100.0), (50.0, 75.0), (100.0, 50.0), (150.0, 25.0), (200.0, 0.0)], [50.0, 40.0, 30.0, 20.0, 10.0]),
        ],
    )
    def test_collinear_idw_and_kriging_numerical_stability(
        self, coords: list[tuple[float, float]], values: list[float]
    ):
        """Both IDW and Kriging must solve collinear configurations without singular matrix crashes."""
        dataset = GeologicalFactorDataset(
            factor_name="porosity",
            unit="%",
            points=[
                GeologicalFactor(
                    name="porosity",
                    value=val,
                    x=x,
                    y=y,
                    well_name=f"Well_{i}",
                )
                for i, ((x, y), val) in enumerate(zip(coords, values))
            ],
        )

        assert not dataset.validate(), "Collinear points with non-zero spread should pass dataset validation"

        # 1. IDW
        idw_res = IDWInterpolator().interpolate(dataset, InterpolationOptions(method="idw", grid_n=30))
        assert idw_res.shape == (30, 30)
        assert np.all(np.isfinite(idw_res.grid_z)), "IDW grid on collinear points must be finite"
        assert idw_res.statistics.valid_count == 30 * 30

        # 2. Kriging with all variogram models
        for model in ("spherical", "exponential", "gaussian"):
            krig_opts = InterpolationOptions(method="kriging", variogram_model=model, grid_n=30)
            krig_res = KrigingInterpolator().interpolate(dataset, krig_opts)
            assert krig_res.shape == (30, 30)
            assert np.all(np.isfinite(krig_res.grid_z)), f"Kriging ({model}) grid on collinear points must be finite"
            if krig_res.variance_grid is not None:
                assert np.all(np.isfinite(krig_res.variance_grid))
                assert np.all(krig_res.variance_grid >= 0.0)

        # 3. Pure numpy fallback directly
        xs, ys, zs = dataset.to_arrays()
        gx = np.linspace(min(xs), max(xs), 20)
        gy = np.linspace(min(ys), max(ys), 20)
        gz, gvar, params = _pure_numpy_kriging(xs, ys, zs, gx, gy, model="gaussian")
        assert np.all(np.isfinite(gz))
        assert np.all(np.isfinite(gvar))
        assert np.all(gvar >= 0.0)

    def test_collinear_end_to_end_contour_and_polygon_generation(self):
        """End-to-end mapping pipeline on collinear wells generates valid map document."""
        points = [
            {"well": f"W{i}", "x": float(i * 100), "y": float(i * 100), "POR": float(10 + i * 3)}
            for i in range(6)
        ]
        pipeline = GeologicalMappingPipeline()
        dataset = pipeline.extract_factors(points, "porosity")
        doc = pipeline.build_factor_map_document(
            dataset,
            InterpolationOptions(method="idw", grid_n=40),
            include_grid=True,
            include_contours=True,
            include_polygons=True,
            include_wells=True,
        )

        assert len(doc.layers) == 4
        assert doc.extent[0] < doc.extent[2]
        assert doc.extent[1] < doc.extent[3]


# ===========================================================================
# 2. Duplicate and Collocated Coordinates Stress Tests
# ===========================================================================

class TestDuplicateCoordinates:
    """Stress test handling of identical or duplicate (x, y) coordinates."""

    def test_exact_duplicate_coordinates_same_values(self):
        """Exact duplicate coordinates with identical values must be handled smoothly."""
        dataset = GeologicalFactorDataset(
            factor_name="permeability",
            unit="mD",
            points=[
                GeologicalFactor(name="permeability", value=15.0, x=100.0, y=200.0, well_name="W1"),
                GeologicalFactor(name="permeability", value=15.0, x=100.0, y=200.0, well_name="W1_dup"),
                GeologicalFactor(name="permeability", value=30.0, x=300.0, y=400.0, well_name="W2"),
                GeologicalFactor(name="permeability", value=45.0, x=500.0, y=200.0, well_name="W3"),
            ],
        )

        # IDW
        idw_res = IDWInterpolator().interpolate(dataset, InterpolationOptions(method="idw", grid_n=25))
        assert np.all(np.isfinite(idw_res.grid_z))

        # Kriging
        krig_res = KrigingInterpolator().interpolate(dataset, InterpolationOptions(method="kriging", grid_n=25))
        assert np.all(np.isfinite(krig_res.grid_z))

    def test_duplicate_coordinates_conflicting_values(self):
        """Duplicate coordinates with conflicting values (e.g. multi-layer or re-entry well)."""
        dataset = GeologicalFactorDataset(
            factor_name="thickness",
            unit="m",
            points=[
                GeologicalFactor(name="thickness", value=10.0, x=50.0, y=50.0, well_name="W1_A"),
                GeologicalFactor(name="thickness", value=20.0, x=50.0, y=50.0, well_name="W1_B"),
                GeologicalFactor(name="thickness", value=30.0, x=150.0, y=50.0, well_name="W2"),
                GeologicalFactor(name="thickness", value=40.0, x=100.0, y=150.0, well_name="W3"),
            ],
        )

        # IDW should not crash and produce finite predictions
        idw_res = IDWInterpolator().interpolate(dataset, InterpolationOptions(method="idw", grid_n=20))
        assert np.all(np.isfinite(idw_res.grid_z))

        # Kriging should deduplicate by averaging conflicting values (15.0) and solve
        krig_res = KrigingInterpolator().interpolate(dataset, InterpolationOptions(method="kriging", grid_n=20))
        assert np.all(np.isfinite(krig_res.grid_z))

    def test_all_points_collocated_rejected_by_dataset(self):
        """When 100% of points are at the exact same point, validate() reports issue."""
        dataset = GeologicalFactorDataset(
            factor_name="porosity",
            points=[
                GeologicalFactor(name="porosity", value=10.0, x=100.0, y=100.0, well_name="W1"),
                GeologicalFactor(name="porosity", value=20.0, x=100.0, y=100.0, well_name="W2"),
                GeologicalFactor(name="porosity", value=30.0, x=100.0, y=100.0, well_name="W3"),
            ],
        )
        issues = dataset.validate()
        assert any("collocated" in iss.lower() for iss in issues)
        with pytest.raises(ValueError, match="collocated"):
            IDWInterpolator().interpolate(dataset, InterpolationOptions())


# ===========================================================================
# 3. Zero Variance Constant Values Stress Tests
# ===========================================================================

class TestZeroVarianceConstantValues:
    """Stress test when all sample observations have the exact same numeric value (zero variance)."""

    def test_zero_variance_kriging_and_idw(self):
        """Constant sample field (sill = 0) produces a perfectly flat prediction grid."""
        constant_val = 42.0
        points = [
            GeologicalFactor(name="porosity", value=constant_val, x=float(x), y=float(y), well_name=f"W_{i}")
            for i, (x, y) in enumerate([(0, 0), (100, 0), (0, 100), (100, 100), (50, 50), (25, 75)])
        ]
        dataset = GeologicalFactorDataset(factor_name="porosity", points=points)

        # IDW
        idw_res = IDWInterpolator().interpolate(dataset, InterpolationOptions(method="idw", grid_n=20))
        assert np.allclose(idw_res.grid_z, constant_val, atol=1e-5)
        assert math.isclose(idw_res.statistics.min, constant_val)
        assert math.isclose(idw_res.statistics.max, constant_val)
        assert math.isclose(idw_res.statistics.std, 0.0, abs_tol=1e-6)

        # Kriging
        krig_res = KrigingInterpolator().interpolate(dataset, InterpolationOptions(method="kriging", grid_n=20))
        assert np.allclose(krig_res.grid_z, constant_val, atol=1e-4)

    def test_zero_variance_contouring_and_polygonization(self):
        """Contouring and facies polygonization handle uniform grids gracefully."""
        flat_grid = FactorGridResult(
            grid_z=np.full((30, 30), 25.0, dtype=np.float32),
            grid_x=np.linspace(0, 100, 30),
            grid_y=np.linspace(0, 100, 30),
            factor_name="porosity",
            algorithm_id="idw",
        )

        # Nice contour levels on flat grid returns empty list
        nice_levels = calculate_nice_contour_levels(25.0, 25.0)
        assert nice_levels == []

        # Contours layer generates 0 contour features without crashing
        contour_layer = generate_contour_layer(flat_grid, levels=[10.0, 20.0, 30.0])
        assert len(contour_layer.features) == 0

        # Polygonization generates a single uniform polygon for the matching facies
        poly_layer = generate_facies_polygon_layer(
            flat_grid,
            thresholds=[20.0, 30.0],
            facies_names=["Low", "Medium", "High"],
        )
        assert len(poly_layer.features) >= 1
        # The medium facies should cover 100% of the area
        medium_feat = [f for f in poly_layer.features if f["properties"]["facies_name"] == "Medium"]
        assert len(medium_feat) == 1
        assert math.isclose(medium_feat[0]["properties"]["area_percent"], 100.0, abs_tol=1.0)


# ===========================================================================
# 4. Extreme Coordinates Stress Tests
# ===========================================================================

class TestExtremeCoordinates:
    """Stress test extreme coordinates: large negative, massive magnitude, and zero-crossing."""

    def test_large_negative_coordinates(self):
        """Coordinates in negative quadrant [-10,000,000, -9,990,000]."""
        base_x = -10_000_000.0
        base_y = -8_000_000.0
        points = [
            GeologicalFactor(name="net_pay", value=12.0, x=base_x + 0.0, y=base_y + 0.0, well_name="W1"),
            GeologicalFactor(name="net_pay", value=18.0, x=base_x + 5000.0, y=base_y + 2000.0, well_name="W2"),
            GeologicalFactor(name="net_pay", value=25.0, x=base_x + 2000.0, y=base_y + 6000.0, well_name="W3"),
            GeologicalFactor(name="net_pay", value=30.0, x=base_x + 7000.0, y=base_y + 8000.0, well_name="W4"),
        ]
        dataset = GeologicalFactorDataset(factor_name="net_pay", points=points)

        xmin, ymin, xmax, ymax = dataset.extent
        assert xmin < xmax and ymin < ymax
        assert xmin < base_x

        res = IDWInterpolator().interpolate(dataset, InterpolationOptions(method="idw", grid_n=25))
        assert res.dx > 0.0
        assert res.dy > 0.0
        assert np.all(np.isfinite(res.grid_z))
        assert math.isclose(res.extent[0], xmin)
        assert math.isclose(res.extent[2], xmax)

    def test_massive_positive_coordinates(self):
        """Coordinates with massive offset ~ 1e9."""
        offset = 1_000_000_000.0
        points = [
            GeologicalFactor(name="porosity", value=10.0, x=offset + 100.0, y=offset + 100.0, well_name="W1"),
            GeologicalFactor(name="porosity", value=20.0, x=offset + 500.0, y=offset + 100.0, well_name="W2"),
            GeologicalFactor(name="porosity", value=30.0, x=offset + 100.0, y=offset + 500.0, well_name="W3"),
            GeologicalFactor(name="porosity", value=40.0, x=offset + 500.0, y=offset + 500.0, well_name="W4"),
        ]
        dataset = GeologicalFactorDataset(factor_name="porosity", points=points)

        krig_res = KrigingInterpolator().interpolate(dataset, InterpolationOptions(method="kriging", grid_n=20))
        assert np.all(np.isfinite(krig_res.grid_z))
        assert krig_res.dx > 0.0
        assert krig_res.dy > 0.0

    def test_coordinates_crossing_zero(self):
        """Domain crossing zero in both axes: [-500, 500] x [-300, 300]."""
        points = [
            GeologicalFactor(name="sand_thickness", value=15.0, x=-500.0, y=-300.0, well_name="W1"),
            GeologicalFactor(name="sand_thickness", value=25.0, x=500.0, y=-300.0, well_name="W2"),
            GeologicalFactor(name="sand_thickness", value=35.0, x=-500.0, y=300.0, well_name="W3"),
            GeologicalFactor(name="sand_thickness", value=45.0, x=500.0, y=300.0, well_name="W4"),
            GeologicalFactor(name="sand_thickness", value=30.0, x=0.0, y=0.0, well_name="W0"),
        ]
        dataset = GeologicalFactorDataset(factor_name="sand_thickness", points=points)
        res = IDWInterpolator().interpolate(dataset, InterpolationOptions(method="idw", grid_n=31))
        assert res.extent[0] < 0 < res.extent[2]
        assert res.extent[1] < 0 < res.extent[3]
        assert np.all(np.isfinite(res.grid_z))


# ===========================================================================
# 5. Sparse Wells & Search Radius (Partial NaN Grids) Stress Tests
# ===========================================================================

class TestSparseWellsAndSearchRadius:
    """Stress test sparse well distributions with low/high search_radius producing partial NaN grids."""

    @pytest.fixture
    def sparse_dataset(self) -> GeologicalFactorDataset:
        # 4 wells in corners of 1000m x 1000m domain
        return GeologicalFactorDataset(
            factor_name="porosity",
            unit="%",
            points=[
                GeologicalFactor(name="porosity", value=10.0, x=100.0, y=100.0, well_name="SW"),
                GeologicalFactor(name="porosity", value=20.0, x=900.0, y=100.0, well_name="SE"),
                GeologicalFactor(name="porosity", value=30.0, x=100.0, y=900.0, well_name="NW"),
                GeologicalFactor(name="porosity", value=40.0, x=900.0, y=900.0, well_name="NE"),
            ],
        )

    def test_low_search_radius_produces_partial_nan_grid(self, sparse_dataset):
        """Low search_radius leaves central grid cells unpopulated (NaN)."""
        options = InterpolationOptions(
            method="idw",
            grid_n=40,
            search_radius=150.0,  # Far less than well spacing of 800m
            min_neighbors=1,
        )
        res = IDWInterpolator().interpolate(sparse_dataset, options)

        nan_count = int(np.isnan(res.grid_z).sum())
        valid_count = int(np.isfinite(res.grid_z).sum())
        total = res.grid_z.size

        assert nan_count > 0, "Grid must contain unpopulated NaN cells"
        assert valid_count > 0, "Grid must contain populated valid cells around wells"
        assert nan_count + valid_count == total

        # Verify FactorGridResult metadata and strict JSON descriptor
        assert res.statistics.valid_count == valid_count
        assert res.statistics.total_count == total
        desc = res.to_descriptor()
        assert desc["statistics"]["valid_count"] == valid_count
        assert desc["statistics"]["total_count"] == total
        json_str = json.dumps(desc)
        assert "NaN" not in json_str, "Descriptor must be strict JSON without raw NaN"

        # Verify legacy dict encoding
        leg = res.to_legacy_dict()
        assert any(cell is None for row in leg["grid_z"] for cell in row)

    def test_marching_squares_and_facies_on_partial_nan_grid(self, sparse_dataset):
        """Marching Squares and Facies Polygonization execute safely on partial NaN grids."""
        options = InterpolationOptions(
            method="idw",
            grid_n=40,
            search_radius=200.0,
            min_neighbors=1,
        )
        res = IDWInterpolator().interpolate(sparse_dataset, options)

        # 1. Contours
        contour_layer = generate_contour_layer(res, interval=5.0)
        assert contour_layer is not None
        assert isinstance(contour_layer.features, tuple)
        # All contour points must be finite
        for feat in contour_layer.features:
            geom = feat["geometry"]
            coords = geom["coordinates"]
            if geom["type"] == "LineString":
                assert all(math.isfinite(pt[0]) and math.isfinite(pt[1]) for pt in coords)
            elif geom["type"] == "MultiLineString":
                for line in coords:
                    assert all(math.isfinite(pt[0]) and math.isfinite(pt[1]) for pt in line)

        # 2. Facies Polygons
        poly_layer = generate_facies_polygon_layer(
            res,
            thresholds=[15.0, 25.0, 35.0],
            facies_names=["Poor", "Fair", "Good", "Excellent"],
        )
        assert poly_layer is not None
        for feat in poly_layer.features:
            props = feat["properties"]
            assert props["area"] >= 0.0
            assert 0.0 <= props["area_percent"] <= 100.0

        # 3. Full MapDocument assembly
        pipeline = GeologicalMappingPipeline()
        map_doc = pipeline.build_factor_map_document(
            sparse_dataset,
            options,
            include_grid=True,
            include_contours=True,
            include_polygons=True,
            include_wells=True,
        )
        assert len(map_doc.layers) == 4

    def test_min_and_max_neighbors_filtering(self, sparse_dataset):
        """min_neighbors > available in radius forces NaN; max_neighbors bounds contributors."""
        # 1. min_neighbors = 2 when radius only reaches 1 well
        opts_min = InterpolationOptions(
            method="idw",
            grid_n=30,
            search_radius=300.0,
            min_neighbors=2,
        )
        res_min = IDWInterpolator().interpolate(sparse_dataset, opts_min)
        # Since wells are 800m apart, radius of 300m reaches at most 1 well per target cell -> 100% NaN
        assert np.isnan(res_min.grid_z).all()

        # 2. Large radius with max_neighbors = 2
        opts_max = InterpolationOptions(
            method="idw",
            grid_n=30,
            search_radius=2000.0,
            max_neighbors=2,
            min_neighbors=1,
        )
        res_max = IDWInterpolator().interpolate(sparse_dataset, opts_max)
        assert np.all(np.isfinite(res_max.grid_z))


# ===========================================================================
# 6. Factor Extraction & Computational Geometry Edge Cases
# ===========================================================================

class TestFactorExtractionAndGeometryEdgeCases:
    """Stress test factor derivation, invalid inputs, and computational geometry helpers."""

    def test_derived_factors_with_adversarial_values(self):
        """Test derived sand ratio and thickness calculation with zero/inverted denominators."""
        pipeline = GeologicalMappingPipeline()
        records = [
            # Zero formation thickness -> sand ratio should not divide by zero
            {"well_id": "W1", "x": 100.0, "y": 100.0, "sand_thickness": 20.0, "formation_thickness": 0.0},
            # Negative formation thickness -> sand ratio should be ignored
            {"well_id": "W2", "x": 200.0, "y": 200.0, "sand_thickness": 10.0, "formation_thickness": -5.0},
            # Valid sand ratio
            {"well_id": "W3", "x": 300.0, "y": 300.0, "sand_thickness": 25.0, "formation_thickness": 100.0},
            # Inverted depths (base < top) -> thickness calculation should be ignored
            {"well_id": "W4", "x": 400.0, "y": 400.0, "top_depth": 2500.0, "base_depth": 2400.0},
            # Valid depths
            {"well_id": "W5", "x": 500.0, "y": 500.0, "top_depth": 2500.0, "base_depth": 2580.0},
        ]

        # Sand ratio
        ds_ratio = pipeline.extract_factors(records, "sand_ratio")
        assert len(ds_ratio.valid_points) == 1
        assert ds_ratio.valid_points[0].well_id == "W3"
        assert math.isclose(ds_ratio.valid_points[0].value, 0.25)

        # Formation thickness from tops/bases only
        depth_records = [
            # Inverted depths (base < top) -> thickness calculation should be ignored
            {"well_id": "W4", "x": 400.0, "y": 400.0, "top_depth": 2500.0, "base_depth": 2400.0},
            # Equal depths (base == top) -> thickness is 0, base <= top ignored
            {"well_id": "W4b", "x": 450.0, "y": 450.0, "top_depth": 2500.0, "base_depth": 2500.0},
            # Valid depths (base > top)
            {"well_id": "W5", "x": 500.0, "y": 500.0, "top_depth": 2500.0, "base_depth": 2580.0},
        ]
        ds_thick = pipeline.extract_factors(depth_records, "formation_thickness")
        assert len(ds_thick.valid_points) == 1
        assert ds_thick.valid_points[0].well_id == "W5"
        assert math.isclose(ds_thick.valid_points[0].value, 80.0)

    def test_geometry_helpers_degenerate_inputs(self):
        """Test Shoelace, Douglas-Peucker, and Chaikin with degenerate geometries."""
        # 1. Shoelace with empty, 1-point, 2-point, collinear polygons
        assert calculate_shoelace_area([]) == 0.0
        assert calculate_shoelace_area([[0.0, 0.0]]) == 0.0
        assert calculate_shoelace_area([[0.0, 0.0], [10.0, 10.0]]) == 0.0
        assert calculate_shoelace_area([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]]) == 0.0

        # Valid triangle area: (0,0), (10,0), (0,10) -> area = 50.0
        assert math.isclose(calculate_shoelace_area([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [0.0, 0.0]]), 50.0)

        # 2. Douglas-Peucker with 2 points or 0 tolerance
        pts2 = [[0.0, 0.0], [10.0, 10.0]]
        assert douglas_peucker_2d(pts2, 1.0) == pts2
        assert douglas_peucker_2d(pts2, 0.0) == pts2

        # 3. Chaikin smoothing with <3 points or 0 iterations
        assert chaikin_smooth(pts2, 0) == pts2
        assert chaikin_smooth(pts2, 2) == pts2

        # 4. Polyline length
        assert calculate_polyline_length([]) == 0.0
        assert calculate_polyline_length([[0.0, 0.0]]) == 0.0
        assert math.isclose(calculate_polyline_length([[0.0, 0.0], [3.0, 4.0]]), 5.0)


# ===========================================================================
# 7. Multithreaded Concurrency Stress Tests
# ===========================================================================

class TestMultithreadedConcurrency:
    """Stress test concurrent multithreaded execution of pipeline and FactorGridResult."""

    def test_concurrent_pipeline_and_grid_result_operations(self):
        """16 concurrent worker threads executing 100 pipeline runs and exports simultaneously."""
        pipeline = GeologicalMappingPipeline()

        def _worker_task(thread_id: int) -> dict[str, Any]:
            # Generate thread-unique synthetic dataset
            n_pts = 8 + (thread_id % 5)
            rng = np.random.RandomState(seed=1000 + thread_id)
            raw_records = [
                {
                    "well_id": f"W_{thread_id}_{i}",
                    "name": f"井_{thread_id}_{i}",
                    "x": float(rng.uniform(100.0, 1000.0)),
                    "y": float(rng.uniform(200.0, 1200.0)),
                    "POR": float(rng.uniform(5.0, 35.0)),
                    "attributes": {
                        "formation": "Es3",
                        "depth": float(rng.uniform(2000.0, 3500.0)),
                    },
                }
                for i in range(n_pts)
            ]

            # 1. Factor extraction
            dataset = pipeline.extract_factors(raw_records, "porosity", target_horizon="Es3")
            assert len(dataset.valid_points) == n_pts

            # 2. Interpolation
            method = "kriging" if (thread_id % 2 == 0) else "idw"
            options = InterpolationOptions(
                method=method,
                grid_n=25,
                variogram_model="exponential" if (thread_id % 4 == 0) else "spherical",
                search_radius=400.0 if method == "idw" else None,
            )
            grid_res = pipeline.interpolate(dataset, options)
            assert grid_res.shape == (25, 25)

            # 3. FactorGridResult copy and mutation isolation
            copied_res = grid_res.copied()
            copied_res.grid_z[0, 0] = 999.0
            assert grid_res.grid_z[0, 0] != 999.0, "Original grid must not mutate when copy is altered"

            # 4. Descriptors and serialization
            desc = grid_res.to_descriptor()
            assert desc["factor_name"] == "porosity"
            leg = grid_res.to_legacy_dict()
            assert len(leg["grid_z"]) == 25

            # 5. Full MapDocument and Composition
            map_doc = pipeline.build_factor_map_document(
                dataset,
                options,
                include_grid=True,
                include_contours=True,
                include_polygons=True,
                include_wells=True,
            )
            assert len(map_doc.layers) >= 3

            comp = pipeline.build_factor_composition(map_doc, title=f"Thread {thread_id} Map")
            assert comp.title == f"Thread {thread_id} Map"

            return {"thread_id": thread_id, "status": "ok", "valid_cells": grid_res.statistics.valid_count}

        num_threads = 16
        num_tasks = 80
        errors = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(_worker_task, i) for i in range(num_tasks)]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    res = fut.result()
                    assert res["status"] == "ok"
                except Exception as ex:
                    errors.append(str(ex))

        assert not errors, f"Concurrent execution errors encountered: {errors}"
