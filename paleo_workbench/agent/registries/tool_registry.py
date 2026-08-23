"""Tool Registry for Paleo AI GIS Harness.

Provides type-annotated, schema-validated tool registration and execution.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ToolParameter:
    name: str
    param_type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    parameters: tuple[ToolParameter, ...]
    handler: Callable[..., Any]

    def to_schema(self) -> dict[str, Any]:
        """Convert tool definition to JSON Schema (OpenAI / Gemini function calling format)."""
        properties = {}
        required = []
        for param in self.parameters:
            properties[param.name] = {
                "type": param.param_type,
                "description": param.description,
            }
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class ToolRegistry:
    """Central registry of all callable domain tools for AI Agents."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        category: str = "general",
        parameters: list[ToolParameter] | None = None,
    ) -> Callable[[Callable], Callable]:
        """Decorator to register a function as an AI Tool."""
        def decorator(func: Callable) -> Callable:
            params = parameters
            if params is None:
                # Infer parameters from function signature
                sig = inspect.signature(func)
                inferred_params = []
                for p_name, param in sig.parameters.items():
                    if p_name in {"self", "cls", "context"}:
                        continue
                    p_type = "string"
                    if param.annotation is int:
                        p_type = "integer"
                    elif param.annotation is float:
                        p_type = "number"
                    elif param.annotation is bool:
                        p_type = "boolean"
                    elif param.annotation in (dict, Mapping):
                        p_type = "object"
                    elif param.annotation in (list, tuple):
                        p_type = "array"

                    has_default = param.default is not inspect.Parameter.empty
                    inferred_params.append(
                        ToolParameter(
                            name=p_name,
                            param_type=p_type,
                            description=f"Parameter {p_name}",
                            required=not has_default,
                            default=param.default if has_default else None,
                        )
                    )
                params = inferred_params

            tool_def = ToolDefinition(
                name=name,
                description=description,
                category=category,
                parameters=tuple(params),
                handler=func,
            )
            self._tools[name] = tool_def
            return func

        return decorator

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        if category is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.category == category]

    def export_schemas(self, category: str | None = None) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self.list_tools(category)]

    def execute(self, name: str, **kwargs: Any) -> Any:
        tool = self.get_tool(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' is not registered.")
        return tool.handler(**kwargs)


# Global default tool registry instance
tool_registry = ToolRegistry()
