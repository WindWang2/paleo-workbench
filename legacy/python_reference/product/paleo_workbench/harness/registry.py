"""Action registry (P2-C): the single authority for harness actions.

Registration is explicit and code-owned (actions live in
:mod:`paleo_workbench.harness.actions`); the registry validates specs,
refuses duplicate ids, and derives agent tool schemas from the same
ActionSpec objects used for runtime validation — one source of truth.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from paleo_workbench.harness.spec import ActionRisk, ActionSpec, validate_action_spec

logger = logging.getLogger(__name__)


class UnknownActionError(LookupError):
    def __init__(self, action_id: str):
        self.action_id = action_id
        super().__init__(f"unknown harness action {action_id!r}")


class DuplicateActionError(ValueError):
    def __init__(self, action_id: str):
        self.action_id = action_id
        super().__init__(f"harness action {action_id!r} already registered")


class InvalidActionSpecError(ValueError):
    def __init__(self, action_id: str, problems: list[str]):
        self.problems = problems
        super().__init__(f"invalid action spec {action_id!r}: {'; '.join(problems)}")


class ActionRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._actions: dict[str, ActionSpec] = {}

    # ------------------------------------------------------------ register --
    def register(self, spec: ActionSpec, *, replace: bool = False) -> ActionSpec:
        problems = validate_action_spec(spec)
        if problems:
            raise InvalidActionSpecError(spec.action_id, problems)
        if spec.risk is ActionRisk.DESTRUCTIVE:
            # Destructive actions exist in the vocabulary but are refused by
            # the default registry: product policy keeps purge/overwrite out
            # of the agent surface entirely.
            raise InvalidActionSpecError(
                spec.action_id, ["DESTRUCTIVE actions are not installable in the default registry"]
            )
        with self._lock:
            if spec.action_id in self._actions and not replace:
                raise DuplicateActionError(spec.action_id)
            self._actions[spec.action_id] = spec
        return spec

    def unregister(self, action_id: str) -> bool:
        with self._lock:
            return self._actions.pop(action_id, None) is not None

    # -------------------------------------------------------------- lookup --
    def get(self, action_id: str) -> ActionSpec:
        spec = self.find(action_id)
        if spec is None:
            raise UnknownActionError(action_id)
        return spec

    def find(self, action_id: str) -> ActionSpec | None:
        with self._lock:
            return self._actions.get(action_id)

    def specs(self, domain: str | None = None) -> list[ActionSpec]:
        with self._lock:
            specs = list(self._actions.values())
        if domain is not None:
            specs = [s for s in specs if s.domain == domain]
        return sorted(specs, key=lambda s: s.action_id)

    def domains(self) -> list[str]:
        return sorted({s.domain for s in self.specs()})

    def __len__(self) -> int:
        with self._lock:
            return len(self._actions)

    # ---------------------------------------------------------- tool layer --
    def tool_schemas(self, domain: str | None = None) -> list[dict[str, Any]]:
        """Agent-facing tool definitions derived from the specs."""
        return [spec.tool_schema() for spec in self.specs(domain)]

    def inventory(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self.specs()]


_GLOBAL_REGISTRY: ActionRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_action_registry() -> ActionRegistry:
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        if _GLOBAL_REGISTRY is None:
            registry = ActionRegistry()
            from paleo_workbench.harness.actions import register_all

            register_all(registry)
            _GLOBAL_REGISTRY = registry
        return _GLOBAL_REGISTRY


def set_action_registry(registry: ActionRegistry | None) -> None:
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        _GLOBAL_REGISTRY = registry
