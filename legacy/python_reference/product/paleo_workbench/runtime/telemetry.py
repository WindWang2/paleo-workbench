"""Lightweight runtime telemetry aggregation (P2-A).

One read-only snapshot function that pulls together what the single
authorities already count — scheduler handles, governor admission metrics,
memory pressure, and the engine caches' own stats. It is deliberately NOT an
observability platform: no background threads, no writes, no log spam in
production; consumers are the diagnostics/developer surfaces and benchmarks.

``snapshot()`` is cheap enough to call per-refresh of a diagnostics panel
and strict about never raising when an engine is absent (optional native /
GPU stacks may be missing).
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def _safe(fn):
    try:
        value = fn()
        return value if isinstance(value, dict) else {"value": value}
    except Exception as exc:  # a missing engine must never kill diagnostics
        return {"error": f"{type(exc).__name__}: {exc}"}


def _scheduler_stats() -> dict:
    from paleo_workbench.runtime.task_scheduler import get_scheduler

    sched = get_scheduler()
    handles = sched.statuses()
    by_state: dict[str, int] = {}
    wait_times: list[float] = []
    run_times: list[float] = []
    for h in handles:
        by_state[h.state.value] = by_state.get(h.state.value, 0) + 1
        if h.started_at is not None:
            wait_times.append(h.started_at - h.submitted_at)
            if h.finished_at is not None:
                run_times.append(h.finished_at - h.started_at)
    return {
        "max_workers": sched.max_workers,
        "tasks_by_state": by_state,
        "queued_tasks": by_state.get("queued", 0),
        "active_tasks": by_state.get("running", 0),
        "history_size": len(handles),
        "task_wait_time_avg_ms": round(1000 * (sum(wait_times) / len(wait_times)), 2) if wait_times else 0.0,
        "task_run_time_avg_ms": round(1000 * (sum(run_times) / len(run_times)), 2) if run_times else 0.0,
        "cancel_count": by_state.get("cancelled", 0),
        "failure_count": by_state.get("failed", 0),
    }


def _cache_stats() -> dict:
    stats: dict = {}
    try:
        from geoviz_seismic.vram_cache import VRAM

        stats["vram_l2"] = VRAM.stats()
    except Exception as exc:
        stats["vram_l2"] = {"error": str(exc)}
    try:
        from geoviz_seismic.cache import global_stats

        stats["ram_l1"] = global_stats()
    except Exception as exc:
        stats["ram_l1"] = {"error": str(exc)}
    try:
        from paleo_workbench.viz.seismic_volume_cache import get_global_seismic_cache

        stats["seismic_volume"] = get_global_seismic_cache().stats()
    except Exception as exc:
        stats["seismic_volume"] = {"error": str(exc)}
    return stats


def snapshot() -> dict:
    """One process-wide runtime status dict (scheduler+governor+pressure+caches)."""
    from paleo_workbench.runtime.resource_governor import get_governor

    governor = get_governor()
    return {
        "timestamp": time.time(),
        "cpu_budget": {
            "logical_cores": governor.budget.detected_logical_cores,
            "background_cores": governor.budget.background_cores,
            "interactive_reserve_cores": governor.budget.interactive_reserve_cores,
        },
        "ram_budget": {
            "total_gb": round(governor.budget.total_ram_gb, 2),
            "streaming_buffer_bytes": governor.budget.streaming_buffer_bytes,
        },
        "vram_budget": {"budget_mb": governor.budget.vram_budget_mb},
        "io_slots": governor.io_slots(),
        "scheduler": _safe(_scheduler_stats),
        "governor": governor.runtime_status(),
        "caches": _safe(_cache_stats),
    }
