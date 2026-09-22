"""Global resource governor — admission, reservation, pressure, telemetry (P2-A).

The governor is the single authority that turns :mod:`paleo_workbench.runtime.resource_budget`
caps into decisions. It does **not** own any workers or queues — the
TaskScheduler keeps its role as the one heavy queue; pools and engines keep
their own threads. What changes is that every consumer asks the governor
before claiming resources:

- :meth:`ResourceGovernor.try_admit` — non-blocking reservation check used by
  the scheduler (a deferred task simply stays queued, with aging making sure
  it is not starved by a stream of interactive work);
- :meth:`ResourceGovernor.admit` — blocking-ish API for direct callers
  (providers, harness actions): raises :class:`ResourceExhausted` with an
  explainable reason instead of letting the OS OOM-kill the app;
- :meth:`ResourceGovernor.cpu_allowance` — the one question the parallelism
  knobs (transcode workers, factor-prepare workers, ONNX intra-op threads,
  BLAS pinning) ask instead of each calling ``os.cpu_count()``.

RAM pressure is observed via :class:`~paleo_workbench.runtime.memory_pressure.MemoryPressureMonitor`;
under PRESSURE background CPU/IO allowances shrink and caches are evicted,
under CRITICAL non-essential new work is rejected. VRAM stays governed by the
existing VramTextureCache LRU budget (the governor only reports it).

Thread-safety: all accounting is behind one lock; admission decisions are
pure counter checks (microseconds) so the scheduler's interactive latency
budget (< 50 ms queue delay) is unaffected.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from paleo_workbench.runtime.memory_pressure import (
    MemoryPressureMonitor,
    PressureState,
)
from paleo_workbench.runtime.resource_budget import ResourceBudget
from paleo_workbench.runtime.task_categories import (
    CATEGORY_POLICIES,
    TaskCategory,
    category_for_kind,
    policy_for,
)

logger = logging.getLogger(__name__)

# Pressure -> multiplier applied to the background CPU/IO columns.
_PRESSURE_SCALE: dict[PressureState, float] = {
    PressureState.NORMAL: 1.0,
    PressureState.PRESSURE: 0.5,
    PressureState.CRITICAL: 0.25,
}

# Categories that may still be admitted under CRITICAL pressure (small,
# user-facing work must keep responding; everything else is shed).
_CRITICAL_EXEMPT = frozenset(
    {
        TaskCategory.INTERACTIVE_RENDER,
        TaskCategory.INTERACTIVE_QUERY,
        TaskCategory.PREVIEW,
    }
)


class ResourceExhausted(RuntimeError):
    """Admission refusal with an explainable, UI-recoverable reason."""

    def __init__(self, reason: str, *, retryable: bool = True, pressure: str = "normal"):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.pressure = pressure


@dataclass(slots=True)
class TaskRequest:
    """Resource claim of one task. Estimates are best-effort, never hints of
    pre-allocation — they gate admission exactly like the budget's advisory
    caps always have."""

    category: TaskCategory
    priority: int | None = None  # None -> category base priority
    title: str = ""
    estimated_cpu_cores: float = 1.0
    estimated_ram_bytes: int = 0
    estimated_vram_bytes: int = 0
    io_weight: float | None = None  # None -> category default
    cancellable: bool = True
    task_id: str = ""

    @classmethod
    def from_kind(
        cls,
        kind: str,
        *,
        priority: int | None = None,
        title: str = "",
        estimated_cpu_cores: float = 1.0,
        estimated_ram_bytes: int = 0,
        estimated_vram_bytes: int = 0,
        task_id: str = "",
    ) -> "TaskRequest":
        category = category_for_kind(kind)
        return cls(
            category=category,
            priority=priority,
            title=title,
            estimated_cpu_cores=estimated_cpu_cores,
            estimated_ram_bytes=estimated_ram_bytes,
            estimated_vram_bytes=estimated_vram_bytes,
            task_id=task_id,
        )

    @property
    def effective_priority(self) -> int:
        if self.priority is not None:
            return self.priority
        return policy_for(self.category).base_priority

    @property
    def effective_io_weight(self) -> float:
        if self.io_weight is not None:
            return self.io_weight
        return policy_for(self.category).io_weight


@dataclass(slots=True)
class ResourceLease:
    """Reservation returned by a successful admission; release() is required."""

    request: TaskRequest
    governor: "ResourceGovernor"
    acquired_at: float = field(default_factory=time.monotonic)
    released_at: float | None = None
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self.released_at = time.monotonic()
        self.governor._release(self)

    @property
    def held_seconds(self) -> float:
        end = self.released_at if self.released_at is not None else time.monotonic()
        return end - self.acquired_at

    def __enter__(self) -> "ResourceLease":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


@dataclass(slots=True)
class _Accounting:
    reserved_cores: float = 0.0
    reserved_ram_bytes: int = 0
    reserved_vram_bytes: int = 0
    reserved_io_weight: float = 0.0
    interactive_cores: float = 0.0
    active_leases: int = 0


@dataclass(slots=True)
class GovernorMetrics:
    admitted: int = 0
    deferred: int = 0
    rejected: int = 0
    released: int = 0
    pressure_rejections: int = 0
    total_hold_seconds: float = 0.0
    max_hold_seconds: float = 0.0

    def snapshot(self) -> dict:
        return {
            "admitted": self.admitted,
            "deferred": self.deferred,
            "rejected": self.rejected,
            "pressure_rejections": self.pressure_rejections,
            "released": self.released,
            "active_leases": self.admitted - self.released,
            "total_hold_seconds": round(self.total_hold_seconds, 3),
            "max_hold_seconds": round(self.max_hold_seconds, 3),
        }


class ResourceGovernor:
    """One process-wide admission authority over the budget columns."""

    def __init__(
        self,
        budget: ResourceBudget,
        *,
        pressure_monitor: MemoryPressureMonitor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._budget = budget
        self._monitor = pressure_monitor
        self._clock = clock
        self._lock = threading.Lock()
        self._accounting = _Accounting()
        self.metrics = GovernorMetrics()
        self._pressure_state = PressureState.NORMAL

    # ---------------------------------------------------------- policy --
    @property
    def budget(self) -> ResourceBudget:
        return self._budget

    def set_budget(self, budget: ResourceBudget) -> None:
        with self._lock:
            self._budget = budget

    def _effective_budget(self) -> ResourceBudget:
        """Budget with pressure-scaled CPU/IO columns (RAM caps unchanged)."""
        return self._budget.with_pressure_scale(_PRESSURE_SCALE[self._pressure_state])

    # -------------------------------------------------------- admission --
    def try_admit(self, request: TaskRequest) -> ResourceLease | None:
        """Reserve resources if available; ``None`` means "defer, retry later".

        Deferral keeps the task queued in the scheduler — it is not an error.
        """
        with self._lock:
            self._refresh_pressure_locked()
            decision = self._check_locked(request)
            if decision is not None:
                self.metrics.deferred += 1
                return None
            self._acquire_locked(request)
            self.metrics.admitted += 1
            return ResourceLease(request=request, governor=self)

    def admit(self, request: TaskRequest) -> ResourceLease:
        """Reserve resources or raise :class:`ResourceExhausted`.

        Direct-callers variant (providers, harness): unlike the scheduler
        path there is no queue to fall back into, so exhaustion is an
        explicit, explainable error. ``retryable`` tells the caller whether
        waiting could help (capacity) or not (pressure shedding).
        """
        with self._lock:
            self._refresh_pressure_locked()
            reason = self._check_locked(request)
            if reason is not None:
                self.metrics.rejected += 1
                if reason.startswith("pressure:"):
                    self.metrics.pressure_rejections += 1
                raise ResourceExhausted(
                    reason, retryable=not reason.startswith("pressure:"), pressure=self._pressure_state.value
                )
            self._acquire_locked(request)
            self.metrics.admitted += 1
            return ResourceLease(request=request, governor=self)

    def _refresh_pressure_locked(self) -> None:
        if self._monitor is None:
            self._pressure_state = PressureState.NORMAL
            return
        self._pressure_state = self._monitor.state()

    def _check_locked(self, request: TaskRequest) -> str | None:
        """Return a refusal reason or None when admissible."""
        policy = policy_for(request.category)
        budget = self._effective_budget()

        # CRITICAL: shed everything that is not small interactive work.
        if self._pressure_state is PressureState.CRITICAL and request.category not in _CRITICAL_EXEMPT:
            return f"pressure: memory CRITICAL, shedding {request.category.value}"

        # CPU column. Interactive categories draw on the full logical pool
        # minus what background work already holds; background categories
        # are bounded by the (pressure-scaled) background ceiling.
        cores = max(0.0, float(request.estimated_cpu_cores))
        if policy.background:
            if self._accounting.reserved_cores + cores > budget.background_cores:
                return "cpu: background core ceiling exhausted"
        else:
            interactive_pool = budget.detected_logical_cores - budget.background_cores
            if (
                self._accounting.interactive_cores + cores
                > max(1.0, interactive_pool + budget.interactive_reserve_cores)
            ):
                return "cpu: interactive pool exhausted"

        # RAM soft limit: outstanding estimates within the streaming window.
        ram = max(0, int(request.estimated_ram_bytes))
        if ram > 0 and self._accounting.reserved_ram_bytes + ram > self._budget.streaming_buffer_bytes:
            if policy.background or self._pressure_state is not PressureState.NORMAL:
                return "ram: streaming buffer soft limit"
            # Interactive work never gets hard-blocked by estimates; it is
            # exactly the work the reserves exist for.

        # IO slots: weighted concurrency cap for background streams. Interactive
        # work is exactly what the budget reserves exist for and is light by
        # policy (weight 1.0), so it never gets hard-blocked here.
        if (
            policy.background
            and request.effective_io_weight > 0
            and self._accounting.reserved_io_weight + request.effective_io_weight > budget.io_slots
        ):
            return "io: slot budget exhausted"

        # VRAM: admission only guards *reservations*; the L2 cache keeps its
        # own LRU contract (oversize entries stay resident with a warning).
        vram = max(0, int(request.estimated_vram_bytes))
        if vram > 0 and self._accounting.reserved_vram_bytes + vram > self._budget.vram_budget_mb * 1024 * 1024:
            if policy.background:
                return "vram: L2 budget would be oversubscribed"
        return None

    def _acquire_locked(self, request: TaskRequest) -> None:
        policy = policy_for(request.category)
        acc = self._accounting
        acc.reserved_cores += max(0.0, float(request.estimated_cpu_cores))
        acc.reserved_ram_bytes += max(0, int(request.estimated_ram_bytes))
        acc.reserved_vram_bytes += max(0, int(request.estimated_vram_bytes))
        acc.reserved_io_weight += max(0.0, request.effective_io_weight)
        if policy.interactive:
            acc.interactive_cores += max(0.0, float(request.estimated_cpu_cores))
        acc.active_leases += 1

    def _release(self, lease: ResourceLease) -> None:
        request = lease.request
        policy = policy_for(request.category)
        with self._lock:
            acc = self._accounting
            acc.reserved_cores = max(0.0, acc.reserved_cores - max(0.0, float(request.estimated_cpu_cores)))
            acc.reserved_ram_bytes = max(0, acc.reserved_ram_bytes - max(0, int(request.estimated_ram_bytes)))
            acc.reserved_vram_bytes = max(0, acc.reserved_vram_bytes - max(0, int(request.estimated_vram_bytes)))
            acc.reserved_io_weight = max(0.0, acc.reserved_io_weight - max(0.0, request.effective_io_weight))
            if policy.interactive:
                acc.interactive_cores = max(0.0, acc.interactive_cores - max(0.0, float(request.estimated_cpu_cores)))
            acc.active_leases = max(0, acc.active_leases - 1)
            held = lease.held_seconds
            self.metrics.released += 1
            self.metrics.total_hold_seconds += held
            self.metrics.max_hold_seconds = max(self.metrics.max_hold_seconds, held)

    # ------------------------------------------------------- allowances --
    def cpu_allowance(self, category: TaskCategory, *, requested: int | None = None) -> int:
        """Cores a *new* parallel pipeline of ``category`` may use.

        This replaces the scattered ``os.cpu_count()`` calls: the answer is
        the pressure-scaled background ceiling (interactive categories the
        full pool), never more than ``requested`` when given.
        """
        with self._lock:
            self._refresh_pressure_locked()
            policy = policy_for(category)
            budget = self._effective_budget()
        ceiling = budget.detected_logical_cores if policy.interactive else budget.background_cores
        allowance = max(1, ceiling)
        if requested is not None:
            allowance = min(allowance, max(1, int(requested)))
        return allowance

    def io_slots(self) -> float:
        with self._lock:
            self._refresh_pressure_locked()
            return self._effective_budget().io_slots

    def onnx_thread_allowance(self) -> int:
        """Intra-op threads for a new ONNX session (INFERENCE category)."""
        return self.cpu_allowance(TaskCategory.INFERENCE)

    # ---------------------------------------------------------- status --
    def pressure_state(self) -> PressureState:
        with self._lock:
            self._refresh_pressure_locked()
            return self._pressure_state

    def runtime_status(self) -> dict:
        with self._lock:
            self._refresh_pressure_locked()
            budget = self._effective_budget()
            acc = self._accounting
            monitor_snapshot = self._monitor.snapshot() if self._monitor is not None else {"state": "unmonitored"}
            return {
                "budget": {
                    "total_ram_gb": round(self._budget.total_ram_gb, 2),
                    "logical_cores": self._budget.detected_logical_cores,
                    "background_cores_effective": budget.background_cores,
                    "io_slots_effective": round(budget.io_slots, 2),
                    "vram_budget_mb": self._budget.vram_budget_mb,
                    "l1_slice_cache_bytes": self._budget.l1_slice_cache_bytes,
                    "streaming_buffer_bytes": self._budget.streaming_buffer_bytes,
                },
                "reserved": {
                    "cores": round(acc.reserved_cores, 2),
                    "ram_bytes": acc.reserved_ram_bytes,
                    "vram_bytes": acc.reserved_vram_bytes,
                    "io_weight": round(acc.reserved_io_weight, 2),
                    "active_leases": acc.active_leases,
                },
                "pressure": monitor_snapshot,
                "metrics": self.metrics.snapshot(),
                "categories": {c.value: p.base_priority for c, p in CATEGORY_POLICIES.items()},
            }


# ------------------------------------------------------------- singleton

_GLOBAL_GOVERNOR: ResourceGovernor | None = None
_GOVERNOR_LOCK = threading.Lock()


def get_governor() -> ResourceGovernor:
    """Process-wide governor over the active budget (lazily created)."""
    global _GLOBAL_GOVERNOR
    with _GOVERNOR_LOCK:
        if _GLOBAL_GOVERNOR is None:
            from paleo_workbench.runtime.memory_pressure import get_pressure_monitor
            from paleo_workbench.runtime.resource_budget import active_budget

            _GLOBAL_GOVERNOR = ResourceGovernor(
                active_budget(), pressure_monitor=get_pressure_monitor()
            )
        return _GLOBAL_GOVERNOR


def set_governor(governor: ResourceGovernor | None) -> None:
    """Test/teardown helper; ``None`` resets to lazy default."""
    global _GLOBAL_GOVERNOR
    with _GOVERNOR_LOCK:
        _GLOBAL_GOVERNOR = governor


def configure_runtime_budget(budget: ResourceBudget) -> dict[str, bool]:
    """One stable configuration path: budget -> governor + engine caches.

    Order matters: the caches are pushed first so a pressure sample taken by
    the reconfigured governor sees the new caps already in effect.
    """
    from paleo_workbench.runtime.memory_pressure import get_pressure_monitor
    from paleo_workbench.runtime.resource_budget import (
        apply_all_budgets,
        set_budget,
    )

    applied = apply_all_budgets(budget)
    set_budget(budget)
    monitor = get_pressure_monitor()
    governor = get_governor()
    governor.set_budget(budget)
    # Thresholds follow the new policy (public rebinding, state survives).
    monitor.rebind_budget(budget)
    return applied
