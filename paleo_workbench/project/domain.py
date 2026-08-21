"""WorkArea-centered geological domain model.

Extends :class:`~paleo_workbench.project.models.ProjectDocument` with first-class
domain entities so data management becomes::

    ProjectDocument.workarea (1 Project = 1 WorkArea)
        ├── wells                (Well master records)
        ├── seismic_surveys      (SeismicSurvey master records)
        ├── geological_entities  (horizons/faults/… lightweight entities)
        ├── auxiliary_entities   (non-geological project materials)
        └── entity_asset_links   (explicit Entity ↔ DataAsset relations)

Design rules (ADR docs/adr/0057-workarea-domain.md):

- ``ProjectDocument.coordinate`` stays THE canonical CRS authority;
  ``WorkArea.project_crs`` / ``display_crs`` are projections kept in sync by
  :func:`sync_workarea_with_coordinate`.  Never write one without the other.
- ``Well.id`` is the stable canonical identity.  A Well is NOT a LAS file,
  NOT a ``WellTableRow``, NOT a filename.  Assets attach via
  :class:`EntityAssetLink`; relationships must never be inferred from tags.
- All helpers here are pure (no Qt, no IO) so they run on worker threads and
  in unit tests.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ENTITY_TYPE = Literal["well", "seismic_survey", "geological_entity", "auxiliary_entity"]

WELL_ROLES = (
    "well_head",
    "well_log",
    "trajectory",
    "tops",
    "time_depth",
    "interpretation",
    "other",
)

SURVEY_ROLES = (
    "seismic_volume",
    "geometry",
    "velocity",
    "horizon",
    "fault",
    "interpretation",
    "other",
)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def normalize_well_name(name: str) -> str:
    """Canonical comparison key for well/survey identity matching.

    NFKC-normalizes, casefolds, strips whitespace/punctuation noise and
    collapses internal whitespace so ``"W-01 "`/``w－01`` compare equal while
    genuinely different names never collide.
    """
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = text.casefold()
    # Full-width/hyphen-like separators become spaces, then collapse.
    text = re.sub(r"[\s_\-–—·.,()（）\[\]【】]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class WorkArea(BaseModel):
    """The single study-area container of a project (1 Project = 1 WorkArea).

    CRS fields are *projections* of ``ProjectDocument.coordinate`` (canonical);
    :func:`sync_workarea_with_coordinate` keeps them aligned.
    """

    id: str = Field(default_factory=lambda: _id("wa"))
    name: str = ""
    description: str = ""
    # Closed-polygon outline [[x, y], ...] in the workarea project CRS.
    boundary: list[list[float]] = Field(default_factory=list)
    boundary_crs: str = ""  # CRS the boundary coordinates are expressed in
    project_crs: str = ""
    display_crs: str = ""
    vertical_datum: str = ""
    horizontal_units: str = ""
    vertical_units: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class CoordinateStatus:
    OK = "ok"
    UNTRANSFORMED = "untransformed"  # source coords present, transform impossible/unperformed
    INVALID = "invalid"  # parsed but non-finite / unusable
    MISSING = "missing"


class WellEntity(BaseModel):
    """Well master record — stable canonical identity for one physical well."""

    id: str = Field(default_factory=lambda: _id("well"))
    name: str
    uwi: str = ""
    aliases: list[str] = Field(default_factory=list)
    # Surface location exactly as found in the source file (never rewritten).
    surface_x: float | None = None
    surface_y: float | None = None
    surface_z: float | None = None
    source_crs: str = ""
    # Surface location projected into the workarea project CRS.
    project_x: float | None = None
    project_y: float | None = None
    coordinate_status: str = CoordinateStatus.MISSING
    kb: float | None = None
    td: float | None = None
    status: str = "active"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def match_keys(self) -> set[str]:
        """All normalized identity keys this well answers to."""
        keys = {normalize_well_name(self.name)}
        if self.uwi:
            keys.add(normalize_well_name(self.uwi))
            keys.add(f"uwi:{normalize_well_name(self.uwi)}")
        for alias in self.aliases:
            normalized = normalize_well_name(alias)
            if normalized:
                keys.add(normalized)
        return {key for key in keys if key}


class SeismicSurveyEntity(BaseModel):
    """Seismic survey master record (3D bin grid geometry frozen at import)."""

    id: str = Field(default_factory=lambda: _id("svy"))
    name: str
    survey_type: Literal["3d", "2d"] = "3d"
    crs: str = ""
    # Survey extent corners [[x, y], ...] in the survey CRS (or project CRS
    # when ``crs`` equals the project CRS).  Typically 3–4 corners.
    extent: list[list[float]] = Field(default_factory=list)
    inline_range: list[float] = Field(default_factory=list)  # [start, stop, step]
    crossline_range: list[float] = Field(default_factory=list)
    n_samples: int | None = None
    dt_ms: float | None = None
    t0_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def match_keys(self) -> set[str]:
        return {normalize_well_name(self.name)} - {""}


class DomainEntity(BaseModel):
    """Lightweight named entity for geological interpretations or auxiliary material."""

    id: str = Field(default_factory=lambda: _id("ent"))
    kind: Literal["geological", "auxiliary"] = "geological"
    name: str
    entity_kind: str = ""  # e.g. horizon / fault / document / image_reference
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class EntityAssetLink(BaseModel):
    """Explicit Entity ↔ DataAsset relation.

    ``asset_id`` references a catalog :class:`DataAsset` id (NOT a ResourceItem
    id — resolve legacy ids via ``legacy_resource_id`` first).
    """

    id: str = Field(default_factory=lambda: _id("link"))
    entity_type: ENTITY_TYPE = "well"
    entity_id: str
    asset_id: str
    role: str = "other"
    is_primary: bool = False
    unresolved: bool = False  # True when entity matching was ambiguous
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


# ---------------------------------------------------------------------------
# Registry views
# ---------------------------------------------------------------------------


class WellRegistry:
    """Read-only indexed view over ``project.wells`` (O(1) lookups).

    ``by_key`` deliberately returns None for AMBIGUOUS keys (two+ wells
    sharing a normalized identity): callers must go through
    :func:`resolve_well` to handle ambiguity explicitly — silent first-wins
    matching is how duplicate wells get merged by accident.
    """

    def __init__(self, wells: Iterable[WellEntity]):
        self._by_id: dict[str, WellEntity] = {}
        self._by_key: dict[str, WellEntity] = {}
        self._ambiguous_keys: set[str] = set()
        for well in wells:
            self._by_id[well.id] = well
            for key in well.match_keys():
                existing = self._by_key.get(key)
                if existing is None:
                    self._by_key[key] = well
                elif existing.id != well.id:
                    self._ambiguous_keys.add(key)

    def by_id(self, well_id: str) -> WellEntity | None:
        return self._by_id.get(well_id)

    def by_key(self, key: str) -> WellEntity | None:
        normalized = normalize_well_name(key)
        if normalized in self._ambiguous_keys:
            return None
        return self._by_key.get(normalized)

    def find_all_by_name(self, name: str) -> list[WellEntity]:
        normalized = normalize_well_name(name)
        return [
            well
            for well in self._by_id.values()
            if normalized and normalized in well.match_keys()
        ]

    def __len__(self) -> int:
        return len(self._by_id)

    def all(self) -> list[WellEntity]:
        return list(self._by_id.values())


class SurveyRegistry:
    """Read-only indexed view over ``project.seismic_surveys``."""

    def __init__(self, surveys: Iterable[SeismicSurveyEntity]):
        self._by_id: dict[str, SeismicSurveyEntity] = {}
        self._by_key: dict[str, SeismicSurveyEntity] = {}
        for survey in surveys:
            self._by_id[survey.id] = survey
            for key in survey.match_keys():
                self._by_key.setdefault(key, survey)

    def by_id(self, survey_id: str) -> SeismicSurveyEntity | None:
        return self._by_id.get(survey_id)

    def by_key(self, key: str) -> SeismicSurveyEntity | None:
        return self._by_key.get(normalize_well_name(key))

    def __len__(self) -> int:
        return len(self._by_id)

    def all(self) -> list[SeismicSurveyEntity]:
        return list(self._by_id.values())


def well_registry(project: Any) -> WellRegistry:
    return WellRegistry(getattr(project, "wells", []) or [])


def survey_registry(project: Any) -> SurveyRegistry:
    return SurveyRegistry(getattr(project, "seismic_surveys", []) or [])


# ---------------------------------------------------------------------------
# Link helpers (idempotent)
# ---------------------------------------------------------------------------


def upsert_entity_asset_link(
    project: Any,
    *,
    entity_type: ENTITY_TYPE,
    entity_id: str,
    asset_id: str,
    role: str = "other",
    is_primary: bool = False,
    unresolved: bool = False,
    note: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[EntityAssetLink, bool]:
    """Create or update the (entity, asset, role) link.

    Returns ``(link, created)``.  Idempotent: re-running with identical inputs
    never duplicates.  When ``is_primary`` flips on, sibling primary links of
    the same (entity_type, entity_id, role) are demoted so at most one primary
    exists per role.
    """
    links: list[EntityAssetLink] = project.entity_asset_links
    for link in links:
        if (
            link.entity_type == entity_type
            and link.entity_id == entity_id
            and link.asset_id == asset_id
            and link.role == role
        ):
            changed = False
            if is_primary and not link.is_primary:
                link.is_primary = True
                changed = True
            if unresolved != link.unresolved:
                link.unresolved = unresolved
                changed = True
            if note and note != link.note:
                link.note = note
                changed = True
            if metadata:
                link.metadata.update(metadata)
                changed = True
            if is_primary:
                changed |= _demote_sibling_primaries(links, entity_type, entity_id, role, link.id)
            return link, changed
    if is_primary:
        _demote_sibling_primaries(links, entity_type, entity_id, role, None)
    link = EntityAssetLink(
        entity_type=entity_type,
        entity_id=entity_id,
        asset_id=asset_id,
        role=role or "other",
        is_primary=is_primary,
        unresolved=unresolved,
        note=note,
        metadata=dict(metadata or {}),
    )
    links.append(link)
    return link, True


def _demote_sibling_primaries(
    links: list[EntityAssetLink],
    entity_type: str,
    entity_id: str,
    role: str,
    keep_link_id: str | None,
) -> bool:
    changed = False
    for link in links:
        if (
            link.id != keep_link_id
            and link.entity_type == entity_type
            and link.entity_id == entity_id
            and link.role == role
            and link.is_primary
        ):
            link.is_primary = False
            changed = True
    return changed


def remove_links_for_asset(project: Any, asset_id: str) -> int:
    """Drop every link pointing at ``asset_id`` (asset removed from catalog)."""
    links = project.entity_asset_links
    before = len(links)
    project.entity_asset_links = [link for link in links if link.asset_id != asset_id]
    return before - len(project.entity_asset_links)


def links_for_entity(project: Any, entity_type: str, entity_id: str) -> list[EntityAssetLink]:
    return [
        link
        for link in project.entity_asset_links
        if link.entity_type == entity_type and link.entity_id == entity_id
    ]


def links_for_asset(project: Any, asset_id: str) -> list[EntityAssetLink]:
    return [link for link in project.entity_asset_links if link.asset_id == asset_id]


def entity_ids_for_asset(
    project: Any, asset_id: str, entity_type: str | None = None
) -> list[tuple[str, str]]:
    """(entity_type, entity_id) pairs attached to ``asset_id``."""
    return [
        (link.entity_type, link.entity_id)
        for link in project.entity_asset_links
        if link.asset_id == asset_id and (entity_type is None or link.entity_type == entity_type)
    ]


def asset_ids_for_entity(
    project: Any, entity_type: str, entity_id: str, role: str | None = None
) -> list[str]:
    seen: list[str] = []
    for link in project.entity_asset_links:
        if (
            link.entity_type == entity_type
            and link.entity_id == entity_id
            and (role is None or link.role == role)
            and link.asset_id not in seen
        ):
            seen.append(link.asset_id)
    return seen


# ---------------------------------------------------------------------------
# WorkArea lifecycle
# ---------------------------------------------------------------------------


def ensure_workarea(project: Any) -> Any:
    """Return the project's WorkArea, creating it from meta/coordinate if absent.

    Deterministic and idempotent.  The created WorkArea derives its CRS fields
    from the canonical ``coordinate`` block so both authorities agree from birth.
    """
    workarea = getattr(project, "workarea", None)
    if workarea is not None:
        sync_workarea_with_coordinate(project)
        return workarea
    meta = project.meta
    coordinate = project.coordinate
    workarea = WorkArea(
        name=str(meta.name or ""),
        project_crs=str(coordinate.project_crs or ""),
        display_crs=str(coordinate.display_crs or ""),
    )
    project.workarea = workarea
    return workarea


def sync_workarea_with_coordinate(project: Any) -> bool:
    """Project canonical ``coordinate`` CRS values into the WorkArea.

    Returns True when anything changed.  Safe to call before every save.
    """
    workarea = getattr(project, "workarea", None)
    if workarea is None:
        return False
    coordinate = project.coordinate
    changed = False
    project_crs = str(coordinate.project_crs or "")
    display_crs = str(coordinate.display_crs or "")
    if workarea.project_crs != project_crs:
        workarea.project_crs = project_crs
        changed = True
    if workarea.display_crs != display_crs:
        workarea.display_crs = display_crs
        changed = True
    return changed


def crs_equivalent(left: str, right: str) -> bool:
    """pyproj ``CRS.equals`` semantics with a case-insensitive fallback.

    Shared by binding (transform decisions) and views (render gating) so a
    single definition of "same frame" exists.
    """
    if not left or not right:
        return False
    if left == right:
        return True
    try:
        from pyproj import CRS  # noqa: PLC0415

        return bool(CRS.from_user_input(left).equals(CRS.from_user_input(right)))
    except Exception:
        return left.strip().casefold() == right.strip().casefold()


def domain_signature(project: Any) -> tuple:
    """Cheap change key covering every domain field the UI renders.

    Used by DataPage (tree rebuild gate) and the well map page so both stay
    consistent — review finding #5 (stale flags after coordinate changes).
    Includes identity fields (uwi/aliases) and source coordinates so
    governance edits and re-imports invalidate the caches too.
    """
    wells = getattr(project, "wells", None) or []
    surveys = getattr(project, "seismic_surveys", None) or []
    links = getattr(project, "entity_asset_links", None) or []
    workarea = getattr(project, "workarea", None)
    coordinate = getattr(project, "coordinate", None)
    return (
        len(wells),
        tuple(
            (
                w.id,
                w.name,
                w.uwi,
                tuple(w.aliases),
                w.surface_x,
                w.surface_y,
                w.coordinate_status,
                w.project_x,
                w.project_y,
            )
            for w in wells
        ),
        tuple(
            (s.id, s.name, s.crs, bool(getattr(s, "extent", None))) for s in surveys
        ),
        len(links),
        str(getattr(coordinate, "project_crs", "") or ""),
        bool(getattr(workarea, "boundary", None)),
    )


# ---------------------------------------------------------------------------
# Resolution service
# ---------------------------------------------------------------------------


class ResolutionOutcome(BaseModel):
    """Result of attempting to bind incoming data to a Well/Survey entity."""

    matched: bool = False
    ambiguous: bool = False
    well_id: str | None = None
    survey_id: str | None = None
    strategy: str = ""  # persisted_id | uwi | canonical_name | alias | none
    candidates: list[str] = Field(default_factory=list)


def resolve_well(
    project: Any,
    *,
    name: str = "",
    uwi: str = "",
    well_id: str = "",
    overrides: dict[str, str] | None = None,
) -> ResolutionOutcome:
    """Match incoming well data against the registry (§13 priority order).

    Order: persisted id → UWI → normalized canonical name → alias →
    explicit mapping.  ``overrides`` maps a normalized name (or
    ``uwi:<normalized uwi>`` key) to a Well.id and is consulted LAST — it
    exists so governance UIs can settle cases the automatic chain cannot.
    When omitted, project-level governance overrides
    (``workarea.metadata["well_identity_overrides"]``) apply automatically;
    pass an empty dict to disable.  Ambiguous name hits NEVER merge
    silently — ``ambiguous=True`` with all candidate ids so callers can
    surface an unresolved state.
    """
    registry = well_registry(project)
    if well_id:
        well = registry.by_id(well_id)
        if well is not None:
            return ResolutionOutcome(matched=True, well_id=well.id, strategy="persisted_id")
    if uwi:
        normalized_uwi = f"uwi:{normalize_well_name(uwi)}"
        well = registry.by_key(normalized_uwi)
        if well is not None:
            return ResolutionOutcome(matched=True, well_id=well.id, strategy="uwi")
    normalized = normalize_well_name(name)
    if normalized:
        candidates = registry.find_all_by_name(normalized)
        if len(candidates) == 1:
            well = candidates[0]
            strategy = "canonical_name"
            if uwi and normalize_well_name(uwi) in {
                normalize_well_name(alias) for alias in well.aliases
            }:
                strategy = "alias"
            return ResolutionOutcome(matched=True, well_id=well.id, strategy=strategy)
        if len(candidates) > 1:
            return ResolutionOutcome(
                ambiguous=True,
                candidates=[candidate.id for candidate in candidates],
                strategy="ambiguous_name",
            )
    if overrides is None:
        overrides = well_identity_overrides(project)
    if overrides:
        well = _explicit_mapping_hit(registry, overrides, name=name, uwi=uwi)
        if well is not None:
            return ResolutionOutcome(matched=True, well_id=well.id, strategy="explicit_mapping")
    return ResolutionOutcome(strategy="none")


def well_identity_overrides(project: Any) -> dict[str, str]:
    """Governance-managed name/uwi → Well.id mappings (explicit mapping step)."""
    workarea = getattr(project, "workarea", None)
    overrides = getattr(workarea, "metadata", {}).get("well_identity_overrides") if workarea else None
    return dict(overrides) if isinstance(overrides, dict) else {}


def set_well_identity_override(project: Any, key: str, well_id: str) -> bool:
    """Record an explicit identity mapping (governance action).

    ``key`` may be a raw well name or UWI; it is stored normalized.  Returns
    True when the mapping was written, False when the target well does not
    exist or the key collides with the automatic chain (a mapping that the
    UWI/name steps already resolve would be dead weight).
    """
    workarea = getattr(project, "workarea", None)
    if workarea is None:
        ensure_workarea(project)
        workarea = project.workarea
    registry = well_registry(project)
    if registry.by_id(well_id) is None:
        return False
    normalized = normalize_well_name(key)
    if not normalized:
        return False
    # Never store a mapping the automatic chain already resolves.
    outcome = resolve_well(project, name=key, uwi=key)
    if outcome.matched and outcome.strategy != "explicit_mapping":
        return False
    overrides = workarea.metadata.setdefault("well_identity_overrides", {})
    overrides[normalized] = well_id
    return True


def _explicit_mapping_hit(
    registry: WellRegistry, overrides: dict[str, str], *, name: str, uwi: str
) -> WellEntity | None:
    keys = [normalize_well_name(name)]
    if uwi:
        keys.append(f"uwi:{normalize_well_name(uwi)}")
    for key in keys:
        hit = overrides.get(key)
        if hit:
            well = registry.by_id(hit)
            if well is not None:
                return well
    return None
