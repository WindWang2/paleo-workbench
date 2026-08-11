"""T-CONSTRAINED-IDW: haiyou constrained-IDW integrated into 单因素图制备.

Covers the host-side integration boundary (``constrained_idw_adapter``), the
method routing in ``factor_interpolation``, contract compatibility with the
existing single-factor pipeline, and that the bridge does NOT pull PyQt6 into
the host process (haiyou's package init is Qt-coupled; the host is PySide6).
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
    ProjectMeta,
)
from paleo_workbench.tokens import INTERPOLATION_METHODS, INTERPOLATION_METHOD_TOOLTIPS
from paleo_workbench.workflow import constrained_idw_adapter as cia
from paleo_workbench.workflow.constrained_idw_adapter import (
    CONSTRAINED_IDW_ENGINE_LABEL,
    run_constrained_idw,
)
from paleo_workbench.workflow.factor_interpolation import (
    METHOD_LABEL_TO_ENGINE,
    apply_interpolation_to_task,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _sample_points(n: int = 8, seed: int = 0) -> list[dict]:
    """Deterministic, well-spread sample points with values in [0, 1)."""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0.0, 10.0, size=n)
    ys = rng.uniform(0.0, 10.0, size=n)
    vals = (np.sin(xs) + np.cos(ys) + 2.0) / 4.0  # in (0, 1)
    return [{"x": float(x), "y": float(y), "value": float(v)} for x, y, v in zip(xs, ys, vals)]


def _break_layer() -> ConstraintLayers:
    """A vertical break line splitting the unit roughly in half."""
    line = ConstraintLine(
        id="break-1", name="fault", role="break", coordinates=[[5.0, -1.0], [5.0, 11.0]]
    )
    return ConstraintLayers(id="cl-1", name="breaks", lines=[line])


def _direction_layer() -> ConstraintLayers:
    line = ConstraintLine(
        id="dir-1",
        name="depocenter axis",
        role="direction",
        coordinates=[[0.0, 5.0], [10.0, 5.0]],
        semi_major=2.0,
        semi_minor=0.5,
    )
    return ConstraintLayers(id="cl-2", name="dirs", lines=[line])


@pytest.fixture(scope="module", autouse=True)
def _no_pyqt6_after_import():
    """Sanity gate: importing/running the bridge must not load PyQt6."""
    import sys

    yield
    assert "PyQt6" not in sys.modules, (
        "constrained-IDW bridge leaked PyQt6 into the host process"
    )


# --------------------------------------------------------------------------- #
# Adapter input mapping
# --------------------------------------------------------------------------- #


def test_build_wells_maps_xy_and_lnglat_and_drops_invalid():
    pts = [
        {"x": 1.0, "y": 2.0, "value": 3.0},
        {"lng": 4.0, "lat": 5.0, "value": 6.0},
        {"x": "bad", "y": 0, "value": 1.0},  # invalid coord
        {"x": 0.0, "y": 0.0, "value": float("nan")},  # invalid value
    ]
    wells = cia._build_wells(pts)
    assert len(wells) == 2
    assert (wells[0].x, wells[0].y, wells[0].value) == (1.0, 2.0, 3.0)
    assert (wells[1].x, wells[1].y, wells[1].value) == (4.0, 5.0, 6.0)


def test_build_barriers_skips_short_polylines():
    barriers = cia._build_barriers([[(1.0, 1.0)], [(0.0, 0.0), (5.0, 5.0)]])
    assert len(barriers) == 1
    assert len(barriers[0].points) == 2


def test_boundary_from_samples_is_closed_polygon():
    pts = _sample_points(8)
    wells = cia._build_wells(pts)
    boundary, exterior = cia._boundary_from_samples(pts, wells)
    assert len(exterior) >= 4  # a real polygon ring
    # Boundary polygon exterior must close (first == last) for a valid ring.
    assert tuple(exterior[0]) == tuple(exterior[-1])


def test_boundary_falls_back_to_bbox_for_collinear_points():
    # Collinear points → degenerate hull → bbox rectangle fallback.
    pts = [{"x": 0.0, "y": 0.0, "value": 0.1}, {"x": 5.0, "y": 0.0, "value": 0.2},
           {"x": 10.0, "y": 0.0, "value": 0.3}]
    wells = cia._build_wells(pts)
    _boundary, exterior = cia._boundary_from_samples(pts, wells)
    assert len(exterior) == 4  # bbox rectangle


def test_build_directions_from_constraint_layers():
    dirs = cia._build_directions([_direction_layer()], target_horizon=None)
    assert len(dirs) == 1
    # ratio derived from semi_major/semi_minor (2.0 / 0.5 = 4.0).
    assert dirs[0].ratio == pytest.approx(4.0)
    assert len(dirs[0].points) == 2


# --------------------------------------------------------------------------- #
# Algorithm behavior + contract
# --------------------------------------------------------------------------- #


def test_run_returns_interpolate_factor_grid_contract():
    result = run_constrained_idw(_sample_points(8), grid_n=30, power=2.0)
    # Contract keys consumed by apply_interpolation_to_task + downstream.
    for key in ("grid_x", "grid_y", "grid_z", "backend", "grid_n", "n_points",
                "n_break_lines", "min", "max", "mean", "r_squared"):
        assert key in result, f"missing contract key: {key}"
    assert result["backend"] == CONSTRAINED_IDW_ENGINE_LABEL
    gz = np.array(result["grid_z"])
    assert gz.shape == (result["grid_n"], result["grid_n"])
    assert np.isfinite(gz).sum() > 0
    assert result["min"] <= result["mean"] <= result["max"]
    assert 0.0 <= result["r_squared"] <= 1.0
    assert result["n_points"] == 8


def test_run_grid_resolution_clamped_to_safe_bounds():
    result = run_constrained_idw(_sample_points(6), grid_n=5000)
    assert result["grid_n"] == cia._MAX_GRID_RESOLUTION
    low = run_constrained_idw(_sample_points(6), grid_n=2)
    assert low["grid_n"] == cia._MIN_GRID_RESOLUTION


def test_run_accepts_lnglat_points():
    pts = [{"lng": float(x), "lat": float(y), "value": float(v)}
           for p in _sample_points(6) for x, y, v in [(p["x"], p["y"], p["value"])]]
    result = run_constrained_idw(pts, grid_n=24)
    assert result["n_points"] == 6
    assert np.isfinite(np.array(result["grid_z"])).sum() > 0


def test_run_is_deterministic_for_same_input():
    pts = _sample_points(7, seed=3)
    a = run_constrained_idw(pts, grid_n=28)
    b = run_constrained_idw(pts, grid_n=28)
    # Grids legitimately contain NaN outside the domain → compare NaN-aware.
    assert np.array_equal(
        np.array(a["grid_z"]), np.array(b["grid_z"]), equal_nan=True
    )


def test_run_with_barriers_counts_break_lines():
    result = run_constrained_idw(
        _sample_points(8), grid_n=30, layers=[_break_layer()], target_horizon=None
    )
    assert result["n_break_lines"] == 1
    assert isinstance(result["boundary"], list) and len(result["boundary"]) >= 4


def test_run_with_directions_counts_direction_lines():
    result = run_constrained_idw(
        _sample_points(8), grid_n=30, layers=[_direction_layer()], target_horizon=None
    )
    assert result["n_direction_lines"] == 1


def test_run_barriers_change_surface_vs_unconstrained():
    """Barriers are not a no-op: the barrier run must differ from the plain run."""
    pts = _sample_points(10, seed=1)
    plain = np.array(run_constrained_idw(pts, grid_n=30)["grid_z"])
    blocked = np.array(
        run_constrained_idw(pts, grid_n=30, layers=[_break_layer()], target_horizon=None)[
            "grid_z"
        ]
    )
    assert not np.array_equal(plain, blocked)


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #


def test_run_raises_on_too_few_valid_points():
    with pytest.raises(ValueError, match="至少 3 个"):
        run_constrained_idw(
            [{"x": 0.0, "y": 0.0, "value": 0.1}, {"x": 1.0, "y": 1.0, "value": 0.2}],
            grid_n=20,
        )


def test_run_raises_when_all_values_invalid():
    with pytest.raises(ValueError):
        run_constrained_idw(
            [{"x": 0.0, "y": 0.0, "value": float("nan")},
             {"x": 1.0, "y": 0.0, "value": float("nan")},
             {"x": 0.0, "y": 1.0, "value": float("nan")}],
            grid_n=20,
        )


def test_run_respects_cancellation_token_before_compute():
    from geoviz import CancellationToken, JobCancelled

    token = CancellationToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        run_constrained_idw(_sample_points(6), grid_n=24, cancellation_token=token)


# --------------------------------------------------------------------------- #
# Host dispatch (apply_interpolation_to_task) + provenance
# --------------------------------------------------------------------------- #


def test_method_label_routes_to_constrained_idw():
    assert METHOD_LABEL_TO_ENGINE["约束IDW"] == CONSTRAINED_IDW_ENGINE_LABEL


def test_apply_interpolation_runs_constrained_idw_and_sets_provenance():
    task = FactorMapTask(
        name="H 砂地比",
        target_horizon="H",
        factor_type="砂地比",
        method="约束IDW",
        parameters={"sample_points": _sample_points(8)},
        status="pending",
    )
    apply_interpolation_to_task(task, method="约束IDW", grid_n=30)
    assert task.status == "complete"
    assert task.method == "约束IDW"
    assert task.generator_version is not None
    assert task.input_snapshot_hash
    p = task.parameters
    assert p["interp_backend"] == CONSTRAINED_IDW_ENGINE_LABEL
    assert "grid_z" not in p  # Stage-3: live FactorGrid cache, not nested lists
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    assert np.isfinite(factor_grid_result_for_task(task).grid_z).sum() > 0
    qm = task.quality_metrics
    assert qm["backend"] == CONSTRAINED_IDW_ENGINE_LABEL
    assert "r_squared" in qm and 0.0 <= qm["r_squared"] <= 1.0


def test_apply_interpolation_persists_break_polylines_with_project_constraints():
    project = ProjectDocument(meta=ProjectMeta(name="t"))
    project.constraint_layers.append(_break_layer())
    task = FactorMapTask(
        name="H 砂地比",
        target_horizon="",
        factor_type="砂地比",
        method="约束IDW",
        parameters={"sample_points": _sample_points(8)},
        status="pending",
    )
    apply_interpolation_to_task(task, method="约束IDW", grid_n=30, project=project)
    # Barriers resolved from project constraint layers and persisted for provenance.
    assert task.parameters["n_break_lines"] == 1
    assert "break_polylines" in task.parameters
    assert len(task.parameters["break_polylines"]) == 1


def test_constrained_idw_and_plain_idw_produce_different_grids():
    """约束IDW is a distinct method, not an alias of IDW."""
    pts = _sample_points(9, seed=2)
    t_c = FactorMapTask(name="c", target_horizon="H", factor_type="砂地比",
                        method="约束IDW", parameters={"sample_points": pts}, status="pending")
    t_i = FactorMapTask(name="i", target_horizon="H", factor_type="砂地比",
                        method="IDW", parameters={"sample_points": pts}, status="pending")
    apply_interpolation_to_task(t_c, method="约束IDW", grid_n=30)
    apply_interpolation_to_task(t_i, method="IDW", grid_n=30)
    assert t_c.parameters["interp_backend"] == CONSTRAINED_IDW_ENGINE_LABEL
    assert t_i.parameters["interp_backend"] == "idw"
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    # NaN-aware: the methods must differ on at least one finite cell.
    zc = factor_grid_result_for_task(t_c).grid_z
    zi = factor_grid_result_for_task(t_i).grid_z
    both_finite = np.isfinite(zc) & np.isfinite(zi)
    assert both_finite.any()
    assert not np.allclose(zc[both_finite], zi[both_finite])


# --------------------------------------------------------------------------- #
# UI registration + project serialization round-trip
# --------------------------------------------------------------------------- #


def test_ui_registers_constrained_idw_method_and_tooltip():
    assert "约束IDW" in INTERPOLATION_METHODS
    assert "约束IDW" in INTERPOLATION_METHOD_TOOLTIPS


def test_factor_task_with_constrained_idw_serializes_round_trip():
    task = FactorMapTask(
        name="H 砂地比",
        target_horizon="H",
        factor_type="砂地比",
        method="约束IDW",
        parameters={"sample_points": _sample_points(7)},
        status="pending",
    )
    apply_interpolation_to_task(task, method="约束IDW", grid_n=26)
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    live_before = factor_grid_result_for_task(task).grid_z.copy()
    # Project save → reopen path uses pydantic model_dump / model_validate.
    # Metadata round-trips; numerical payload is live-cache / artifact, not dump.
    dump = task.model_dump()
    restored = FactorMapTask.model_validate(dump)
    assert restored.method == "约束IDW"
    assert restored.parameters["interp_backend"] == CONSTRAINED_IDW_ENGINE_LABEL
    assert "grid_z" not in restored.parameters
    # Same task id still hits live cache in-process.
    restored.id = task.id
    np.testing.assert_array_equal(
        factor_grid_result_for_task(restored).grid_z, live_before
    )
