"""Small main-thread queue for non-visible project-page bindings.

Project open needs the data/navigation page immediately, while scientific
pages may load previews or native state as part of ``set_project`` /
``update_state``.  This queue holds only the newest callback for each named
binding and intentionally owns no project model: callers retain authority for
the live document and invoke :meth:`flush` on the GUI thread.
"""

from __future__ import annotations

from collections.abc import Callable


class DeferredPageBindings:
    """Coalesce newest non-visible page bindings until first visit."""

    def __init__(self) -> None:
        self._pending: dict[int, dict[str, Callable[[], None]]] = {}

    def schedule(self, index: int, name: str, callback: Callable[[], None]) -> None:
        self._pending.setdefault(index, {})[name] = callback

    def flush(self, index: int) -> None:
        # A project binding may enqueue the matching state callback.  Drain
        # until stable so first navigation never requires a second click; run
        # project assignment ahead of state regardless of enqueue order.
        while callbacks := self._pending.pop(index, None):
            project = callbacks.pop("project", None)
            if project is not None:
                project()
            for callback in callbacks.values():
                callback()

    def has_pending(self, index: int) -> bool:
        return bool(self._pending.get(index))
