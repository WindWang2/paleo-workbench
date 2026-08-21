"""Canonical Well identity adapter for legacy modules (ADR 0059 §7).

Five well-id namespaces coexist today (preview ``record_id``, joint
``JointWellId``, factor-table ``WellTableRow.well_id``, workstation UUIDs,
raw ``well_name`` strings).  New code must use ``WellEntity.id``; legacy
modules migrate incrementally by routing their lookups through THIS adapter
instead of adding a sixth namespace.

Thread-safe: read-only views over the project document; safe on workers.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.domain import (
    WellEntity,
    normalize_well_name,
    resolve_well,
)

_ENTITY_TYPE_WELL = "well"


class WellIdentityAdapter:
    """Single lookup surface between legacy identities and canonical Well.id."""

    def __init__(self, project: Any, catalog_service: Any = None):
        self._project = project
        self._service = catalog_service
        # asset_id → legacy_resource_id (lazy; catalog may be absent).
        self._legacy_by_asset: dict[str, str] | None = None
        # resource_id/asset_id → well ids (lazy link index).
        self._wells_by_asset: dict[str, list[str]] | None = None

    # ------------------------------------------------------------------
    # name / uwi resolution (replaces raw string matching)
    # ------------------------------------------------------------------

    def resolve(self, *, name: str = "", uwi: str = "", well_id: str = "") -> WellEntity | None:
        outcome = resolve_well(self._project, name=name, uwi=uwi, well_id=well_id)
        if not outcome.matched or outcome.well_id is None:
            return None
        return self.by_id(outcome.well_id)

    def display_name(self, well_id: str) -> str:
        well = self.by_id(well_id)
        return well.name if well is not None else ""

    def all_wells(self) -> list[WellEntity]:
        return list(getattr(self._project, "wells", None) or [])

    def by_id(self, well_id: str) -> WellEntity | None:
        return next(
            (
                well
                for well in self.all_wells()
                if well.id == well_id
            ),
            None,
        )

    def by_display_name(self, name: str) -> WellEntity | None:
        """Exact normalized-name match (no fuzzy, no creation)."""
        normalized = normalize_well_name(name)
        if not normalized:
            return None
        return next(
            (well for well in self.all_wells() if normalize_well_name(well.name) == normalized),
            None,
        )

    # ------------------------------------------------------------------
    # catalog bridge: ResourceItem/DataAsset ids ↔ wells
    # ------------------------------------------------------------------

    def _asset_legacy_map(self) -> dict[str, str]:
        if self._legacy_by_asset is not None:
            return self._legacy_by_asset
        mapping: dict[str, str] = {}
        if self._service is not None:
            try:
                for asset in self._service.list_assets(include_trashed=False):
                    legacy = getattr(asset, "legacy_resource_id", None)
                    if legacy:
                        mapping[asset.id] = str(legacy)
            except Exception:
                mapping = {}
        self._legacy_by_asset = mapping
        return mapping

    def _well_links_index(self) -> dict[str, list[str]]:
        if self._wells_by_asset is not None:
            return self._wells_by_asset
        index: dict[str, list[str]] = {}
        for link in getattr(self._project, "entity_asset_links", None) or []:
            if link.entity_type != _ENTITY_TYPE_WELL:
                continue
            index.setdefault(link.asset_id, []).append(link.entity_id)
        self._wells_by_asset = index
        return index

    def invalidate(self) -> None:
        """Drop cached indexes (call after imports/migrations mutate links)."""
        self._legacy_by_asset = None
        self._wells_by_asset = None

    def well_ids_for_resource(self, resource_id: str) -> list[str]:
        """Wells linked to the DataAsset bridged from this legacy ResourceItem."""
        index = self._well_links_index()
        well_ids = list(index.get(resource_id, []))
        if well_ids:
            return well_ids
        legacy_map = self._asset_legacy_map()
        for asset_id, legacy in legacy_map.items():
            if legacy == resource_id:
                return list(index.get(asset_id, []))
        return []

    def well_for_resource(self, resource_id: str) -> WellEntity | None:
        well_ids = self.well_ids_for_resource(resource_id)
        if len(well_ids) != 1:
            return None  # zero or ambiguous → caller decides, no silent pick
        return self.by_id(well_ids[0])

