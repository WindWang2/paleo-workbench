"""Dependency impact & staleness service (V11 §11 / docs 07-staleness.md).

Answers, over the catalog lineage graph:

- *downstream staleness* — which derived/intermediate/output versions were
  built on inputs that have since evolved (direct vs transitive), with the
  nearest changed ancestor explaining WHY;
- *upstream impact* — everything a given version depends on;
- *delete impact* — what breaks (lineage-wise) if a version/asset goes away;
- *entity staleness* — the same staleness question scoped to one well/survey.

Rules shared with ``workflow/freshness.py`` (its "current selection" view is
unchanged): staleness is NEVER written back to versions — it is recomputed
from lineage + asset current-version pointers on every query. Pinned
downstreams are reported but classified ``pinned`` (a decision, not an
error). Trashed ancestors make live downstreams stale (``reason`` says so).
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from paleo_workbench.catalog.service import DataCatalogService

# Hard bounds keeping pathological graphs from becoming unbounded walks
# (docs/development/data-fabric-v11/11-scale.md). Results exceeding the node
# budget are truncated and flagged, never silently cut.
MAX_IMPACT_NODES = 20_000
MAX_STALE_ITEMS = 2_000

_STALE_CACHE_MAX = 8
_STALE_CACHE: "OrderedDict[tuple, tuple[Any, list['StaleItem']]]" = OrderedDict()


@dataclass
class StaleItem:
    """One stale downstream version and why."""

    version_id: str
    asset_id: str
    direct: bool
    via_run_id: str | None = None
    nearest_changed_ancestor: tuple[str, str, str] | None = None
    # (asset_id, old_version_id, current_version_id)
    reason: str = ""
    pinned: bool = False
    reproducible: bool = False
    stage: str = ""
    trashed: bool = False

    @property
    def classification(self) -> str:
        """``stale`` (needs attention) vs ``pinned`` (known, accepted)."""
        return "pinned" if self.pinned else "stale"


@dataclass
class UpstreamImpact:
    """Everything a version depends on (its ancestor closure)."""

    version_id: str
    ancestor_version_ids: list[str] = field(default_factory=list)
    ancestor_asset_ids: list[str] = field(default_factory=list)
    runs_involved: list[str] = field(default_factory=list)
    missing_ancestors: list[str] = field(default_factory=list)  # referenced, unknown
    trashed_ancestors: list[str] = field(default_factory=list)


@dataclass
class DeleteImpact:
    """What breaks when a version (or a whole asset) disappears."""

    target_version_ids: list[str] = field(default_factory=list)
    target_asset_ids: list[str] = field(default_factory=list)
    live_descendants: list[StaleItem] = field(default_factory=list)
    runs_consuming: list[str] = field(default_factory=list)
    runs_producing: list[str] = field(default_factory=list)
    linked_entities: list[tuple[str, str]] = field(default_factory=list)
    broken_lineage_edges: int = 0
    cascade_advice: list[str] = field(default_factory=list)


class ImpactService:
    """Read-only graph queries over catalog lineage; no second storage."""

    def __init__(self, service: "DataCatalogService"):
        self._service = service

    # ------------------------------------------------------------------
    # staleness
    # ------------------------------------------------------------------

    def downstream_stale(
        self,
        changed_version_ids: Iterable[str] | None = None,
        *,
        include_trashed: bool = False,
    ) -> list[StaleItem]:
        """All live downstream versions whose inputs evolved past them.

        With *changed_version_ids* (hypothetical mode) those versions are
        additionally treated as superseded even if they are still current —
        the caller asks "if these change, what becomes stale".
        """
        changed = {str(v) for v in changed_version_ids or ()}
        service = self._service
        cache_key = None
        try:
            serial = int(getattr(service, "mutation_serial", 0) or 0)
            revision = service.document.catalog_revision
            cache_key = (
                id(service.document), revision, serial,
                tuple(sorted(changed))[:64], include_trashed,
            )
            hit = _STALE_CACHE.get(cache_key)
            if hit is not None and hit[0] is service.document:
                return list(hit[1])
        except Exception:
            cache_key = None

        maps = service._ensure_maps()
        version_by_id = maps.version_by_id
        children_by_parent = maps.children_by_parent
        asset_by_id = maps.asset_by_id

        # Candidates: descendants of the trigger set. Without an explicit
        # trigger set, the triggers are every non-current version of every
        # multi-version asset (the "state" triggers).
        triggers: set[str] = set(changed)
        if not changed:
            for asset in asset_by_id.values():
                current = asset.current_version_id
                versions = maps.versions_by_asset.get(asset.id, ())
                if current is not None and len(versions) > 1:
                    for version in versions:
                        if version.id != current:
                            triggers.add(version.id)
                # A trashed ancestor is always a trigger: its live descendants
                # are built on an input that went to the recycle bin (whether
                # or not a successor version exists).
                for version in versions:
                    if version.trashed:
                        triggers.add(version.id)
        if not triggers:
            return []

        # Descendant closure over children edges, breadth-first with a node
        # budget; depth bookkeeping distinguishes direct (depth 1) from
        # transitive downstream.
        depth: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque()
        for trigger in triggers:
            if trigger not in depth:
                depth[trigger] = 0
                queue.append((trigger, 0))
        walked = 0
        truncated = False
        while queue:
            node, d = queue.popleft()
            for child in children_by_parent.get(node, ()):
                if child.id in depth:
                    continue
                walked += 1
                if walked > MAX_IMPACT_NODES:
                    truncated = True
                    break
                depth[child.id] = d + 1
                queue.append((child.id, d + 1))
            if truncated:
                break

        items: list[StaleItem] = []
        for version_id, d in depth.items():
            if d == 0:
                continue  # the trigger versions themselves
            version = version_by_id.get(version_id)
            if version is None:
                continue
            if version.trashed and not include_trashed:
                continue
            nearest = self._nearest_changed_ancestor(
                version_id, version_by_id, children_by_parent, asset_by_id, triggers
            )
            if nearest is None:
                continue
            asset_id, old_id, current_id = nearest
            run = maps.run_by_id.get(version.run_id) if version.run_id else None
            pinned = bool(
                isinstance(version.metadata.get("pin"), dict)
                and version.metadata["pin"]
            )
            old_version = version_by_id.get(old_id)
            reason_trashed = old_version is not None and old_version.trashed
            if reason_trashed:
                reason = (
                    f"上游 {asset_id} 的版本 {old_id} 已被删除（回收站），"
                    f"本版本基于该输入"
                )
            else:
                reason = (
                    f"上游 {asset_id} 已从 {old_id} 演进到 {current_id}，"
                    f"本版本仍基于旧输入"
                )
            items.append(
                StaleItem(
                    version_id=version_id,
                    asset_id=version.asset_id,
                    direct=d == 1,
                    via_run_id=version.run_id,
                    nearest_changed_ancestor=nearest,
                    reason=reason,
                    pinned=pinned,
                    reproducible=run is not None,
                    stage=version.stage.value,
                    trashed=version.trashed,
                )
            )
            if len(items) >= MAX_STALE_ITEMS:
                truncated = True
                break
        items.sort(key=lambda item: (not item.direct, item.version_id))
        if truncated and items:
            items[-1].reason += "（结果已截断：影响面超出节点上限）"
        if cache_key is not None:
            _STALE_CACHE[cache_key] = (service.document, items)
            _STALE_CACHE.move_to_end(cache_key)
            while len(_STALE_CACHE) > _STALE_CACHE_MAX:
                _STALE_CACHE.popitem(last=False)
        return list(items)

    def _nearest_changed_ancestor(
        self,
        version_id: str,
        version_by_id: dict,
        children_by_parent: dict,
        asset_by_id: dict,
        triggers: set[str],
    ) -> tuple[str, str, str] | None:
        """BFS up the parent chain for the closest evolved/trashed ancestor.

        Returns ``(asset_id, old_version_id, current_version_id)`` — the
        current id equals the old one when the evolution is "trashed"
        (the ancestor went to the recycle bin rather than being superseded).
        """
        best: tuple[int, tuple[str, str, str]] | None = None
        visited = {version_id}
        queue: deque[tuple[str, int]] = deque([(version_id, 0)])
        while queue:
            node, d = queue.popleft()
            version = version_by_id.get(node)
            if version is None:
                continue
            for parent_id in version.parent_version_ids:
                if parent_id in visited:
                    continue
                visited.add(parent_id)
                parent = version_by_id.get(parent_id)
                if parent is None:
                    continue
                if parent.trashed:
                    candidate = (d + 1, (parent.asset_id, parent_id, parent_id))
                    if best is None or candidate[0] < best[0]:
                        best = candidate
                    continue  # keep walking for a possibly nearer trigger
                asset = asset_by_id.get(parent.asset_id)
                current = asset.current_version_id if asset else None
                evolved = (
                    current is not None
                    and current != parent_id
                    and not (asset.trashed if asset else False)
                )
                if evolved or parent_id in triggers:
                    current_ref = current if current else parent_id
                    candidate = (d + 1, (parent.asset_id, parent_id, current_ref))
                    if best is None or candidate[0] < best[0]:
                        best = candidate
                    continue
                queue.append((parent_id, d + 1))
        return best[1] if best else None

    # ------------------------------------------------------------------
    # upstream / delete impact
    # ------------------------------------------------------------------

    def upstream_impact(self, version_id: str) -> UpstreamImpact:
        """The full ancestor closure of one version (its dependency set)."""
        maps = self._service._ensure_maps()
        version_by_id = maps.version_by_id
        impact = UpstreamImpact(version_id=version_id)
        seen = {version_id}
        queue = deque(version_by_id[version_id].parent_version_ids)
        seen.update(queue)
        runs: set[str] = set()
        while queue:
            node = queue.popleft()
            version = version_by_id.get(node)
            if version is None:
                impact.missing_ancestors.append(node)
                continue
            impact.ancestor_version_ids.append(node)
            impact.ancestor_asset_ids.append(version.asset_id)
            if version.run_id:
                runs.add(version.run_id)
            if version.trashed:
                impact.trashed_ancestors.append(node)
            for parent in version.parent_version_ids:
                if parent not in seen:
                    seen.add(parent)
                    queue.append(parent)
        # runs that CONSUMED any ancestor (full provenance view)
        for run in maps.run_by_id.values():
            if run.id in runs:
                continue
            if any(v in seen for v in run.input_version_ids):
                runs.add(run.id)
        impact.runs_involved = sorted(runs)
        impact.ancestor_version_ids = sorted(set(impact.ancestor_version_ids))
        impact.ancestor_asset_ids = sorted(set(impact.ancestor_asset_ids))
        return impact

    def delete_impact(
        self,
        *,
        version_id: str | None = None,
        asset_id: str | None = None,
        project: Any = None,
    ) -> DeleteImpact:
        """What breaks (lineage-wise) if a version or asset is removed.

        The report is informational — deletion itself goes through the
        catalog trash flow, which keeps runs as historical provenance. This
        answers "what should I recompute or pin first".
        """
        maps = self._service._ensure_maps()
        version_by_id = maps.version_by_id
        impact = DeleteImpact()
        if version_id is not None:
            impact.target_version_ids = [version_id]
            version = version_by_id.get(version_id)
            if version is not None:
                impact.target_asset_ids = [version.asset_id]
        elif asset_id is not None:
            impact.target_asset_ids = [asset_id]
            impact.target_version_ids = [
                v.id for v in maps.versions_by_asset.get(asset_id, ())
            ]
        target_set = set(impact.target_version_ids)

        # Descendants of any target version become lineage-broken.
        depth: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((t, 0) for t in target_set)
        for t in target_set:
            depth[t] = 0
        broken_edges = 0
        while queue:
            node, d = queue.popleft()
            for child in maps.children_by_parent.get(node, ()):
                broken_edges += 1 if child.id not in depth else 0
                if child.id in depth:
                    continue
                depth[child.id] = d + 1
                queue.append((child.id, d + 1))
        for vid, d in depth.items():
            if d == 0:
                continue
            version = version_by_id.get(vid)
            if version is None or (version.trashed and vid not in target_set):
                continue
            pinned = bool(
                isinstance(version.metadata.get("pin"), dict)
                and version.metadata["pin"]
            )
            run = maps.run_by_id.get(version.run_id) if version.run_id else None
            impact.live_descendants.append(
                StaleItem(
                    version_id=vid,
                    asset_id=version.asset_id,
                    direct=d == 1,
                    via_run_id=version.run_id,
                    reason=(
                        f"删除目标位于其上游依赖链（距离 {d}）"
                    ),
                    pinned=pinned,
                    reproducible=run is not None,
                    stage=version.stage.value,
                    trashed=version.trashed,
                )
            )
        impact.broken_lineage_edges = broken_edges

        for run in maps.run_by_id.values():
            if target_set & set(run.input_version_ids):
                impact.runs_consuming.append(run.id)
            if target_set & set(run.output_version_ids):
                impact.runs_producing.append(run.id)

        if project is not None:
            for link in getattr(project, "entity_asset_links", None) or ():
                if link.asset_id in set(impact.target_asset_ids) | target_set:
                    impact.linked_entities.append((link.entity_type, link.entity_id))

        non_pinned = [d for d in impact.live_descendants if not d.pinned]
        if non_pinned:
            impact.cascade_advice.append(
                f"{len(non_pinned)} 个下游成果将基于残缺 lineage：建议先重算或固定（pin）"
                "这些下游版本，再执行删除。"
            )
        pinned = [d for d in impact.live_descendants if d.pinned]
        if pinned:
            impact.cascade_advice.append(
                f"{len(pinned)} 个下游版本已 pin：删除不会改变其科学结论标记，"
                "但 lineage 解析将显示缺失上游。"
            )
        if impact.runs_consuming:
            impact.cascade_advice.append(
                f"{len(impact.runs_consuming)} 个 run 以其为输入（历史溯源保留，"
                "不阻塞删除）。"
            )
        return impact

    # ------------------------------------------------------------------
    # entity scoping
    # ------------------------------------------------------------------

    def entity_staleness(
        self, project: Any, entity_type: str, entity_id: str
    ) -> list[StaleItem]:
        """Staleness scoped to one well/survey: the stale items whose nearest
        changed ancestor belongs to an asset linked to the entity."""
        from paleo_workbench.project.domain import asset_ids_for_entity

        asset_ids = set(
            asset_ids_for_entity(project, entity_type, entity_id)
        )
        if not asset_ids:
            return []
        stale = self.downstream_stale()
        scoped: list[StaleItem] = []
        for item in stale:
            if item.nearest_changed_ancestor and item.nearest_changed_ancestor[0] in asset_ids:
                scoped.append(item)
        return scoped
