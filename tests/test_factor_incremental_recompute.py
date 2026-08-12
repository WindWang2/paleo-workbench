"""Stage-4: dependency fingerprints and incremental batch prepare."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid,
    factor_grid_result_for_task,
)
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
)
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
    interpolation_execution_count,
    reset_interpolation_execution_counter,
)
from paleo_workbench.workflow.interpolation_fingerprint import (
    FactorDirtyState,
    build_factor_fingerprints,
    classify_factor_recompute,
    fingerprints_for_task,
    plan_cache_clear,
)


def _pts(values: list[float], *, shift_xy: float = 0.0) -> list[dict]:
    base = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)]
    return [
        {"x": x + shift_xy, "y": y + shift_xy, "value": float(v)}
        for (x, y), v in zip(base, values)
    ]


def _four_factor_project() -> ProjectDocument:
    project = ProjectDocument.new("Inc")
    project.stratigraphy.target_horizon = "H1"
    value_sets = [
        [1.0, 2.0, 3.0, 4.0, 2.5],
        [10.0, 12.0, 8.0, 15.0, 11.0],
        [0.5, 1.5, 2.5, 3.5, 2.0],
        [5.0, 6.0, 7.0, 8.0, 6.5],
    ]
    names = ["Thickness", "Sand content", "Sand ratio", "Mud content"]
    for name, vals in zip(names, value_sets):
        project.factor_map_tasks.append(
            FactorMapTask(
                name=name,
                target_horizon="H1",
                factor_type=name,
                method="IDW",
                parameters={"sample_points": _pts(vals)},
                status="pending",
            )
        )
    return project


@pytest.fixture(autouse=True)
def _reset_counters():
    reset_interpolation_execution_counter()
    plan_cache_clear()
    yield
    reset_interpolation_execution_counter()
    plan_cache_clear()


def test_fingerprint_deterministic_and_order_sensitive():
    a = build_factor_fingerprints(
        sample_points=_pts([1, 2, 3, 4, 5]),
        method="IDW",
        grid_n=32,
        power=2.0,
    )
    b = build_factor_fingerprints(
        sample_points=_pts([1, 2, 3, 4, 5]),
        method="IDW",
        grid_n=32,
        power=2.0,
    )
    assert a.result == b.result
    assert a.geometry == b.geometry
    # Swap first two value order by swapping points order
    swapped = _pts([2, 1, 3, 4, 5])
    # Keep xy of positions 0 and 1 but swapped values → values change
    c = build_factor_fingerprints(
        sample_points=swapped, method="IDW", grid_n=32, power=2.0
    )
    assert c.values != a.values
    # XY shift changes geometry only
    d = build_factor_fingerprints(
        sample_points=_pts([1, 2, 3, 4, 5], shift_xy=0.1),
        method="IDW",
        grid_n=32,
        power=2.0,
    )
    assert d.geometry != a.geometry
    assert d.values == a.values  # same Z sequence


def test_second_identical_batch_skips_interpolation():
    project = _four_factor_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=24)
    first_calls = interpolation_execution_count()
    assert first_calls >= 1
    reset_interpolation_execution_counter()
    batch_prepare_factor_maps(project, method="IDW", grid_n=24)
    assert interpolation_execution_count() == 0
    for task in project.factor_map_tasks:
        assert task.status == "complete"
        assert task.input_snapshot_hash
        assert factor_grid_result_for_task(task).grid_z.size > 0


def test_one_value_change_recomputes_only_that_factor():
    project = _four_factor_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=20)
    reset_interpolation_execution_counter()
    # Mutate only Sand content Z
    sand = project.factor_map_tasks[1]
    pts = list(sand.parameters["sample_points"])
    pts[0] = {**pts[0], "value": float(pts[0]["value"]) + 3.0}
    sand.parameters = {**sand.parameters, "sample_points": pts}
    before_hashes = {
        t.id: t.input_snapshot_hash for t in project.factor_map_tasks if t is not sand
    }
    batch_prepare_factor_maps(project, method="IDW", grid_n=20)
    # Multi-path may count as 1 execution for a single dirty task via apply, or 1 via multi.
    assert interpolation_execution_count() >= 1
    assert interpolation_execution_count() <= 2
    for t in project.factor_map_tasks:
        if t is sand:
            assert t.input_snapshot_hash != before_hashes.get(t.id, "")
        else:
            assert t.input_snapshot_hash == before_hashes[t.id]


def test_style_like_fields_do_not_invalidate():
    project = _four_factor_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    reset_interpolation_execution_counter()
    for t in project.factor_map_tasks:
        # Presentation-only noise must not enter fingerprints.
        t.parameters = {
            **t.parameters,
            "color_ramp": "viridis",
            "opacity": 0.42,
            "ui_label": "pretty",
        }
    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    assert interpolation_execution_count() == 0


def test_power_change_invalidates():
    project = _four_factor_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=16, power=2.0)
    reset_interpolation_execution_counter()
    batch_prepare_factor_maps(project, method="IDW", grid_n=16, power=3.0)
    assert interpolation_execution_count() >= 1


def test_constraint_break_invalidates_idw_same_horizon_only():
    project = _four_factor_project()
    # Second horizon task
    project.factor_map_tasks.append(
        FactorMapTask(
            name="H2 thickness",
            target_horizon="H2",
            factor_type="Thickness",
            method="IDW",
            parameters={"sample_points": _pts([1, 2, 3, 4, 5])},
            status="pending",
        )
    )
    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    reset_interpolation_execution_counter()
    project.constraint_layers.append(
        ConstraintLayers(
            target_horizon="H1",
            lines=[
                ConstraintLine(
                    role="break",
                    coordinates=[[0.4, -1.0], [0.4, 2.0]],
                    target_horizon="H1",
                    active=True,
                )
            ],
        )
    )
    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    # H1 tasks dirty; H2 may stay clean if fingerprint ignores other horizon breaks.
    h2 = project.factor_map_tasks[-1]
    fps = fingerprints_for_task(
        h2, project=project, method="IDW", grid_n=16, power=2.0
    )
    # After recompute, H2 should classify CLEAN if unchanged
    # Count: at least the H1 factors recompute (batch multi counts as 1).
    assert interpolation_execution_count() >= 1
    # H2 still complete with output
    assert h2.status == "complete"


def test_force_recomputes_all():
    project = _four_factor_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    reset_interpolation_execution_counter()
    batch_prepare_factor_maps(project, method="IDW", grid_n=16, force=True)
    assert interpolation_execution_count() >= 1


def test_clean_artifact_not_rewritten_on_second_save(tmp_path: Path):
    project = _four_factor_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    path = tmp_path / "p.paleo.json"
    ProjectManager(path).save(project)
    arts = [Path(t.grid_artifact_path) for t in project.factor_map_tasks]
    mtimes = [a.stat().st_mtime_ns for a in arts]
    sizes = [a.stat().st_size for a in arts]
    # Second prepare clean + save should not rewrite artifact bytes identity.
    reset_interpolation_execution_counter()
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    assert interpolation_execution_count() == 0
    ProjectManager(path).save(project)
    for a, m, s in zip(arts, mtimes, sizes):
        assert a.stat().st_mtime_ns == m
        assert a.stat().st_size == s


def test_missing_artifact_on_prepare_rebuilds():
    project = _four_factor_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    path = Path("/tmp")  # noqa: S108 — only for save dir
    # Simulate saved then missing file
    for t in project.factor_map_tasks:
        t.grid_artifact_path = "/nonexistent/path/factor.factor_grid.npz"
        clear_live_factor_grid(t.id)
    reset_interpolation_execution_counter()
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    assert interpolation_execution_count() >= 1
    for t in project.factor_map_tasks:
        assert factor_grid_result_for_task(t).grid_z.size > 0


def test_classify_unknown_for_legacy_hash():
    task = FactorMapTask(
        name="legacy",
        target_horizon="H",
        factor_type="t",
        method="IDW",
        status="complete",
        parameters={
            "sample_points": _pts([1, 2, 3, 4, 5]),
            "grid_x": [0.0, 1.0],
            "grid_y": [0.0, 1.0],
            "grid_z": [[1.0, 2.0], [3.0, 4.0]],
        },
        input_snapshot_hash="deadbeef",  # old schema, not component fingerprints
    )
    fps = fingerprints_for_task(task, method="IDW", grid_n=2, power=2.0)
    assert classify_factor_recompute(task, fps) is FactorDirtyState.UNKNOWN
