"""Workflow package — compilation orchestration, factors, QC, freshness."""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_affected_products_plan",
    "create_compilation_run",
    "dashboard_state",
    "downstream_impact_for_version",
    "home_workflow_steps",
    "infer_workflow_step_status",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from paleo_workbench.workflow import service as _service

        return getattr(_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
