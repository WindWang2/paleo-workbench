"""RAM pressure monitoring for global resource governance (P2-A).

The budget module decides *what the process may use*; this module observes
*what the machine actually has left* and classifies it into three states:

- ``NORMAL``   — business as usual, full budgets apply;
- ``PRESSURE`` — caches are evicted, background CPU/IO allowances shrink,
                 new low-priority prefetch is discouraged;
- ``CRITICAL`` — non-essential large tasks are rejected with an explainable
                 error instead of waiting for the OS OOM-killer.

Sampling is lazy and rate-limited (no background thread in production):
the governor samples on admission and anyone may call :meth:`refresh`.
System-wide memory is the primary signal (the workbench shares the machine
with the OS and other processes); process RSS is reported alongside for
diagnostics. On machines without psutil we fall back to ``/proc`` and
finally to a permanent NORMAL so the app never bricks on exotic platforms.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum

from paleo_workbench.runtime.resource_budget import ResourceBudget

logger = logging.getLogger(__name__)


class PressureState(str, Enum):
    NORMAL = "normal"
    PRESSURE = "pressure"
    CRITICAL = "critical"


# Eviction callbacks registered by cache owners: name -> callable returning
# the number of bytes actually freed (best effort, must never raise).
Evictable = Callable[[], int]


class MemoryPressureMonitor:
    """Rate-limited sampler + eviction dispatcher for one budget."""

    def __init__(
        self,
        budget: ResourceBudget,
        *,
        sample_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sampler: Callable[[ResourceBudget], tuple[float, int, int]] | None = None,
    ) -> None:
        self._budget = budget
        self._interval = max(0.0, sample_interval_s)
        self._clock = clock
        self._sampler = sampler or _read_memory
        self._lock = threading.Lock()
        self._evictables: dict[str, Evictable] = {}
        self._state = PressureState.NORMAL
        self._sampled_at: float = float("-inf")
        self._system_used_frac = 0.0
        self._rss_bytes = 0
        self._total_bytes = int(budget.total_ram_gb * 1024**3)
        self._relief_bytes_total = 0
        self._relief_runs = 0

    # ------------------------------------------------------------ setup --
    def register_evictable(self, name: str, evict: Evictable) -> None:
        """Register a best-effort cache-eviction callback (idempotent)."""
        with self._lock:
            self._evictables[name] = evict

    def unregister_evictable(self, name: str) -> None:
        with self._lock:
            self._evictables.pop(name, None)

    # ----------------------------------------------------------- sample --
    def state(self, *, refresh: bool = False) -> PressureState:
        """Current state; re-samples if the cached sample is stale."""
        with self._lock:
            if refresh or (self._clock() - self._sampled_at) >= self._interval:
                self._sample()
            return self._state

    def refresh(self) -> PressureState:
        return self.state(refresh=True)

    def _sample(self) -> None:
        """Must be called under ``self._lock``."""
        self._sampled_at = self._clock()
        system_used, rss, total = self._sampler(self._budget)
        self._system_used_frac = system_used
        self._rss_bytes = rss
        self._total_bytes = total
        previous, self._state = self._state, _classify(
            system_used, self._budget.ram_pressure_frac, self._budget.ram_critical_frac
        )
        if self._state != previous:
            logger.warning(
                "memory pressure %s -> %s (system used %.1f%%)",
                previous.value,
                self._state.value,
                system_used * 100.0,
            )
        # State *transitions* and re-entries into PRESSURE both trigger
        # relief; NORMAL is the only state where relief is a no-op.
        if self._state is not PressureState.NORMAL:
            self._run_relief_locked()

    def _run_relief_locked(self) -> None:
        freed_total = 0
        for name, evict in list(self._evictables.items()):
            try:
                freed_total += int(evict() or 0)
            except Exception:  # relief must never take the app down
                logger.exception("pressure relief evictable %r failed", name)
        self._relief_bytes_total += freed_total
        self._relief_runs += 1

    # ------------------------------------------------------------ facts --
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "system_used_frac": round(self._system_used_frac, 4),
                "rss_bytes": self._rss_bytes,
                "total_bytes": self._total_bytes,
                "pressure_frac": self._budget.ram_pressure_frac,
                "critical_frac": self._budget.ram_critical_frac,
                "relief_runs": self._relief_runs,
                "relief_freed_bytes": self._relief_bytes_total,
                "evictables": sorted(self._evictables),
            }


def _classify(used_frac: float, pressure: float, critical: float) -> PressureState:
    if used_frac >= critical:
        return PressureState.CRITICAL
    if used_frac >= pressure:
        return PressureState.PRESSURE
    return PressureState.NORMAL


def _read_memory(budget: ResourceBudget) -> tuple[float, int, int]:
    """(system_used_fraction, process_rss_bytes, system_total_bytes).

    psutil first; ``/proc`` fallback; final fallback trusts the budget so the
    governor still functions (NORMAL) on platforms without either.
    """
    try:
        import psutil

        vm = psutil.virtual_memory()
        rss = psutil.Process().memory_info().rss
        return vm.used / vm.total if vm.total else 0.0, rss, vm.total
    except Exception:
        pass
    total, avail, rss = _read_proc_meminfo()
    if total <= 0:
        total = int(budget.total_ram_gb * 1024**3)
        avail = total
    used = max(0, total - avail)
    return (used / total if total else 0.0), rss, total


def _read_proc_meminfo() -> tuple[int, int, int]:
    """(MemTotal, MemAvailable, VmRSS) bytes from /proc; zeros if unavailable."""
    total = avail = rss = 0
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
                    break
    except (OSError, ValueError, IndexError):
        pass
    return total, avail, rss


# ------------------------------------------------------------- singleton

_GLOBAL_MONITOR: MemoryPressureMonitor | None = None
_MONITOR_LOCK = threading.Lock()


def get_pressure_monitor() -> MemoryPressureMonitor:
    """Process-wide monitor bound to the active budget (lazily created)."""
    global _GLOBAL_MONITOR
    with _MONITOR_LOCK:
        if _GLOBAL_MONITOR is None:
            from paleo_workbench.runtime.resource_budget import active_budget

            _GLOBAL_MONITOR = MemoryPressureMonitor(active_budget())
            _install_default_evictables(_GLOBAL_MONITOR)
        return _GLOBAL_MONITOR


def set_pressure_monitor(monitor: MemoryPressureMonitor | None) -> None:
    """Test/teardown helper; ``None`` resets to lazy default."""
    global _GLOBAL_MONITOR
    with _MONITOR_LOCK:
        _GLOBAL_MONITOR = monitor


def _install_default_evictables(monitor: MemoryPressureMonitor) -> None:
    """Wire the process caches as relief targets (missing engines are fine)."""
    try:
        from paleo_workbench.viz.seismic_volume_cache import get_global_seismic_cache

        monitor.register_evictable("seismic_volume_cache", get_global_seismic_cache().clear)
    except Exception:
        pass
    try:
        from geoviz_seismic.cache import global_stats, set_global_budget  # type: ignore

        def _trim_l1_ledger() -> int:
            # Shrinking to 50% and restoring the budget evicts global-LRU
            # entries immediately; restore keeps future puts bounded by the
            # configured budget rather than by the relief value.
            from paleo_workbench.runtime.resource_budget import active_budget

            budget = active_budget()
            before = global_stats()["bytes_now"]
            set_global_budget(max(1, budget.l1_slice_cache_bytes // 2))
            set_global_budget(budget.l1_slice_cache_bytes)
            return max(0, before - global_stats()["bytes_now"])

        monitor.register_evictable("l1_slice_ledger", _trim_l1_ledger)
    except Exception:
        pass
