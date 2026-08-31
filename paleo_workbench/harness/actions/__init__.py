"""Domain action registration (P2-C).

One module per domain; each exposes ``register(registry)``. Actions are the
only agent-callable surface — coarse-grained, professional, composable.
"""
from __future__ import annotations


def register_all(registry) -> list[str]:
    from paleo_workbench.harness.actions import (
        geology_workflow,
        mapping,
        seismic,
        well,
        workspace,
    )

    registered: list[str] = []
    for module in (workspace, well, seismic, mapping, geology_workflow):
        before = set()
        try:
            before = {s.action_id for s in registry.specs()}
            module.register(registry)
            registered.extend(
                s.action_id for s in registry.specs() if s.action_id not in before
            )
        except Exception:  # one domain failing must not hide the others
            import logging

            logging.getLogger(__name__).exception(
                "harness action registration failed for %s", module.__name__
            )
    return registered


__all__ = ["register_all"]
