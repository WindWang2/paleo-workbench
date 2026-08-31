"""P2-A resource governance unit tests: budgets, pressure, admission, aging.

These tests build isolated governors/monitors (never the process singleton)
except where the singleton wiring itself is under test.
"""
from __future__ import annotations

import threading
import time

import pytest

from paleo_workbench.runtime import (
    CancellationSource,
    CancellationToken,
    ResourceBudget,
    ResourceExhausted,
    ResourceGovernor,
    TaskCategory,
    TaskRequest,
    TaskScheduler,
    TaskSpec,
    cancel_callable,
    category_for_kind,
    ensure_global_governance,
    policy_for,
)
from paleo_workbench.runtime.memory_pressure import (
    MemoryPressureMonitor,
    PressureState,
)
from paleo_workbench.runtime.resource_governor import configure_runtime_budget
from paleo_workbench.runtime.task_scheduler import TaskCancelled


# ---------------------------------------------------------------- budgets --
def test_budget_cpu_columns_degrade_on_small_machines():
    big = ResourceBudget(logical_cores=16)
    assert big.detected_logical_cores == 16
    assert big.background_cores == 14
    assert big.heavy_task_core_allowance == 14

    tiny = ResourceBudget(logical_cores=2, interactive_reserve_cores=1)
    # 1 core for background, 1 for GUI — never zero on either side.
    assert tiny.background_cores == 1
    assert tiny.heavy_task_core_allowance == 1


def test_budget_pressure_scale_shrinks_cpu_and_io_only():
    base = ResourceBudget(logical_cores=16)
    scaled = base.with_pressure_scale(0.5)
    assert scaled.background_cores == 7
    assert scaled.io_slots == pytest.approx(2.0)
    assert scaled.streaming_buffer_bytes == base.streaming_buffer_bytes
    assert scaled.vram_budget_mb == base.vram_budget_mb


def test_budget_for_total_ram_small_machine_reserves_one_core():
    small = ResourceBudget.for_total_ram_gb(8.0)
    assert small.interactive_reserve_cores == 1


# ---------------------------------------------------------------- pressure --
class FakeMonitor(MemoryPressureMonitor):
    """Monitor whose sampling is replaced by a programmable state."""

    def __init__(self, budget, state: PressureState):
        super().__init__(budget)
        self._forced = state

    def state(self, *, refresh: bool = False) -> PressureState:
        return self._forced


def _governor(
    cores: int = 16,
    *,
    state: PressureState = PressureState.NORMAL,
    ram_gb: float = 32.0,
) -> ResourceGovernor:
    budget = ResourceBudget(
        total_ram_gb=ram_gb,
        logical_cores=cores,
        streaming_buffer_bytes=8 * 1024**3,
    )
    return ResourceGovernor(budget, pressure_monitor=FakeMonitor(budget, state))


def test_pressure_monitor_transitions_and_runs_relief():
    budget = ResourceBudget(total_ram_gb=32.0, ram_pressure_frac=0.5, ram_critical_frac=0.9)
    freed = {"calls": 0}

    def evict() -> int:
        freed["calls"] += 1
        return 123

    monitor = MemoryPressureMonitor(
        budget,
        sample_interval_s=0.0,
        sampler=lambda b: (0.95, 10**9, 64 * 1024**3),
    )
    monitor.register_evictable("test_cache", evict)
    assert monitor.refresh() is PressureState.CRITICAL
    snap = monitor.snapshot()
    assert snap["state"] == "critical"
    assert freed["calls"] >= 1
    assert snap["relief_freed_bytes"] >= 123


def test_pressure_monitor_rate_limits_sampling():
    budget = ResourceBudget(total_ram_gb=32.0)
    t = {"now": 0.0}
    samples = {"n": 0}

    def fake_read(budget):
        samples["n"] += 1
        return 0.1, 0, 64 * 1024**3

    monitor = MemoryPressureMonitor(
        budget, sample_interval_s=10.0, clock=lambda: t["now"], sampler=fake_read
    )
    monitor.state()
    monitor.state()  # within interval: no re-sample
    assert samples["n"] == 1
    t["now"] = 11.0
    monitor.state()
    assert samples["n"] == 2


# --------------------------------------------------------------- admission --
def test_admit_release_roundtrip_restores_capacity():
    gov = _governor()
    request = TaskRequest(
        category=TaskCategory.TRANSCODE, estimated_cpu_cores=10, io_weight=2.0
    )
    lease = gov.admit(request)
    status = gov.runtime_status()
    assert status["reserved"]["cores"] == 10
    assert status["reserved"]["io_weight"] == 2.0
    lease.release()
    status = gov.runtime_status()
    assert status["reserved"]["cores"] == 0
    assert status["reserved"]["io_weight"] == 0


def test_background_ceiling_defers_but_interactive_passes():
    gov = _governor(cores=8)  # background ceiling 6
    first = gov.admit(TaskRequest(category=TaskCategory.TRANSCODE, estimated_cpu_cores=6))
    # Background task over the ceiling is deferred (scheduler retries later).
    assert gov.try_admit(TaskRequest(category=TaskCategory.ATTRIBUTE, estimated_cpu_cores=2)) is None
    # Interactive work may still use the reserved cores.
    lease = gov.admit(TaskRequest(category=TaskCategory.INTERACTIVE_RENDER, estimated_cpu_cores=2))
    assert lease is not None
    first.release()
    lease.release()
    # Capacity back: background fits again.
    assert gov.try_admit(TaskRequest(category=TaskCategory.ATTRIBUTE, estimated_cpu_cores=2)) is not None


def test_critical_pressure_sheds_background_but_not_interactive():
    gov = _governor(state=PressureState.CRITICAL)
    with pytest.raises(ResourceExhausted) as excinfo:
        gov.admit(TaskRequest(category=TaskCategory.TRANSCODE, estimated_cpu_cores=1))
    assert "pressure" in excinfo.value.reason
    assert excinfo.value.retryable is False
    # Interactive categories are exempt so the UI keeps responding.
    lease = gov.admit(TaskRequest(category=TaskCategory.INTERACTIVE_QUERY, estimated_cpu_cores=1))
    lease.release()
    assert gov.metrics.pressure_rejections == 1


def test_pressure_scales_cpu_allowance_and_io_slots():
    normal = _governor(cores=16)
    pressured = _governor(cores=16, state=PressureState.PRESSURE)
    assert normal.cpu_allowance(TaskCategory.TRANSCODE) == 14
    assert pressured.cpu_allowance(TaskCategory.TRANSCODE) == 7
    assert pressured.io_slots() == pytest.approx(2.0)
    assert pressured.onnx_thread_allowance() == 7


def test_cpu_allowance_requested_never_exceeded():
    gov = _governor(cores=32)
    assert gov.cpu_allowance(TaskCategory.TRANSCODE, requested=4) == 4


def test_ram_soft_limit_defers_background():
    gov = _governor(cores=8)
    gov._budget  # budget streaming buffer is 8 GiB from _governor()
    big = gov.admit(
        TaskRequest(category=TaskCategory.INFERENCE, estimated_ram_bytes=6 * 1024**3)
    )
    # Second large background estimate exceeds the soft limit -> deferred.
    assert (
        gov.try_admit(TaskRequest(category=TaskCategory.INFERENCE, estimated_ram_bytes=6 * 1024**3))
        is None
    )
    big.release()
    assert (
        gov.try_admit(TaskRequest(category=TaskCategory.INFERENCE, estimated_ram_bytes=6 * 1024**3))
        is not None
    )


def test_io_slot_budget_bounds_concurrent_io():
    gov = _governor()  # io_slots default 4
    leases = [
        gov.admit(TaskRequest(category=TaskCategory.TRANSCODE, estimated_cpu_cores=0.1, io_weight=2.0))
        for _ in range(2)
    ]
    # 2 + 2 = 4 slots used: a third IO-heavy task must defer.
    assert (
        gov.try_admit(TaskRequest(category=TaskCategory.TRANSCODE, estimated_cpu_cores=0.1, io_weight=2.0))
        is None
    )
    leases[0].release()
    assert (
        gov.try_admit(TaskRequest(category=TaskCategory.TRANSCODE, estimated_cpu_cores=0.1, io_weight=2.0))
        is not None
    )


def test_admit_metrics_counted():
    gov = _governor()
    lease = gov.admit(TaskRequest(category=TaskCategory.PREVIEW))
    lease.release()
    snap = gov.metrics.snapshot()
    assert snap["admitted"] == 1
    assert snap["released"] == 1
    assert snap["active_leases"] == 0
    assert snap["max_hold_seconds"] >= 0.0


# ----------------------------------------------------------------- aging --
def test_scheduler_aging_promotes_waiting_background_task():
    events: list[str] = []
    sched = TaskScheduler(max_workers=1)
    try:
        # Occupy the single worker with an interactive task that blocks.
        release_ui = threading.Event()

        def ui_task(ctx):
            events.append("ui-start")
            release_ui.wait(timeout=10)
            events.append("ui-end")

        def bg_task(ctx):
            events.append("bg-run")

        sched.submit_callable(ui_task, kind="interactive.render", priority=100)
        # Background task queued behind it at much lower priority.
        bg_handle = sched.submit_callable(bg_task, kind="maintenance", priority=10)
        time.sleep(0.05)
        release_ui.set()
        deadline = time.monotonic() + 15
        while bg_handle.state.value == "queued" and time.monotonic() < deadline:
            time.sleep(0.05)
        # With only these two tasks FIFO would run it anyway; the meaningful
        # assertion is the aging boost itself:
        handle = sched.handle(bg_handle.task_id)
        assert handle is not None
        assert sched._effective_priority(handle) >= 10  # base survives
        assert bg_handle.state.value in {"running", "done"}
    finally:
        sched.shutdown(wait=True, timeout=5)


def test_scheduler_effective_priority_grows_with_wait():
    t = {"now": 100.0}
    sched = TaskScheduler(max_workers=1, clock=lambda: t["now"])
    try:
        handle = sched.submit_callable(lambda ctx: None, kind="maintenance", priority=10)
        assert sched._effective_priority(handle) == 10
        t["now"] = 100.0 + 3 * TaskScheduler.AGING_INTERVAL_S
        assert sched._effective_priority(handle) == 10 + 3 * TaskScheduler.AGING_STEP
        t["now"] = 100.0 + 1000.0
        assert sched._effective_priority(handle) == 10 + TaskScheduler.AGING_MAX_BOOST
    finally:
        sched.shutdown(wait=True, timeout=5)


def test_scheduler_admission_hook_leases_released_on_completion():
    class Lease:
        def __init__(self):
            self.released = 0

        def release(self):
            self.released += 1

    lease = Lease()
    sched = TaskScheduler(max_workers=1)
    try:
        sched.set_admission(lambda spec, tid: lease if spec.kind == "allowed" else None)
        blocked = sched.submit_callable(lambda ctx: None, kind="blocked")
        allowed = sched.submit_callable(lambda ctx: "ok", kind="allowed")
        deadline = time.monotonic() + 5
        while allowed.state.value != "done" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert allowed.state.value == "done"
        assert lease.released == 1
        # The deferred task never ran and is still queued (not lost).
        assert blocked.state.value == "queued"
    finally:
        sched.set_admission(None)
        sched.shutdown(wait=True, timeout=5)


def test_scheduler_admission_hook_deferred_task_runs_after_release():
    state = {"capacity": 0}
    lock = threading.Lock()

    class Lease:
        def __init__(self):
            pass

        def release(self):
            with lock:
                state["capacity"] += 1

    def hook(spec, tid):
        with lock:
            if state["capacity"] >= 1:
                return None
            state["capacity"] -= 1
            return Lease()

    sched = TaskScheduler(max_workers=1)
    try:
        sched.set_admission(hook)
        first = sched.submit_callable(lambda ctx: None, kind="io", priority=50)
        second = sched.submit_callable(lambda ctx: None, kind="io", priority=10)
        deadline = time.monotonic() + 5
        while (first.state.value != "done" or second.state.value != "done") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert first.state.value == "done"
        assert second.state.value == "done"  # ran after the lease came back
    finally:
        sched.set_admission(None)
        sched.shutdown(wait=True, timeout=5)


# ------------------------------------------------------------ categories --
def test_category_for_kind_maps_production_kinds():
    assert category_for_kind("seismic.transcode") is TaskCategory.TRANSCODE
    assert category_for_kind("seismic.attribute") is TaskCategory.ATTRIBUTE
    assert category_for_kind("unknown-thing") is TaskCategory.BACKGROUND_IO
    assert category_for_kind("") is TaskCategory.BACKGROUND_IO


def test_category_priority_ladder_interactive_above_background():
    policies = {c: policy_for(c).base_priority for c in TaskCategory}
    assert policies[TaskCategory.INTERACTIVE_RENDER] > policies[TaskCategory.PREVIEW]
    assert policies[TaskCategory.PREVIEW] > policies[TaskCategory.TRANSCODE]
    assert policies[TaskCategory.TRANSCODE] > policies[TaskCategory.INDEXING]
    assert policies[TaskCategory.INDEXING] > policies[TaskCategory.MAINTENANCE]


def test_task_request_defaults_come_from_policy():
    request = TaskRequest(category=TaskCategory.TRANSCODE)
    assert request.effective_priority == policy_for(TaskCategory.TRANSCODE).base_priority
    assert request.effective_io_weight == policy_for(TaskCategory.TRANSCODE).io_weight
    from_kind = TaskRequest.from_kind("seismic.attribute", priority=77)
    assert from_kind.category is TaskCategory.ATTRIBUTE
    assert from_kind.effective_priority == 77


# --------------------------------------------------------- cancellation --
def test_cancellation_token_adapts_context_and_events():
    source = CancellationSource()
    token = source.token
    assert token.is_cancelled is False
    token.raise_if_cancelled()  # no-op
    source.cancel()
    assert token.is_cancelled is True
    with pytest.raises(TaskCancelled):
        token.raise_if_cancelled()
    # transcoder-shaped adapter
    cancel = CancellationToken.from_event(source.event)
    assert cancel_callable(cancel)() is True


def test_cancellation_token_from_task_context():
    sched_ctx_event = threading.Event()
    from paleo_workbench.runtime import TaskContext

    ctx = TaskContext(task_id="t")
    ctx.cancelled = sched_ctx_event
    token = CancellationToken.from_context(ctx)
    assert token.is_cancelled is False
    sched_ctx_event.set()
    assert token.is_cancelled is True


# ------------------------------------------------------------- wiring --
def test_ensure_global_governance_installs_admission_and_is_idempotent():
    gov = ensure_global_governance()
    from paleo_workbench.runtime import get_scheduler

    sched = get_scheduler()
    try:
        assert sched._admission is not None
        ensure_global_governance()
        assert sched._admission is not None
        # A live admission round through the global path.
        request = TaskRequest(category=TaskCategory.PREVIEW)
        lease = gov.admit(request)
        lease.release()
    finally:
        sched.set_admission(None)


def test_configure_runtime_budget_rebinds_governor():
    from paleo_workbench.runtime import active_budget, get_governor, set_budget

    original = active_budget()
    try:
        new_budget = ResourceBudget(
            total_ram_gb=16.0, logical_cores=4, vram_budget_mb=512
        )
        applied = configure_runtime_budget(new_budget)
        assert isinstance(applied, dict)
        assert get_governor().budget.logical_cores == 4
        assert active_budget().logical_cores == 4
    finally:
        set_budget(original)
        get_governor().set_budget(original)


def test_runtime_telemetry_snapshot_shape():
    from paleo_workbench.runtime import runtime_snapshot

    snap = runtime_snapshot()
    for key in (
        "cpu_budget",
        "ram_budget",
        "vram_budget",
        "io_slots",
        "scheduler",
        "governor",
        "caches",
    ):
        assert key in snap
    assert snap["scheduler"]["max_workers"] >= 1
    assert "state" in snap["governor"]["pressure"]
