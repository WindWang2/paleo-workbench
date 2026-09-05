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


class DuplicateToolError(ValueError):
    """A different handler is already registered under the tool name."""


class ToolValidationError(TypeError):
    """Call kwargs do not satisfy the tool's declared parameter schema."""


_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list, tuple),
}


def _check_param_value(param: ToolParameter, value: Any) -> bool:
    """True when *value* satisfies the declared scalar/container type."""
    expected = _TYPE_CHECKS.get(param.param_type, ())
    if param.param_type in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, expected)


class ToolRegistry:
    """Central registry of all callable domain tools for AI Agents (validated)."""

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
            # #1185: same handler re-registration is idempotent; a
            # different handler under the name raises instead of hijacking.
            existing = self._tools.get(name)
            if existing is not None and existing.handler is not func:
                raise DuplicateToolError(
                    f"tool {name!r} is already registered by a different handler"
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
        # #1185: validate against the declared schema before anything
        # reaches the handler — unknown kwargs, missing required params,
        # and type mismatches are refused, not injected.
        tool = self.get_tool(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' is not registered.")
        declared = {p.name: p for p in tool.parameters}
        unknown = sorted(set(kwargs) - set(declared))
        if unknown:
            raise ToolValidationError(
                f"tool {name!r} rejects unknown arguments: {unknown}"
            )
        missing = [p.name for p in tool.parameters if p.required and p.name not in kwargs]
        if missing:
            raise ToolValidationError(
                f"tool {name!r} misses required arguments: {missing}"
            )
        for key, value in kwargs.items():
            if not _check_param_value(declared[key], value):
                raise ToolValidationError(
                    f"tool {name!r} argument {key!r} must be "
                    f"{declared[key].param_type}, got {type(value).__name__}"
                )
        return tool.handler(**kwargs)


# Global default tool registry instance
tool_registry = ToolRegistry()
