"""QGIS scalar mirror cache tests (uses GDAL only when locally available)."""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.scalar_raster_mirror import ScalarRasterMirrorCache
from paleo_workbench.viz.native_factor_map import MapScene
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


gdal = pytest.importorskip("osgeo.gdal")


def _scalar_snapshot():
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [100.0, 120.0],
            "grid_y": [30.0, 50.0],
            "grid_z": [[0.0, 1.0], [0.5, None]],
            "backend": "idw",
            "n_points": 4,
        },
        factor_name="Porosity",
        crs="EPSG:3857",
    )
    scene = MapScene()
    scene.add_factor_grid(result, layer_id="porosity")
    return scene, scene.render_snapshot(project_crs="EPSG:3857").layers[0]


def test_scalar_raster_mirror_reuses_native_raster_until_a_revision_changes(tmp_path) -> None:
    scene, layer = _scalar_snapshot()
    scalar = scene.scalar_layer("porosity")
    cache = ScalarRasterMirrorCache(tmp_path)

    first = cache.ensure(layer)
    second = cache.ensure(layer)
    dataset = gdal.Open(first)

    assert first == second
    assert scalar.rasterize_count == 1
    assert dataset.RasterCount == 4
    assert dataset.GetGeoTransform() == pytest.approx((100.0, 10.0, 0.0, 50.0, 0.0, -10.0))
    assert "3857" in dataset.GetProjection()
    dataset = None

    scene.set_scalar_style("porosity", gamma=1.2)
    styled = scene.render_snapshot(project_crs="EPSG:3857").layers[0]
    assert cache.ensure(styled) != first
    assert scalar.rasterize_count == 2
    cache.clear()
