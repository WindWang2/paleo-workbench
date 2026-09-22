"""Regression tests for #834 — cross-entry factor-compute generation races.

Factor computation has three GUI entries (prepare page, well-log send-to-
prepare, home recompute) that each used to guard a PRIVATE generation
counter while ``store_live_factor_grid`` keyed a process-global cache by
task id. Two concurrent runs could both pass their own guards, pairing one
run's task metadata with the other run's grid — silent scientific data
corruption on the next save.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid,
    current_factor_prepare_generation,
    next_factor_prepare_generation,
    peek_live_factor_grid,
    store_live_factor_grid,
)
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.factor_prepare_scheduler import (
    FactorPrepareBatchResult,
    FactorPrepareTaskResult,
    commit_prepare_batch_result,
)


def _grid(value: float, fingerprint: str, algorithm_id: str = "kriging") -> FactorGridResult:
    gx = np.linspace(0.0, 10.0, 8)
    gy = np.linspace(0.0, 10.0, 6)
    gz = np.full((6, 8), value, dtype=np.float32)
    return FactorGridResult(
        grid_z=gz,
        grid_x=gx,
        grid_y=gy,
        factor_name="f0",
        algorithm_id=algorithm_id,
        algorithm_parameters={"result_fingerprint": fingerprint},
    )


def _project_with_task() -> tuple[ProjectDocument, FactorMapTask]:
    project = ProjectDocument.new("Race")
    task = FactorMapTask(
        name="f0",
        target_horizon="H1",
        factor_type="sand",
        parameters={"sample_points": [{"x": 1.0, "y": 1.0, "value": 0.5}]},
        method="克里金",
        status="pending",
    )
    project.factor_map_tasks.append(task)
    return project, task


@pytest.fixture(autouse=True)
def _clean_cache():
    yield
    # Task ids are uuids unique per test; entries created here do not
    # collide with other tests' ids.


def _batch(generation: int, task: FactorMapTask, grid: FactorGridResult) -> FactorPrepareBatchResult:
    return FactorPrepareBatchResult(
        generation=generation,
        method=task.method,
        task_results=(
            FactorPrepareTaskResult(
                task_id=task.id,
                dirty_state="dirty",
                reused=False,
                task=task,
                scheduled_result_fingerprint=None,
                error=None,
                grid=grid,
            ),
        ),
        clean_count=0,
        dirty_count=1,
        executed_count=1,
        failed_count=0,
    )


def test_next_generation_is_global_and_monotonic() -> None:
    a = next_factor_prepare_generation()
    b = next_factor_prepare_generation()
    assert b == a + 1
    assert current_factor_prepare_generation() == b


def test_superseded_generation_commit_discards_metadata() -> None:
    project, task = _project_with_task()
    gen = next_factor_prepare_generation()
    newer = next_factor_prepare_generation()  # a competing entry superseded us
    staged = task.model_copy(deep=True)
    staged.status = "complete"
    store_live_factor_grid(task.id, _grid(1.0, "fp-ours"))

    discarded = commit_prepare_batch_result(
        project, _batch(gen, staged, _grid(1.0, "fp-ours")),
        expected_generation=current_factor_prepare_generation(),
    )
    assert task.id in discarded
    assert project.factor_map_tasks[0].status == "pending"
    assert newer > gen


def test_commit_restores_carried_grid_over_competing_store() -> None:
    """The winning metadata must be paired with ITS OWN grid even when a
    competing run keyed over the live cache between compute and commit."""
    project, task = _project_with_task()
    gen = next_factor_prepare_generation()
    staged = task.model_copy(deep=True)
    staged.status = "complete"
    ours = _grid(7.0, "fp-ours", algorithm_id="kriging")
    # A competing send-to-prep run (fixed IDW) keyed over our task id.
    store_live_factor_grid(task.id, _grid(9.0, "fp-theirs", algorithm_id="idw"))

    discarded = commit_prepare_batch_result(
        project, _batch(gen, staged, ours),
        expected_generation=current_factor_prepare_generation(),
    )
    assert discarded == []
    assert project.factor_map_tasks[0].status == "complete"
    cached = peek_live_factor_grid(task.id)
    assert cached is not None
    assert float(cached.grid_z.flat[0]) == pytest.approx(7.0)  # OUR grid
    assert cached.algorithm_parameters.get("result_fingerprint") == "fp-ours"
    clear_live_factor_grid(task.id)


def test_superseded_discard_does_not_evict_newer_grid() -> None:
    """A losing run's cleanup must not drop the WINNING run's cache entry."""
    project, task = _project_with_task()
    gen = next_factor_prepare_generation()
    next_factor_prepare_generation()  # supersede
    staged = task.model_copy(deep=True)
    # The winning run's grid is what's cached now, under the same task id.
    store_live_factor_grid(task.id, _grid(9.0, "fp-theirs"))

    discarded = commit_prepare_batch_result(
        project, _batch(gen, staged, _grid(7.0, "fp-ours")),
        expected_generation=current_factor_prepare_generation(),
    )
    assert task.id in discarded
    cached = peek_live_factor_grid(task.id)
    assert cached is not None  # the newer run's grid survives our discard
    assert float(cached.grid_z.flat[0]) == pytest.approx(9.0)
    clear_live_factor_grid(task.id)


def test_entry_points_share_the_global_generation() -> None:
    """All three UI entries bump ONE counter (#834): the page's private
    counter no longer decides readiness alone."""
    from paleo_workbench.ui.pages import preparation_page as prep_mod

    assert hasattr(prep_mod, "next_factor_prepare_generation")
    from paleo_workbench.ui import workflow_controller as ctrl_mod

    assert hasattr(ctrl_mod, "next_factor_prepare_generation")
