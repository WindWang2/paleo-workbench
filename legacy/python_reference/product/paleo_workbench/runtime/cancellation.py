"""Cancellation-token adapters (P2-A).

The workbench grew three cooperative-cancellation dialects:

1. :class:`~paleo_workbench.runtime.task_scheduler.TaskContext` — the heavy
   scheduler contract (``check_cancelled`` raises ``TaskCancelled``);
2. geoviz ``CancellationToken`` — ``cancel()`` / ``is_cancelled`` /
   ``raise_if_cancelled()`` raising ``JobCancelled`` (factor prepare, plots);
3. ad-hoc callables ``cancel: Callable[[], bool]`` + ``progress`` kwargs
   (transcoder, tiled inference) and raw ``threading.Event``.

This module adapts between them instead of replacing any of them: the
scheduler stays canonical for queued heavy tasks; engines keep their own
signatures. ``TaskCancelled`` and ``JobCancelled`` both surface through the
scheduler's existing CANCELLED state because the adapters translate.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from paleo_workbench.runtime.task_scheduler import TaskCancelled, TaskContext


class CancellationToken:
    """geoviz-shaped token backed by any check callable or event.

    Mirrors ``geoviz.jobs.CancellationToken`` (import avoided so the runtime
    package stays engine-optional) and additionally adapts
    :class:`TaskContext`, so a TaskSpec callable can hand its context to
    engine code that expects a token.
    """

    __slots__ = ("_check", "_event")

    def __init__(self, check: Callable[[], bool] | None = None, event: threading.Event | None = None):
        self._check = check
        self._event = event

    @classmethod
    def from_context(cls, ctx: TaskContext) -> "CancellationToken":
        return cls(check=ctx.cancelled.is_set)

    @classmethod
    def from_event(cls, event: threading.Event) -> "CancellationToken":
        return cls(event=event)

    # -- geoviz contract --------------------------------------------------
    @property
    def is_cancelled(self) -> bool:
        if self._event is not None:
            return self._event.is_set()
        return bool(self._check()) if self._check is not None else False

    def cancel(self) -> None:
        if self._event is not None:
            self._event.set()
        elif self._check is not None:
            # Best effort for check-only tokens: nothing to set; callers
            # wrapping mutable state should pass an event instead.
            raise RuntimeError("check-only token cannot be cancelled externally")

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskCancelled("cancellation token fired")

    # -- scheduler-shaped convenience -------------------------------------
    def check_cancelled(self) -> None:
        self.raise_if_cancelled()


class CancellationSource:
    """Owner side of a token pair: ``source.token`` for the task, ``source``
    for the canceller. One event, no polling cost."""

    __slots__ = ("event", "_token")

    def __init__(self) -> None:
        self.event = threading.Event()
        self._token = CancellationToken.from_event(self.event)

    @property
    def token(self) -> CancellationToken:
        return self._token

    @property
    def is_cancelled(self) -> bool:
        return self.event.is_set()

    def cancel(self) -> None:
        self.event.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self.event.wait(timeout)


def cancel_callable(token: CancellationToken) -> Callable[[], bool]:
    """Adapt a token to the transcoder/inference ``cancel=...`` kwarg shape."""

    def cancel() -> bool:
        return token.is_cancelled

    return cancel


def as_event(ctx: TaskContext) -> threading.Event:
    """The scheduler context's event, for APIs taking a raw Event."""
    return ctx.cancelled
