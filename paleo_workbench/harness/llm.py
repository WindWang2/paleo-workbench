"""LLM provider seam (P2-C) — protocols only, zero vendors.

The harness is model-agnostic by construction: an external agent runtime
(LLM or otherwise) binds through :class:`ToolSource` to expose actions and
execute them. No OpenAI/Anthropic/Zhipu/Gemini client lives here; adapters
for any vendor implement :class:`ChatModel` where they live.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolSource(Protocol):
    """The tool-exposure seam an agent runtime binds to."""

    def tool_schemas(self) -> list[dict[str, Any]]: ...

    def execute_tool(self, name: str, arguments: Mapping[str, Any]) -> Any: ...


@runtime_checkable
class ChatModel(Protocol):
    """Vendor-neutral chat model seam (messages in, tool calls / text out).

    Implementations wrap a concrete provider wherever that provider's client
    is configured; the harness never imports one.
    """

    @property
    def model_id(self) -> str: ...

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]: ...


class HarnessToolSource:
    """Bind an :class:`~paleo_workbench.harness.executor.HarnessExecutor` +
    :class:`~paleo_workbench.harness.context.ActionContext` as a ToolSource."""

    def __init__(self, executor, context_factory: Callable[[], Any] | None = None):
        self._executor = executor
        self._context_factory = context_factory

    def tool_schemas(self) -> list[dict[str, Any]]:
        from paleo_workbench.harness.registry import get_action_registry

        return get_action_registry().tool_schemas()

    def execute_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        action_id = name.replace("__", ".")
        context = self._context_factory() if self._context_factory is not None else None
        result = self._executor.execute(action_id, dict(arguments), context)
        return result.to_dict()
