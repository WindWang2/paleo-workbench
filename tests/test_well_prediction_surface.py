"""测井相预测井点提取与点到面（无 Qt）。"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.well_prediction_surface import (
    POINTS_LAYER_TASK_ID,
    SURFACE_LAYER_TASK_ID,
    WellFaciesPoint,
    point_to_surface_features,
    representative_facies,
    well_facies_points,
    well_xy,
)
from paleo_workbench.project.domain import EntityAssetLink, WellEntity, WorkArea
from paleo_workbench.project.models import (
    PredictionTask,
    ProjectDocument,
    ResourceItem,
)


def test_representative_facies_picks_thickest():
    picked = representative_facies([
        {"facies": "三角洲", "top": 0, "bottom": 10, "probability": 0.4},
        {"facies": "滨浅湖", "top": 10, "bottom": 40, "probability": 0.9},
        {"facies": "三角洲", "top": 40, "bottom": 45, "probability": 0.8},
    ])
    assert picked is not None
    assert picked[0] == "滨浅湖"


def test_representative_facies_sums_same_class_thickness():
    picked = representative_facies([
        {"facies": "三角洲", "top": 0, "bottom": 20, "probability": 0.5},
        {"facies": "滨浅湖", "top": 20, "bottom": 25, "probability": 0.9},
        {"facies": "三角洲", "top": 25, "bottom": 40, "probability": 0.5},
    ])
    assert picked is not None
    assert picked[0] == "三角洲"


def test_representative_facies_honors_horizon_when_present():
    picked = representative_facies(
        [
            {"facies": "三角洲", "top": 0, "bottom": 50,
             "stratigraphic_unit": "T1", "probability": 0.9},
            {"facies": "滨浅湖", "top": 50, "bottom": 55,
             "stratigraphic_unit": "D63", "probability": 0.4},
        ],
        horizon="D63",
    )
    assert picked is not None
    assert picked[0] == "滨浅湖"


def test_well_xy_prefers_project_crs():
    well = WellEntity(
        name="W1", surface_x=1.0, surface_y=2.0,
        project_x=10.0, project_y=20.0,
    )
    assert well_xy(well) == (10.0, 20.0)


def _project_with_well_prediction() -> ProjectDocument:
    project = ProjectDocument.new("测井预测面")
    well = WellEntity(
        id="well_w1", name="W1",
        project_x=0.0, project_y=0.0, surface_x=0.0, surface_y=0.0,
    )
    project.wells.append(well)
    project.resources.append(ResourceItem(
        id="res_w1", name="W1", path="w1.las", type="well_log", format="las",
    ))
    project.entity_asset_links.append(EntityAssetLink(
        entity_type="well", entity_id="well_w1", asset_id="res_w1",
        role="well_log",
    ))
    project.prediction_tasks.append(PredictionTask(
        id="pred_w1",
        name="测井相预测 · D63",
        adapter_kind="http",
        input_refs={"well_log_resource_ids": ["res_w1"]},
        result_summary={
            "predicted_regions": [
                {"facies": "三角洲前缘", "top": 100, "bottom": 140, "probability": 0.8},
                {"facies": "滨浅湖", "top": 140, "bottom": 145, "probability": 0.5},
            ],
            "spatial": {"type": "WELL_INTERVALS"},
        },
    ))
    return project


def test_well_facies_points_join_intervals_to_well_xy():
    project = _project_with_well_prediction()
    points = well_facies_points(project)
    assert len(points) == 1
    assert points[0].facies == "三角洲前缘"
    assert points[0].x == pytest.approx(0.0)
    assert points[0].y == pytest.approx(0.0)
    assert points[0].well_id == "well_w1"


def test_well_facies_points_empty_without_xy():
    project = _project_with_well_prediction()
    project.wells[0].project_x = None
    project.wells[0].project_y = None
    project.wells[0].surface_x = None
    project.wells[0].surface_y = None
    assert well_facies_points(project) == []


def test_spatial_point_features_used_when_present():
    project = ProjectDocument.new("空间井点")
    project.prediction_tasks.append(PredictionTask(
        name="测井相预测",
        input_refs={"well_logs": ["r1"]},
        result_summary={"spatial": {
            "type": "WELL_INTERVALS",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
                "properties": {"facies": "分流河道", "probability": 0.7},
            }],
        }},
    ))
    points = well_facies_points(project)
    assert len(points) == 1
    assert points[0].facies == "分流河道"
    assert points[0].x == pytest.approx(3.0)


def test_point_to_surface_assigns_nearest_well_facies():
    points = [
        WellFaciesPoint(x=0.0, y=0.0, facies="三角洲"),
        WellFaciesPoint(x=10.0, y=0.0, facies="滨浅湖"),
    ]
    project = ProjectDocument.new("点到面")
    project.workarea = WorkArea(
        name="工区",
        boundary=[[-1, -1], [11, -1], [11, 1], [-1, 1], [-1, -1]],
        project_crs="EPSG:32650",
        boundary_crs="EPSG:32650",
    )
    project.coordinate.project_crs = "EPSG:32650"
    features = point_to_surface_features(points, project=project, grid_n=20)
    assert features
    names = {str(props.get("facies") or "") for _geom, props in features}
    assert "三角洲" in names
    assert "滨浅湖" in names


def test_point_to_surface_empty_without_points():
    assert point_to_surface_features([]) == []


def test_surface_layer_task_id_is_stable():
    assert POINTS_LAYER_TASK_ID == "well_facies_points"
    assert SURFACE_LAYER_TASK_ID == "well_facies_point_to_surface"
