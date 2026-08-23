"""Four fundamental registries for Paleo AI GIS Harness."""

from paleo_workbench.agent.registries.tool_registry import (
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    tool_registry,
)
from paleo_workbench.agent.registries.skill_registry import (
    SkillDefinition,
    SkillRegistry,
    skill_registry,
)
from paleo_workbench.agent.registries.algorithm_registry import (
    AlgorithmMetadata,
    AlgorithmRegistry,
    algorithm_registry,
)
from paleo_workbench.agent.registries.template_registry import (
    MapLayoutTemplate,
    TemplateRegistry,
    template_registry,
)

__all__ = [
    "AlgorithmMetadata",
    "AlgorithmRegistry",
    "MapLayoutTemplate",
    "SkillDefinition",
    "SkillRegistry",
    "TemplateRegistry",
    "ToolDefinition",
    "ToolParameter",
    "ToolRegistry",
    "algorithm_registry",
    "skill_registry",
    "template_registry",
    "tool_registry",
]
