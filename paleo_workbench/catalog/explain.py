"""Explain service — "why does this file exist?" (V11 §15).

One service-level answer object assembled from catalog + domain + lineage so
UIs never stitch provenance themselves. Covers the question set:

- What generated it? (producing run: operation/generator/model/parameters)
- Which inputs? (typed ports when present, flat ids otherwise)
- Which well/survey? (entity links over the owning asset)
- Which downstream results use it?
- Can I delete it? (cleanup eligibility)
- Can it be regenerated? (producing run present)
- Is it stale? (impact service, pinned-aware)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from paleo_workbench.catalog.service import DataCatalogService


@dataclass
class VersionExplanation:
    version_id: str
    asset_id: str
    asset_name: str = ""
    asset_type: str = ""
    stage: str = ""
    bundle: bool = False
    member_count: int = 0

    # provenance
    producing_run_id: str | None = None
    operation: str | None = None
    generator: str = ""
    model_ref: dict[str, Any] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    input_ports: list[dict[str, Any]] = field(default_factory=list)
    output_ports: list[dict[str, Any]] = field(default_factory=list)
    parent_version_ids: list[str] = field(default_factory=list)
    typed_lineage: bool = False  # False = anonymous ports (legacy run)

    # entity context
    entities: list[dict[str, str]] = field(default_factory=list)

    # usage
    downstream_version_ids: list[str] = field(default_factory=list)
    downstream_run_ids: list[str] = field(default_factory=list)

    # lifecycle answers
    deletable: bool = True
    delete_blockers: list[str] = field(default_factory=list)
    regenerable: bool = False
    stale: bool = False
    stale_reason: str = ""
    pinned: bool = False
    integrity_status: str = "unknown"


class ExplainService:
    """Read-only composition over catalog + impact + domain links."""

    def __init__(self, service: "DataCatalogService"):
        self._service = service

    def explain_version(
        self, version_id: str, *, project: Any = None
    ) -> VersionExplanation:
        service = self._service
        version = service.get_version(version_id)
        asset = service.get_asset(version.asset_id)
        explanation = VersionExplanation(
            version_id=version.id,
            asset_id=asset.id,
            asset_name=asset.name,
            asset_type=asset.type,
            stage=version.stage.value,
            bundle=bool(version.members),
            member_count=len(version.members),
            created_at=version.created_at,
            parent_version_ids=list(version.parent_version_ids),
            pinned=service.is_pinned(version_id),
        )
        maps = service._ensure_maps()

        # --- provenance ------------------------------------------------
        run = maps.run_by_id.get(version.run_id) if version.run_id else None
        if run is not None:
            explanation.producing_run_id = run.id
            explanation.operation = run.operation
            explanation.generator = run.generator
            explanation.model_ref = run.model_ref
            explanation.parameters = dict(run.parameters)
            ports = service.ports_for_run(run.id)
            explanation.typed_lineage = bool(run.input_ports or run.output_ports)
            explanation.input_ports = [p.model_dump() for p in ports["input"]]
            explanation.output_ports = [p.model_dump() for p in ports["output"]]
        explanation.regenerable = run is not None

        # --- upstream closure (entity context + dependency view) ----------
        from paleo_workbench.catalog.impact import ImpactService

        impact = ImpactService(service)
        upstream = impact.upstream_impact(version_id)

        # --- entity context ---------------------------------------------
        if project is not None:
            from paleo_workbench.project.domain import entity_ids_for_asset

            seen_entities: set[tuple[str, str]] = set()
            # Own asset first, then the ancestor closure's assets: results
            # usually carry no direct link — their wells/surveys answer
            # through lineage (goal §15 "which well/survey?").
            ancestor_assets = list(upstream.ancestor_asset_ids)
            if version.asset_id not in ancestor_assets:
                ancestor_assets.append(version.asset_id)
            for related_asset_id in ancestor_assets:
                for entity_type, entity_id in entity_ids_for_asset(
                    project, related_asset_id
                ):
                    if (entity_type, entity_id) not in seen_entities:
                        seen_entities.add((entity_type, entity_id))
                        explanation.entities.append(
                            {"entity_type": entity_type, "entity_id": entity_id}
                        )

        # --- downstream usage --------------------------------------------
        for run_iter in maps.run_by_id.values():
            if version.id in run_iter.input_version_ids:
                explanation.downstream_run_ids.append(run_iter.id)
                explanation.downstream_version_ids.extend(
                    vid for vid in run_iter.output_version_ids
                    if vid != version.id and vid not in explanation.downstream_version_ids
                )
        for child in maps.children_by_parent.get(version.id, ()):
            if child.id not in explanation.downstream_version_ids:
                explanation.downstream_version_ids.append(child.id)

        # --- lifecycle answers --------------------------------------------
        eligibility = service.cleanup_eligibility(version_id)
        explanation.deletable = eligibility["eligible"]
        explanation.delete_blockers = eligibility["blockers"]

        # staleness of THIS version (is it built on evolved inputs?)
        stale, stale_reason = impact.is_stale(version_id)
        if stale:
            explanation.stale = True
            explanation.stale_reason = stale_reason + (
                "该下游版本被 pin 固定在旧输入。" if explanation.pinned else "建议重算。"
            )
        return explanation

    def explain_asset(self, asset_id: str, *, project: Any = None) -> dict[str, Any]:
        """Asset-level rollup: current version explanation + version count +
        role bindings across entities."""
        service = self._service
        asset = service.get_asset(asset_id)
        versions = service.list_versions(asset_id)
        current_id = asset.current_version_id or (versions[-1].id if versions else None)
        current_explanation = (
            self.explain_version(current_id, project=project)
            if current_id else None
        )
        roles: list[dict[str, Any]] = []
        if project is not None:
            from paleo_workbench.project.domain import links_for_asset

            for link in links_for_asset(project, asset_id):
                roles.append(
                    {
                        "entity_type": link.entity_type,
                        "entity_id": link.entity_id,
                        "role": link.role,
                        "is_primary": link.is_primary,
                        "unresolved": link.unresolved,
                    }
                )
        return {
            "asset_id": asset.id,
            "name": asset.name,
            "type": asset.type,
            "version_count": len(versions),
            "current_version_id": current_id,
            "current": (
                current_explanation.__dict__ if current_explanation else None
            ),
            "roles": roles,
            "trashed": asset.trashed,
        }
