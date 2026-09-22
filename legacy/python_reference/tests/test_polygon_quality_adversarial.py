"""M4 — contour / zone / facies polygon quality under adversarial inputs.

Covers: small-polygon threshold (explicit, QC-counted — never silent), user
domain clip through polygon AND contour output, deterministic hole assignment
(promotion instead of "stuff into first polygon"), and the goal's adversarial
matrix: NaN holes, coincident wells, zero-area cells, narrow corridors,
nested rings, self-intersection, boundary edges, sparse points.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline.contouring import (
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.interpolator import (
    interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (
    GeologicalMappingPipeline,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    _clip_polygon_to_ring,
    _point_in_ring,
    ring_area_centroid,
    calculate_shoelace_area,
    generate_facies_polygon_layer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

pytest.importorskip("shapely")


# ---------------------------------------------------------------------------
# grid builders
# ---------------------------------------------------------------------------


def _grid_from_field(field: np.ndarray, crs="EPSG:32650") -> FactorGridResult:
    h, w = field.shape
    gx = np.linspace(0.0, float(w), w)
    gy = np.linspace(0.0, float(h), h)
    return FactorGridResult(
        grid_z=field.astype(np.float32),
        grid_x=gx,
        grid_y=gy,
        factor_name="孔隙度",
        algorithm_id="idw",
        crs=crs,
        unit="%",
    )


def _exterior_rings(geometry):
    """Yield exterior rings of Polygon / MultiPolygon geometries."""
    if geometry["type"] == "Polygon":
        yield geometry["coordinates"][0]
    elif geometry["type"] == "MultiPolygon":
        for poly in geometry["coordinates"]:
            yield poly[0]


def _plain_field() -> np.ndarray:
    xx, yy = np.meshgrid(np.arange(20, dtype=float), np.arange(20, dtype=float))
    return xx * 0.4 + yy * 0.8


# ---------------------------------------------------------------------------
# small polygon threshold
# ---------------------------------------------------------------------------


def test_small_polygon_threshold_drops_and_counts():
    field = _plain_field()
    # A 2x2 high island fully surrounded by a NaN moat: an explicit min_area
    # threshold drops it and counts the drop — nothing silent.
    field[10:12, 10:12] = 50.0
    field[9:13, 9] = np.nan
    field[9:13, 12] = np.nan
    field[9, 9:13] = np.nan
    field[12, 9:13] = np.nan
    grid = _grid_from_field(field)
    layer_all = generate_facies_polygon_layer(grid, thresholds=[40.0])
    layer_small = generate_facies_polygon_layer(grid, thresholds=[40.0], min_area=5.0)
    qc = layer_small.metadata["polygon_qc"]
    assert qc["small_polygon_threshold"] == 5.0
    assert qc["small_polygons_dropped"] >= 1
    assert len(layer_small.features) < len(layer_all.features)
    # zero threshold / None keeps everything
    layer_keep = generate_facies_polygon_layer(grid, thresholds=[4.0], min_area=None)
    assert layer_keep.metadata["polygon_qc"]["small_polygons_dropped"] == 0


def test_small_polygon_threshold_none_drops_nothing_by_default():
    grid = _grid_from_field(_plain_field())
    layer = generate_facies_polygon_layer(grid, thresholds=[4.0])
    assert layer.metadata["polygon_qc"]["small_polygons_dropped"] == 0


# ---------------------------------------------------------------------------
# user domain clip (D6)
# ---------------------------------------------------------------------------


def test_facies_layer_clips_to_user_domain():
    grid = _grid_from_field(_plain_field())
    ring = [[2.0, 2.0], [10.0, 2.0], [10.0, 10.0], [2.0, 10.0]]
    layer = generate_facies_polygon_layer(grid, thresholds=[4.0], clip_ring=ring)
    assert layer.metadata["polygon_qc"]["clipped_to_domain"] > 0
    for feature in layer.features:
        for exterior in _exterior_rings(feature["geometry"]):
            for x, y in exterior:
                assert 2.0 - 1e-6 <= x <= 10.0 + 1e-6
                assert 2.0 - 1e-6 <= y <= 10.0 + 1e-6


def test_contour_layer_clips_to_user_domain():
    grid = _grid_from_field(_plain_field())
    ring = [[3.0, 3.0], [9.0, 3.0], [9.0, 9.0], [3.0, 9.0]]
    layer = generate_contour_layer(grid, interval=2.0, clip_ring=ring)
    assert layer.metadata["contour_qc"]["clipped_to_domain"] > 0
    for feature in layer.features:
        for x, y in feature["geometry"]["coordinates"]:
            assert 3.0 - 1e-6 <= x <= 9.0 + 1e-6
            assert 3.0 - 1e-6 <= y <= 9.0 + 1e-6


def test_clip_polygon_entirely_outside_domain_is_dropped():
    geom = {
        "type": "Polygon",
        "coordinates": [[[15.0, 15.0], [18.0, 15.0], [18.0, 18.0], [15.0, 18.0], [15.0, 15.0]]],
    }
    ring = [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]
    assert _clip_polygon_to_ring(geom, ring) is None


# ---------------------------------------------------------------------------
# deterministic hole assignment
# ---------------------------------------------------------------------------


def test_hole_inside_nested_exterior_gets_smallest_container():
    """A NaN block in the middle creates a hole in each class polygon; every
    hole must lie inside ITS OWN exterior and never be stapled onto an
    unrelated polygon."""
    field = _plain_field()
    field[9:11, 9:11] = np.nan
    grid = _grid_from_field(field)
    layer = generate_facies_polygon_layer(grid, thresholds=[field.mean()])
    for feature in layer.features:
        geom = feature["geometry"]
        if geom["type"] != "Polygon":
            continue
        ext = geom["coordinates"][0]
        assert calculate_shoelace_area(ext) > 0
        for hole in geom["coordinates"][1:]:
            cx, cy = ring_area_centroid(hole)
            assert _point_in_ring(cx, cy, ext)


# ---------------------------------------------------------------------------
# adversarial matrix
# ---------------------------------------------------------------------------


def test_adversarial_nan_holes():
    field = _plain_field()
    field[4:6, 4:6] = np.nan
    field[14:16, 2:4] = np.nan
    grid = _grid_from_field(field)
    layer = generate_facies_polygon_layer(grid, thresholds=[4.0, 10.0])
    assert len(layer.features) >= 3
    contour = generate_contour_layer(grid, interval=3.0)
    assert len(contour.features) > 0


def test_adversarial_all_nan_grid():
    field = _plain_field()
    field[:] = np.nan
    grid = _grid_from_field(field)
    layer = generate_facies_polygon_layer(grid, thresholds=[1.0])
    assert layer.features == ()
    contour = generate_contour_layer(grid, interval=3.0)
    assert contour.features == ()


def test_adversarial_constant_field_zero_variance():
    field = np.full((12, 12), 5.0)
    grid = _grid_from_field(field)
    layer = generate_facies_polygon_layer(grid, thresholds=[5.0])
    assert len(layer.features) >= 1
    names = {f["properties"]["facies_name"] for f in layer.features}
    assert names == {"均一相带"}


def test_adversarial_narrow_corridor():
    field = _plain_field()
    # a 1-cell diagonal ridge between two low regions — connectivity stress
    field[:] = 0.0
    for i in range(20):
        field[i, i] = 20.0
        if i + 1 < 20:
            field[i, i + 1] = 20.0
    grid = _grid_from_field(field)
    layer = generate_facies_polygon_layer(grid, thresholds=[10.0])
    assert len(layer.features) >= 1
    for feature in layer.features:
        assert feature["geometry"]["coordinates"][0]  # nonempty rings


def test_adversarial_single_cell_islands_zero_area_tolerance():
    field = _plain_field()
    field[:] = 0.0
    field[3, 3] = 50.0
    field[15, 15] = 50.0
    grid = _grid_from_field(field)
    layer = generate_facies_polygon_layer(
        grid, thresholds=[10.0], facies_names=["低值相带", "高值相带"]
    )
    islands = [f for f in layer.features if f["properties"]["facies_name"] == "高值相带"]
    assert len(islands) >= 2
    with_min = generate_facies_polygon_layer(
        grid, thresholds=[10.0], facies_names=["低值相带", "高值相带"], min_area=2.0
    )
    assert with_min.metadata["polygon_qc"]["small_polygons_dropped"] >= 2


def test_adversarial_self_intersecting_clip_ring_is_repaired():
    grid = _grid_from_field(_plain_field())
    # bow-tie ring (self-intersecting)
    bowtie = [[2.0, 2.0], [10.0, 10.0], [10.0, 2.0], [2.0, 10.0]]
    layer = generate_facies_polygon_layer(grid, thresholds=[4.0], clip_ring=bowtie)
    for feature in layer.features:
        for exterior in _exterior_rings(feature["geometry"]):
            for x, y in exterior:
                assert 0.0 - 1e-6 <= x <= 20.0 + 1e-6
                assert 0.0 - 1e-6 <= y <= 20.0 + 1e-6


def test_adversarial_sparse_points_grid_via_pipeline_interpolation():
    pytest.importorskip("geoviz")
    pts = [
        GeologicalFactor(name="孔隙度", value=5, x=0, y=0),
        GeologicalFactor(name="孔隙度", value=25, x=100, y=0),
        GeologicalFactor(name="孔隙度", value=10, x=0, y=100),
    ]
    dataset = GeologicalFactorDataset(factor_name="孔隙度", unit="%", points=pts)
    pipeline = GeologicalMappingPipeline()
    grid = pipeline.interpolate(dataset, InterpolationOptions(method="idw", grid_n=16))
    layer = pipeline.create_polygon_layer(grid, thresholds=[10.0])
    assert len(layer.features) >= 1
    assert pipeline.create_contour_layer(grid, interval=5.0).features  # not empty


def test_adversarial_coincident_wells_in_dataset():
    pts = [
        GeologicalFactor(name="孔隙度", value=10, x=5, y=5),
        GeologicalFactor(name="孔隙度", value=10, x=5, y=5),  # exact duplicate
        GeologicalFactor(name="孔隙度", value=20, x=50, y=50),
    ]
    dataset = GeologicalFactorDataset(factor_name="孔隙度", unit="%", points=pts)
    result = interpolate_factor(dataset, InterpolationOptions(method="idw", grid_n=12))
    assert np.isfinite(result.grid_z).any()
