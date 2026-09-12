"""Entity data views — query facade over project domain + catalog (V11 §6.2).

``EntityViewService`` assembles WellDataView / SurveyDataView snapshots from
the two existing authorities (ProjectDocument entities/links + catalog
assets/versions). It owns NO storage of its own — every query reads through
to the authorities (docs/development/data-fabric-v11/02 D5), so there is no
second canonical copy to drift.

Scale contract (11-scale): the well index is assembled from ``project.wells``
(≤10k) plus in-memory link aggregation — never ``list_assets()``. Expanding
one well issues batched point lookups only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from paleo_workbench.project.roles import (
    role_definition,
    roles_for_entity_type,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from paleo_workbench.catalog.service import DataCatalogService


@dataclass
class AssetSummary:
    """Lightweight asset view entry (identity + current version pointer)."""

    asset_id: str
    name: str
    type: str
    role: str
    is_primary: bool
    ordinal: int
    unresolved: bool
    current_version_id: str | None
    version_count: int
    trashed: bool
    stage: str = ""
    format: str = ""
    bundle: bool = False


@dataclass
class RoleSlot:
    """All assets bound to one (entity, role) pair, primary first."""

    role: str
    display: str
    members: list[AssetSummary] = field(default_factory=list)
    unresolved: list[AssetSummary] = field(default_factory=list)

    @property
    def primary(self) -> AssetSummary | None:
        for member in self.members:
            if member.is_primary:
                return member
        return self.members[0] if self.members else None


@dataclass
class WorkingCopyLite:
    working_id: str
    source_version_id: str
    path: str
    state: str
    dirty_hint: bool


@dataclass
class WellDataView:
    well: Any  # WellEntity (kept untyped: no project dependency here)
    slots: dict[str, RoleSlot]
    stale_count: int = 0
    stale_items: list[Any] = field(default_factory=list)
    missing_source_asset_ids: list[str] = field(default_factory=list)
    uncommitted_edits: list[WorkingCopyLite] = field(default_factory=list)


@dataclass
class SurveyDataView:
    survey: Any
    slots: dict[str, RoleSlot]
    stale_count: int = 0
    stale_items: list[Any] = field(default_factory=list)
    # Status fields shared with WellDataView so the detail panel can render
    # both shapes uniformly (defaults keep survey views cheap).
    missing_source_asset_ids: list[str] = field(default_factory=list)
    uncommitted_edits: list[WorkingCopyLite] = field(default_factory=list)


@dataclass
class WellIndexEntry:
    """One row of the light well index (tree root layer)."""

    well_id: str
    name: str
    uwi: str
    role_fill: dict[str, int]  # role -> linked live asset count
    unresolved_count: int = 0
    stale_count: int = 0


class EntityViewService:
    """Read-only view assembly; constructed per project open, cheap."""

    def __init__(self, service: "DataCatalogService", project: Any):
        self._service = service
        self._project = project
        self._impact = None  # lazy; impact import is heavier

    # ------------------------------------------------------------------
    # index (tree root)
    # ------------------------------------------------------------------

    def well_index(self, *, with_stale: bool = False) -> list[WellIndexEntry]:
        """One light entry per well — O(W) over wells + links, no catalog
        full-materialization."""
        wells = list(getattr(self._project, "wells", None) or ())
        links = list(getattr(self._project, "entity_asset_links", None) or ())
        # Link counting is live-only by construction: the trash flow removes
        # entity links when it removes the asset.
        per_well: dict[str, dict[str, int]] = {w.id: {} for w in wells}
        unresolved: dict[str, int] = {w.id: 0 for w in wells}
        for link in links:
            if link.entity_type != "well":
                continue
            counts = per_well.get(link.entity_id)
            if counts is None:
                continue
            counts[link.role] = counts.get(link.role, 0) + 1
            if link.unresolved:
                unresolved[link.entity_id] += 1
        stale_counts: dict[str, int] = {}
        if with_stale:
            impact = self._impact_service()
            for item in impact.downstream_stale():
                if item.nearest_changed_ancestor:
                    stale_counts[item.nearest_changed_ancestor[0]] = stale_counts.get(
                        item.nearest_changed_ancestor[0], 0
                    ) + 1
            # map stale (by asset) back onto wells via links
            asset_to_wells: dict[str, list[str]] = {}
            for link in links:
                if link.entity_type == "well":
                    asset_to_wells.setdefault(link.asset_id, []).append(link.entity_id)
            stale_per_well: dict[str, int] = {}
            for asset_id, count in stale_counts.items():
                for well_id in asset_to_wells.get(asset_id, ()):
                    stale_per_well[well_id] = stale_per_well.get(well_id, 0) + count
            stale_counts = stale_per_well
        return [
            WellIndexEntry(
                well_id=well.id,
                name=well.name,
                uwi=getattr(well, "uwi", "") or "",
                role_fill=per_well.get(well.id, {}),
                unresolved_count=unresolved.get(well.id, 0),
                stale_count=stale_counts.get(well.id, 0),
            )
            for well in wells
        ]

    def survey_index(self) -> list[WellIndexEntry]:
        surveys = list(getattr(self._project, "seismic_surveys", None) or ())
        per_survey: dict[str, dict[str, int]] = {s.id: {} for s in surveys}
        for link in getattr(self._project, "entity_asset_links", None) or ():
            if link.entity_type != "seismic_survey":
                continue
            counts = per_survey.get(link.entity_id)
            if counts is None:
                continue
            counts[link.role] = counts.get(link.role, 0) + 1
        return [
            WellIndexEntry(
                well_id=survey.id,
                name=survey.name,
                uwi="",
                role_fill=per_survey.get(survey.id, {}),
            )
            for survey in surveys
        ]

    # ------------------------------------------------------------------
    # per-entity views
    # ------------------------------------------------------------------

    def well_view(self, well_id: str, *, with_stale: bool = False) -> WellDataView | None:
        well = next(
            (w for w in getattr(self._project, "wells", None) or () if w.id == well_id),
            None,
        )
        if well is None:
            return None
        slots = self._slots_for_entity("well", well_id)
        view = WellDataView(well=well, slots=slots)
        self._attach_status(
            [m for slot in slots.values() for m in slot.members],
            view,
            with_stale=with_stale,
            entity_type="well",
            entity_id=well_id,
        )
        return view

    def survey_view(self, survey_id: str, *, with_stale: bool = False) -> SurveyDataView | None:
        survey = next(
            (
                s
                for s in getattr(self._project, "seismic_surveys", None) or ()
                if s.id == survey_id
            ),
            None,
        )
        if survey is None:
            return None
        slots = self._slots_for_entity("seismic_survey", survey_id)
        view = SurveyDataView(survey=survey, slots=slots)
        self._attach_status(
            [m for slot in slots.values() for m in slot.members],
            view,
            with_stale=with_stale,
            entity_type="seismic_survey",
            entity_id=survey_id,
        )
        return view

    def _slots_for_entity(self, entity_type: str, entity_id: str) -> dict[str, RoleSlot]:
        vocabulary = roles_for_entity_type(entity_type)
        slots: dict[str, RoleSlot] = {
            role: RoleSlot(role=role, display=role_definition(role).display)
            for role in vocabulary
        }
        links = [
            link
            for link in getattr(self._project, "entity_asset_links", None) or ()
            if link.entity_type == entity_type and link.entity_id == entity_id
        ]
        asset_ids = []
        for link in links:
            if link.asset_id not in asset_ids:
                asset_ids.append(link.asset_id)
        models = (
            {a.id: a for a in self._service.resolve_asset_models(asset_ids)}
            if asset_ids else {}
        )
        maps = self._service._ensure_maps()
        for link in links:
            slot = slots.get(link.role)
            if slot is None:
                # Unknown role (foreign vocabulary): visible, grouped under
                # a synthetic slot instead of being dropped silently.
                slot = slots.setdefault(
                    link.role,
                    RoleSlot(
                        role=link.role,
                        display=role_definition(link.role).display or link.role,
                    ),
                )
            asset = models.get(link.asset_id)
            if asset is None:
                # Linked asset unknown to catalog — surface honestly.
                summary = AssetSummary(
                    asset_id=link.asset_id,
                    name=f"<未注册资产 {link.asset_id}>",
                    type="unknown",
                    role=link.role,
                    is_primary=link.is_primary,
                    ordinal=getattr(link, "ordinal", 0),
                    unresolved=True,
                    current_version_id=None,
                    version_count=0,
                    trashed=False,
                )
            else:
                versions = maps.versions_by_asset.get(asset.id, ())
                current = maps.version_by_id.get(asset.current_version_id)
                summary = AssetSummary(
                    asset_id=asset.id,
                    name=asset.name,
                    type=asset.type,
                    role=link.role,
                    is_primary=link.is_primary,
                    ordinal=getattr(link, "ordinal", 0),
                    unresolved=link.unresolved,
                    current_version_id=asset.current_version_id,
                    version_count=len(versions),
                    trashed=asset.trashed,
                    stage=current.stage.value if current else "",
                    format=current.format if current else (asset.metadata.get("format") or ""),
                    bundle=bool(current.members) if current else False,
                )
            if link.unresolved:
                slot.unresolved.append(summary)
            else:
                slot.members.append(summary)
        for slot in slots.values():
            slot.members.sort(key=lambda m: (not m.is_primary, m.ordinal, m.name))
            slot.unresolved.sort(key=lambda m: m.name)
        return slots

    def _attach_status(
        self,
        members: list[AssetSummary],
        view: Any,
        *,
        with_stale: bool,
        entity_type: str,
        entity_id: str,
    ) -> None:
        asset_ids = [m.asset_id for m in members]
        # Missing sources: BOUNDED first-rung probe over the view's own
        # member assets only (F7 — the full find_missing_sources scan is
        # O(all versions) filesystem stats and must not run per expansion).
        view.missing_source_asset_ids = self._probe_missing_members(asset_ids)
        # uncommitted edits on the entity's asset versions
        try:
            copies = self._service.list_working_copies()
        except Exception:
            copies = []
        maps = self._service._ensure_maps()
        entity_asset_ids = set(asset_ids)
        for row in copies:
            version = maps.version_by_id.get(row.get("source_version_id"))
            if version is None or version.asset_id not in entity_asset_ids:
                continue
            view.uncommitted_edits.append(
                WorkingCopyLite(
                    working_id=row.get("working_id", ""),
                    source_version_id=row["source_version_id"],
                    path=str(row.get("path", "")),
                    state=str(row.get("state", "")),
                    dirty_hint=bool(row.get("dirty_hint")),
                )
            )
        if with_stale:
            stale = self._impact_service().entity_staleness(
                self._project, entity_type, entity_id
            )
            view.stale_items = stale
            view.stale_count = len(stale)

    def _probe_missing_members(self, asset_ids: list[str]) -> list[str]:
        """First-rung existence probe for the current versions of *asset_ids*.

        Mirrors sources._probe_path's cheap rungs (project-join + recorded
        absolute) without the relocation/identity-hash rungs — bounded to
        the view's assets, never the whole catalog.
        """
        maps = self._service._ensure_maps()
        project_dir = (
            Path(self._service.project_path).expanduser().resolve().parent
        )
        missing: list[str] = []
        for asset_id in asset_ids:
            version = maps.version_by_id.get(
                maps.asset_by_id.get(asset_id).current_version_id
            ) if maps.asset_by_id.get(asset_id) is not None else None
            if version is None or version.trashed:
                continue
            if version.managed:
                candidate = project_dir / version.path
            else:
                raw = Path(version.path)
                candidate = raw if raw.is_absolute() else project_dir / raw
            if not candidate.exists():
                missing.append(asset_id)
        return missing

    def _impact_service(self):
        if self._impact is None:
            from paleo_workbench.catalog.impact import ImpactService

            self._impact = ImpactService(self._service)
        return self._impact
