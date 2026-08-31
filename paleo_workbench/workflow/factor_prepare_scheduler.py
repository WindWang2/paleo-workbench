"""Bounded factor-prepare scheduler (Stage-5).

Replaces the worker-side ``project.model_copy(deep=True)`` path with a narrow
scientific execution snapshot:

* only coordinate / stratigraphy / constraints / factor tasks are cloned;
* Stage-4 fingerprints decide CLEAN vs DIRTY (no second dirty system);
* dirty plain-IDW tasks still group for InterpolationPlan multi-factor reuse;
* optional bounded parallelism across *independent* geometry groups only;
* results are staged DTOs committed on the host/GUI thread by task id.

Workers never mutate the live ProjectDocument.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from geoviz import JobCancelled

from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid_if_fingerprint,
    grid_result_fingerprint,
    peek_live_factor_grid,
    store_live_factor_grid,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.project.models import (
    CoordinateReference,
    FactorMapTask,
    ProjectDocument,
    StratigraphicFramework,
)
from paleo_workbench.workflow.factor_interpolation import (
    DEFAULT_GRID_N,
    GENERATOR_VERSION,
    batch_prepare_factor_maps,
)
from paleo_workbench.workflow.interpolation_fingerprint import (
    FactorDirtyState,
    classify_factor_recompute,
    fingerprints_for_task,
)

ProgressCallback = Callable[["FactorPrepareProgress"], None]


def prepare_worker_count() -> int:
    """Bounded concurrency for independent geometry groups.

    Default 1: multi-factor reuse already amortises same-geometry work; NumPy
    kernels often oversubscribe when many groups run in parallel.  Override with
    ``PALEO_PREPARE_WORKERS`` (clamped 1..4).

    P2-A: the env override still wins, but the final value is additionally
    clamped by the ResourceGovernor's BACKGROUND_COMPUTE allowance so
    factor preparation sheds cores under memory pressure.
    """
    raw = os.environ.get("PALEO_PREPARE_WORKERS", "1").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1
    from paleo_workbench.runtime.governance import clamp_workers

    return clamp_workers("background.compute", max(1, min(4, value)))


@dataclass(frozen=True, slots=True)
class FactorPrepareProgress:
    generation: int
    total_tasks: int
    clean: int
    dirty: int
    completed: int
    failed: int
    cancelled: int = 0
    phase: str = ""
    current_task_id: str | None = None
    current_group: str | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class FactorPrepareTaskResult:
    task_id: str
    dirty_state: str
    reused: bool
    task: FactorMapTask | None = None
    scheduled_result_fingerprint: str | None = None
    error: str | None = None
    elapsed_ms: float = 0.0
    # The grid this run computed for the task (#834): carried alongside the
    # staged metadata so the commit can (re)store the EXACT grid the task
    # describes, even if a competing run keyed over it in the process-global
    # live cache between compute and commit.
    grid: FactorGridResult | None = None


@dataclass(frozen=True, slots=True)
class FactorPrepareBatchResult:
    generation: int
    method: str
    task_results: tuple[FactorPrepareTaskResult, ...]
    clean_count: int
    dirty_count: int
    executed_count: int
    failed_count: int
    cancelled: bool = False
    snapshot_ms: float = 0.0
    classify_ms: float = 0.0
    execute_ms: float = 0.0
    workers: int = 1
    created_default_tasks: bool = False
    # Schedule-time overrides actually used for execution. The commit-time
    # stale-input guard must re-derive fingerprints with THESE values; falling
    # back to per-task defaults would discard every non-default prepare.
    grid_n: int | None = None
    power: float = 2.0

    @property
    def count(self) -> int:
        """Tasks considered by this prepare request (clean + dirty)."""
        return len(self.task_results)

    @property
    def factor_map_tasks(self) -> list[FactorMapTask]:
        """Backward-compatible flat list of outcome tasks (dirty patches + clean).

        Prefer :func:`commit_prepare_batch_result` for host commits.
        """
        out: list[FactorMapTask] = []
        for item in self.task_results:
            if item.task is not None:
                out.append(item.task)
        return out


@dataclass(slots=True)
class FactorPrepareSnapshot:
    """Immutable scientific inputs for one prepare request."""

    generation: int
    method: str
    grid_n: int
    power: float
    force: bool
    seed: int
    target_horizon: str
    project_crs: str | None
    coordinate: CoordinateReference
    stratigraphy: StratigraphicFramework
    constraint_layers: list[Any]
    tasks: list[FactorMapTask]
    created_defaults: bool = False
    build_ms: float = 0.0


def build_prepare_snapshot(
    project: ProjectDocument,
    *,
    generation: int,
    method: str = "IDW",
    grid_n: int = DEFAULT_GRID_N,
    power: float = 2.0,
    force: bool = False,
    seed: int = 0,
    target_horizon: str | None = None,
    factor_types: list[str] | tuple[str, ...] | None = None,
) -> FactorPrepareSnapshot:
    """Clone only scientific state needed for Stage-4 prepare (not whole project)."""
    t0 = time.perf_counter()
    horizon = (
        target_horizon
        or project.stratigraphy.target_horizon
        or (project.factor_map_tasks[0].target_horizon if project.factor_map_tasks else "")
        or "未指定层位"
    )
    # Deep-copy *tasks* and *constraints* only — never resources / maps / catalog.
    tasks = [task.model_copy(deep=True) for task in project.factor_map_tasks]
    constraints = [layer.model_copy(deep=True) for layer in project.constraint_layers]
    coordinate = project.coordinate.model_copy(deep=True)
    stratigraphy = project.stratigraphy.model_copy(deep=True)
    created_defaults = False
    if not tasks:
        from paleo_workbench.workflow.factor_interpolation import (
            DEFAULT_FACTOR_TYPES,
            synthetic_sample_points,
        )

        types = list(factor_types or DEFAULT_FACTOR_TYPES)
        for index, factor_type in enumerate(types):
            points = synthetic_sample_points(
                seed=seed + index, factor_type=factor_type
            )
            tasks.append(
                FactorMapTask(
                    name=f"{horizon} {factor_type}",
                    target_horizon=horizon,
                    factor_type=factor_type,
                    method=method,
                    parameters={"sample_points": points},
                    status="pending",
                    source_kind="mixed",
                    seed=seed + index,
                )
            )
        created_defaults = True
        stratigraphy = stratigraphy.model_copy(update={"target_horizon": horizon})

    return FactorPrepareSnapshot(
        generation=int(generation),
        method=method or "IDW",
        grid_n=int(grid_n),
        power=float(power),
        force=bool(force),
        seed=int(seed),
        target_horizon=str(horizon),
        project_crs=getattr(project.coordinate, "project_crs", None),
        coordinate=coordinate,
        stratigraphy=stratigraphy,
        constraint_layers=constraints,
        tasks=tasks,
        created_defaults=created_defaults,
        build_ms=(time.perf_counter() - t0) * 1000.0,
    )


def materialize_execution_project(snapshot: FactorPrepareSnapshot) -> ProjectDocument:
    """Build a throwaway ProjectDocument carrying only prepare-relevant fields."""
    project = ProjectDocument.new(f"_prepare_gen_{snapshot.generation}")
    project.coordinate = snapshot.coordinate
    project.stratigraphy = snapshot.stratigraphy
    project.constraint_layers = list(snapshot.constraint_layers)
    project.factor_map_tasks = list(snapshot.tasks)
    return project


def classify_snapshot_tasks(
    snapshot: FactorPrepareSnapshot,
    project: ProjectDocument,
    fingerprint_memo: dict | None = None,
) -> tuple[list[tuple[FactorMapTask, FactorDirtyState, str]], list[tuple[FactorMapTask, FactorDirtyState, str]]]:
    """Return (clean, dirty) pairs of (task, state, result_fingerprint)."""
    clean: list[tuple[FactorMapTask, FactorDirtyState, str]] = []
    dirty: list[tuple[FactorMapTask, FactorDirtyState, str]] = []
    for task in project.factor_map_tasks:
        fps = fingerprints_for_task(
            task,
            project=project,
            method=snapshot.method,
            grid_n=snapshot.grid_n,
            power=snapshot.power,
            generator_version=GENERATOR_VERSION,
            memo=fingerprint_memo,
        )
        state = classify_factor_recompute(task, fps, force=snapshot.force)
        if state is FactorDirtyState.CLEAN:
            clean.append((task, state, fps.result))
        else:
            dirty.append((task, state, fps.result))
    return clean, dirty


def _task_failure(task: FactorMapTask) -> str | None:
    """Return the recorded per-task failure diagnostic, if any.

    ``_apply_interpolation_isolated`` marks a degenerate task ``failed`` with a
    ``last_error`` parameter instead of raising through the batch.
    """
    if getattr(task, "status", "") == "failed":
        return str((task.parameters or {}).get("last_error") or "interpolation failed")
    return None


def run_factor_prepare_schedule(
    snapshot: FactorPrepareSnapshot,
    *,
    cancellation_token=None,
    progress: ProgressCallback | None = None,
    workers: int | None = None,
) -> FactorPrepareBatchResult:
    """Classify + execute dirty tasks on a slim execution project."""
    worker_n = prepare_worker_count() if workers is None else max(1, min(4, int(workers)))
    t_class0 = time.perf_counter()

    def _emit(
        *,
        total: int,
        clean_n: int,
        dirty_n: int,
        completed: int,
        failed: int,
        cancelled: int = 0,
        phase: str = "",
        task_id: str | None = None,
        group: str | None = None,
        message: str = "",
    ) -> None:
        if progress is None:
            return
        progress(
            FactorPrepareProgress(
                generation=snapshot.generation,
                total_tasks=total,
                clean=clean_n,
                dirty=dirty_n,
                completed=completed,
                failed=failed,
                cancelled=cancelled,
                phase=phase,
                current_task_id=task_id,
                current_group=group,
                message=message,
            )
        )

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    exec_project = materialize_execution_project(snapshot)
    # One fingerprint derivation per task for this whole request: the classify
    # phase and the execute phase (batch_prepare_factor_maps) share the memo.
    fp_memo: dict = {}
    # Ensure sample points exist on pending tasks (same as batch_prepare).
    for task in exec_project.factor_map_tasks:
        params = task.parameters or {}
        points = params.get("sample_points") or []
        if not points:
            from geoviz import synthetic_sample_points

            points = synthetic_sample_points(
                seed=(task.seed if task.seed is not None else snapshot.seed),
                factor_type=task.factor_type or task.name,
            )
            task.parameters = {**params, "sample_points": points}

    clean_pairs, dirty_pairs = classify_snapshot_tasks(
        snapshot, exec_project, fingerprint_memo=fp_memo
    )
    classify_ms = (time.perf_counter() - t_class0) * 1000.0
    total = len(exec_project.factor_map_tasks)
    clean_n = len(clean_pairs)
    dirty_n = len(dirty_pairs)

    results_by_id: dict[str, FactorPrepareTaskResult] = {}
    for task, state, result_fp in clean_pairs:
        results_by_id[task.id] = FactorPrepareTaskResult(
            task_id=task.id,
            dirty_state=state.value,
            reused=True,
            task=task.model_copy(deep=True),
            scheduled_result_fingerprint=result_fp,
        )

    _emit(
        total=total,
        clean_n=clean_n,
        dirty_n=dirty_n,
        completed=clean_n,
        failed=0,
        phase="classified",
        message=f"复用 {clean_n} · 需计算 {dirty_n}",
    )

    if not dirty_pairs:
        ordered = tuple(
            results_by_id[t.id]
            for t in exec_project.factor_map_tasks
            if t.id in results_by_id
        )
        return FactorPrepareBatchResult(
            generation=snapshot.generation,
            method=snapshot.method,
            task_results=ordered,
            clean_count=clean_n,
            dirty_count=0,
            executed_count=0,
            failed_count=0,
            snapshot_ms=snapshot.build_ms,
            classify_ms=classify_ms,
            execute_ms=0.0,
            workers=worker_n,
            created_default_tasks=snapshot.created_defaults,
        )

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    # Execute dirty tasks via Stage-4 batch path on a project that only contains
    # dirty tasks for classification bookkeeping, but we pass the full exec
    # project so CLEAN tasks are skipped again (force=False) and grouping works.
    t_exec0 = time.perf_counter()
    failed_n = 0
    cancelled = False
    executed = 0
    try:
        # When workers==1, one call preserves multi-factor grouping across all
        # dirty plain-IDW tasks.  Parallel mode splits by geometry group key.
        if worker_n == 1 or dirty_n == 1:
            _emit(
                total=total,
                clean_n=clean_n,
                dirty_n=dirty_n,
                completed=clean_n,
                failed=0,
                phase="executing",
                message=f"计算 0/{dirty_n}",
            )
            batch_prepare_factor_maps(
                exec_project,
                method=snapshot.method,
                target_horizon=snapshot.target_horizon,
                grid_n=snapshot.grid_n,
                power=snapshot.power,
                force=snapshot.force,
                seed=snapshot.seed,
                cancellation_token=cancellation_token,
                fingerprint_memo=fp_memo,
            )
            for task, state, result_fp in dirty_pairs:
                executed += 1
                error = _task_failure(task)
                if error is not None:
                    failed_n += 1
                results_by_id[task.id] = FactorPrepareTaskResult(
                    task_id=task.id,
                    dirty_state=state.value,
                    reused=False,
                    task=task.model_copy(deep=True),
                    scheduled_result_fingerprint=result_fp,
                    error=error,
                    # A failed run computed nothing this round; carrying the
                    # PEEKED (previous run's) grid would let the commit's
                    # fingerprint-conditional invalidation evict that still
                    # valid payload (#918). Only successful runs own a grid.
                    grid=peek_live_factor_grid(task.id) if error is None else None,
                )
            _emit(
                total=total,
                clean_n=clean_n,
                dirty_n=dirty_n,
                completed=clean_n + executed,
                failed=failed_n,
                phase="executed",
                message=f"计算 {executed}/{dirty_n}",
            )
        else:
            # Independent groups: rebuild sub-projects that share only one group.
            from paleo_workbench.workflow.factor_interpolation import (
                _task_plan_group_key,
            )

            groups: dict[str | None, list[tuple[FactorMapTask, FactorDirtyState, str]]] = {}
            for task, state, result_fp in dirty_pairs:
                gkey = _task_plan_group_key(
                    task,
                    method=snapshot.method,
                    grid_n=snapshot.grid_n,
                    power=snapshot.power,
                    project=exec_project,
                )
                groups.setdefault(gkey, []).append((task, state, result_fp))

            def _run_group(
                items: list[tuple[FactorMapTask, FactorDirtyState, str]],
            ) -> list[FactorPrepareTaskResult]:
                sub = ProjectDocument.new("_prepare_group")
                sub.coordinate = snapshot.coordinate.model_copy(deep=True)
                sub.stratigraphy = snapshot.stratigraphy.model_copy(deep=True)
                sub.constraint_layers = [
                    layer.model_copy(deep=True) for layer in snapshot.constraint_layers
                ]
                # Use the *same* task objects from exec_project so live cache
                # ids match; clone for isolation across threads.
                clones = [t.model_copy(deep=True) for t, _, _ in items]
                id_map = {c.id: c for c in clones}
                sub.factor_map_tasks = clones
                batch_prepare_factor_maps(
                    sub,
                    method=snapshot.method,
                    target_horizon=snapshot.target_horizon,
                    grid_n=snapshot.grid_n,
                    power=snapshot.power,
                    force=True,  # already known dirty; avoid re-classify miss
                    seed=snapshot.seed,
                    cancellation_token=cancellation_token,
                    fingerprint_memo=fp_memo,
                )
                out: list[FactorPrepareTaskResult] = []
                for task, state, result_fp in items:
                    updated = id_map[task.id]
                    error = _task_failure(updated)
                    out.append(
                        FactorPrepareTaskResult(
                            task_id=task.id,
                            dirty_state=state.value,
                            reused=False,
                            task=updated.model_copy(deep=True),
                            scheduled_result_fingerprint=result_fp,
                            error=error,
                            # Same contract as the serial path (#918): a failed
                            # run owns no grid and must not carry the peeked
                            # previous-run payload into commit invalidation.
                            grid=(
                                peek_live_factor_grid(task.id)
                                if error is None
                                else None
                            ),
                        )
                    )
                return out

            with ThreadPoolExecutor(max_workers=worker_n) as pool:
                futures = {
                    pool.submit(_run_group, items): key
                    for key, items in groups.items()
                }
                group_items_by_key = {key: items for key, items in groups.items()}
                for fut in as_completed(futures):
                    if cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
                    group_key = futures[fut]
                    try:
                        group_results = fut.result()
                    except (JobCancelled, Exception) as exc:  # noqa: BLE001
                        # One failing group must not discard the OTHER groups'
                        # completed results (audit #848): record the group's
                        # tasks as failed and keep collecting. (The serial
                        # path already had per-task isolation.) #939-7 parallel
                        # count must be per-task, not per-group.
                        group_size = len(group_items_by_key.get(group_key, ()))
                        failed_n += max(1, group_size)
                        logging.getLogger(__name__).warning(
                            "factor prepare group %r failed: %s",
                            str(group_key),
                            exc,
                        )
                        for task, _state, _fp in group_items_by_key.get(
                            group_key, ()
                        ):
                            results_by_id[task.id] = FactorPrepareTaskResult(
                                task_id=task.id,
                                dirty_state="dirty",
                                reused=False,
                                task=None,
                                scheduled_result_fingerprint="",
                                error=f"group failed: {exc}",
                            )
                            executed += 1
                        continue
                    for item in group_results:
                        results_by_id[item.task_id] = item
                        executed += 1
                        if item.error:
                            failed_n += 1
                    _emit(
                        total=total,
                        clean_n=clean_n,
                        dirty_n=dirty_n,
                        completed=clean_n + executed,
                        failed=failed_n,
                        phase="executing",
                        group=str(group_key),
                        message=f"计算 {executed}/{dirty_n}",
                    )
    except JobCancelled:
        cancelled = True
        for task, state, result_fp in dirty_pairs:
            if task.id not in results_by_id:
                results_by_id[task.id] = FactorPrepareTaskResult(
                    task_id=task.id,
                    dirty_state=state.value,
                    reused=False,
                    task=None,
                    scheduled_result_fingerprint=result_fp,
                    error="cancelled",
                )

    execute_ms = (time.perf_counter() - t_exec0) * 1000.0
    ordered = tuple(
        results_by_id[t.id]
        for t in exec_project.factor_map_tasks
        if t.id in results_by_id
    )
    return FactorPrepareBatchResult(
        generation=snapshot.generation,
        method=snapshot.method,
        task_results=ordered,
        clean_count=clean_n,
        dirty_count=dirty_n,
        executed_count=executed,
        failed_count=failed_n,
        cancelled=cancelled,
        snapshot_ms=snapshot.build_ms,
        classify_ms=classify_ms,
        execute_ms=execute_ms,
        workers=worker_n,
        created_default_tasks=snapshot.created_defaults,
        grid_n=snapshot.grid_n,
        power=snapshot.power,
    )


def commit_prepare_batch_result(
    live_project: ProjectDocument,
    result: FactorPrepareBatchResult,
    *,
    expected_generation: int,
    scheduled_task_fingerprints: dict[str, str] | None = None,
) -> list[str]:
    """Apply staged task patches onto *live_project* (host thread only).

    Returns list of discarded task ids (stale generation / fingerprint mismatch).
    """
    discarded: list[str] = []

    items_by_id = {item.task_id: item for item in result.task_results}

    def _invalidate_live_grids(ids: list[str]) -> list[str]:
        # A discarded commit must not leave its grid in the process-global
        # live cache: the renderer/saver would otherwise serve (or persist)
        # the rejected grid for the task (H11 torn-cache finding). Clearing
        # is FINGERPRINT-CONDITIONAL (#834): a superseded run must not evict
        # a newer run's grid that keyed over the same task id.
        #
        # When this run produced NO grid for the task (failed, cancelled, or
        # never executed) it stored nothing, so it owns nothing to evict and
        # must clear nothing. Falling back to an unconditional clear here
        # deleted the *winning* run's freshly committed grid, leaving a task
        # marked `complete` whose payload then went missing on save (#881).
        for tid in ids:
            try:
                item = items_by_id.get(tid)
                fp = grid_result_fingerprint(item.grid) if item is not None else None
                if fp is not None:
                    clear_live_factor_grid_if_fingerprint(tid, fp)
            except Exception:
                pass
        return ids

    if int(result.generation) != int(expected_generation):
        return _invalidate_live_grids([item.task_id for item in result.task_results])

    if result.cancelled:
        # Default: no partial commit on cancel.
        return _invalidate_live_grids(
            [item.task_id for item in result.task_results if not item.reused]
        )

    live_by_id = {t.id: t for t in live_project.factor_map_tasks}
    new_tasks: list[FactorMapTask] = []

    if result.created_default_tasks and not live_project.factor_map_tasks:
        # First prepare created defaults — accept all non-failed patches.
        for item in result.task_results:
            if item.task is None or item.error:
                discarded.append(item.task_id)
                continue
            new_tasks.append(item.task)
        live_project.factor_map_tasks = new_tasks
        return _invalidate_live_grids(discarded)

    for item in result.task_results:
        if item.reused:
            continue
        if item.task is None or item.error:
            discarded.append(item.task_id)
            continue
        live = live_by_id.get(item.task_id)
        if live is None:
            # New task id not on live project — append only if defaults path.
            if result.created_default_tasks:
                live_project.factor_map_tasks.append(item.task)
            else:
                discarded.append(item.task_id)
            continue
        # Stale-input guard: live scientific inputs must still match schedule.
        if item.scheduled_result_fingerprint:
            try:
                current = fingerprints_for_task(
                    live,
                    project=live_project,
                    method=result.method,
                    # Re-derive with the SCHEDULED overrides (not per-task
                    # defaults) or every non-default prepare looks stale.
                    grid_n=result.grid_n,
                    power=result.power,
                    generator_version=GENERATOR_VERSION,
                )
                if current.result != item.scheduled_result_fingerprint:
                    discarded.append(item.task_id)
                    continue
            except Exception:
                discarded.append(item.task_id)
                continue
        # Targeted field replacement by index.
        idx = live_project.factor_map_tasks.index(live)
        live_project.factor_map_tasks[idx] = item.task
        # Pair the accepted metadata with EXACTLY the grid this run computed
        # (#834): a competing entry may have keyed over the live cache since
        # the worker stored it; re-storing the carried (immutable) grid
        # repairs the pairing, and is a no-op when nothing intervened.
        if item.grid is not None:
            try:
                store_live_factor_grid(item.task_id, item.grid)
            except Exception:
                pass

    return _invalidate_live_grids(discarded)
