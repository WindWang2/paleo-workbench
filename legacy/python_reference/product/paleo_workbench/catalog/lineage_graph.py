"""Full-chain lineage walks over the canonical document (collaborator module).

Two read-only services used by :class:`DataCatalogService`:

- :func:`build_lineage_chain` — the recursive version→run→version chain from
  any version up to its RAW roots (or down to its descendants), as a tree of
  :class:`LineageChainNode` interleaved with producing-run info. This powers
  the Data Manager's 血缘 visualization: one call answers "which seismic /
  horizon / well inputs, through which runs, produced this output".
- :func:`compute_summaries` — per-version lineage status (hops to the nearest
  RAW ancestor, broken-parent flag) in one pass, memoized inside DFS so the
  diamond-heavy graphs stay cheap. Powers the table's 血缘 column.

Both walk the service's maintained id maps (rebuilt once per revision, not
per query) and are cycle-safe via visited sets.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.catalog.models import DataStage

DEFAULT_MAX_NODES = 5000


@dataclass
class LineageChainNode:
    """One version in the lineage tree plus its producing-run facts."""

    version_id: str
    asset_id: str
    asset_name: str
    stage: DataStage
    version_number: int
    depth: int  # hops from the start version
    managed: bool = True
    trashed: bool = False
    path: str = ""
    sha256: str | None = None
    created_at: str = ""
    tags: list[str] = field(default_factory=list)
    run_id: str | None = None
    run_operation: str | None = None
    run_status: str | None = None
    run_generator: str | None = None
    children: list["LineageChainNode"] = field(default_factory=list)


@dataclass
class LineageChain:
    """Result of :func:`build_lineage_chain`.

    ``root`` is the start version; ancestors mode expands ``children`` towards
    RAW inputs, descendants mode towards downstream products. ``truncated`` is
    True when the walk hit *max_depth* / *max_nodes* (the display should say
    so instead of implying the chain ends).
    """

    start_version_id: str
    direction: str  # "ancestors" | "descendants"
    root: LineageChainNode
    node_count: int = 1
    truncated: bool = False


def _version_tags(tag_by_id: dict[str, Any], version_tags: Any, version_id: str) -> list[str]:
    try:
        tag_ids = version_tags.get(version_id, [])
        return [
            tag_by_id[tid].display_name or tag_by_id[tid].name
            for tid in tag_ids
            if tid in tag_by_id
        ]
    except Exception:
        return []


def _make_node(
    maps: Any,
    tag_by_id: dict[str, Any],
    version_tags: Any,
    version: Any,
    depth: int,
) -> LineageChainNode:
    try:
        asset_name = maps.asset_by_id[version.asset_id].name
    except Exception:
        asset_name = version.asset_id
    run = maps.run_by_id.get(version.run_id) if version.run_id is not None else None
    return LineageChainNode(
        version_id=version.id,
        asset_id=version.asset_id,
        asset_name=asset_name,
        stage=version.stage,
        version_number=version.version_number,
        depth=depth,
        managed=version.managed,
        trashed=version.trashed,
        path=version.path,
        sha256=version.sha256,
        created_at=version.created_at or "",
        tags=_version_tags(tag_by_id, version_tags, version.id),
        run_id=version.run_id,
        run_operation=run.operation if run is not None else None,
        run_status=run.status if run is not None else None,
        run_generator=run.generator if run is not None else None,
    )


def build_lineage_chain(
    service: Any,
    version_id: str,
    *,
    direction: str = "ancestors",
    max_depth: int | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> LineageChain:
    """Walk the full lineage tree from *version_id* (cycle-safe).

    ``direction="ancestors"`` follows ``parent_version_ids`` towards RAW
    inputs; ``"descendants"`` follows the maintained child index towards
    downstream products. Because parents mirror run inputs (the adapter's
    ``_register_produced`` convention), the ancestor tree IS the
    version→run→input chain; each node carries its producing run for display.
    """
    if direction not in ("ancestors", "descendants"):
        raise ValueError(f"direction must be 'ancestors' or 'descendants', got {direction!r}")
    with service._lock:
        start = service._version_or_raise(version_id)
        maps = service._ensure_maps()
        by_id = maps.version_by_id
        children_index = maps.children_by_parent
        # One precomputed index set per traversal (#1059): rebuilding the tag
        # map per node cost O(V×T) and get_asset/get_run re-locked per lookup.
        tag_by_id = {t.id: t for t in service.document.tags}
        version_tags = service.document.version_tags

        root = _make_node(maps, tag_by_id, version_tags, start, 0)
        seen = {start.id}
        truncated = False
        queue = deque([root])
        while queue:
            node = queue.popleft()
            version = by_id.get(node.version_id)
            if version is None:
                continue
            if direction == "ancestors":
                next_ids: list[str] = list(version.parent_version_ids)
            else:
                next_ids = [v.id for v in children_index.get(node.version_id, ())]
            if max_depth is not None and node.depth >= max_depth:
                # Only a real truncation when there was more to expand.
                truncated = truncated or bool(next_ids)
                continue
            for next_id in next_ids:
                child_version = by_id.get(next_id)
                if child_version is None or next_id in seen:
                    continue  # dangling parents are audit findings, not tree nodes
                if len(seen) >= max_nodes:
                    truncated = True
                    break
                seen.add(next_id)
                child = _make_node(maps, tag_by_id, version_tags, child_version, node.depth + 1)
                node.children.append(child)
                queue.append(child)
        return LineageChain(
            start_version_id=start.id,
            direction=direction,
            root=root,
            node_count=len(seen),
            truncated=truncated,
        )


def compute_summaries(service: Any) -> dict[str, dict[str, Any]]:
    """Per-version lineage status in one pass:

    ``{"to_raw": int | None, "broken": bool, "has_parents": bool}`` where
    ``to_raw`` is the minimum hop count to a RAW ancestor (0 when the version
    itself is RAW; None when no RAW ancestor is reachable — e.g. an isolated
    derived registration) and ``broken`` flags dangling parent references.

    Iterative DFS with memoization; a cycle terminates at the visited set and
    reports the cycle member as unreachable-from-there (audit reports the
    cycle itself separately).
    """
    with service._lock:
        by_id = service._ensure_maps().version_by_id
        memo: dict[str, int | None] = {}
        broken: set[str] = set()
        has_parents: dict[str, bool] = {}

        def visit(start_id: str) -> int | None:
            # Iterative post-order DFS: (version_id, phase) with phase 0 =
            # enter, 1 = merge children.
            stack: list[tuple[str, int]] = [(start_id, 0)]
            on_path: set[str] = set()
            local_results: dict[str, int | None] = {}
            while stack:
                vid, phase = stack.pop()
                if vid in memo:
                    local_results[vid] = memo[vid]
                    continue
                version = by_id.get(vid)
                if version is None:
                    local_results[vid] = None
                    memo[vid] = None
                    continue
                if phase == 0:
                    if vid in on_path:
                        # Cycle: treat as no-path-through-here (audit reports it).
                        local_results[vid] = None
                        continue
                    if not version.parent_version_ids:
                        memo[vid] = 0 if version.stage == DataStage.RAW else None
                        local_results[vid] = memo[vid]
                        continue
                    on_path.add(vid)
                    stack.append((vid, 1))
                    for pid in version.parent_version_ids:
                        if pid not in by_id:
                            broken.add(vid)
                        stack.append((pid, 0))
                    continue
                # phase 1: children evaluated into local_results/memo
                on_path.discard(vid)
                best: int | None = None
                if version.stage == DataStage.RAW:
                    best = 0
                for pid in version.parent_version_ids:
                    child_depth = local_results.get(pid, memo.get(pid))
                    if child_depth is None:
                        continue
                    candidate = child_depth if version.stage == DataStage.RAW else child_depth + 1
                    best = candidate if best is None else min(best, candidate)
                memo[vid] = best
                local_results[vid] = best
            return local_results.get(start_id)

        summaries: dict[str, dict[str, Any]] = {}
        for version in service.document.versions:
            has_parents[version.id] = bool(version.parent_version_ids)
            visit(version.id)
        for version in service.document.versions:
            summaries[version.id] = {
                "to_raw": memo.get(version.id),
                "broken": version.id in broken,
                "has_parents": has_parents[version.id],
            }
        return summaries
