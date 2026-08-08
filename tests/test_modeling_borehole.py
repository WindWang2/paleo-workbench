import numpy as np
import pytest
from geoviz import BoreholeTraceGenerator, get_seam_boundaries

def test_get_seam_boundaries_flat():
    data = {
        "seam_1_top": 10.0,
        "seam_1_bottom": 5.0,
        "seam_3_top": -5.0,
        "seam_3_bottom": -10.0,
    }
    s1_top, s1_bot, s3_top, s3_bot = get_seam_boundaries(data)
    assert s1_top == 10.0
    assert s1_bot == 5.0
    assert s3_top == -5.0
    assert s3_bot == -10.0

def test_get_seam_boundaries_nested():
    data = {
        "seams": {
            "seam 1": {"top": 20.0, "bottom": 15.0},
            "seam 3": {"top": 0.0, "bottom": -5.0}
        }
    }
    s1_top, s1_bot, s3_top, s3_bot = get_seam_boundaries(data)
    assert s1_top == 20.0
    assert s1_bot == 15.0
    assert s3_top == 0.0
    assert s3_bot == -5.0

def test_get_seam_boundaries_fallback():
    data = {}
    s1_top, s1_bot, s3_top, s3_bot = get_seam_boundaries(data)
    assert s1_top == 0.0
    assert s1_bot == -10.0
    assert s3_top == -100.0
    assert s3_bot == -110.0

def test_borehole_vertical_segmentation():
    # Vertical well from z=50 down to z=-150
    trajectory = [
        [0.0, 0.0, 50.0],
        [0.0, 0.0, -150.0]
    ]
    well_data = {
        "id": "W-01",
        "trajectory": trajectory,
        "seam_1_top": 10.0,
        "seam_1_bottom": 5.0,
        "seam_3_top": -50.0,
        "seam_3_bottom": -60.0
    }
    
    results = BoreholeTraceGenerator.generate_segments([well_data])
    assert len(results) == 1
    well_result = results[0]
    assert well_result["well_id"] == "W-01"
    
    segments = well_result["segments"]
    # We expect 5 segments: above_seam_1, seam_1, between_seam_1_and_3, seam_3, below_seam_3
    assert len(segments) == 5
    
    # 1. above_seam_1 (from 50.0 down to 10.0)
    assert segments[0]["type"] == "above_seam_1"
    pts0 = segments[0]["points"]
    assert np.allclose(pts0[0], [0.0, 0.0, 50.0])
    assert np.allclose(pts0[-1], [0.0, 0.0, 10.0])
    
    # 2. seam_1 (from 10.0 down to 5.0)
    assert segments[1]["type"] == "seam_1"
    pts1 = segments[1]["points"]
    assert np.allclose(pts1[0], [0.0, 0.0, 10.0])
    assert np.allclose(pts1[-1], [0.0, 0.0, 5.0])
    
    # 3. between_seam_1_and_3 (from 5.0 down to -50.0)
    assert segments[2]["type"] == "between_seam_1_and_3"
    pts2 = segments[2]["points"]
    assert np.allclose(pts2[0], [0.0, 0.0, 5.0])
    assert np.allclose(pts2[-1], [0.0, 0.0, -50.0])
    
    # 4. seam_3 (from -50.0 down to -60.0)
    assert segments[3]["type"] == "seam_3"
    pts3 = segments[3]["points"]
    assert np.allclose(pts3[0], [0.0, 0.0, -50.0])
    assert np.allclose(pts3[-1], [0.0, 0.0, -60.0])
    
    # 5. below_seam_3 (from -60.0 down to -150.0)
    assert segments[4]["type"] == "below_seam_3"
    pts4 = segments[4]["points"]
    assert np.allclose(pts4[0], [0.0, 0.0, -60.0])
    assert np.allclose(pts4[-1], [0.0, 0.0, -150.0])

def test_borehole_deviated_segmentation():
    # Deviated well where x, y and z change
    trajectory = [
        [0.0, 0.0, 20.0],
        [10.0, 10.0, -20.0]
    ]
    well_data = {
        "id": "W-02",
        "trajectory": trajectory,
        "seam_1_top": 10.0,
        "seam_1_bottom": 0.0,
        "seam_3_top": -10.0,
        "seam_3_bottom": -15.0
    }
    
    # z changes from 20 to -20 (delta z = -40)
    # x changes from 0 to 10 (delta x = 10)
    # y changes from 0 to 10 (delta y = 10)
    # Let's verify boundary points:
    # seam_1_top (10.0) -> t = (10 - 20) / -40 = 0.25 -> P = [2.5, 2.5, 10.0]
    # seam_1_bottom (0.0) -> t = (0 - 20) / -40 = 0.50 -> P = [5.0, 5.0, 0.0]
    # seam_3_top (-10.0) -> t = (-10 - 20) / -40 = 0.75 -> P = [7.5, 7.5, -10.0]
    # seam_3_bottom (-15.0) -> t = (-15 - 20) / -40 = 0.875 -> P = [8.75, 8.75, -15.0]
    
    results = BoreholeTraceGenerator.generate_segments([well_data])
    segments = results[0]["segments"]
    assert len(segments) == 5
    
    assert segments[0]["type"] == "above_seam_1"
    assert np.allclose(segments[0]["points"][-1], [2.5, 2.5, 10.0])
    
    assert segments[1]["type"] == "seam_1"
    assert np.allclose(segments[1]["points"][0], [2.5, 2.5, 10.0])
    assert np.allclose(segments[1]["points"][-1], [5.0, 5.0, 0.0])
    
    assert segments[2]["type"] == "between_seam_1_and_3"
    assert np.allclose(segments[2]["points"][0], [5.0, 5.0, 0.0])
    assert np.allclose(segments[2]["points"][-1], [7.5, 7.5, -10.0])
    
    assert segments[3]["type"] == "seam_3"
    assert np.allclose(segments[3]["points"][0], [7.5, 7.5, -10.0])
    assert np.allclose(segments[3]["points"][-1], [8.75, 8.75, -15.0])
    
    assert segments[4]["type"] == "below_seam_3"
    assert np.allclose(segments[4]["points"][0], [8.75, 8.75, -15.0])
    assert np.allclose(segments[4]["points"][-1], [10.0, 10.0, -20.0])

def test_borehole_partial_or_missing_seams():
    # Trajectory that does not reach seam 3
    trajectory = [
        [0.0, 0.0, 20.0],
        [0.0, 0.0, -20.0]
    ]
    well_data = {
        "id": "W-03",
        "trajectory": trajectory,
        "seam_1_top": 10.0,
        "seam_1_bottom": 5.0,
        "seam_3_top": -50.0, # Not reached!
        "seam_3_bottom": -60.0 # Not reached!
    }
    
    results = BoreholeTraceGenerator.generate_segments([well_data])
    segments = results[0]["segments"]
    
    # We expect segments: above_seam_1, seam_1, between_seam_1_and_3 (down to -20.0)
    assert len(segments) == 3
    assert segments[0]["type"] == "above_seam_1"
    assert segments[1]["type"] == "seam_1"
    assert segments[2]["type"] == "between_seam_1_and_3"
    assert np.allclose(segments[2]["points"][-1], [0.0, 0.0, -20.0])

def test_borehole_empty_and_invalid():
    # Invalid or empty inputs
    assert BoreholeTraceGenerator.generate_segments([]) == []
    
    results = BoreholeTraceGenerator.generate_segments([{"id": "empty", "trajectory": []}])
    assert results[0]["segments"] == []
    
    results = BoreholeTraceGenerator.generate_segments([{"id": "single", "trajectory": [[0, 0, 0]]}])
    assert results[0]["segments"] == []
