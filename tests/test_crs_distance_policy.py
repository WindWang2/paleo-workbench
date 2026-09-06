"""M3 — boundary / CRS / unit scientific correctness.

Covers the D5 distance-policy resolution + annotation, removal of the silent
EPSG:4326 fallback at the layer-construction boundary (undeclared CRS stays
undeclared), and the previously-dead ``InterpolationOptions.boundary`` now
being consumed as a domain mask identical along the chain (D6).
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
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    generate_facies_polygon_layer,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (
    GeologicalMappingPipeline,
)
from paleo_workbench.project.factor_grid_artifacts import (
    clear_session_caches,
    peek_live_factor_grid,
)
from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.workflow.crs_policy import (
    crs_is_geographic,
    resolve_distance_policy,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
)


@pytest.fixture(autouse=True)
def _clean_live_cache():
    clear_session_caches()
    yield
    clear_session_caches()


# ---------------------------------------------------------------------------
# CRS axis-unit knowledge
# ---------------------------------------------------------------------------


def test_crs_is_geographic_known_ids():
    assert crs_is_geographic("EPSG:4326") is True
    assert crs_is_geographic("EPSG:3857") is False
    assert crs_is_geographic(None) is None
    assert crs_is_geographic("") is None


def test_crs_is_geographic_pyproj_projected():
    pytest.importorskip("pyproj")
    assert crs_is_geographic("EPSG:32650") is False
    assert crs_is_geographic("EPSG:4490") is True  # CGCS2000 geographic


# ---------------------------------------------------------------------------
# distance policy resolution (D5)
# ---------------------------------------------------------------------------


def test_geographic_crs_default_resolves_to_annotated_planar_degrees():
    resolved = resolve_distance_policy("EPSG:4326")
    assert resolved["policy"] == "planar_degrees"
    assert resolved["warning"] is not None
    assert "planar_degrees" in resolved["annotation"]


def test_explicit_planar_degrees_override_has_no_warning():
    resolved = resolve_distance_policy("EPSG:4326", "planar_degrees")
    assert resolved["policy"] == "planar_degrees"
    assert resolved["warning"] is None


def test_projected_crs_default_stays_planar():
    pytest.importorskip("pyproj")
    resolved = resolve_distance_policy("EPSG:32650")
    assert resolved["policy"] == "planar"
    assert resolved["warning"] is None


def test_undeclared_crs_marks_assumption_unverified():
    resolved = resolve_distance_policy(None)
    assert resolved["axes_known"] is None
    assert "undeclared" in resolved["annotation"]


def test_unknown_policy_rejected():
    with pytest.raises(ValueError, match="distance_policy"):
        resolve_distance_policy("EPSG:4326", "planar_lightyears")


# ---------------------------------------------------------------------------
# task pipeline carries the policy + warning
# ---------------------------------------------------------------------------


def _points_grid():
    return [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 10.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 10.0, "value": 3.5},
        {"x": 10.0, "y": 10.0, "value": 4.0},
    ]


def test_task_pipeline_annotates_geographic_distance_policy():
    project = type(
        "ProjectStub",
        (),
        {
            "coordinate": type("Coord", (), {"project_crs": None})(),
            "constraint_layers": [],
        },
    )()
    task = FactorMapTask(
        name="T1 地层厚度",
        target_horizon="T1",
        factor_type="地层厚度",
        method="IDW",
        parameters={"sample_points": _points_grid()},
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8, project=project)
    grid = peek_live_factor_grid(task.id)
    assert grid is not None
    # No project → CRS undeclared: planar assumption flagged unverified.
    assert grid.algorithm_parameters["distance_policy"] == "planar"
    assert "undeclared" in grid.algorithm_parameters["distance_policy_annotation"]
    assert task.quality_metrics["distance_policy"] == "planar"


def test_task_pipeline_geographic_project_crs_gets_warning():
    project = type(
        "ProjectStub",
        (),
        {
            "coordinate": type("Coord", (), {"project_crs": "EPSG:4326"})(),
            "constraint_layers": [],
        },
    )()
    task = FactorMapTask(
        name="T1 地层厚度",
        target_horizon="T1",
        factor_type="地层厚度",
        method="IDW",
        parameters={"sample_points": _points_grid()},
    )
    apply_interpolation_to_task(
        task, method="IDW", grid_n=8, project=project
    )
    grid = peek_live_factor_grid(task.id)
    assert grid is not None
    assert grid.algorithm_parameters["distance_policy"] == "planar_degrees"
    assert task.quality_metrics["distance_policy"] == "planar_degrees"
    assert "degrees as planar" in task.quality_metrics["distance_warning"]


# ---------------------------------------------------------------------------
# layer boundary: undeclared stays undeclared (no EPSG:4326 guess)
# ---------------------------------------------------------------------------


def _undeclared_grid() -> FactorGridResult:
    gx = np.linspace(0.0, 10.0, 6)
    gy = np.linspace(0.0, 10.0, 6)
    xx, yy = np.meshgrid(gx, gy)
    gz = (xx + yy).astype(np.float32)
    return FactorGridResult(
        grid_z=gz,
        grid_x=gx,
        grid_y=gy,
        factor_name="地层厚度",
        algorithm_id="idw",
        crs=None,
        unit="m",
    )


def test_contour_layer_carries_undeclared_crs_not_a_guess():
    layer = generate_contour_layer(_undeclared_grid())
    assert layer.crs == ""


def test_facies_layer_carries_undeclared_crs_not_a_guess():
    layer = generate_facies_polygon_layer(_undeclared_grid())
    assert layer.crs == ""


def test_grid_layer_carries_undeclared_crs_not_a_guess():
    pipeline = GeologicalMappingPipeline()
    layer = pipeline.create_grid_layer(_undeclared_grid())
    assert layer.crs == ""


def test_declared_crs_still_propagates_to_layers():
    pipeline = GeologicalMappingPipeline()
    grid = _undeclared_grid()
    grid.crs = "EPSG:32650"
    assert pipeline.create_grid_layer(grid).crs == "EPSG:32650"
    assert generate_contour_layer(grid).crs == "EPSG:32650"
    assert generate_facies_polygon_layer(grid).crs == "EPSG:32650"


# ---------------------------------------------------------------------------
# dead boundary option is now consumed (D6)
# ---------------------------------------------------------------------------


def _dataset() -> GeologicalFactorDataset:
    return GeologicalFactorDataset(
        factor_name="孔隙度",
        unit="%",
        target_horizon="T1",
        crs="EPSG:32650",
        points=[
            GeologicalFactor(name="孔隙度", value=10, x=1000, y=1000, crs="EPSG:32650"),
            GeologicalFactor(name="孔隙度", value=12, x=2000, y=1000, crs="EPSG:32650"),
            GeologicalFactor(name="孔隙度", value=14, x=1000, y=2000, crs="EPSG:32650"),
            GeologicalFactor(name="孔隙度", value=16, x=2000, y=2000, crs="EPSG:32650"),
        ],
    )


def test_interpolation_options_boundary_is_consumed_as_domain_mask():
    options = InterpolationOptions(
        method="idw",
        grid_n=12,
        boundary=[(900.0, 900.0), (1600.0, 900.0), (1600.0, 1600.0), (900.0, 1600.0)],
    )
    result = interpolate_factor(_dataset(), options)
    assert result.algorithm_parameters["domain_mask"] == "user_boundary"
    assert result.algorithm_parameters["domain_masked_cells"] > 0
    # Cells outside the ring are nodata; the ring itself is recorded.
    inside_x = [x for x in result.grid_x if 900 <= x <= 1600]
    inside_y = [y for y in result.grid_y if 900 <= y <= 1600]
    assert inside_x and inside_y
    iy = [i for i, y in enumerate(result.grid_y if False else result.grid_y) if 900 <= y <= 1600]
    ix = [i for i, x in enumerate(result.grid_x) if 900 <= x <= 1600]
    outside_vals = [
        result.grid_z[j, i]
        for j in range(result.grid_z.shape[0])
        if j not in iy
        for i in ix
    ]
    assert all(not np.isfinite(v) for v in outside_vals)


def test_interpolate_factor_annotates_distance_policy_dataset_path():
    options = InterpolationOptions(method="idw", grid_n=12)
    result = interpolate_factor(_dataset(), options)
    assert result.algorithm_parameters["distance_policy"] == "planar"
    assert "EPSG:32650" in result.algorithm_parameters["distance_policy_annotation"]
