"""Geological AI/Agent Harness (P2-C).

Architecture::

    LLM / Agent (external, vendor-agnostic via ToolSource/ChatModel)
        ↓
    HarnessExecutor (validate → permissions → context → admission →
                     execute → verify → ActionResult)
        ↓
    ActionRegistry (ActionSpec = single source for validation, tool
                    schemas and docs)
        ↓
    Domain services (catalog / well / seismic / mapping / workflow)
        ↓
    DataCatalogService / open_volume / provider SDK (P2-B) /
    ResourceGovernor (P2-A)

The agent never drives UI, never touches SQLite, never writes the project
file: reads come through actions over services; writes happen only inside
WRITE-risk actions via domain services with provenance.

Minimal action example::

    from paleo_workbench.harness import ActionContext, ActionSpec, HarnessExecutor
    from paleo_workbench.harness.spec import ActionRisk

    def my_handler(context, parameters):
        return {"answer": 42}

    from paleo_workbench.harness.registry import get_action_registry
    get_action_registry().register(ActionSpec(
        action_id="demo.answer",
        description="Return the answer.",
        handler=my_handler,
        risk=ActionRisk.READ,
    ))
    result = HarnessExecutor().execute("demo.answer", {})
"""
from __future__ import annotations

from paleo_workbench.harness.context import ActionContext, SelectionSnapshot
from paleo_workbench.harness.executor import (
    ActionContextError,
    ActionPermissionError,
    ActionResult,
    ActionValidationError,
    HarnessExecutor,
)
from paleo_workbench.harness.llm import ChatModel, HarnessToolSource, ToolSource
from paleo_workbench.harness.registry import (
    ActionRegistry,
    DuplicateActionError,
    InvalidActionSpecError,
    UnknownActionError,
    get_action_registry,
    set_action_registry,
)
from paleo_workbench.harness.spec import (
    DEFAULT_PERMISSIONS,
    ActionRisk,
    ActionSpec,
    validate_action_spec,
)
from paleo_workbench.harness.validation import (
    FAIL,
    PASS,
    WARNING,
    MapValidationHook,
    ScientificValidator,
    ValidationReport,
)

__all__ = [
    "FAIL",
    "PASS",
    "ActionContext",
    "ActionContextError",
    "ActionPermissionError",
    "ActionRegistry",
    "ActionRisk",
    "ActionResult",
    "ActionSpec",
    "ActionValidationError",
    "ChatModel",
    "DEFAULT_PERMISSIONS",
    "DuplicateActionError",
    "HarnessExecutor",
    "HarnessToolSource",
    "InvalidActionSpecError",
    "MapValidationHook",
    "ScientificValidator",
    "SelectionSnapshot",
    "ToolSource",
    "UnknownActionError",
    "ValidationReport",
    "WARNING",
    "get_action_registry",
    "set_action_registry",
    "validate_action_spec",
]
