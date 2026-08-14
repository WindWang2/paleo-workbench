"""Lineage-derived dependency graph for scientific freshness (Stage 9).

Graph edges come only from catalog provenance:

    DataVersion  --input-->  DataRun  --output-->  DataVersion

Workflow page order is *not* scientific lineage. This module rebuilds a
runtime adjacency index from ``CatalogPort.list_runs()`` / versions; it does
not create a second persistent database.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from paleo_workbench.catalog.types import DataRunRef, DataVersionRef


class DependencyGraphError(RuntimeError):
    """Raised when the provenance graph is unusable (e.g. cycles)."""


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One directed edge: input version → run → output version."""

    source_version_id: str
    run_id: str
    target_version_id: str
    operation: str = ""


@dataclass
class DependencyGraph:
    """Runtime DAG built from catalog runs.

    Indexes (rebuildable, not persisted):

    * ``version_id → producing run_id``
    * ``version_id → dependent run ids`` (runs that list it as input)
    * ``run_id → input / output version ids``
    * ``version_id → asset_id``
    """

    runs: dict[str, DataRunRef] = field(default_factory=dict)
    versions: dict[str, DataVersionRef] = field(default_factory=dict)
    # version_id → run that produced it
    producing_run: dict[str, str] = field(default_factory=dict)
    # version_id → runs that consume it
    consumers: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    # run_id → input version ids / output version ids (mirrors run)
    run_inputs: dict[str, list[str]] = field(default_factory=dict)
    run_outputs: dict[str, list[str]] = field(default_factory=dict)
    # version_id → asset_id
    version_asset: dict[str, str] = field(default_factory=dict)
    # asset_id → all version ids for that asset (registration order)
    asset_versions: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    edges: list[GraphEdge] = field(default_factory=list)
    # Domain task bridge: domain_task_id → run_ids (newest last)
    domain_task_runs: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    cycle_nodes: frozenset[str] = field(default_factory=frozenset)
    _built: bool = False

    @classmethod
    def from_catalog(cls, catalog: Any) -> "DependencyGraph":
        """Build graph from a :class:`CatalogPort` (or duck-typed list APIs)."""
        graph = cls()
        graph.rebuild(catalog)
        return graph

    def rebuild(self, catalog: Any) -> None:
        """Rebuild all indexes from catalog listings. Safe to call repeatedly."""
        self.runs.clear()
        self.versions.clear()
        self.producing_run.clear()
        self.consumers = defaultdict(list)
        self.run_inputs.clear()
        self.run_outputs.clear()
        self.version_asset.clear()
        self.asset_versions = defaultdict(list)
        self.edges.clear()
        self.domain_task_runs = defaultdict(list)
        self.cycle_nodes = frozenset()

        versions: Sequence[DataVersionRef] = list(catalog.list_versions())
        runs: Sequence[DataRunRef] = list(catalog.list_runs())

        for ver in versions:
            self.versions[ver.version_id] = ver
            self.version_asset[ver.version_id] = ver.asset_id
            self.asset_versions[ver.asset_id].append(ver.version_id)
            if ver.producing_run_id:
                self.producing_run[ver.version_id] = ver.producing_run_id

        for run in runs:
            self.runs[run.run_id] = run
            inputs = list(run.input_version_ids or [])
            outputs = list(run.output_version_ids or [])
            self.run_inputs[run.run_id] = inputs
            self.run_outputs[run.run_id] = outputs
            for vid in inputs:
                self.consumers[vid].append(run.run_id)
            for vid in outputs:
                self.producing_run.setdefault(vid, run.run_id)
            if run.domain_task_id:
                self.domain_task_runs[run.domain_task_id].append(run.run_id)
            for in_vid in inputs:
                for out_vid in outputs:
                    self.edges.append(
                        GraphEdge(
                            source_version_id=in_vid,
                            run_id=run.run_id,
                            target_version_id=out_vid,
                            operation=run.operation or "",
                        )
                    )

        self.cycle_nodes = frozenset(self._detect_cycle_nodes())
        self._built = True

    def _detect_cycle_nodes(self) -> set[str]:
        """Detect cycles on the version→version graph (iterative DFS).

        Self-loops are collected like any other cycle (no early return that
        would mask additional cycles elsewhere in the graph).
        """
        adj: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            adj[edge.source_version_id].append(edge.target_version_id)

        # Deduplicate adjacency lists
        adj = {k: list(dict.fromkeys(v)) for k, v in adj.items()}

        WHITE, GRAY, BLACK = 0, 1, 2
        nodes: set[str] = set(self.versions)
        nodes.update(adj.keys())
        for targets in adj.values():
            nodes.update(targets)
        color: dict[str, int] = {n: WHITE for n in nodes}
        cycle: set[str] = set()

        for start in nodes:
            if color[start] != WHITE:
                continue
            # stack entries: (node, next_child_index)
            stack: list[tuple[str, int]] = [(start, 0)]
            color[start] = GRAY
            while stack:
                node, idx = stack[-1]
                children = adj.get(node, ())
                if idx < len(children):
                    stack[-1] = (node, idx + 1)
                    nxt = children[idx]
                    c = color.get(nxt, WHITE)
                    if c == GRAY:
                        cycle.add(node)
                        cycle.add(nxt)
                    elif c == WHITE:
                        color[nxt] = GRAY
                        stack.append((nxt, 0))
                else:
                    color[node] = BLACK
                    stack.pop()
        return cycle

    def has_cycle(self) -> bool:
        return bool(self.cycle_nodes)

    def asset_id_for(self, version_id: str) -> str | None:
        if version_id in self.version_asset:
            return self.version_asset[version_id]
        ver = self.versions.get(version_id)
        return ver.asset_id if ver is not None else None

    def direct_downstream_runs(self, version_id: str) -> list[DataRunRef]:
        """Runs that declare *version_id* as an input."""
        return [
            self.runs[rid]
            for rid in self.consumers.get(version_id, ())
            if rid in self.runs
        ]

    def transitive_downstream_runs(
        self, version_ids: Iterable[str], *, max_nodes: int = 100_000
    ) -> list[DataRunRef]:
        """BFS: all runs reachable by consuming outputs of prior runs.

        Starts from *version_ids* as roots. If a cycle is present, traversal
        still terminates via visited sets and reports cycle membership on the
        graph object (``has_cycle`` / ``cycle_nodes``).
        """
        roots = [v for v in version_ids if v]
        if not roots:
            return []
        visited_versions: set[str] = set()
        visited_runs: set[str] = set()
        ordered: list[DataRunRef] = []
        q: deque[str] = deque(roots)
        steps = 0
        while q:
            steps += 1
            if steps > max_nodes:
                break
            vid = q.popleft()
            if vid in visited_versions:
                continue
            visited_versions.add(vid)
            for rid in self.consumers.get(vid, ()):
                if rid in visited_runs:
                    continue
                visited_runs.add(rid)
                run = self.runs.get(rid)
                if run is None:
                    continue
                ordered.append(run)
                for out_vid in self.run_outputs.get(rid, ()):
                    if out_vid not in visited_versions:
                        q.append(out_vid)
        return ordered

    def transitive_downstream_versions(
        self, version_ids: Iterable[str]
    ) -> list[str]:
        """Output version ids of all transitive downstream runs (topo-ish BFS order)."""
        out: list[str] = []
        seen: set[str] = set()
        for run in self.transitive_downstream_runs(version_ids):
            for vid in self.run_outputs.get(run.run_id, ()):
                if vid not in seen:
                    seen.add(vid)
                    out.append(vid)
        return out

    def latest_run_for_domain_task(self, domain_task_id: str) -> DataRunRef | None:
        ids = self.domain_task_runs.get(domain_task_id) or []
        if not ids:
            return None
        return self.runs.get(ids[-1])

    def find_reuse_run(
        self,
        *,
        operation: str,
        input_version_ids: Sequence[str],
        generator_version: str | None = None,
        input_snapshot_hash: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        require_outputs: bool = True,
    ) -> DataRunRef | None:
        """Find a completed run with the same scientific identity (provenance reuse)."""
        wanted_inputs = list(input_version_ids)
        wanted_params = dict(parameters or {})
        for run in reversed(list(self.runs.values())):
            if run.operation != operation:
                continue
            if run.status not in {"complete", "completed"}:
                continue
            if list(run.input_version_ids or []) != wanted_inputs:
                continue
            if generator_version is not None and (run.generator_version or "") != (
                generator_version or ""
            ):
                continue
            if input_snapshot_hash is not None and (
                run.input_snapshot_hash or ""
            ) != (input_snapshot_hash or ""):
                continue
            if wanted_params:
                # Only compare keys the caller cares about.
                run_params = dict(run.parameters or {})
                if any(run_params.get(k) != v for k, v in wanted_params.items()):
                    continue
            if require_outputs and not (run.output_version_ids or []):
                continue
            return run
        return None

    def topological_runs(self, run_ids: Iterable[str]) -> list[DataRunRef]:
        """Order *run_ids* so producers come before consumers.

        Uses version edges between runs. Raises :class:`DependencyGraphError`
        only when the *requested subset* contains a cycle; global cycles that
        do not involve the subset are ignored.
        """
        wanted = {rid for rid in run_ids if rid in self.runs}
        if not wanted:
            return []

        # Edge A→B means A produces a version that B consumes.
        adj: dict[str, set[str]] = defaultdict(set)
        indeg: dict[str, int] = {rid: 0 for rid in wanted}
        for rid in wanted:
            for out_vid in self.run_outputs.get(rid, ()):
                for consumer in self.consumers.get(out_vid, ()):
                    if consumer in wanted and consumer != rid:
                        if consumer not in adj[rid]:
                            adj[rid].add(consumer)
                            indeg[consumer] = indeg.get(consumer, 0) + 1

        # Synthetic domain edges: a map_compile consuming a prediction task's
        # product must run AFTER that prediction run even when the version
        # edge is absent (in-memory prediction results, H11 ordering). Bind to
        # the LATEST run of the task deterministically (a set iteration order
        # would pick arbitrarily across processes). Guarded by reachability so
        # we never introduce a cycle.
        by_domain: dict[str, list[str]] = {}
        for rid in wanted:
            run = self.runs[rid]
            if run.domain_task_id:
                by_domain.setdefault(run.domain_task_id, []).append(rid)
        latest_by_domain: dict[str, str] = {}
        for tid, rids in by_domain.items():
            latest_by_domain[tid] = max(
                rids,
                key=lambda rid: (
                    getattr(self.runs[rid], "started_at", "") or "",
                    rid,
                ),
            )
        synthetic: list[tuple[str, str]] = []
        for rid in wanted:
            run = self.runs[rid]
            if run.operation != "map_compile":
                continue
            params = run.parameters or {}
            linked = str(params.get("linked_prediction_task_id") or "")
            source_ids = [str(s) for s in (params.get("source_task_ids") or [])]
            for tid in ([linked] if linked else []) + source_ids:
                prod_rid = latest_by_domain.get(tid)
                if prod_rid is None or prod_rid == rid or prod_rid not in wanted:
                    continue
                if not _reachable(adj, rid, prod_rid):
                    synthetic.append((prod_rid, rid))
        for src, dst in synthetic:
            if dst not in adj[src]:
                adj[src].add(dst)
                indeg[dst] = indeg.get(dst, 0) + 1

        q = deque(sorted(rid for rid, d in indeg.items() if d == 0))
        ordered: list[DataRunRef] = []
        while q:
            rid = q.popleft()
            ordered.append(self.runs[rid])
            for nxt in sorted(adj.get(rid, ())):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    q.append(nxt)
        if len(ordered) != len(wanted):
            raise DependencyGraphError(
                "cycle detected in recompute subset; cannot topologically order plan"
            )
        return ordered


def _reachable(adj: dict[str, set[str]], src: str, dst: str) -> bool:
    """True when *dst* is reachable from *src* via directed edges."""
    if src == dst:
        return True
    seen = {src}
    stack = [src]
    while stack:
        node = stack.pop()
        for nxt in adj.get(node, ()):
            if nxt == dst:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False
