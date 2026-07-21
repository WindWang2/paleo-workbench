"""Tests for Vector Map Spatial Index & Zoom Debounce (Issue #14)."""
import time
import numpy as np
import pytest

from geoviz_paleo_map.spatial_index import PolygonSpatialIndex, numpy_bbox_filter
from geoviz_paleo_map.paint_scheduler import LayerPixmapCache


def test_polygon_spatial_index_bbox_query():
    # Construct 3 polygons
    polygons = [
        {"id": "poly1", "bbox": [10.0, 10.0, 20.0, 20.0]},  # inside vp (15, 15, 25, 25)
        {"id": "poly2", "bbox": [100.0, 100.0, 120.0, 120.0]}, # far outside
        {"id": "poly3", "bbox": [18.0, 18.0, 30.0, 30.0]},  # overlaps vp
    ]
    
    index = PolygonSpatialIndex(polygons)
    # Query bbox: [min_x, min_y, max_x, max_y]
    result_ids = index.query_bbox([15.0, 15.0, 25.0, 25.0])
    
    assert "poly1" in result_ids
    assert "poly3" in result_ids
    assert "poly2" not in result_ids


def test_numpy_bbox_filter_wells():
    # 1000 well coordinates: [lng, lat]
    coords = np.array([
        [110.0, 30.0],
        [150.0, 50.0],
        [111.0, 30.5],
        [80.0, 10.0],
    ])
    
    vp_bbox = (109.0, 29.0, 112.0, 31.0)  # min_lng, min_lat, max_lng, max_lat
    mask = numpy_bbox_filter(coords, vp_bbox)
    
    assert mask[0] is True or mask[0] == True  # (110, 30)
    assert mask[1] == False  # (150, 50)
    assert mask[2] == True   # (111, 30.5)
    assert mask[3] == False  # (80, 10)
