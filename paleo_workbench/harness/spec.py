"""Geological harness action specifications (P2-C, Harness 2.0 contracts).

An :class:`ActionSpec` is the single source of truth for one stable,
professional geological action. From it derive — never by hand, never a
second copy — the runtime validation, the machine-readable agent tool
schema, and the docs. Actions are coarse-grained and domain-semantic
(``map.create_factor_map``), not UI gestures (no findChild, no clicks).

Harness 2.0 additions (backward-compatible constructor arguments):

- ``version``: the action contract version — part of every cache key and
  receipt, bumped whenever behaviour or schema changes meaning;
- ``deterministic`` / ``cacheable`` / ``idempotent``: the reproducibility
  vocabulary. ``cacheable`` *requires* ``deterministic`` and a non-empty
  ``output_refs`` declaration — a cache hit must re-materialise from
  catalog-resolvable outputs, never from in-process handles;
- ``verifier``: an action-specific verification hook run by the executor
  after the built-in scientific/map checks (fail-closed);
- ``input_refs`` / ``output_refs``: typed-ref vocabulary names (see
  :data:`paleo_workbench.providers.contracts.TYPED_REFS`) the action
  consumes/produces — documentation *and* a registry-level check;
- ``domain_tags``: free-form, lowercase retrieval tags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){0,3}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ActionRisk(str, Enum):
    READ = "read"          # observe workspace/catalog/context — no mutation
    COMPUTE = "compute"    # derive new data through providers/services
    WRITE = "write"        # mutate documents/versions via domain services
    DESTRUCTIVE = "destructive"  # purge/overwrite; never a default agent action


class ActionStatus(str, Enum):
    """Canonical terminal states of one action execution (Harness 2.0).

    Six states, no aliases: ``rejected`` means a *guard* refused the
    request before/at admission (schema, permission, context, resources);
    ``failed`` means the execution or its verification did not hold;
    ``unavailable`` means a required production capability is missing —
    never a fake result. ``degraded`` is a success carrying warnings.
    """

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


#: Statuses an agent may treat as "the work happened" (data was produced).
#: Everything else is a terminal non-result.
POSITIVE_STATUSES = frozenset({ActionStatus.SUCCESS, ActionStatus.DEGRADED})

#: Default permission set for programmatic/headless contexts: READ + COMPUTE.
#: WRITE is granted explicitly (the app context grants it — a user session
#: sits behind the UI and writes go through domain services either way);
#: DESTRUCTIVE is not installable at all.
DEFAULT_PERMISSIONS = frozenset({ActionRisk.READ, ActionRisk.COMPUTE})


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
    # --- Harness 2.0 -------------------------------------------------------
    version: str = "1.0"  # action contract version; cache/receipt identity
    deterministic: bool = False  # same inputs+params+version → same outputs
    cacheable: bool = False  # may reuse a prior catalog-complete execution
    idempotent: bool = False  # re-execution with same inputs is safe
    verifier: Any = field(compare=False, default=None, repr=False)  # callable(payload, parameters, context) -> report
    domain_tags: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()   # typed-ref vocabulary names consumed
    output_refs: tuple[str, ...] = ()  # typed-ref vocabulary names produced

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
            "version": self.version,
            "deterministic": self.deterministic,
            "cacheable": self.cacheable,
            "idempotent": self.idempotent,
            "domain_tags": list(self.domain_tags),
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
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


def validate_schema_shape(schema: Any, *, _path: str = "schema") -> list[str]:
    """Recursively check that ``schema`` is a well-formed JSON-schema subset.

    Registration-time gate: unknown ``type`` names, non-dict ``properties``,
    non-list ``required``, non-dict ``items`` and misplaced bounds are
    reported here instead of silently passing at execution time.
    """
    problems: list[str] = []
    if not isinstance(schema, dict):
        return [f"{_path}: must be a dict (JSON schema)"]
    expected = schema.get("type")
    known = {"object", "array", "string", "integer", "number", "boolean", "null"}
    if expected is not None:
        names = [str(t) for t in expected] if isinstance(expected, list) else [str(expected)]
        for name in names:
            if name not in known:
                problems.append(f"{_path}: unknown type {name!r}")
    if "enum" in schema and not isinstance(schema["enum"], list):
        problems.append(f"{_path}: enum must be a list")
    for bound in ("minimum", "maximum"):
        if bound in schema and not isinstance(schema[bound], (int, float)):
            problems.append(f"{_path}: {bound} must be numeric")
    for bound in ("minItems", "maxItems"):
        if bound in schema and not isinstance(schema[bound], int):
            problems.append(f"{_path}: {bound} must be an integer")
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            problems.append(f"{_path}.properties: must be a dict")
        else:
            for key, sub in properties.items():
                problems.extend(validate_schema_shape(sub, _path=f"{_path}.properties.{key}"))
    required = schema.get("required")
    if required is not None and not (isinstance(required, list) and all(isinstance(r, str) for r in required)):
        problems.append(f"{_path}.required: must be a list of strings")
    items = schema.get("items")
    if items is not None:
        if isinstance(items, dict):
            problems.extend(validate_schema_shape(items, _path=f"{_path}.items"))
        else:
            problems.append(f"{_path}.items: must be a dict")
    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        problems.append(f"{_path}.additionalProperties: must be a boolean")
    return problems


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
    if isinstance(schema, dict):
        problems.extend(validate_schema_shape(schema, _path="input_schema"))
    if spec.output_schema:
        problems.extend(validate_schema_shape(spec.output_schema, _path="output_schema"))
    if spec.version and not _VERSION_RE.match(spec.version):
        problems.append(f"version {spec.version!r} must be numeric dotted (e.g. 1.0)")
    if spec.cacheable and not spec.deterministic:
        problems.append("cacheable requires deterministic (a cache hit replays the execution)")
    if spec.cacheable and not spec.output_refs:
        problems.append(
            "cacheable requires declared output_refs: a cache hit must "
            "re-materialise from catalog-resolvable outputs"
        )
    if spec.verifier is not None and not callable(spec.verifier):
        problems.append("verifier must be callable(payload, parameters, context)")
    for tag in spec.domain_tags:
        if not isinstance(tag, str) or not _TAG_RE.match(tag):
            problems.append(f"domain_tag {tag!r} must match {_TAG_RE.pattern}")
    from paleo_workbench.providers.contracts import TYPED_REFS

    for role, refs in (("input_refs", spec.input_refs), ("output_refs", spec.output_refs)):
        for ref in refs:
            if ref not in TYPED_REFS:
                problems.append(f"{role} entry {ref!r} is not a known typed ref {sorted(TYPED_REFS)}")
    profile = spec.resource_profile
    if not isinstance(profile, dict):
        problems.append("resource_profile must be a dict")
    else:
        if float(profile.get("estimated_cpu_cores", 0.5)) <= 0:
            problems.append("resource_profile.estimated_cpu_cores must be > 0")
        if float(profile.get("io_weight", 0.5)) < 0:
            problems.append("resource_profile.io_weight must be >= 0")
        for key in ("estimated_temp_bytes",):
            if key in profile and not isinstance(profile[key], (int, float)):
                problems.append(f"resource_profile.{key} must be numeric")
    return problems
