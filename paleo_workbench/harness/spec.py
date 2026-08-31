"""Geological harness action specifications (P2-C).

An :class:`ActionSpec` is the single source of truth for one stable,
professional geological action. From it derive — never by hand, never a
second copy — the runtime validation, the machine-readable agent tool
schema, and the docs. Actions are coarse-grained and domain-semantic
(``map.create_factor_map``), not UI gestures (no findChild, no clicks).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class ActionRisk(str, Enum):
    READ = "read"          # observe workspace/catalog/context — no mutation
    COMPUTE = "compute"    # derive new data through providers/services
    WRITE = "write"        # mutate documents/versions via domain services
    DESTRUCTIVE = "destructive"  # purge/overwrite; never a default agent action


#: Default agent permission set: READ + COMPUTE always; WRITE passes through
#: domain services with provenance; DESTRUCTIVE is not installable by default.
DEFAULT_PERMISSIONS = frozenset({ActionRisk.READ, ActionRisk.COMPUTE, ActionRisk.WRITE})


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """Declarative contract of one harness action."""

    action_id: str
    description: str
    handler: Any = field(compare=False, default=None, repr=False)  # callable(ActionContext, dict) -> Any
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk: ActionRisk = ActionRisk.READ
    category: str = "background.compute"  # TaskCategory value for admission
    resource_profile: dict[str, Any] = field(
        default_factory=lambda: {
            "estimated_cpu_cores": 0.5,
            "estimated_ram_bytes": 0,
            "estimated_vram_bytes": 0,
            "io_weight": 0.5,
        }
    )
    required_context: tuple[str, ...] = ()  # ActionContext attrs that must be present
    supports_cancel: bool = False
    provider_id: str | None = None  # when execution delegates to a capability provider
    side_effect_notes: str = ""

    @property
    def domain(self) -> str:
        return self.action_id.split(".", 1)[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk": self.risk.value,
            "category": self.category,
            "resource_profile": dict(self.resource_profile),
            "required_context": list(self.required_context),
            "supports_cancel": self.supports_cancel,
            "provider_id": self.provider_id,
            "side_effect_notes": self.side_effect_notes,
        }

    def tool_schema(self) -> dict[str, Any]:
        """Agent tool definition (OpenAI/Gemini function-calling shape),
        derived — the schema is never re-authored anywhere else."""
        return {
            "type": "function",
            "function": {
                "name": self.action_id.replace(".", "__"),
                "description": (
                    f"{self.description} [risk: {self.risk.value}"
                    + (f"; via provider {self.provider_id}" if self.provider_id else "")
                    + "]"
                ),
                "parameters": self.input_schema
                or {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }


def validate_action_spec(spec: ActionSpec) -> list[str]:
    problems: list[str] = []
    if not _ACTION_ID_RE.match(spec.action_id or ""):
        problems.append(
            f"action_id {spec.action_id!r} must be '<domain>.<name>' lowercase dotted"
        )
    if not (spec.description or "").strip():
        problems.append("description must be non-empty")
    if not isinstance(spec.risk, ActionRisk):
        problems.append(f"risk {spec.risk!r} is not an ActionRisk")
    if spec.handler is None and spec.provider_id is None:
        problems.append("spec needs a handler or a provider_id to be executable")
    schema = spec.input_schema
    if not isinstance(schema, dict):
        problems.append("input_schema must be a dict (JSON schema)")
    elif schema.get("type") not in (None, "object"):
        problems.append("input_schema must describe an object at the top level")
    profile = spec.resource_profile
    if not isinstance(profile, dict):
        problems.append("resource_profile must be a dict")
    else:
        if float(profile.get("estimated_cpu_cores", 0.5)) <= 0:
            problems.append("resource_profile.estimated_cpu_cores must be > 0")
        if float(profile.get("io_weight", 0.5)) < 0:
            problems.append("resource_profile.io_weight must be >= 0")
    return problems
