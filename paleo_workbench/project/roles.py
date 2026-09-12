"""Role registry — the single authority for entity↔asset link roles.

V11 (docs/development/data-fabric-v11/03-entity-asset-model.md) promotes the
old bare tuples (:data:`WELL_ROLES` / :data:`SURVEY_ROLES`) into first-class
role definitions carrying cardinality and primary policy so the well
multi-file model becomes a product-level contract instead of an implicit
convention.

Design rules:

- The registry is *descriptive guidance* for ingest inference, conflict
  detection and UI grouping — it is deliberately NOT an admission gate:
  documents with unknown roles (older/newer app versions) must always load
  and round-trip. Validation helpers classify, never reject.
- ``WELL_ROLES`` / ``SURVEY_ROLES`` are derived here and re-exported from
  :mod:`paleo_workbench.project.domain` so existing imports keep working;
  ``other`` is always last to preserve the historical tuple order for
  anything positional.
- Cardinality is per (entity, role) pair. ``primary_policy`` documents how
  the single-primary invariant of ``upsert_entity_asset_link`` should be
  applied for that role.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoleDefinition:
    """One link role and its business semantics."""

    role: str
    entity_types: tuple[str, ...]
    cardinality: str = "0..N"  # "0..1" | "0..N"
    primary_policy: str = "optional"  # none | optional | required_single
    ordered: bool = False
    display: str = ""
    stage_default: str = "raw"
    description: str = ""
    # File-format hints used by ingest role inference (extension lowercase,
    # no dot). Inference NEVER invents scientific semantics — a hint only
    # fires on a type the scanner already classified.
    format_hints: tuple[str, ...] = field(default=())


_WELL_ROLE_DEFS: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        role="well_head",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="required_single",
        display="井身/井位",
        format_hints=(".dat", ".xml"),
        description="井位/井史主记录（SMI DAT / XML 交付）；多文件时一个 primary。",
    ),
    RoleDefinition(
        role="well_log",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="optional",
        ordered=True,
        display="测井曲线",
        stage_default="raw",
        format_hints=(".las", ".lis", ".dlis", ".xml"),
        description="一口井可有多个测井文件（LAS/DLIS…）；ordinal 表达加载顺序。",
    ),
    RoleDefinition(
        role="trajectory",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="optional",
        display="井斜轨迹",
        format_hints=(".xlsx", ".xls", ".csv", ".dev"),
        description="井斜/轨迹数据；primary 为当前生效版本，其余为历史。",
    ),
    RoleDefinition(
        role="tops",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="optional",
        display="分层顶",
        format_hints=(".csv", ".txt"),
        description="地层顶数据，多版本并存。",
    ),
    RoleDefinition(
        role="time_depth",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="required_single",
        display="时深关系",
        format_hints=(".dat", ".csv", ".txt"),
        description="时深曲线/校验炮；primary 即当前 active 版本。",
    ),
    RoleDefinition(
        role="core",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="optional",
        display="岩心",
        description="岩心描述/图像数据。",
    ),
    RoleDefinition(
        role="interpretation",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="none",
        display="井周解释",
        description="井尺度解释成果（多方案并存）。",
    ),
    RoleDefinition(
        role="qc",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="none",
        display="质量控制",
        description="QC 报告与附件。",
    ),
    RoleDefinition(
        role="other",
        entity_types=("well",),
        cardinality="0..N",
        primary_policy="none",
        display="其他",
        description="兜底角色。",
    ),
)

_SURVEY_ROLE_DEFS: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        role="seismic_volume",
        entity_types=("seismic_survey",),
        cardinality="0..N",
        primary_policy="required_single",
        display="地震数据体",
        format_hints=(".sgy", ".segy"),
        description="SEG-Y 体（或其转码 store）；primary 为当前体。",
    ),
    RoleDefinition(
        role="geometry",
        entity_types=("seismic_survey",),
        cardinality="0..N",
        primary_policy="optional",
        display="观测系统",
        description="采集几何/观测系统描述。",
    ),
    RoleDefinition(
        role="velocity",
        entity_types=("seismic_survey",),
        cardinality="0..N",
        primary_policy="optional",
        display="速度场",
        description="速度模型/速度谱。",
    ),
    RoleDefinition(
        role="horizon",
        entity_types=("seismic_survey",),
        cardinality="0..N",
        primary_policy="optional",
        display="层位",
        description="地震层位解释。",
    ),
    RoleDefinition(
        role="fault",
        entity_types=("seismic_survey",),
        cardinality="0..N",
        primary_policy="optional",
        display="断层",
        description="断层解释。",
    ),
    RoleDefinition(
        role="interpretation",
        entity_types=("seismic_survey",),
        cardinality="0..N",
        primary_policy="none",
        display="调查解释",
        description="调查尺度解释成果。",
    ),
    RoleDefinition(
        role="other",
        entity_types=("seismic_survey",),
        cardinality="0..N",
        primary_policy="none",
        display="其他",
        description="兜底角色。",
    ),
)

_GEOLOGICAL_ROLE_DEFS: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        role="horizon",
        entity_types=("geological_entity",),
        cardinality="0..N",
        primary_policy="optional",
        display="层位",
    ),
    RoleDefinition(
        role="tops",
        entity_types=("geological_entity",),
        cardinality="0..N",
        primary_policy="optional",
        display="分层",
    ),
    RoleDefinition(
        role="fault",
        entity_types=("geological_entity",),
        cardinality="0..N",
        primary_policy="optional",
        display="断层",
    ),
    RoleDefinition(
        role="other",
        entity_types=("geological_entity",),
        cardinality="0..N",
        primary_policy="none",
        display="其他",
    ),
)

ROLE_DEFINITIONS: dict[str, RoleDefinition] = {
    definition.role: definition
    for definition in (*_WELL_ROLE_DEFS, *_SURVEY_ROLE_DEFS, *_GEOLOGICAL_ROLE_DEFS)
}

# Historical tuples, derived and order-preserving ("other" last).
WELL_ROLES: tuple[str, ...] = tuple(d.role for d in _WELL_ROLE_DEFS)
SURVEY_ROLES: tuple[str, ...] = tuple(d.role for d in _SURVEY_ROLE_DEFS)
GEOLOGICAL_ROLES: tuple[str, ...] = tuple(d.role for d in _GEOLOGICAL_ROLE_DEFS)

FALLBACK_ROLE_DEFINITION = RoleDefinition(
    role="other",
    entity_types=(),
    cardinality="0..N",
    primary_policy="none",
    display="其他",
)


def role_definition(role: str) -> RoleDefinition:
    """The definition for *role*; unknown roles get the permissive fallback.

    Unknown never raises: the registry is guidance, not an admission gate.
    """
    return ROLE_DEFINITIONS.get(str(role or ""), FALLBACK_ROLE_DEFINITION)


def known_role(role: str) -> bool:
    return str(role or "") in ROLE_DEFINITIONS


def roles_for_entity_type(entity_type: str) -> tuple[str, ...]:
    """Ordered role vocabulary for one entity type (UI grouping order)."""
    entity_type = str(entity_type or "")
    if entity_type == "well":
        return WELL_ROLES
    if entity_type == "seismic_survey":
        return SURVEY_ROLES
    if entity_type == "geological_entity":
        return GEOLOGICAL_ROLES
    return ("other",)


def infer_role_for_type(
    resource_type: str,
    *,
    file_suffix: str = "",
    file_name: str = "",
) -> str | None:
    """Best registry role for a scanner-classified resource type.

    Uses only the type the scanner already established plus optional
    extension / well-known-filename hints — this maps *known*
    classifications onto the role vocabulary; it never guesses identity.
    Filename patterns only fire for generically-typed files (the ingest
    plan surfaces every proposal for user confirmation before executing).
    Returns None when no mapping applies (caller keeps its legacy default).
    """
    rtype = str(resource_type or "").strip().lower()
    suffix = str(file_suffix or "").strip().lower()
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    stem = str(file_name or "").rsplit(".", 1)[0].lower()
    if rtype in {"well_head"}:
        return "well_head"
    if rtype in {"well_log", "las", "dlis", "lis"}:
        return "well_log"
    if rtype in {"well_stratification", "tops"}:
        return "tops"
    if rtype in {"seismic", "segy"}:
        return "seismic_volume"
    if rtype in {"horizon"}:
        return "horizon"
    if rtype in {"fault", "faults"}:
        return "fault"
    if rtype in {"trajectory", "deviation"}:
        return "trajectory"
    if rtype in {"time_depth", "checkshot", "td_table"}:
        return "time_depth"
    if rtype in {"core"}:
        return "core"
    # Well-known filename patterns for generically-typed files (spreadsheet/
    # tabular/csv): these are presentation conventions of the domain, not
    # identity claims — the plan always asks for confirmation.
    if rtype in {"table", "tabular", "spreadsheet", "csv", "unknown", "document"}:
        if any(token in stem for token in ("deviation", "trajectory", "survey_", "wellpath")):
            return "trajectory"
        if any(token in stem for token in ("tops", "marker", "formation")):
            return "tops"
        if any(token in stem for token in ("checkshot", "check_shot", "td_table", "timedepth", "time_depth")):
            return "time_depth"
        if any(token in stem for token in ("core",)):
            return "core"
    # Format-only hints for types the scanner reports generically.
    if rtype in {"table", "tabular", "spreadsheet", "csv", "unknown"}:
        for role, definition in ROLE_DEFINITIONS.items():
            if definition.entity_types and suffix in definition.format_hints:
                if role == "trajectory":
                    # A bare .xlsx/.csv is far more often tops than deviation;
                    # only claim trajectory when the scanner/filename said so.
                    continue
                return role
    return None


def cardinality_allows_multiple(role: str) -> bool:
    return role_definition(role).cardinality != "0..1"


def primary_required(role: str) -> bool:
    return role_definition(role).primary_policy == "required_single"
