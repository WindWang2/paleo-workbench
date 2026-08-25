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
