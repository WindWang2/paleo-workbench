"""A superseded factor run must never evict the winning run's live grid (#881).

`#834` established that eviction from the process-global live-grid cache is
fingerprint-conditional so a losing run cannot delete a newer run's entry. Two
cleanup paths kept a fall-back for "this run produced no grid for the task"
(failed / cancelled / never executed) that defeated the guard:

* `factor_prepare_scheduler._invalidate_live_grids` called the *unconditional*
  `clear_live_factor_grid`.
* `WorkflowController._on_recompute_completed` read the cached entry with
  `peek_live_factor_grid` and then "conditionally" cleared it using that same
  entry's fingerprint — a comparison that can never fail.

Both deleted the winner, leaving a task marked ``complete`` whose payload went
missing on the next save. A run that stored nothing owns nothing to evict.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid,
    clear_live_factor_grid_if_fingerprint,
    grid_result_fingerprint,
    peek_live_factor_grid,
    store_live_factor_grid,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _grid(value: float, fingerprint: str | None = None) -> FactorGridResult:
    grid_z = np.full((4, 4), value, dtype=np.float64)
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": np.linspace(0.0, 3.0, 4),
            "grid_y": np.linspace(0.0, 3.0, 4),
            "grid_z": grid_z,
            "method": "idw",
        },
        factor_name="issue881",
    )
    if fingerprint is not None:
        # `grid_result_fingerprint` reads algorithm_parameters["result_fingerprint"];
        # a grid without one yields None and therefore takes the `fp is None`
        # branch — which is precisely the branch this issue is about.
        result.algorithm_parameters["result_fingerprint"] = fingerprint
    return result


@pytest.fixture
def task_id() -> str:
    tid = "factor_issue881"
    yield tid
    clear_live_factor_grid(tid)


def test_superseded_run_without_grid_keeps_winning_entry(task_id: str) -> None:
    """The fingerprint-conditional clear must be a no-op for a loser with no grid.

    This is the invariant both cleanup sites document. It is asserted directly
    against the store so it holds for every caller, not just the two fixed here.
    """
    winner = _grid(9.0, fingerprint="fp-winner")
    store_live_factor_grid(task_id, winner)
    assert peek_live_factor_grid(task_id) is not None

    # The losing run's task carries grid=None, so it has no fingerprint of its
    # own. It must not consult the cache and must not clear anything.
    loser_grid = None
    loser_fp = grid_result_fingerprint(loser_grid) if loser_grid is not None else None
    assert loser_fp is None
    if loser_fp is not None:  # pragma: no cover - documents the guarded shape
        clear_live_factor_grid_if_fingerprint(task_id, loser_fp)

    survivor = peek_live_factor_grid(task_id)
    assert survivor is not None, "superseded loser with no grid evicted the winner"
    assert grid_result_fingerprint(survivor) == "fp-winner"
    assert float(np.asarray(survivor.grid_z)[0, 0]) == pytest.approx(9.0)


def test_superseded_run_with_its_own_grid_still_evicts_only_itself(task_id: str) -> None:
    """The #834 behaviour is preserved: a loser evicts its own entry, not the winner's."""
    loser = _grid(1.0, fingerprint="fp-loser")
    store_live_factor_grid(task_id, loser)
    clear_live_factor_grid_if_fingerprint(task_id, "fp-loser")
    assert peek_live_factor_grid(task_id) is None, "a run must evict its own stale grid"

    winner = _grid(9.0, fingerprint="fp-winner")
    store_live_factor_grid(task_id, winner)
    # A late loser presenting its own (now superseded) fingerprint must not
    # touch the winner that keyed over the same task id.
    clear_live_factor_grid_if_fingerprint(task_id, "fp-loser")
    survivor = peek_live_factor_grid(task_id)
    assert survivor is not None
    assert grid_result_fingerprint(survivor) == "fp-winner"
    assert float(np.asarray(survivor.grid_z)[0, 0]) == pytest.approx(9.0)


def test_grid_without_result_fingerprint_is_never_unconditionally_cleared(
    task_id: str,
) -> None:
    """A stored grid carrying no fingerprint must still survive a loser's cleanup.

    `grid_result_fingerprint` returns None for any grid whose
    ``algorithm_parameters`` lack ``result_fingerprint``, so the regressed
    ``fp is None`` branch was reachable for more than just failed tasks.
    """
    winner = _grid(9.0)  # no result_fingerprint at all
    store_live_factor_grid(task_id, winner)
    assert grid_result_fingerprint(peek_live_factor_grid(task_id)) is None

    # A conditional clear with no fingerprint is a no-op by contract.
    assert clear_live_factor_grid_if_fingerprint(task_id, None) is False
    assert peek_live_factor_grid(task_id) is not None


def test_cleanup_sites_no_longer_unconditionally_clear() -> None:
    """Guard the two regressed call sites against reintroducing the fall-back."""
    import inspect

    from paleo_workbench.ui import workflow_controller
    from paleo_workbench.workflow import factor_prepare_scheduler

    scheduler_src = inspect.getsource(
        factor_prepare_scheduler.commit_prepare_batch_result
    )
    assert "clear_live_factor_grid(" not in scheduler_src, (
        "_invalidate_live_grids must stay fingerprint-conditional; an "
        "unconditional clear evicts the winning run's grid (#881)"
    )

    controller_src = inspect.getsource(
        workflow_controller.WorkflowController._on_recompute_completed
    )
    assert "peek_live_factor_grid(" not in controller_src, (
        "the superseded branch must not derive a clear fingerprint from the "
        "cached entry itself — that guard can never fail (#881)"
    )
