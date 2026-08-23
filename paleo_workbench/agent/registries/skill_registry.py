"""Skill Registry for Paleo AI GIS Harness.

Provides multi-step composite skill workflow definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    category: str
    steps: tuple[str, ...]
    handler: Callable[..., Any]


class SkillRegistry:
    """Registry of higher-order geological and GIS workflow skills."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        category: str = "workflow",
        steps: tuple[str, ...] = (),
    ) -> Callable[[Callable], Callable]:
        def decorator(func: Callable) -> Callable:
            skill_def = SkillDefinition(
                name=name,
                description=description,
                category=category,
                steps=steps,
                handler=func,
            )
            self._skills[name] = skill_def
            return func
        return decorator

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_skills(self, category: str | None = None) -> list[SkillDefinition]:
        if category is None:
            return list(self._skills.values())
        return [s for s in self._skills.values() if s.category == category]

    def execute_skill(self, name: str, context: dict[str, Any], **kwargs: Any) -> Any:
        skill = self.get_skill(name)
        if skill is None:
            raise KeyError(f"Skill '{name}' is not registered.")
        return skill.handler(context, **kwargs)


skill_registry = SkillRegistry()
