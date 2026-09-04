"""Unit and integration tests for Geological Mapping Pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline import (
    DEFAULT_GEOLOGICAL_PIPELINE,
    GeologicalFactor,
    GeologicalFactorDataset,
    GeologicalMappingPipeline,
    IDWInterpolator,
    InterpolationOptions,
    KrigingInterpolator,
    calculate_nice_contour_levels,
    create_geological_factor_map_template,
    generate_contour_layer,
    generate_facies_polygon_layer,
    interpolate_factor,
)
from paleo_workbench.mapping.layers import (
    ContourMapLayer,
    GridMapLayer,
    MapDocument,
    PolygonMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.project.models import (
    ProjectDocument,
    ProjectMeta,
    WellTable,
    WellTableRow,
)
from paleo_workbench.services.geological_mapping_service import GeologicalMappingService
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


@pytest.fixture
def sample_well_dataset() -> GeologicalFactorDataset:
    """Fixture providing 8 realistic well point measurements for Porosity (孔隙度)."""
    dataset = GeologicalFactorDataset(
        factor_name="孔隙度",
        unit="%",
        target_horizon="T1",
        crs="EPSG:4326",
    )
    wells = [
        ("W1", "井-1", 114.10, 22.50, 18.5),
        ("W2", "井-2", 114.25, 22.52, 22.3),
        ("W3", "井-3", 114.38, 22.48, 15.2),
        ("W4", "井-4", 114.15, 22.65, 24.1),
        ("W5", "井-5", 114.30, 22.68, 19.8),
        ("W6", "井-6", 114.42, 22.62, 12.4),
        ("W7", "井-7", 114.20, 22.80, 26.5),
        ("W8", "井-8", 114.35, 22.82, 21.0),
    ]
    for wid, wname, x, y, val in wells:
        dataset.add_point(
            GeologicalFactor(
                name="孔隙度",
                value=val,
                unit="%",
                well_id=wid,
                well_name=wname,
                x=x,
                y=y,
                crs="EPSG:4326",
                formation="T1",
            )
        )
    return dataset


def test_dataset_arrays_and_extent(sample_well_dataset):
    xs, ys, zs = sample_well_dataset.to_arrays()
    assert len(xs) == 8
    assert len(ys) == 8
    assert len(zs) == 8
    assert np.isclose(xs[0], 114.10)
    assert np.isclose(zs[0], 18.5)

    extent = sample_well_dataset.extent
    assert extent[0] < 114.10
    assert extent[2] > 114.42
    assert extent[1] < 22.48
    assert extent[3] > 22.82


def test_kriging_interpolation(sample_well_dataset):
    options = InterpolationOptions(
        method="kriging",
        grid_n=40,
        variogram_model="spherical",
        color_ramp="porosity",
    )
    result = interpolate_factor(sample_well_dataset, options)

    assert result.factor_name == "孔隙度"
    assert result.algorithm_id == "kriging"
    assert result.grid_z.shape == (40, 40)
    assert result.grid_x.shape == (40,)
    assert result.grid_y.shape == (40,)
    assert np.isfinite(result.grid_z).all()
    # Kriging variance grid should be populated
    assert result.variance_grid is not None
    assert result.variance_grid.shape == (40, 40)
    assert (result.variance_grid >= 0.0).all()


def test_idw_interpolation(sample_well_dataset):
    options = InterpolationOptions(
        method="idw",
        grid_n=30,
        power=2.0,
    )
    result = interpolate_factor(sample_well_dataset, options)

    assert result.factor_name == "孔隙度"
    assert result.algorithm_id == "idw"
    assert result.grid_z.shape == (30, 30)
    assert np.isfinite(result.grid_z).all()


def test_contour_generation_marching_squares(sample_well_dataset):
    options = InterpolationOptions(method="kriging", grid_n=35)
    grid_result = interpolate_factor(sample_well_dataset, options)

    contour_layer = generate_contour_layer(
        grid_result,
        levels=[15.0, 18.0, 21.0, 24.0],
    )
    assert isinstance(contour_layer, ContourMapLayer)
    assert contour_layer.levels == [15.0, 18.0, 21.0, 24.0]
    assert len(contour_layer.features) > 0

    first_feat = contour_layer.features[0]
    assert first_feat["geometry"]["type"] == "LineString"
    assert len(first_feat["geometry"]["coordinates"]) >= 2
    assert "level" in first_feat["properties"]


def test_facies_polygonization(sample_well_dataset):
    options = InterpolationOptions(method="kriging", grid_n=30)
    grid_result = interpolate_factor(sample_well_dataset, options)

    poly_layer = generate_facies_polygon_layer(
        grid_result,
        thresholds=[16.0, 22.0],
        facies_names=["致密相带", "常规储层", "优质甜点"],
    )
    assert isinstance(poly_layer, PolygonMapLayer)
    assert len(poly_layer.features) > 0

    first_poly = poly_layer.features[0]
    assert first_poly["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert "facies_name" in first_poly["properties"]


def test_end_to_end_geological_mapping_pipeline(sample_well_dataset):
    pipeline = GeologicalMappingPipeline()
    options = InterpolationOptions(
        method="kriging",
        grid_n=40,
        color_ramp="porosity",
    )

    # 1. Build multi-layer MapDocument
    map_doc = pipeline.build_factor_map_document(
        sample_well_dataset,
        options=options,
        include_grid=True,
        include_contours=True,
        include_wells=True,
        include_polygons=True,
        title="T1段孔隙度分布图",
    )

    assert isinstance(map_doc, MapDocument)
    assert map_doc.title == "T1段孔隙度分布图"
    assert len(map_doc.layers) == 4

    # Verify layer types and order
    types = [lyr.layer_type for lyr in map_doc.layers]
    assert types == ["grid", "polygon", "contour", "well_point"]

    # 2. Build cartographic composition
    comp_doc = pipeline.build_factor_composition(map_doc)
    assert comp_doc.title == "T1段孔隙度分布图"
    assert len(comp_doc.elements) >= 4

    # 3. Render SVG
    from paleo_workbench.mapping.composer.renderer import MapComposerRenderer
    renderer = MapComposerRenderer()
    svg = renderer.render_to_svg(comp_doc)

    assert "<svg" in svg
    assert "</svg>" in svg
    assert 'id="elem_main_map"' in svg
    assert 'id="elem_legend"' in svg
    assert "孔隙度" in svg


def test_geological_mapping_service_with_project():
    project = ProjectDocument(
        meta=ProjectMeta(name="测试盆地工程"),
    )
    # Add a WellTable
    wtable = WellTable(
        name="T1井位表",
        target_horizon="T1",
        factor_type="砂岩厚度",
        rows=[
            WellTableRow(well_id="w1", name="W-1", x=100.0, y=30.0, H_s=25.4, H_t=100.0),
            WellTableRow(well_id="w2", name="W-2", x=105.0, y=32.0, H_s=42.1, H_t=110.0),
            WellTableRow(well_id="w3", name="W-3", x=108.0, y=28.0, H_s=12.0, H_t=95.0),
            WellTableRow(well_id="w4", name="W-4", x=102.0, y=35.0, H_s=55.8, H_t=120.0),
        ],
    )
    project.well_tables.append(wtable)

    service = GeologicalMappingService()
    map_doc, task = service.create_factor_map(
        project,
        factor_name="砂岩厚度",
        target_horizon="T1",
        method="kriging",
        grid_n=30,
        color_ramp="sand_thickness",
        include_grid=True,
        include_contours=True,
        include_wells=True,
    )

    assert isinstance(map_doc, MapDocument)
    assert task.status == "complete"
    assert task.factor_type == "砂岩厚度"
    assert len(project.factor_map_tasks) == 1
    assert len(project.paleomap_documents) == 1


def test_factor_extraction_all_types():
    pipeline = GeologicalMappingPipeline()
    records = [
        {"well_id": "W1", "name": "井-1", "x": 100.0, "y": 20.0, "POR": 18.5, "PERM": 45.2, "NET_PAY": 12.0, "TOP_DEPTH": 1500.0, "BASE_DEPTH": 1550.0},
        {"well_id": "W2", "name": "井-2", "x": 102.0, "y": 22.0, "porosity": 22.1, "permeability": 120.0, "net_pay": 18.5, "top_md": 1520.0, "base_md": 1580.0},
        {"well_id": "W3", "name": "井-3", "x": 104.0, "y": 21.0, "孔隙度": 15.3, "渗透率": 25.0, "有效厚度": 8.0, "地层顶界": 1490.0, "地层底界": 1545.0},
    ]

    # 1. Porosity extraction with mnemonics
    ds_por = pipeline.extract_factors(records, "porosity")
    assert len(ds_por.valid_points) == 3
    assert ds_por.unit == "%"
    vals_por = [p.value for p in ds_por.valid_points]
    assert np.allclose(vals_por, [18.5, 22.1, 15.3])

    # 2. Permeability extraction
    ds_perm = pipeline.extract_factors(records, "permeability")
    assert len(ds_perm.valid_points) == 3
    assert ds_perm.unit == "mD"
    assert np.allclose([p.value for p in ds_perm.valid_points], [45.2, 120.0, 25.0])

    # 3. Net pay extraction
    ds_pay = pipeline.extract_factors(records, "net_pay")
    assert len(ds_pay.valid_points) == 3
    assert ds_pay.unit == "m"
    assert np.allclose([p.value for p in ds_pay.valid_points], [12.0, 18.5, 8.0])

    # 4. Top depth extraction
    ds_top = pipeline.extract_factors(records, "top_depth")
    assert len(ds_top.valid_points) == 3
    assert ds_top.unit == "m"
    assert np.allclose([p.value for p in ds_top.valid_points], [1500.0, 1520.0, 1490.0])

    # 5. Derived formation thickness
    ds_thick = pipeline.extract_factors(records, "formation_thickness")
    assert len(ds_thick.valid_points) == 3
    assert np.allclose([p.value for p in ds_thick.valid_points], [50.0, 60.0, 55.0])


def test_extraction_from_well_entities():
    from paleo_workbench.project.domain import WellEntity

    project = ProjectDocument(meta=ProjectMeta(name="实体工程"))
    project.wells = [
        WellEntity(name="WELL_A", project_x=10.0, project_y=20.0, metadata={"porosity": 19.5, "formation": "T1"}),
        WellEntity(name="WELL_B", project_x=12.0, project_y=22.0, metadata={"porosity": 24.0, "formation": "T1"}),
        WellEntity(name="WELL_C", project_x=15.0, project_y=25.0, metadata={"porosity": 16.2, "formation": "T1"}),
    ]

    service = GeologicalMappingService()
    dataset = service.extract_well_factors(project, "porosity")
    assert len(dataset.valid_points) == 3
    assert np.allclose([p.value for p in dataset.valid_points], [19.5, 24.0, 16.2])


def test_idw_search_radius_and_neighbors():
    dataset = GeologicalFactorDataset(
        factor_name="渗透率",
        unit="mD",
        points=[
            GeologicalFactor(name="渗透率", value=10.0, x=0.0, y=0.0),
            GeologicalFactor(name="渗透率", value=50.0, x=10.0, y=0.0),
            GeologicalFactor(name="渗透率", value=100.0, x=0.0, y=10.0),
            GeologicalFactor(name="渗透率", value=200.0, x=10.0, y=10.0),
        ],
    )

    # 1. Search radius that is small should leave far corners as NaN
    opts = InterpolationOptions(
        method="idw",
        grid_n=20,
        search_radius=3.0,
        min_neighbors=1,
    )
    res = IDWInterpolator().interpolate(dataset, opts)
    assert np.isnan(res.grid_z).any()
    # Near corners should be finite
    assert np.isfinite(res.grid_z[0, 0])
    assert np.isfinite(res.grid_z[-1, -1])

    # 2. Min neighbors = 3 with small radius should leave center as NaN
    opts2 = InterpolationOptions(
        method="idw",
        grid_n=20,
        search_radius=5.0,
        min_neighbors=3,
    )
    res2 = IDWInterpolator().interpolate(dataset, opts2)
    assert np.isnan(res2.grid_z).any()


def test_kriging_variogram_models(sample_well_dataset):
    from paleo_workbench.mapping.geological_pipeline.interpolator import _pure_numpy_kriging

    xs, ys, zs = sample_well_dataset.to_arrays()
    gx = np.linspace(114.1, 114.5, 20)
    gy = np.linspace(22.4, 22.9, 20)

    for model in ("spherical", "exponential", "gaussian"):
        z_pred, v_grid, params = _pure_numpy_kriging(xs, ys, zs, gx, gy, model=model)
        assert z_pred.shape == (20, 20)
        assert v_grid.shape == (20, 20)
        assert np.isfinite(z_pred).all()
        assert np.isfinite(v_grid).all()
        assert (v_grid >= 0.0).all()
        assert params["model"] == model


def test_factor_grid_result_properties_and_descriptor(sample_well_dataset):
    options = InterpolationOptions(method="idw", grid_n=25)
    result = interpolate_factor(sample_well_dataset, options)

    assert result.dx > 0.0
    assert result.dy > 0.0
    assert result.cell_size == (result.dx, result.dy)
    assert isinstance(result.input_points, list)
    assert len(result.input_points) == 8

    # Set mock contours and verify descriptor
    result.contours = {"20.0": [[[114.1, 22.5], [114.3, 22.7]]]}
    descriptor = result.to_descriptor()
    assert "contours" in descriptor
    assert "20.0" in descriptor["contours"]
    assert descriptor["width"] == 25
    assert descriptor["height"] == 25


def test_marching_squares_saddle_disambiguation():
    from paleo_workbench.mapping.geological_pipeline.contouring import _marching_squares_pure_python

    # Create a 2x2 saddle grid:
    # Corner 0 (bottom-left) = 10, Corner 1 (bottom-right) = 0
    # Corner 3 (top-left) = 0,    Corner 2 (top-right) = 10
    # Center average = (10 + 0 + 10 + 0) / 4 = 5.0
    grid_x = np.array([0.0, 1.0], dtype=np.float64)
    grid_y = np.array([0.0, 1.0], dtype=np.float64)
    grid_z = np.array([[10.0, 0.0], [0.0, 10.0]], dtype=np.float64)

    # Test level = 4.0: v_center (5.0) >= level (4.0) -> high corners connect
    lines_high = _marching_squares_pure_python(grid_z, grid_x, grid_y, level=4.0)
    assert len(lines_high) >= 1

    # Test level = 6.0: v_center (5.0) < level (6.0) -> low corners connect
    lines_low = _marching_squares_pure_python(grid_z, grid_x, grid_y, level=6.0)
    assert len(lines_low) >= 1


def test_marching_squares_simplification_and_smoothing():
    from paleo_workbench.mapping.geological_pipeline.contouring import (
        chaikin_smooth,
        douglas_peucker_2d,
    )

    # Collinear points on straight line
    straight = [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0], [4.0, 4.0]]
    simplified = douglas_peucker_2d(straight, tolerance=0.1)
    assert len(simplified) == 2
    assert simplified[0] == [0.0, 0.0]
    assert simplified[1] == [4.0, 4.0]

    # Smoothing corner
    corner = [[0.0, 0.0], [0.0, 10.0], [10.0, 10.0]]
    smoothed = chaikin_smooth(corner, iterations=1)
    assert len(smoothed) > len(corner)
    assert smoothed[0] == [0.0, 0.0]
    assert smoothed[-1] == [10.0, 10.0]


def test_quantile_and_fixed_interval_contour_levels(sample_well_dataset):
    options = InterpolationOptions(method="kriging", grid_n=30)
    grid_result = interpolate_factor(sample_well_dataset, options)

    # 1. Quantile leveling
    layer_quantile = generate_contour_layer(grid_result, leveling_mode="quantile")
    assert len(layer_quantile.levels) > 0
    assert len(layer_quantile.features) > 0

    # 2. Fixed interval leveling
    layer_fixed = generate_contour_layer(grid_result, interval=2.0)
    assert len(layer_fixed.levels) > 0
    # Every 5th interval should be an index contour
    index_contours = [f for f in layer_fixed.features if f["properties"].get("is_index_contour")]
    assert len(index_contours) >= 0


def test_facies_polygonization_pure_python_metrics(sample_well_dataset):
    options = InterpolationOptions(method="idw", grid_n=20)
    grid_result = interpolate_factor(sample_well_dataset, options)

    poly_layer = generate_facies_polygon_layer(
        grid_result,
        thresholds=[18.0, 22.0],
        facies_names=["低值相", "中值相", "高值相"],
    )

    assert len(poly_layer.features) > 0
    total_area_pct = 0.0
    for feat in poly_layer.features:
        props = feat["properties"]
        assert "area" in props
        assert "area_percent" in props
        assert "mean_value" in props
        assert "facies_id" in props
        assert props["area"] >= 0.0
        total_area_pct += props["area_percent"]

    assert total_area_pct > 0.0


def test_facies_polygonization_with_holes():
    # Construct a 5x5 grid with a high ring surrounding a low center hole
    # Grid: border is 30.0, center (row 2, col 2) is 5.0
    z = np.full((7, 7), 30.0, dtype=np.float32)
    z[2:5, 2:5] = 5.0

    result = FactorGridResult(
        grid_z=z,
        grid_x=np.linspace(0.0, 70.0, 7),
        grid_y=np.linspace(0.0, 70.0, 7),
        factor_name="孔隙度",
        algorithm_id="mock",
        algorithm_parameters={},
    )

    poly_layer = generate_facies_polygon_layer(
        result,
        thresholds=[15.0],
        facies_names=["低孔穴", "高孔背景"],
    )

    assert len(poly_layer.features) >= 2
    names = [f["properties"]["facies_name"] for f in poly_layer.features]
    assert "高孔背景" in names
    assert "低孔穴" in names


def test_edge_cases_nans_uniform_and_degenerates():
    # 1. 100% NaN grid
    nan_z = np.full((10, 10), np.nan, dtype=np.float32)
    nan_result = FactorGridResult(
        grid_z=nan_z,
        grid_x=np.linspace(0.0, 10.0, 10),
        grid_y=np.linspace(0.0, 10.0, 10),
        factor_name="测试NaN",
        algorithm_id="mock",
        algorithm_parameters={},
    )

    c_layer = generate_contour_layer(nan_result)
    assert len(c_layer.features) == 0
    p_layer = generate_facies_polygon_layer(nan_result)
    assert len(p_layer.features) == 0

    # 2. Uniform constant grid
    const_z = np.full((10, 10), 20.0, dtype=np.float32)
    const_result = FactorGridResult(
        grid_z=const_z,
        grid_x=np.linspace(0.0, 10.0, 10),
        grid_y=np.linspace(0.0, 10.0, 10),
        factor_name="测试常量",
        algorithm_id="mock",
        algorithm_parameters={},
    )

    c_const = generate_contour_layer(const_result)
    assert len(c_const.features) == 0
    p_const = generate_facies_polygon_layer(const_result)
    assert len(p_const.features) == 1
    assert p_const.features[0]["properties"]["area_percent"] == 100.0



# ------------------------------------------------------- audit #1150 tests


def test_extract_factors_keeps_zero_coordinates():
    """0.0 is a legal coordinate: a pure (0, 0) well must not be dropped.

    The old or-chain (``rec.get("x") or rec.get("lng") or ...``) treated 0.0
    as missing and silently discarded such records.
    """
    pipeline = GeologicalMappingPipeline()
    records = [
        {"well_id": "W0", "name": "origin", "x": 0.0, "y": 0.0, "porosity": 15.0},
        {"well_id": "W1", "name": "w1", "x": 114.0, "y": 22.5, "porosity": 18.0},
    ]
    ds = pipeline.extract_factors(records, "porosity")
    by_id = {p.well_id: p for p in ds.points}
    assert "W0" in by_id
    assert by_id["W0"].x == 0.0 and by_id["W0"].y == 0.0
    assert by_id["W0"].value == 15.0
    assert ds.metadata["skipped_missing_coordinates"] == 0


def test_extract_factors_never_cross_pairs_coordinate_key_families():
    """x from one CRS family must never pair with y from another (#1150)."""
    pipeline = GeologicalMappingPipeline()
    records = [
        # x/y family present but y missing; lat from the lng/lat family must
        # NOT be grafted in as y.
        {"well_id": "BAD", "x": 114.0, "lat": 22.5, "porosity": 10.0},
    ]
    ds = pipeline.extract_factors(records, "porosity")
    assert ds.points == []
    assert ds.metadata["skipped_missing_coordinates"] == 1
    assert ds.metadata["coordinate_key_families_used"] == {}


def test_extract_factors_coordinate_family_priority_project_first():
    """project_* keys win over raw x/y when both families are complete."""
    pipeline = GeologicalMappingPipeline()
    records = [
        {
            "well_id": "W1",
            "x": 114.0,
            "y": 22.5,
            "project_x": 500000.0,
            "project_y": 3400000.0,
            "porosity": 12.0,
        }
    ]
    ds = pipeline.extract_factors(records, "porosity")
    assert len(ds.points) == 1
    assert ds.points[0].x == 500000.0
    assert ds.points[0].y == 3400000.0
    assert ds.metadata["coordinate_key_families_used"] == {"project": 1}


def test_extract_factors_missing_y_skipped_and_counted():
    pipeline = GeologicalMappingPipeline()
    records = [
        {"well_id": "OK", "x": 1.0, "y": 2.0, "porosity": 10.0},
        {"well_id": "NOY", "x": 5.0, "porosity": 11.0},
        {"well_id": "NOX", "y": 7.0, "porosity": 12.0},
    ]
    ds = pipeline.extract_factors(records, "porosity")
    assert [p.well_id for p in ds.points] == ["OK"]
    assert ds.metadata["skipped_missing_coordinates"] == 2
    assert ds.metadata["coordinate_key_families_used"] == {"xy": 1}


def test_extract_factors_mixed_key_families_recorded_as_diagnostic(caplog):
    """Batch mixing project_* and raw x/y families is flagged, not silent."""
    pipeline = GeologicalMappingPipeline()
    records = [
        {"well_id": "P", "project_x": 500000.0, "project_y": 3400000.0, "porosity": 10.0},
        {"well_id": "G", "lng": 114.1, "lat": 22.6, "porosity": 12.0},
    ]
    with caplog.at_level("WARNING", logger="paleo_workbench.mapping.geological_pipeline.pipeline"):
        ds = pipeline.extract_factors(records, "porosity")
    assert len(ds.points) == 2
    assert ds.metadata["coordinate_key_family_mixing"] is True
    assert ds.metadata["coordinate_key_families_used"] == {"project": 1, "lnglat": 1}
    assert any("mixed coordinate key families" in r.message for r in caplog.records)
