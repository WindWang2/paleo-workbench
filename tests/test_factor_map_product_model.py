"""M1 — unified single-factor map product model.

Covers the ``FactorMapSpec`` / ``FactorMapOutput`` contract, the factor unit
authority (workflow leaf module), unit propagation through the task
interpolation pipeline, and derived-factor provenance markers (decision D11).
"""

from __future__ import annotations

import math

import pytest

from paleo_workbench.mapping.geological_pipeline.pipeline import (
    GeologicalMappingPipeline,
)
from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.project.factor_grid_artifacts import (
    clear_session_caches,
    peek_live_factor_grid,
)
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
)
from paleo_workbench.workflow.factor_map import (
    FactorMapOutput,
    FactorMapSpec,
    spec_from_task,
)
from paleo_workbench.workflow.factor_units import (
    DERIVED_FORMATION_THICKNESS_RULE,
    DERIVED_SAND_RATIO_RULE,
    color_ramp_for_factor,
    unit_for_factor,
)


@pytest.fixture(autouse=True)
def _clean_live_cache():
    clear_session_caches()
    yield
    clear_session_caches()


# ---------------------------------------------------------------------------
# factor unit authority
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factor_name", "expected_unit"),
    [
        ("砂岩厚度", "m"),
        ("H_s", "m"),
        ("地层厚度", "m"),
        ("砂地比", "%"),
        ("孔隙度", "%"),
        ("porosity", "%"),
        ("古水深", "m"),
        ("paleo_water_depth", "m"),
        ("probability", "1"),
        ("概率", "1"),
    ],
)
def test_factor_unit_authority_covers_goal_factor_families(factor_name, expected_unit):
    assert unit_for_factor(factor_name) == expected_unit


def test_factor_unit_authority_color_ramps_known():
    assert color_ramp_for_factor("孔隙度") == "porosity"
    assert color_ramp_for_factor("砂岩厚度") == "sand_thickness"
    assert color_ramp_for_factor("古水深") == "water_depth"


def test_factor_unit_authority_unknown_is_none_not_guessed():
    assert unit_for_factor("神秘参数") is None
    assert color_ramp_for_factor("神秘参数") is None


# ---------------------------------------------------------------------------
# FactorMapSpec
# ---------------------------------------------------------------------------


def _sample_spec() -> FactorMapSpec:
    return FactorMapSpec(
        factor_name="砂岩厚度",
        method="IDW",
        target_horizon="T1",
        unit="m",
        crs="EPSG:32650",
        parameters={"grid_n": 32, "power": 2.0},
        bounds=(0.0, 0.0, 10.0, 10.0),
        mask_polygon=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
        fault_polylines=[[[1.0, 1.0], [5.0, 5.0]]],
        source_refs=["asset-1@v2"],
        task_id="task-7",
    )


def test_factor_map_spec_roundtrip_is_lossless():
    spec = _sample_spec()
    restored = FactorMapSpec.from_dict(spec.to_dict())
    assert restored == spec
    assert restored.fingerprint() == spec.fingerprint()


def test_factor_map_spec_fingerprint_tracks_scientific_content():
    spec = _sample_spec()
    other = FactorMapSpec.from_dict({**spec.to_dict(), "parameters": {"grid_n": 64}})
    assert other.fingerprint() != spec.fingerprint()


def test_factor_map_spec_rejects_unknown_distance_policy():
    with pytest.raises(ValueError, match="distance_policy"):
        FactorMapSpec(factor_name="x", method="IDW", distance_policy="planar_miles")


def test_spec_with_declared_unit_resolves_known_factor_only():
    spec = FactorMapSpec(factor_name="砂地比", method="IDW")
    assert spec.with_declared_unit().unit == "%"
    unknown = FactorMapSpec(factor_name="神秘参数", method="IDW")
    assert unknown.with_declared_unit().unit is None
    already = FactorMapSpec(factor_name="砂地比", method="IDW", unit="v/v")
    assert already.with_declared_unit() is already


def test_spec_from_task_views_task_inputs():
    task = FactorMapTask(
        name="T1 孔隙度",
        target_horizon="T1",
        factor_type="孔隙度",
        method="克里金",
        parameters={"sample_points": [{"x": 0, "y": 0, "value": 12.0}], "grid_n": 24},
    )
    spec = spec_from_task(task)
    assert spec.factor_name == "孔隙度"
    assert spec.method == "克里金"
    assert spec.target_horizon == "T1"
    assert spec.unit == "%"
    assert spec.parameters["grid_n"] == 24
    assert spec.task_id == task.id


# ---------------------------------------------------------------------------
# unit propagation through the task pipeline
# ---------------------------------------------------------------------------


def _points_grid():
    return [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 10.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 10.0, "value": 3.5},
        {"x": 10.0, "y": 10.0, "value": 4.0},
    ]


def test_task_pipeline_propagates_known_unit_to_grid_and_metrics():
    task = FactorMapTask(
        name="T1 地层厚度",
        target_horizon="T1",
        factor_type="地层厚度",
        method="IDW",
        parameters={"sample_points": _points_grid()},
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    grid = peek_live_factor_grid(task.id)
    assert grid is not None
    assert grid.unit == "m"
    assert task.quality_metrics["unit"] == "m"
    assert grid.to_descriptor()["unit"] == "m"


def test_task_pipeline_explicit_parameter_unit_wins():
    task = FactorMapTask(
        name="T1 砂地比",
        target_horizon="T1",
        factor_type="砂地比",
        method="IDW",
        parameters={"sample_points": _points_grid(), "unit": "v/v"},
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    grid = peek_live_factor_grid(task.id)
    assert grid is not None
    assert grid.unit == "v/v"


def test_task_pipeline_unknown_factor_keeps_unit_undeclared():
    task = FactorMapTask(
        name="T1 神秘参数",
        target_horizon="T1",
        factor_type="神秘参数",
        method="IDW",
        parameters={"sample_points": _points_grid()},
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    grid = peek_live_factor_grid(task.id)
    assert grid is not None
    assert grid.unit is None
    assert "unit" not in task.quality_metrics


def test_factor_map_output_assembles_qc_and_provenance():
    task = FactorMapTask(
        name="T1 孔隙度",
        target_horizon="T1",
        factor_type="孔隙度",
        method="IDW",
        parameters={"sample_points": _points_grid()},
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    grid = peek_live_factor_grid(task.id)
    spec = spec_from_task(task)
    output = FactorMapOutput.from_task_result(spec, grid, task_parameters=task.parameters)
    assert output.qc["n_points"] == 4
    assert output.provenance["unit_declared"] is True
    assert output.provenance["spec_fingerprint"] == spec.fingerprint()
    described = output.describe()
    assert described["grid"]["unit"] == "%"
    # JSON-safe: round-trips through json without NaN literals.
    import json as _json

    _json.dumps(described, allow_nan=False)


# ---------------------------------------------------------------------------
# derived-factor provenance (D11)
# ---------------------------------------------------------------------------


def test_extract_factors_derived_sand_ratio_carries_provenance():
    pipeline = GeologicalMappingPipeline()
    dataset = pipeline.extract_factors(
        [
            {"well_id": "w1", "name": "W1", "x": 1.0, "y": 2.0, "H_s": 4.0, "H_t": 8.0},
            {"well_id": "w2", "name": "W2", "x": 3.0, "y": 4.0, "R_s": 50.0},
        ],
        "砂地比",
    )
    derived = [p for p in dataset.points if "derived" in p.metadata]
    measured = [p for p in dataset.points if "derived" not in p.metadata]
    assert len(derived) == 1
    assert derived[0].metadata["derived"]["rule"] == DERIVED_SAND_RATIO_RULE
    assert derived[0].value == pytest.approx(0.5)
    assert measured[0].value == 50.0
    assert dataset.metadata["derived_points"] == 1


def test_extract_factors_derived_formation_thickness_carries_provenance():
    pipeline = GeologicalMappingPipeline()
    dataset = pipeline.extract_factors(
        [
            {
                "well_id": "w1",
                "name": "W1",
                "x": 1.0,
                "y": 2.0,
                "base_depth": 120.0,
                "top_depth": 80.0,
            },
        ],
        "地层厚度",
    )
    assert len(dataset.points) == 1
    point = dataset.points[0]
    assert point.value == pytest.approx(40.0)
    assert point.metadata["derived"]["rule"] == DERIVED_FORMATION_THICKNESS_RULE


def test_extract_factors_unit_resolution_uses_authority():
    pipeline = GeologicalMappingPipeline()
    dataset = pipeline.extract_factors(
        [{"well_id": "w1", "x": 1.0, "y": 2.0, "probability": 0.75}],
        "probability",
    )
    assert dataset.unit == "1"
    assert dataset.points[0].unit == "1"


def test_no_implicit_z_to_rs_to_ht_fallback():
    """#1151 regression: a record carrying only z never yields a sand-ratio value."""
    pipeline = GeologicalMappingPipeline()
    dataset = pipeline.extract_factors(
        [{"well_id": "w1", "name": "W1", "x": 1.0, "y": 2.0, "z": 10.0}],
        "砂地比",
    )
    assert dataset.points == []
    assert not math.isnan(0.0)  # sanity: module imported cleanly


def test_spec_from_dict_rejects_bad_geometry():
    with pytest.raises(ValueError, match="bounds"):
        FactorMapSpec.from_dict({
            "factor_name": "x", "method": "IDW",
            "bounds": [0.0, 0.0, float("nan"), 1.0],
        })
    with pytest.raises(ValueError, match="bounds"):
        FactorMapSpec.from_dict({
            "factor_name": "x", "method": "IDW", "bounds": [0.0, 1.0],
        })
    with pytest.raises(ValueError, match="mask_polygon"):
        FactorMapSpec.from_dict({
            "factor_name": "x", "method": "IDW", "mask_polygon": [[0.0, 0.0]],
        })
