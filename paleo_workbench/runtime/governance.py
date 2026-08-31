"""Single installation point for global resource governance (P2-A).

``ensure_global_governance()`` is the one call the app bootstrap (and any
benchmark) makes: it pushes the active budget into the engine caches, binds
the pressure monitor, and installs the governor's admission hook on the
global TaskScheduler. It is idempotent and safe to call repeatedly.

Nothing else in the workbench may build a second scheduler, budget, monitor
or governor — this module wires the existing singletons together.
"""
from __future__ import annotations

import logging

from paleo_workbench.runtime.resource_budget import ResourceBudget, active_budget
from paleo_workbench.runtime.resource_governor import (
    ResourceGovernor,
    TaskRequest,
    get_governor,
)
from paleo_workbench.runtime.task_categories import category_for_kind, policy_for
from paleo_workbench.runtime.task_scheduler import TaskScheduler, get_scheduler

logger = logging.getLogger(__name__)


def _request_for_spec(spec, task_id: str) -> TaskRequest:
    """Build the governor's claim from a TaskSpec.

    Estimates ride in ``spec.payload["resources"]`` (dict with
    ``estimated_cpu_cores`` / ``estimated_ram_bytes`` / ``estimated_vram_bytes``
    / ``io_weight``); categories derive from the kind; missing estimates fall
    back to the category policy defaults.
    """
    estimates = spec.payload.get("resources") if isinstance(spec.payload, dict) else None
    estimates = estimates or {}
    category = category_for_kind(spec.kind)
    policy = policy_for(category)
    return TaskRequest(
        category=category,
        priority=spec.priority if spec.priority else None,
        title=spec.title or spec.kind,
        estimated_cpu_cores=float(estimates.get("estimated_cpu_cores", policy.default_cpu_cores)),
        estimated_ram_bytes=int(estimates.get("estimated_ram_bytes", 0)),
        estimated_vram_bytes=int(estimates.get("estimated_vram_bytes", 0)),
        io_weight=estimates.get("io_weight"),
        task_id=task_id,
    )


def scheduler_admission_hook(governor: ResourceGovernor):
    """Admission hook adapting the governor to the TaskScheduler lease protocol."""

    def hook(spec, task_id: str):
        return governor.try_admit(_request_for_spec(spec, task_id))

    return hook


def ensure_global_governance(
    *, budget: ResourceBudget | None = None, scheduler: TaskScheduler | None = None
) -> ResourceGovernor:
    """Idempotent: apply budgets, bind monitor, install scheduler admission."""
    governor = get_governor()
    if budget is not None:
        from paleo_workbench.runtime.resource_governor import configure_runtime_budget

        configure_runtime_budget(budget)
    sched = scheduler if scheduler is not None else get_scheduler()
    sched.set_background_nice(governor.budget.background_nice)
    sched.set_admission(scheduler_admission_hook(governor))
    _apply_gil_latency_policy()
    logger.debug(
        "global resource governance active (background_cores=%d, io_slots=%.1f)",
        governor.budget.background_cores,
        governor.budget.io_slots,
    )
    return governor


def _apply_gil_latency_policy() -> None:
    """Bound how long a CPU-saturated background thread can hold the GIL.

    CPython's default switch interval (5 ms) lets one pure-Python burn loop
    delay interactive threads by multiples of 5 ms under contention; 2 ms
    keeps dispatch tail latencies low at negligible throughput cost. Only
    ever lowers the interval, never raises a user-chosen tighter value.
    """
    import sys

    try:
        if sys.getswitchinterval() > 0.002:
            sys.setswitchinterval(0.002)
    except Exception:  # pragma: no cover - exotic interpreters
        pass
