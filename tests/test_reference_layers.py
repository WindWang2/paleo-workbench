from __future__ import annotations

import json

import numpy as np
import pytest
from osgeo import gdal, ogr, osr

from paleo_workbench.mapping.reference_layers import (
    ReferenceLayerError,
    ReferenceLayerService,
)
from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument


def _write_geojson(path, *, include_crs: bool) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Fault A"},
                "geometry": {"type": "LineString", "coordinates": [[120.0, 30.0], [120.1, 30.1]]},
            }
        ],
    }
    if include_crs:
        payload["crs"] = {"type": "name", "properties": {"name": "EPSG:4326"}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_unreferenced_shapefile(path) -> None:
    driver = ogr.GetDriverByName("ESRI Shapefile")
    dataset = driver.CreateDataSource(str(path))
    layer = dataset.CreateLayer("unreferenced", srs=None, geom_type=ogr.wkbPoint)
    feature = ogr.Feature(layer.GetLayerDefn())
    geometry = ogr.Geometry(ogr.wkbPoint)
    geometry.AddPoint(120.0, 30.0)
    feature.SetGeometry(geometry)
    assert layer.CreateFeature(feature) == 0
    feature = None
    dataset = None


def _write_geotiff(path) -> None:
    """Write a tiny GeoTIFF without requiring osgeo.gdal_array (numpy bridge).

    CI pins gdal to system libgdal; the wheel/sdist may not ship ``_gdal_array``
    unless numpy was present at build time. WriteRaster avoids that dependency.
    """
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 8, 4, 1, gdal.GDT_Byte)
    data = np.arange(32, dtype=np.uint8).reshape(4, 8)
    band = dataset.GetRasterBand(1)
    try:
        band.WriteArray(data)
    except (ImportError, AttributeError):
        # Fall back when gdal_array is unavailable.
        band.WriteRaster(0, 0, 8, 4, data.tobytes())
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dataset.SetProjection(srs.ExportToWkt())
    dataset.SetGeoTransform([120.0, 0.1, 0.0, 30.0, 0.0, -0.1])
    dataset = None


def test_vector_reference_is_normalized_to_project_crs(tmp_path):
    source = tmp_path / "faults.geojson"
    _write_geojson(source, include_crs=True)

    service = ReferenceLayerService()
    layer = service.import_layer(source, "EPSG:3857")

    assert layer.source_kind == "vector"
    assert layer.source_crs == "EPSG:4326"
    assert layer.project_crs == "EPSG:3857"
    assert layer.status == "ready"
    assert layer.participates_in_snap is False
    assert service.vector_snap_points(layer)[0][0] > 13_000_000


def test_vector_reference_render_payload_is_cached_and_uses_project_crs(tmp_path):
    source = tmp_path / "faults.geojson"
    _write_geojson(source, include_crs=True)
    service = ReferenceLayerService()
    layer = service.import_layer(source, "EPSG:3857")

    features, extent = service.vector_render_payload(layer)
    cached_features, cached_extent = service.vector_render_payload(layer)

    assert features is cached_features
    assert extent == cached_extent
    assert features[0]["properties"]["name"] == "Fault A"
    assert features[0]["geometry"]["coordinates"][0][0] > 13_000_000
    assert extent[0] < extent[2] and extent[1] < extent[3]


def test_reference_without_crs_is_rejected(tmp_path):
    source = tmp_path / "unreferenced.shp"
    _write_unreferenced_shapefile(source)

    with pytest.raises(ReferenceLayerError, match="坐标"):
        ReferenceLayerService().import_layer(source, "EPSG:3857")


def test_reference_layers_round_trip_on_map_document(tmp_path):
    source = tmp_path / "reference.geojson"
    _write_geojson(source, include_crs=True)
    layer = MapReferenceLayer(
        name="断层参考",
        source_path=str(source),
        source_kind="vector",
        source_crs="EPSG:4326",
        project_crs="EPSG:3857",
        cache_key="fixture-key",
        participates_in_snap=True,
    )
    doc = PaleoMapDocument(
        name="Map A",
        linked_target_horizon="H1",
        reference_layers=[layer],
    )

    restored = PaleoMapDocument.model_validate(doc.model_dump())

    assert restored.reference_layers == [layer]
    assert restored.reference_layers[0].participates_in_snap is True


def test_raster_reference_has_bounded_preview(tmp_path):
    source = tmp_path / "reference.tif"
    _write_geotiff(source)
    layer = ReferenceLayerService().import_layer(source, "EPSG:3857")

    preview = ReferenceLayerService().raster_preview(layer, max_size=4)

    assert layer.source_kind == "raster"
    assert preview.width() == 4
    assert preview.height() == 2
    assert not preview.isNull()


def test_raster_reference_extent_is_transformed_for_unified_map_navigation(tmp_path):
    source = tmp_path / "reference.tif"
    _write_geotiff(source)
    layer = ReferenceLayerService().import_layer(source, "EPSG:3857")

    extent = ReferenceLayerService().raster_render_extent(layer)

    assert extent[0] > 13_000_000
    assert extent[0] < extent[2] and extent[1] < extent[3]


def test_refresh_status_marks_missing_source_offline(tmp_path):
    source = tmp_path / "faults.geojson"
    _write_geojson(source, include_crs=True)
    layer = ReferenceLayerService().import_layer(source, "EPSG:3857")
    assert layer.status == "ready"

    source.unlink()
    ReferenceLayerService.refresh_status(layer)

    assert layer.status == "offline"
    assert "不可用" in layer.error_message
    assert ReferenceLayerService().vector_snap_points(layer) == []


def test_refresh_status_restores_ready_when_file_returns(tmp_path):
    source = tmp_path / "faults.geojson"
    _write_geojson(source, include_crs=True)
    layer = ReferenceLayerService().import_layer(source, "EPSG:3857")
    source.unlink()
    ReferenceLayerService.refresh_status(layer)
    assert layer.status == "offline"

    _write_geojson(source, include_crs=True)
    ReferenceLayerService.refresh_status(layer)
    assert layer.status == "ready"
    assert layer.error_message == ""
