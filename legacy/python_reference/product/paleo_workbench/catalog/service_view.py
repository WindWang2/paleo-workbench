"""Adapter-shaped view over :class:`DataCatalogService` for run-graph helpers.

Both ``prediction.inference_service`` and ``prediction.input_contract`` used
to carry byte-identical private copies of this view (audit #848: "dual
prediction subsystem"). It lives here so the two consumers share ONE
implementation.

:class:`DataRun` stores ``domain_task_id`` in ``parameters["_domain_task_id"]``
(mirroring :class:`~paleo_workbench.catalog.adapter.CoreCatalogAdapter`), so
the proxy exposes it as an attribute like the ``DataRunRef`` the lifecycle
helpers expect.
"""

from __future__ import annotations

from typing import Any


class ServiceRunView:
    """Adapter-shaped view over the service for lifecycle run-graph helpers."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def list_runs(self):
        return [RunProxy(run) for run in self._service.document.runs]

    def resolve_version(self, version_id: str):
        try:
            return self._service.get_version(version_id)
        except Exception:
            return None


class RunProxy:
    __slots__ = ("_run",)

    def __init__(self, run: Any) -> None:
        self._run = run

    @property
    def domain_task_id(self):
        return (self._run.parameters or {}).get("_domain_task_id")

    @property
    def output_version_ids(self):
        return self._run.output_version_ids

    @property
    def input_version_ids(self):
        return self._run.input_version_ids

    @property
    def status(self):
        return self._run.status