"""Global heavy-task scheduler (#1081) — real threads, real queue semantics.

These tests exercise the production scheduler end to end: FIFO order, single
I/O concurrency, priority + boost, cooperative cancel (queued and running),
progress plumbing, failure states, crash-safe work dirs, duplicate-key
rejection and shutdown. No mocks over the scheduler itself.
"""
from __future__ import annotations

import threading
import time

import pytest

from paleo_workbench.runtime import (
    TaskCancelled,
    TaskScheduler,
    TaskSpec,
    TaskState,
    get_scheduler,
    reset_global_scheduler,
)
from paleo_workbench.runtime.resource_budget import (
    ResourceBudget,
    active_budget,
    apply_vram_budget,
)


def _wait_state(handle, state, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.state == state:
            return True
        time.sleep(0.005)
    return False


@pytest.fixture()
def sched(tmp_path):
    s = TaskScheduler(max_workers=1, work_root=tmp_path / "work")
    yield s
    s.shutdown(wait=True, timeout=5.0)


def test_fifo_order_and_single_concurrency(sched):
    order = []
    lock = threading.Lock()
    overlap = []
    running = [0]

    def make(name):
        def fn(ctx):
            with lock:
                running[0] += 1
                overlap.append(running[0])
                order.append(name)
            time.sleep(0.03)
            with lock:
                running[0] -= 1
            return name

        return fn

    for name in ["a", "b", "c", "d"]:
        sched.submit_callable(make(name), kind="io", title=name)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(order) < 4:
        time.sleep(0.01)
    assert order == ["a", "b", "c", "d"]
    assert max(overlap) == 1, f"concurrency exceeded 1: {overlap}"


def test_priority_and_boost(sched):
    order = []
    started = threading.Event()

    def fn(name):
        def inner(ctx):
            started.set() if name == "first" else None
            order.append(name)
            time.sleep(0.02)
            return name

        return inner

    h_first = sched.submit_callable(fn("first"), priority=0)
    assert _wait_state(h_first, TaskState.RUNNING)
    # queued while the worker is busy: priority decides the drain order
    h_low = sched.submit_callable(fn("low"), priority=0)
    h_high = sched.submit_callable(fn("high"), priority=50)
    h_mid = sched.submit_callable(fn("mid"), priority=5)
    # boost 'mid' above 'high' semantics: raise to 100
    assert sched.boost(h_mid.task_id, priority=100)
    for h in (h_low, h_high, h_mid):
        assert _wait_state(h, TaskState.DONE)
    assert order == ["first", "mid", "high", "low"]


def test_cancel_queued_task_never_runs(sched):
    ran = []
    blocker = threading.Event()
    h_block = sched.submit_callable(lambda ctx: (blocker.wait(3), "x"), title="block")
    h_victim = sched.submit_callable(lambda ctx: ran.append(1), title="victim")
    assert _wait_state(h_block, TaskState.RUNNING)
    assert sched.cancel(h_victim.task_id) is True
    blocker.set()
    assert _wait_state(h_block, TaskState.DONE)
    assert _wait_state(h_victim, TaskState.CANCELLED)
    assert ran == []


def test_cancel_running_task_is_cooperative_and_keeps_partial(sched):
    cancelled_seen = []
    on_cancel_called = []

    def long_task(ctx):
        for i in range(100):
            ctx.check_cancelled()
            (sched.work_dir(ctx.task_id) / f"part{i}").write_text("x")
            ctx.report_progress(i, 100)
            ctx.sleep_interruptible(0.02)
        return "done"

    def canceller(ctx):
        time.sleep(0.08)
        return "c"

    h = sched.submit(
        TaskSpec(
            callable=long_task,
            title="long",
            task_key="op/long-1",
            on_cancel=lambda: on_cancel_called.append(1),
        )
    )
    hc = sched.submit_callable(canceller, title="canceller")
    # cancel the RUNNING long task from the main thread
    time.sleep(0.05)
    assert sched.cancel(h.task_id) is True
    assert _wait_state(h, TaskState.CANCELLED, timeout=3)
    assert _wait_state(hc, TaskState.DONE, timeout=5)
    assert on_cancel_called == [1]
    # crash-safe: partial artifacts still on disk, untouched by the scheduler
    work = sched.work_dir(h.task_id)
    assert work.exists() and any(work.iterdir())
    # and the key is free again for a resume submission
    h2 = sched.submit_callable(lambda ctx: "resumed", task_key="op/long-1")
    assert _wait_state(h2, TaskState.DONE, timeout=5)


def test_duplicate_task_key_rejected_while_active(sched):
    blocker = threading.Event()
    h = sched.submit_callable(lambda ctx: blocker.wait(3), task_key="op/x")
    assert _wait_state(h, TaskState.RUNNING)
    with pytest.raises(ValueError):
        sched.submit_callable(lambda ctx: 1, task_key="op/x")
    blocker.set()
    assert _wait_state(h, TaskState.DONE)
    # same key after completion is fine (resume-style re-run)
    h2 = sched.submit_callable(lambda ctx: 2, task_key="op/x")
    assert _wait_state(h2, TaskState.DONE)


def test_progress_failure_and_callbacks(sched):
    progress_seen = []
    done_seen = []
    fail_seen = []

    def ok(ctx):
        ctx.report_progress(1, 2)
        ctx.report_progress(2, 2, "almost")
        return 42

    def boom(ctx):
        raise RuntimeError("disk exploded")

    h_ok = sched.submit(
        TaskSpec(callable=ok, title="ok", on_done=done_seen.append)
    )
    h_bad = sched.submit(
        TaskSpec(callable=boom, title="bad", on_fail=fail_seen.append)
    )
    assert _wait_state(h_ok, TaskState.DONE)
    assert _wait_state(h_bad, TaskState.FAILED)
    assert h_ok.result == 42 and h_ok.progress == 1.0
    assert h_bad.error is not None and "disk exploded" in h_bad.error
    assert done_seen == [42]
    assert len(fail_seen) == 1 and isinstance(fail_seen[0], RuntimeError)
    # statuses() reflects both
    states = {h.task_id: h.state for h in sched.statuses()}
    assert states[h_ok.task_id] == TaskState.DONE
    assert states[h_bad.task_id] == TaskState.FAILED


def test_shutdown_cancels_and_joins(sched):
    h = sched.submit_callable(lambda ctx: ctx.sleep_interruptible(10), title="long")
    assert _wait_state(h, TaskState.RUNNING)
    sched.shutdown(wait=True, timeout=5.0)
    assert h.state in (TaskState.CANCELLED,)
    # scheduler refuses new work after shutdown
    with pytest.raises(RuntimeError):
        sched.submit_callable(lambda ctx: 1)


def test_boost_matching_kinds(sched):
    blocker = threading.Event()
    h0 = sched.submit_callable(lambda ctx: blocker.wait(3), title="hold", kind="other")
    assert _wait_state(h0, TaskState.RUNNING)
    h_lod = sched.submit_callable(lambda ctx: "lod", kind="seismic.lod", title="lod1")
    h_attr = sched.submit_callable(lambda ctx: "attr", kind="seismic.attribute", title="attr")
    assert sched.boost_matching("seismic.lod", priority=99) == 1
    blocker.set()
    assert _wait_state(h_lod, TaskState.DONE)
    assert _wait_state(h_attr, TaskState.DONE)
    # lod ran before attr despite being submitted first with default priority
    assert h_lod.started_at is not None and h_attr.started_at is not None
    assert h_lod.started_at <= h_attr.started_at


def test_global_singleton_is_io_concurrency_one():
    reset_global_scheduler()
    s = get_scheduler()
    try:
        assert s is get_scheduler()
        assert s.max_workers == 1
    finally:
        reset_global_scheduler()


# ------------------------------------------------------------- budget


def test_budget_scaling_and_env_override(monkeypatch):
    b32 = ResourceBudget.for_total_ram_gb(32)
    assert b32.streaming_buffer_bytes == 5 * 1024**3
    assert b32.l1_slice_cache_bytes == 2 * 1024**3
    assert b32.vram_budget_mb == 1024
    # 16 GB machine: everything scales down, never up
    b16 = ResourceBudget.for_total_ram_gb(16)
    assert b16.streaming_buffer_bytes == int(5 * 1024**3 * 0.5)
    assert b16.vram_budget_mb == 1024
    # caps never exceed spec defaults even on huge machines
    b64 = ResourceBudget.for_total_ram_gb(64)
    assert b64.streaming_buffer_bytes == 5 * 1024**3
    assert b64.page_cache_floor_gb > 0
    # env override
    monkeypatch.setenv("PALEO_BUDGET_RAM_GB", "16")
    import paleo_workbench.runtime.resource_budget as rb

    rb._ACTIVE = None
    try:
        assert rb.active_budget().total_ram_gb == 16.0
    finally:
        rb._ACTIVE = None
        monkeypatch.delenv("PALEO_BUDGET_RAM_GB")


def test_vram_budget_applies_to_engine_cache():
    ok = apply_vram_budget(ResourceBudget(vram_budget_mb=512))
    if ok:  # engine importable in this environment
        from geoviz_seismic.vram_cache import VRAM

        assert VRAM.budget_bytes() == 512 * 1024 * 1024
        # restore spec default for other tests
        VRAM.set_budget(1024 * 1024 * 1024)
    else:
        pytest.skip("geoviz_seismic VRAM cache not importable headless")
