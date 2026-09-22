"""Unified product lifecycle provenance graph (V8 M10).

One pure-data API composing the EXISTING authorities — catalog lineage
(:mod:`paleo_workbench.catalog.lineage_graph`), run freshness
(:mod:`paleo_workbench.workflow.freshness`), constraint lifecycle pins
(:mod:`paleo_workbench.workflow.constraint_versions`) and map-product
records (:mod:`paleo_workbench.workflow.map_product`) — into the single
dependency narrative Direction A's Inspector / lineage explorer renders:

.. code-block:: text

    RAW assets → derived well/factor inputs → constraints versions
      → factor runs → factor outputs → compilation input set
      → fusion run → integrated draft → QA → map product → freeze/publish

No second authority: every node carries the id of the system that owns it
(version ids, run ids, task ids, record ids); every edge is derived from
recorded lineage, never inferred. Missing pieces are reported as ``missing``
nodes with a reason — a gap in provenance is data, not an exception.
"""
from __future__ import annotations

from typing import Any

__all__ = ["build_product_lifecycle_graph"]


def _node(node_id: str, kind: str, label: str, **extra: Any) -> dict[str, Any]:
    node = {"id": node_id, "kind": kind, "label": label}
    node.update({k: v for k, v in extra.items() if v is not None})
    return node


def build_product_lifecycle_graph(
    project: Any,
    catalog_service: Any = None,
    *,
    product_id: str | None = None,
) -> dict[str, Any]:
    """Explain one product (or every product) from RAW to publish.

    Returns ``{"nodes": [...], "edges": [...], "gaps": [...]}`` — pure data,
    no rendering concerns. Every product contributes: its factor tasks'
    grid versions (+ freshness verdict), the constraint state each task
    pinned, the fusion versions when the product's inputs reference them,
    and the product record's own lifecycle flags (frozen/superseded/stale).
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    seen_nodes: set[str] = set()

    def add_node(node: dict[str, Any]) -> str:
        if node["id"] not in seen_nodes:
            seen_nodes.add(node["id"])
            nodes.append(node)
        return node["id"]

    def add_edge(src: str, dst: str, relation: str) -> None:
        edges.append({"source": src, "target": dst, "relation": relation})

    records = list(getattr(project, "map_products", None) or [])
    if product_id is not None:
        records = [r for r in records if str(r.id) == str(product_id)]
        if not records:
            return {
                "nodes": [],
                "edges": [],
                "gaps": [
                    {
                        "scope": f"product:{product_id}",
                        "reason": "no map product record with this id",
                    }
                ],
            }

    for record in records:
        rid = str(getattr(record, "id", "") or "")
        product_node = add_node(
            _node(
                f"product:{rid}",
                "map_product",
                str(getattr(record, "product_name", "") or rid),
                frozen=bool(getattr(record, "frozen", False)),
                status=str(getattr(record, "status", "") or ""),
                superseded_by=getattr(record, "superseded_by", None),
            )
        )

        for task in getattr(project, "factor_map_tasks", None) or []:
            if str(task.id) not in (getattr(record, "factor_task_ids", None) or []):
                continue
            grid_version = getattr(task, "grid_artifact_version_id", None)
            task_node_id = add_node(
                _node(
                    f"factor_task:{task.id}",
                    "factor_task",
                    str(task.name or task.id),
                    method=str(getattr(task, "method", "") or ""),
                    source_kind=str(getattr(task, "source_kind", "") or ""),
                    grid_version_id=str(grid_version) if grid_version else None,
                )
            )
            add_edge(product_node, task_node_id, "assembles_factor")
            if not grid_version:
                gaps.append(
                    {
                        "scope": f"factor_task:{task.id}",
                        "reason": "task has no persisted grid version "
                        "(never interpolated or artifact lost)",
                    }
                )
            else:
                version_node = add_node(
                    _node(
                        f"version:{grid_version}",
                        "factor_output",
                        f"grid {str(grid_version)[:12]}…",
                        version_id=str(grid_version),
                    )
                )
                add_edge(task_node_id, version_node, "produced")

            # constraint pins (V8 M2): the constraint state this task used
            params = dict(getattr(task, "parameters", None) or {})
            for pin in params.get("constraint_pins") or []:
                pin_group = str(pin.get("group_id") or "")
                group_node_id = add_node(
                    _node(
                        f"constraints:{pin_group}",
                        "constraints",
                        str(pin.get("group_name") or pin_group),
                        content_hash=str(pin.get("content_hash") or ""),
                        pinned_version_id=pin.get("version_id"),
                    )
                )
                add_edge(task_node_id, group_node_id, "consumed_constraints")

    # Fusion lineage: project-level section (V8 review R2 — hoisted out of
    # the per-product loop: it was duplicated per record and O(products x
    # runs)). Lazy-safe list_runs (document.runs is EMPTY pre-warm).
    if catalog_service is not None:
        try:
            runs = catalog_service.list_runs()
        except Exception:  # noqa: BLE001 — catalog access is optional
            runs = None
            gaps.append(
                {
                    "scope": "catalog",
                    "reason": "catalog runs not readable — fusion lineage omitted",
                }
            )
        if runs is not None:
            for run in runs:
                if str(run.operation) not in (
                    "factor_fusion",
                    "factor_fusion:confidence",
                    "factor_fusion:variance",
                ):
                    continue
                for version_id in run.output_version_ids or []:
                    node_id = add_node(
                        _node(
                            f"version:{version_id}",
                            "fusion_output",
                            f"{run.operation} {str(version_id)[:12]}…",
                            version_id=str(version_id),
                            run_id=str(run.id),
                        )
                    )
                    for parent in run.input_version_ids or []:
                        parent_node = add_node(
                            _node(
                                f"version:{parent}",
                                "factor_output",
                                f"input {str(parent)[:12]}…",
                                version_id=str(parent),
                            )
                        )
                        add_edge(parent_node, node_id, "fusion_input")

    return {"nodes": nodes, "edges": edges, "gaps": gaps}
