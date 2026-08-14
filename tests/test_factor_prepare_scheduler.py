"""Stage-5 prepare scheduler: slim snapshot, CLEAN/DIRTY, commit, stale, cancel."""

from __future__ import annotations

import tracemalloc

import numpy as np
import pytest

from geoviz import CancellationToken, JobCancelled
from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
    interpolation_execution_count,
    reset_interpolation_execution_counter,
)
from paleo_workbench.workflow.factor_prepare_scheduler import (
    build_prepare_snapshot,
    commit_prepare_batch_result,
    materialize_execution_project,
    prepare_worker_count,
    run_factor_prepare_schedule,
)


def _points(n: int = 8, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    return [
        {
            "x": float(rng.uniform(0, 10)),
            "y": float(rng.uniform(0, 10)),
            "value": float(rng.uniform(0.1, 0.9)),
        }
        for _ in range(n)
    ]


def _project_with_tasks(n: int = 4, *, shared_xy: bool = True) -> ProjectDocument:
    project = ProjectDocument.new("Sched")
    project.stratigraphy.target_horizon = "H1"
    base = _points(12, seed=1)
    for i in range(n):
        pts = list(base) if shared_xy else _points(12, seed=10 + i)
        if shared_xy:
            pts = [
                {**p, "value": float(p["value"]) + 0.01 * i}
                for p in pts
            ]
        project.factor_map_tasks.append(
            FactorMapTask(
                name=f"f{i}",
                target_horizon="H1",
                factor_type=f"type{i}",
                method="IDW",
                parameters={"sample_points": pts},
                status="pending",
            )
        )
    return project


def test_prepare_snapshot_excludes_unrelated_project_bulk():
    project = ProjectDocument.new("Fat")
    project.stratigraphy.target_horizon = "H1"
    for i in range(200):
        project.resources.append(
            ResourceItem(
                name=f"r{i}",
                path=f"/tmp/bulk/{i}/" + ("x" * 120),
                type="well",
                format="las",
            )
        )
    project.factor_map_tasks.append(
        FactorMapTask(
            name="only",
            target_horizon="H1",
            factor_type="砂地比",
            method="IDW",
            parameters={"sample_points": _points()},
            status="pending",
        )
    )
    snap = build_prepare_snapshot(project, generation=1, method="IDW")
    exec_p = materialize_execution_project(snap)
    assert len(exec_p.resources) == 0
    assert len(exec_p.factor_map_tasks) == 1
    assert exec_p.factor_map_tasks[0].id == project.factor_map_tasks[0].id
    # Live project untouched.
    assert len(project.resources) == 200


def test_snapshot_memory_not_linear_in_unrelated_resources():
    def fat(n_res: int) -> ProjectDocument:
        p = ProjectDocument.new(f"M{n_res}")
        p.stratigraphy.target_horizon = "H1"
        for i in range(n_res):
            p.resources.append(
                ResourceItem(
                    name=f"r{i}",
                    path=f"/tmp/{i}/" + ("y" * 256),
                    type="well",
                    format="las",
                )
            )
        p.factor_map_tasks.append(
            FactorMapTask(
                name="t",
                target_horizon="H1",
                factor_type="砂地比",
                method="IDW",
                parameters={"sample_points": _points(16)},
                status="pending",
            )
        )
        return p

    p_small = fat(20)
    p_large = fat(800)

    tracemalloc.start()
    s_small = build_prepare_snapshot(p_small, generation=1)
    _, peak_small = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    s_large = build_prepare_snapshot(p_large, generation=2)
    _, peak_large = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Snapshot allocation must not track unrelated resource bulk.
    ratio = peak_large / max(peak_small, 1)
    assert ratio < 3.0, f"snapshot peak grew {ratio:.1f}x with 40x resources"
    assert len(s_small.tasks) == len(s_large.tasks) == 1
    assert len(materialize_execution_project(s_large).resources) == 0


def test_all_clean_zero_interpolation():
    project = _project_with_tasks(4)
    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    reset_interpolation_execution_counter()
    snap = build_prepare_snapshot(project, generation=3, method="IDW", grid_n=16)
    result = run_factor_prepare_schedule(snap, workers=1)
    assert result.clean_count == 4
    assert result.dirty_count == 0
    assert result.executed_count == 0
    assert interpolation_execution_count() == 0


def test_one_dirty_values_recomputes_only_that_factor():
    project = _project_with_tasks(4)
    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    # Change one factor's Z only.
    pts = list(project.factor_map_tasks[1].parameters["sample_points"])
    pts[0] = {**pts[0], "value": float(pts[0]["value"]) + 1.5}
    project.factor_map_tasks[1].parameters = {
        **project.factor_map_tasks[1].parameters,
        "sample_points": pts,
    }
    reset_interpolation_execution_counter()
    snap = build_prepare_snapshot(project, generation=4, method="IDW", grid_n=16)
    result = run_factor_prepare_schedule(snap, workers=1)
    assert result.clean_count == 3
    assert result.dirty_count == 1
    assert result.executed_count == 1
    dirty_ids = {r.task_id for r in result.task_results if not r.reused}
    assert dirty_ids == {project.factor_map_tasks[1].id}


def test_same_geometry_batch_preserves_multi_factor_path():
    project = _project_with_tasks(4, shared_xy=True)
    reset_interpolation_execution_counter()
    snap = build_prepare_snapshot(project, generation=5, method="IDW", grid_n=16)
    result = run_factor_prepare_schedule(snap, workers=1)
    assert result.dirty_count == 4
    assert result.executed_count == 4
    # Multi-factor vectorised path counts as one interpolation execution.
    assert interpolation_execution_count() == 1
    assert all(
        r.task is not None and r.task.status == "complete"
        for r in result.task_results
        if not r.reused
    )


def test_commit_targets_by_task_id_without_replacing_clean():
    project = _project_with_tasks(3)
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    clean_ids = [t.id for t in project.factor_map_tasks]
    clean_hashes = [t.input_snapshot_hash for t in project.factor_map_tasks]

    # Dirty only task 0.
    pts = list(project.factor_map_tasks[0].parameters["sample_points"])
    pts[0] = {**pts[0], "value": float(pts[0]["value"]) + 2.0}
    project.factor_map_tasks[0].parameters = {
        **project.factor_map_tasks[0].parameters,
        "sample_points": pts,
    }
    snap = build_prepare_snapshot(project, generation=6, method="IDW", grid_n=12)
    result = run_factor_prepare_schedule(snap, workers=1)
    discarded = commit_prepare_batch_result(
        project, result, expected_generation=6
    )
    assert discarded == []
    assert [t.id for t in project.factor_map_tasks] == clean_ids
    # Unchanged tasks keep their previous fingerprint stamp.
    assert project.factor_map_tasks[1].input_snapshot_hash == clean_hashes[1]
    assert project.factor_map_tasks[2].input_snapshot_hash == clean_hashes[2]
    assert project.factor_map_tasks[0].status == "complete"


def test_stale_generation_discards_commit():
    project = _project_with_tasks(2)
    snap = build_prepare_snapshot(project, generation=10, method="IDW", grid_n=12)
    result = run_factor_prepare_schedule(snap, workers=1)
    discarded = commit_prepare_batch_result(
        project, result, expected_generation=11
    )
    assert len(discarded) == result.count
    assert project.factor_map_tasks[0].status == "pending"


def test_input_changed_during_run_discards_stale_patch():
    project = _project_with_tasks(1)
    snap = build_prepare_snapshot(project, generation=7, method="IDW", grid_n=12)
    result = run_factor_prepare_schedule(snap, workers=1)
    # User edits live input after schedule but before commit.
    pts = list(project.factor_map_tasks[0].parameters["sample_points"])
    pts[0] = {**pts[0], "value": 99.0}
    project.factor_map_tasks[0].parameters = {
        **project.factor_map_tasks[0].parameters,
        "sample_points": pts,
    }
    discarded = commit_prepare_batch_result(
        project, result, expected_generation=7
    )
    assert discarded == [project.factor_map_tasks[0].id]
    assert project.factor_map_tasks[0].status == "pending"


def test_cancel_before_execute_marks_cancelled():
    project = _project_with_tasks(2)
    snap = build_prepare_snapshot(project, generation=8, method="IDW", grid_n=12)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        # raise_if_cancelled at start of schedule
        run_factor_prepare_schedule(snap, cancellation_token=token, workers=1)


def test_worker_does_not_mutate_live_project():
    project = _project_with_tasks(2)
    live_ids = [id(t) for t in project.factor_map_tasks]
    snap = build_prepare_snapshot(project, generation=9, method="IDW", grid_n=12)
    result = run_factor_prepare_schedule(snap, workers=1)
    assert [id(t) for t in project.factor_map_tasks] == live_ids
    assert all(t.status == "pending" for t in project.factor_map_tasks)
    assert result.executed_count == 2


def test_constraint_scoped_invalidation_still_works():
    project = _project_with_tasks(2)
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    project.constraint_layers.append(
        ConstraintLayers(
            target_horizon="H1",
            lines=[
                ConstraintLine(
                    role="break",
                    coordinates=[[0.0, 0.0], [5.0, 5.0]],
                    target_horizon="H1",
                )
            ],
        )
    )
    reset_interpolation_execution_counter()
    snap = build_prepare_snapshot(project, generation=12, method="IDW", grid_n=12)
    result = run_factor_prepare_schedule(snap, workers=1)
    assert result.dirty_count == 2
    assert result.clean_count == 0


def test_force_recomputes_all():
    project = _project_with_tasks(3)
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    reset_interpolation_execution_counter()
    snap = build_prepare_snapshot(
        project, generation=13, method="IDW", grid_n=12, force=True
    )
    result = run_factor_prepare_schedule(snap, workers=1)
    assert result.dirty_count == 3
    assert result.clean_count == 0
    assert interpolation_execution_count() >= 1


def test_progress_is_monotonic():
    project = _project_with_tasks(3)
    snap = build_prepare_snapshot(project, generation=14, method="IDW", grid_n=12)
    seen: list[int] = []

    def on_progress(p):
        seen.append(p.completed)

    run_factor_prepare_schedule(snap, workers=1, progress=on_progress)
    assert seen
    assert seen == sorted(seen)


def test_prepare_worker_count_clamped(monkeypatch):
    monkeypatch.setenv("PALEO_PREPARE_WORKERS", "99")
    assert prepare_worker_count() == 4
    monkeypatch.setenv("PALEO_PREPARE_WORKERS", "0")
    assert prepare_worker_count() == 1


def test_plan_cache_rebuilds_when_power_changes():
    """Audit C1: the session plan cache must not serve an old-power plan.

    Power lives in the ALGORITHM fingerprint, not geometry; keying the cache on
    geometry alone silently recomputed with the old power while stamping the
    new one.
    """
    reset_interpolation_execution_counter()
    project = ProjectDocument.new("PowerCache")
    project.stratigraphy.target_horizon = "H1"
    base = _points(12, seed=7)
    for i in range(2):
        pts = [{**p, "value": float(p["value"]) + 0.01 * i} for p in base]
        project.factor_map_tasks.append(
            FactorMapTask(
                name=f"p{i}",
                target_horizon="H1",
                factor_type=f"ptype{i}",
                method="IDW",
                parameters={"sample_points": pts},
                status="pending",
            )
        )

    batch_prepare_factor_maps(project, method="IDW", grid_n=12, power=2.0, force=True)
    means_p2 = [float(t.quality_metrics["mean"]) for t in project.factor_map_tasks]
    assert all(t.parameters["power"] == 2.0 for t in project.factor_map_tasks)

    batch_prepare_factor_maps(project, method="IDW", grid_n=12, power=3.0, force=True)
    assert all(t.parameters["power"] == 3.0 for t in project.factor_map_tasks)
    means_p3 = [float(t.quality_metrics["mean"]) for t in project.factor_map_tasks]
    assert means_p2 != means_p3


def test_degenerate_task_fails_alone_and_batch_commits_survivors():
    """Audit C2: one degenerate task must not abort the whole prepare batch."""
    project = _project_with_tasks(n=2, shared_xy=False)
    project.factor_map_tasks.append(
        FactorMapTask(
            name="degenerate",
            target_horizon="H1",
            factor_type="bad",
            method="IDW",
            # Engine requires >= 2 points; a single point is a ValueError.
            parameters={"sample_points": _points(1, seed=3)},
            status="pending",
        )
    )
    snapshot = build_prepare_snapshot(project, generation=1, method="IDW", grid_n=10, power=2.0)
    id_by_name = {t.name: t.id for t in project.factor_map_tasks}
    degenerate_id = id_by_name["degenerate"]

    result = run_factor_prepare_schedule(snapshot)

    by_id = {item.task_id: item for item in result.task_results}
    assert result.cancelled is False
    assert by_id[degenerate_id].error is not None
    healthy = [item for item in result.task_results if item.task_id != degenerate_id]
    assert healthy and all(item.error is None for item in healthy)
    assert result.failed_count >= 1

    discarded = commit_prepare_batch_result(
        project, result, expected_generation=snapshot.generation
    )
    assert degenerate_id in discarded
    live_by_id = {t.id: t for t in project.factor_map_tasks}
    for item in healthy:
        assert item.task_id not in discarded
        assert live_by_id[item.task_id].status == "complete"


def test_commit_guard_uses_scheduled_grid_n_and_power():
    """Audit C3: commit-time stale-input guard must use the scheduled overrides.

    Re-deriving fingerprints with per-task defaults (grid_n=50/power=2) made
    every non-default prepare discard ALL of its results as stale.
    """
    project = _project_with_tasks(n=2, shared_xy=False)
    snapshot = build_prepare_snapshot(project, generation=1, method="IDW", grid_n=24, power=3.0)

    result = run_factor_prepare_schedule(snapshot)
    assert result.executed_count == 2

    discarded = commit_prepare_batch_result(
        project, result, expected_generation=snapshot.generation
    )
    # With the guard fixed, non-default schedules commit instead of discarding.
    assert discarded == []
    assert all(t.status == "complete" for t in project.factor_map_tasks)
    assert all(t.parameters["power"] == 3.0 for t in project.factor_map_tasks)
    assert all(t.parameters["grid_n"] == 24 for t in project.factor_map_tasks)
