"""Global heavy-task scheduler (#1081).

One process-wide FIFO queue for I/O-heavy background work — seismic
transcode, LOD builds, full-volume attributes, tiled AI inference — so those
modules stop building ad-hoc thread pools that fight each other for disk and
RAM. Deliberately Qt-free (pure threads + events): the UI layer wraps it
with signals/polling, and tests run headless.

Contracts:

- **Concurrency**: I/O-heavy tasks run at concurrency 1 by default
  (``max_workers``); the queue is FIFO within a priority level.
- **Priority**: ``submit(..., priority=N)`` — higher runs first. Views the
  user is actively browsing call :meth:`TaskScheduler.boost` to promote the
  task feeding them (e.g. the LOD build for the opened volume).
- **Cancellation is cooperative**: the task callable receives a
  :class:`TaskContext`; a task that sees ``ctx.cancelled`` must stop at its
  next safe point, leave resumable intermediates on disk, and return (or
  raise :class:`TaskCancelled`). The scheduler NEVER deletes a task's work
  directory — resume/cleanup belongs to the task implementation
  (crash-safe partial results).
- **Resume**: tasks are expected idempotent over their own artifacts (the
  transcoder probes completed shards; attribute jobs scan completed bands;
  inference scans completed tiles). Re-submitting the same ``task_key``
  while one is active raises; after completion it re-runs (implementations
  skip finished work).
- **Progress/failure** are queryable thread-safely for UI status models.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TaskCancelled(Exception):
    """Raised by task callables that abort at a safe point."""


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskContext:
    """Cooperative control handle passed to every task callable."""

    task_id: str
    cancelled: threading.Event = field(default_factory=threading.Event)
    _progress_cb: Callable[[float, str], None] | None = field(default=None, repr=False)

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise TaskCancelled(self.task_id)

    def report_progress(self, done: float, total: float | None = None, message: str = "") -> None:
        ratio = (done / total) if total else done
        if self._progress_cb is not None:
            try:
                self._progress_cb(min(max(ratio, 0.0), 1.0), message)
            except Exception:  # progress must never kill a task
                logger.exception("progress callback failed for %s", self.task_id)

    def sleep_interruptible(self, seconds: float) -> None:
        """Wait that wakes early on cancel (poll granularity 50 ms)."""
        deadline = time.monotonic() + seconds
        while not self.cancelled.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.cancelled.wait(min(remaining, 0.05))


@dataclass
class TaskSpec:
    """One heavy task. ``callable(ctx) -> Any`` runs on the worker thread."""

    callable: Callable[[TaskContext], Any]
    kind: str = "io"
    title: str = ""
    task_key: str | None = None  # dedupe key; None -> unique
    priority: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    on_done: Callable[[Any], None] | None = None
    on_fail: Callable[[BaseException], None] | None = None
    on_cancel: Callable[[], None] | None = None
    keep_work_dir: bool = True


@dataclass
class TaskHandle:
    task_id: str
    spec: TaskSpec
    state: TaskState = TaskState.QUEUED
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    result: Any = None
    submitted_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def task_key(self) -> str:
        return self.spec.task_key or self.task_id


class TaskScheduler:
    """FIFO + priority scheduler with cooperative cancel and crash-safe work dirs.

    P2-A additions (all optional, inactive by default so the scheduler stays
    usable standalone):

    - **Admission hook** (:meth:`set_admission`): before a queued task starts,
      the hook may reserve resources and return a lease-like object (with a
      ``release()`` method). Returning a falsy value defers the task — it
      stays queued and is retried; lower-priority admissible tasks may pass
      it. The scheduler releases the lease when the task reaches a terminal
      state. The :class:`ResourceGovernor` installs exactly such a hook.
    - **Aging**: a task's effective priority grows while it waits
      (``AGING_STEP`` per ``AGING_INTERVAL_S``, capped at ``AGING_MAX_BOOST``)
      so a continuous stream of higher-priority interactive work cannot
      starve background jobs forever.
    """

    HISTORY_LIMIT = 200
    AGING_INTERVAL_S = 5.0
    AGING_STEP = 5
    AGING_MAX_BOOST = 50

    def __init__(self, *, max_workers: int = 1, work_root: str | Path | None = None, clock: Callable[[], float] = time.monotonic):
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1 (I/O-heavy default is 1)")
        self.max_workers = max_workers
        self._work_root = Path(work_root) if work_root else None
        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._clock = clock
        # Heap entries: (-priority, seq, task_id). seq keeps FIFO order.
        self._heap: list[tuple[int, int, str]] = []
        self._seq = itertools.count()
        self._handles: dict[str, TaskHandle] = {}
        self._active_keys: set[str] = set()
        self._cancel_events: dict[str, threading.Event] = {}
        self._work_dirs: dict[str, Path] = {}
        self._threads: list[threading.Thread] = []
        self._shutdown = False
        self._admission: Callable[[TaskSpec, str], Any] | None = None
        self._leases: dict[str, Any] = {}
        self._last_rekey = clock()
        for _ in range(max_workers):
            t = threading.Thread(target=self._worker_loop, name="paleo-heavy-task", daemon=True)
            t.start()
            self._threads.append(t)

    # ---------------------------------------------------------- admission --
    def set_admission(self, hook: Callable[[TaskSpec, str], Any] | None) -> None:
        """Install/replace/clear the admission hook (lease protocol above).

        The hook runs without the scheduler lock held; it must be fast
        (counter checks, no IO) to keep the interactive queue-delay budget.
        """
        with self._lock:
            self._admission = hook
        self._wakeup.set()

    def _release_lease(self, task_id: str) -> None:
        with self._lock:
            lease = self._leases.pop(task_id, None)
        if lease is not None:
            release = getattr(lease, "release", None)
            if callable(release):
                try:
                    release()
                except Exception:
                    logger.exception("admission lease release failed for %s", task_id)

    def _effective_priority(self, handle: TaskHandle) -> int:
        """Base priority plus bounded aging so background work is not starved."""
        wait = max(0.0, self._clock() - handle.submitted_at)
        boost = min(
            int(wait // self.AGING_INTERVAL_S) * self.AGING_STEP, self.AGING_MAX_BOOST
        )
        return handle.spec.priority + boost

    def _rekey_heap_locked(self) -> None:
        """Rebuild the heap with current effective priorities (seq preserved)."""
        entries: list[tuple[int, str]] = []
        while self._heap:
            _, seq, tid = heapq.heappop(self._heap)
            h = self._handles.get(tid)
            if h is not None and h.state == TaskState.QUEUED:
                entries.append((seq, tid))
        for seq, tid in entries:
            heapq.heappush(self._heap, (-self._effective_priority(self._handles[tid]), seq, tid))
        self._last_rekey = self._clock()

    # ------------------------------------------------------------ submit --
    def submit(self, spec: TaskSpec) -> TaskHandle:
        task_id = uuid.uuid4().hex[:12]
        handle = TaskHandle(task_id=task_id, spec=spec, submitted_at=self._clock())
        key = handle.task_key
        with self._lock:
            if self._shutdown:
                raise RuntimeError("scheduler is shut down")
            if key in self._active_keys:
                raise ValueError(f"task with key {key!r} is already queued or running")
            self._handles[task_id] = handle
            self._active_keys.add(key)
            heapq.heappush(self._heap, (-spec.priority, next(self._seq), task_id))
        self._wakeup.set()
        return handle

    def submit_callable(
        self,
        fn: Callable[[TaskContext], Any],
        *,
        kind: str = "io",
        title: str = "",
        task_key: str | None = None,
        priority: int = 0,
    ) -> TaskHandle:
        return self.submit(
            TaskSpec(callable=fn, kind=kind, title=title, task_key=task_key, priority=priority)
        )

    # ------------------------------------------------------------ control --
    def cancel(self, task_id: str) -> bool:
        """Cooperative cancel: queued tasks drop; running tasks get the event."""
        with self._lock:
            handle = self._handles.get(task_id)
            if handle is None or handle.state not in (TaskState.QUEUED, TaskState.RUNNING):
                return False
            if handle.state == TaskState.QUEUED:
                self._heap = [e for e in self._heap if e[2] != task_id]
                heapq.heapify(self._heap)
                self._finish_locked(handle, TaskState.CANCELLED)
                on_cancel = handle.spec.on_cancel
            else:
                self._cancel_events[task_id].set()
                return True
        self._wakeup.set()
        if on_cancel is not None:
            try:
                on_cancel()
            except Exception:
                logger.exception("on_cancel callback failed for %s", task_id)
        return True

    def boost(self, task_id: str, priority: int | None = None) -> bool:
        """Promote a QUEUED task (user started browsing what it feeds)."""
        with self._lock:
            handle = self._handles.get(task_id)
            if handle is None or handle.state != TaskState.QUEUED:
                return False
            if priority is None:
                priority = handle.spec.priority + 10
            self._heap = [e for e in self._heap if e[2] != task_id]
            heapq.heapify(self._heap)
            heapq.heappush(self._heap, (-priority, next(self._seq), task_id))
            return True

    def boost_matching(self, kind: str, priority: int | None = None) -> int:
        with self._lock:
            ids = [
                h.task_id
                for h in self._handles.values()
                if h.state == TaskState.QUEUED and h.spec.kind == kind
            ]
        for tid in ids:
            self.boost(tid, priority)
        return len(ids)

    # ------------------------------------------------------------ status --
    def handle(self, task_id: str) -> TaskHandle | None:
        with self._lock:
            h = self._handles.get(task_id)
            return h

    def statuses(self) -> list[TaskHandle]:
        with self._lock:
            return list(self._handles.values())

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for h in self._handles.values() if h.state == TaskState.RUNNING)

    # ---------------------------------------------------------- work dirs --
    def work_dir(self, task_id: str) -> Path:
        """Scratch dir owned by the task. Survives cancel/crash (crash-safe
        partial results); released only via :meth:`release_work_dir`."""
        with self._lock:
            d = self._work_dirs.get(task_id)
            if d is None:
                root = self._work_root or Path.home() / ".paleo_workbench" / "heavy-tasks"
                d = root / task_id
                d.mkdir(parents=True, exist_ok=True)
                self._work_dirs[task_id] = d
            return d

    def release_work_dir(self, task_id: str) -> None:
        with self._lock:
            d = self._work_dirs.pop(task_id, None)
        if d is not None and d.exists():
            import shutil

            shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------ worker --
    def _worker_loop(self) -> None:  # pragma: no cover - exercised via tests
        while True:
            deferred: list[str] = []
            task_id: str | None = None
            admission = self._admission  # snapshot; hooks may swap mid-loop
            with self._lock:
                if self._shutdown and not self._heap:
                    return
                if self._heap and (self._clock() - self._last_rekey) >= self.AGING_INTERVAL_S / 2:
                    self._rekey_heap_locked()
                while self._heap:
                    _, _, tid = heapq.heappop(self._heap)
                    h = self._handles.get(tid)
                    if h is None or h.state != TaskState.QUEUED:
                        continue
                    if admission is not None:
                        lease = None
                        try:
                            lease = admission(h.spec, tid)
                        except Exception:
                            logger.exception("admission hook failed for %s", tid)
                        if not lease:
                            deferred.append(tid)
                            continue
                        self._leases[tid] = lease
                    task_id = tid
                    break
                # Deferred candidates go back regardless of whether another
                # task was admitted — dropping them would lose the task.
                for tid in deferred:
                    h = self._handles.get(tid)
                    if h is not None and h.state == TaskState.QUEUED:
                        heapq.heappush(
                            self._heap, (-self._effective_priority(h), next(self._seq), tid)
                        )
                if task_id is None:
                    self._wakeup.clear()
            if task_id is None:
                # Deferred tasks may become admissible the moment a lease is
                # released; poll them faster than fresh submits wake us.
                timeout = 0.05 if deferred else 0.2
                self._wakeup.wait(timeout=timeout)
                continue
            self._run_task(task_id)

    def _run_task(self, task_id: str) -> None:
        try:
            self._run_task_inner(task_id)
        finally:
            self._release_lease(task_id)

    def _run_task_inner(self, task_id: str) -> None:
        with self._lock:
            handle = self._handles[task_id]
            handle.state = TaskState.RUNNING
            handle.started_at = self._clock()
            ctx = TaskContext(task_id=task_id)
            self._cancel_events[task_id] = ctx.cancelled

            def report(ratio: float, message: str) -> None:
                handle.progress = ratio
                handle.message = message

            ctx._progress_cb = report
        try:
            result = handle.spec.callable(ctx)
        except TaskCancelled:
            if handle.spec.on_cancel is not None:
                try:
                    handle.spec.on_cancel()
                except Exception:
                    logger.exception("on_cancel callback failed for %s", task_id)
            with self._lock:
                self._finish_locked(handle, TaskState.CANCELLED)
        except BaseException as exc:  # noqa: BLE001 - failure state is part of the contract
            logger.exception("heavy task %s (%s) failed", task_id, handle.spec.title)
            if handle.spec.on_fail is not None:
                try:
                    handle.spec.on_fail(exc)
                except Exception:
                    logger.exception("on_fail callback failed for %s", task_id)
            with self._lock:
                handle.error = f"{type(exc).__name__}: {exc}"
                self._finish_locked(handle, TaskState.FAILED)
        else:
            if ctx.cancelled.is_set():
                # Task returned at a safe point after cancel: its return
                # value is a partial result, not a completion.
                if handle.spec.on_cancel is not None:
                    try:
                        handle.spec.on_cancel()
                    except Exception:
                        logger.exception("on_cancel callback failed for %s", task_id)
                with self._lock:
                    handle.result = result
                    self._finish_locked(handle, TaskState.CANCELLED)
                return
            handle.result = result
            # Callbacks run BEFORE the terminal state lands: observers that
            # see DONE (e.g. derived-version registration) can rely on the
            # on_done side effects having completed.
            if handle.spec.on_done is not None:
                try:
                    handle.spec.on_done(result)
                except Exception:
                    logger.exception("on_done callback failed for %s", task_id)
            with self._lock:
                handle.progress = 1.0
                self._finish_locked(handle, TaskState.DONE)
        finally:
            with self._lock:
                self._cancel_events.pop(task_id, None)
            self._wakeup.set()

    def _finish_locked(self, handle: TaskHandle, state: TaskState) -> None:
        handle.state = state
        handle.finished_at = self._clock()
        self._active_keys.discard(handle.task_key)
        # Bounded history: drop the oldest finished handles.
        finished = [h for h in self._handles.values() if h.finished_at is not None]
        if len(finished) > self.HISTORY_LIMIT:
            for h in sorted(finished, key=lambda x: x.finished_at or 0)[: len(finished) - self.HISTORY_LIMIT]:
                self._handles.pop(h.task_id, None)
                self._work_dirs.pop(h.task_id, None)

    # ---------------------------------------------------------- shutdown --
    def shutdown(self, *, wait: bool = True, timeout: float | None = None) -> None:
        """Stop accepting work; cancel running tasks; optionally join workers."""
        with self._lock:
            self._shutdown = True
            for ev in self._cancel_events.values():
                ev.set()
            queued_cancels = []
            for h in self._handles.values():
                if h.state == TaskState.QUEUED:
                    self._finish_locked(h, TaskState.CANCELLED)
                    if h.spec.on_cancel is not None:
                        queued_cancels.append(h.spec.on_cancel)
            self._heap.clear()
        self._wakeup.set()
        for cb in queued_cancels:
            try:
                cb()
            except Exception:
                logger.exception("on_cancel callback failed during shutdown")
        if wait:
            deadline = None if timeout is None else time.monotonic() + timeout
            for t in self._threads:
                if deadline is None:
                    t.join()
                else:
                    t.join(max(0.0, deadline - time.monotonic()))


# --------------------------------------------------------------- singleton


_GLOBAL: TaskScheduler | None = None
_GLOBAL_LOCK = threading.Lock()


def get_scheduler() -> TaskScheduler:
    """Process-wide scheduler (I/O concurrency 1). Created lazily."""
    global _GLOBAL
    with _GLOBAL_LOCK:
        if _GLOBAL is None:
            _GLOBAL = TaskScheduler(max_workers=1)
        return _GLOBAL


def reset_global_scheduler() -> None:
    """Test/teardown helper: shut down and forget the singleton."""
    global _GLOBAL
    with _GLOBAL_LOCK:
        if _GLOBAL is not None:
            _GLOBAL.shutdown(wait=True, timeout=5.0)
        _GLOBAL = None
