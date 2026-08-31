"""Capability provider base protocol + execution context (P2-B).

The protocol is deliberately tiny: a descriptor property and one execute
method. Everything else (validation, admission, provenance, isolation) is
the SDK's job, not the plugin author's — see
:mod:`paleo_workbench.providers.execution`.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from paleo_workbench.providers.contracts import ProviderDescriptor
from paleo_workbench.providers.refs import ProviderResult

# Cooperative cancellation token shape shared with the runtime adapters:
# is_cancelled property + raise_if_cancelled(). CancellationToken from
# paleo_workbench.runtime.cancellation satisfies this.
CancelToken = Any


@runtime_checkable
class CapabilityProvider(Protocol):
    """The one interface every provider implements."""

    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: "ProviderContext",
    ) -> ProviderResult: ...


@dataclass(slots=True)
class ProviderContext:
    """Execution context handed to providers.

    ``catalog`` is the live :class:`paleo_workbench.catalog.port.CatalogPort`
    (or None in catalog-less unit runs — providers must degrade gracefully).
    ``emit_progress`` forwards to the caller's progress surface (UI panel,
    scheduler TaskContext, harness action); ``cancel`` is the cooperative
    token; ``work_dir`` is a scratch directory owned by this execution.
    """

    catalog: Any | None = None
    workspace_root: str | None = None
    session_id: str = ""
    run_id: str | None = None  # DataRunRef id when the executor opened one
    emit_progress: Callable[[float, str], None] | None = None
    cancel: CancelToken | None = None
    work_dir: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def report_progress(self, ratio: float, message: str = "") -> None:
        if self.emit_progress is not None:
            try:
                self.emit_progress(max(0.0, min(1.0, ratio)), message)
            except Exception:
                pass  # progress must never kill a provider

    def check_cancelled(self) -> None:
        if self.cancel is not None:
            raise_if = getattr(self.cancel, "raise_if_cancelled", None)
            if callable(raise_if):
                raise_if()
            elif getattr(self.cancel, "is_cancelled", False):
                raise RuntimeError("provider execution cancelled")
