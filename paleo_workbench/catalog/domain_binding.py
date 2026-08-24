"""Bind imported data to WorkArea domain entities (Well / SeismicSurvey).

Worker-safe pure layer shared by:

- the import pipeline (:meth:`bind_resources`) — runs after catalog
  registration of freshly imported resources;
- legacy-project migration (:mod:`paleo_workbench.project.domain_migration`)
  — discovers entities from pre-existing resources.

Reuses the canonical geo-viz parsers (no third well parser):
``GeoVizEngine.prepare`` for SMI ``well_head`` DAT files and
``survey_corners_from_segy`` for SEG-Y survey geometry.  Callers may inject
fakes for headless tests via :class:`DomainExtractor` protocol arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, Callable, Iterable

from paleo_workbench.project.domain import (
    CoordinateStatus,
    SeismicSurveyEntity,
    WellEntity,
    asset_ids_for_entity,
    classify_well_spatial_scope,
    ensure_workarea,
    normalize_well_name,
    resolve_well,
    upsert_entity_asset_link,
)

# Resource types that carry geological identity worth binding.
WELL_HEAD_TYPE = "well_head"
SEISMIC_TYPES = {"seismic", "segy"}
WELL_LOG_TYPES = {"well_log"}

# Interpretation-type resources become geological DomainEntities:
# resource type → (DomainEntity.kind, DomainEntity.entity_kind, link role)
GEOLOGICAL_TYPE_MAP = {
    "horizon": ("geological", "horizon", "horizon"),
    "well_stratification": ("geological", "tops", "tops"),
}

PathResolver = Callable[[str], Path]


@dataclass
class WellExtract:
    """One candidate well parsed out of a source file."""

    name: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    kb: float | None = None
    td: float | None = None
    uwi: str = ""
    source_crs: str = ""
    coordinate_units: str = ""
    source_row: int | None = None


@dataclass
class SurveyExtract:
    """Survey geometry extracted from a SEG-Y volume."""

    name: str
    corners: list[list[float]] = field(default_factory=list)
    inline_range: list[float] = field(default_factory=list)
    crossline_range: list[float] = field(default_factory=list)
    n_samples: int | None = None
    dt_ms: float | None = None
    t0_ms: float | None = None
    crs: str = ""


@dataclass
class BindingReport:
    wells_created: int = 0
    wells_updated: int = 0
    surveys_created: int = 0
    surveys_updated: int = 0
    entities_created: int = 0
    links_created: int = 0
    links_updated: int = 0
    ambiguous_assets: int = 0
    issues: list[str] = field(default_factory=list)

    def merge(self, other: "BindingReport") -> None:
        self.wells_created += other.wells_created
        self.wells_updated += other.wells_updated
        self.surveys_created += other.surveys_created
        self.surveys_updated += other.surveys_updated
        self.entities_created += other.entities_created
        self.links_created += other.links_created
        self.links_updated += other.links_updated
        self.ambiguous_assets += other.ambiguous_assets
        self.issues.extend(other.issues)


# ---------------------------------------------------------------------------
# Extraction (guarded engine access — never crash import/migration on engine gap)
# ---------------------------------------------------------------------------


def _resolve_engine():
    try:
        from geoviz import GeoVizEngine, PreviewOptions  # noqa: PLC0415
    except Exception:  # pragma: no cover - environment without geo-viz-engine
        return None
    try:
        return GeoVizEngine.default()
    except Exception:  # pragma: no cover
        return None


def _payload_wells(payload: Any) -> list[WellExtract]:
    names = getattr(payload, "names", None) or ()
    xs = getattr(payload, "x", None)
    ys = getattr(payload, "y", None)
    source_rows = getattr(payload, "source_rows", None) or ()
    source_crs = str(getattr(payload, "source_crs", "") or "")
    units = str(getattr(payload, "coordinate_units", "") or "")
    # File-side UWI (geo-viz-engine ≥ 2a6b3bbf): strong identity signal when
    # the well_head file declares a UWI column; empty tuple otherwise.
    uwis = getattr(payload, "uwis", None) or ()
    count = min(len(names), len(xs), len(ys))
    wells: list[WellExtract] = []
    for index in range(count):
        row = source_rows[index] if index < len(source_rows) else None
        uwi = str(uwis[index]).strip() if index < len(uwis) else ""
        # Placeholder tokens some exporters use for empty cells carry no
        # identity — treat them as absent.
        if uwi in {"-", "--", "N/A", "NA"}:
            uwi = ""
        wells.append(
            WellExtract(
                name=str(names[index]),
                x=float(xs[index]),
                y=float(ys[index]),
                uwi=uwi,
                source_crs=source_crs,
                coordinate_units=units,
                source_row=int(row) if row is not None else None,
            )
        )
    return wells


def extract_wells_from_dat(
    resource: Any,
    *,
    path: Path,
    comparison_crs: str = "",
    engine: Any | None = None,
) -> tuple[list[WellExtract], list[str]]:
    """Parse an SMI well_head DAT through the canonical preview backend."""
    warnings: list[str] = []
    resolved_engine = engine or _resolve_engine()
    if resolved_engine is None:
        return [], ["geo-viz-engine 不可用，跳过井位元数据解析"]
    try:
        from geoviz import PreviewOptions  # noqa: PLC0415

        from paleo_workbench.viz.preview_request import request_from_resource  # noqa: PLC0415
    except Exception:  # pragma: no cover
        return [], ["geoviz PreviewOptions 不可用"]
    request = request_from_resource(
        resource,
        path=str(path),
        semantic_type="well_head",
        label=resource.name,
        comparison_crs=comparison_crs,
    )
    try:
        prepared = resolved_engine.prepare(request, PreviewOptions.local())
    except Exception as exc:
        return [], [f"井位解析失败: {exc.__class__.__name__}"]
    payload = getattr(prepared, "payload", None)
    if payload is None or payload.__class__.__name__ != "XYPreviewPayload":
        warning = str(getattr(prepared, "warning", "") or "")
        return [], [warning] if warning else ["井位文件不是可识别的 SMI well_head 格式"]
    return _payload_wells(payload), warnings


def extract_wells_from_xml(
    path: Path,
) -> tuple[list[WellExtract], list[str]]:
    """Parse a completed XML well-location delivery without a DAT engine path."""
    try:
        from paleo_workbench.resources.well_location_xml import (
            extract_well_locations_xml,
        )
    except Exception as exc:  # pragma: no cover - import boundary only
        return [], [f"XML 井位解析器不可用: {exc.__class__.__name__}"]
    records, warnings = extract_well_locations_xml(path)
    return [
        WellExtract(
            name=record.name,
            x=record.x,
            y=record.y,
            z=record.z,
            uwi=record.uwi,
            source_crs=record.source_crs,
        )
        for record in records
    ], warnings


def extract_survey_from_segy(path: Path, *, crs: str = "") -> tuple[SurveyExtract | None, list[str]]:
    """Header-only SEG-Y survey geometry extraction (no trace decode)."""
    try:
        from geoviz import survey_corners_from_segy  # noqa: PLC0415
    except Exception:  # pragma: no cover
        return None, ["geo-viz-engine 不可用，跳过地震工区几何解析"]
    try:
        p1, p2, p3, meta = survey_corners_from_segy(str(path))
    except Exception as exc:
        return None, [f"地震工区解析失败: {exc.__class__.__name__}: {exc}"]
    meta = meta or {}
    extract = SurveyExtract(
        name=path.stem,
        corners=[
            [float(p1[2]), float(p1[3])],
            [float(p2[2]), float(p2[3])],
            [float(p3[2]), float(p3[3])],
        ],
        inline_range=_range_of(meta, "iline"),
        crossline_range=_range_of(meta, "xline"),
        n_samples=_int_or_none(meta.get("n_samples")),
        dt_ms=_float_or_none(meta.get("dt_ms")),
        t0_ms=_float_or_none(meta.get("t0_ms")),
        crs=crs,
    )
    return extract, []


def _range_of(meta: dict[str, Any], axis: str) -> list[float]:
    start = _float_or_none(meta.get(f"{axis}_start"))
    step = _float_or_none(meta.get(f"{axis}_step"))
    count_key = f"n_{'inlines' if axis == 'iline' else 'crosslines'}"
    count = _int_or_none(meta.get(count_key))
    if start is None or step is None or count is None:
        return []
    return [start, start + step * max(count - 1, 0), step]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# CRS projection into workarea frame
# ---------------------------------------------------------------------------


def project_coordinates(
    x: float | None,
    y: float | None,
    *,
    source_crs: str,
    project_crs: str,
) -> tuple[float | None, float | None, str]:
    """Transform source coords into the project CRS.

    Returns ``(project_x, project_y, status)``.  Missing declarations never
    invent coordinates: undeclared sources stay UNTRANSFORMED (values pass
    through untouched) so the UI can flag them instead of silently plotting
    incompatible frames together.

    Uses pyproj directly (same engine as ``geoviz_plots.crs``) because the
    workarea target CRS is per-project, while ``coerce_to_project_crs``
    transforms toward a process-global target.
    """
    if x is None or y is None:
        return None, None, CoordinateStatus.MISSING
    if not source_crs:
        return float(x), float(y), CoordinateStatus.UNTRANSFORMED
    from paleo_workbench.project.domain import crs_equivalent

    if not project_crs or crs_equivalent(source_crs, project_crs):
        return float(x), float(y), CoordinateStatus.OK
    try:
        import numpy as np  # noqa: PLC0415
        from pyproj import Transformer  # noqa: PLC0415

        transformer = Transformer.from_crs(source_crs, project_crs, always_xy=True)
        px, py = transformer.transform(float(x), float(y))
        px, py = float(px), float(py)
    except Exception:
        return float(x), float(y), CoordinateStatus.UNTRANSFORMED
    if px != px or py != py or abs(px) == float("inf") or abs(py) == float("inf"):  # NaN/Inf guard
        return None, None, CoordinateStatus.INVALID
    return px, py, CoordinateStatus.OK


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def _stamp(entity: Any) -> None:
    from paleo_workbench.project.models import _now_iso  # noqa: PLC0415

    entity.updated_at = _now_iso()
    if not entity.created_at:
        entity.created_at = entity.updated_at


def bind_well_extracts(
    project: Any,
    extracts: Iterable[WellExtract],
    *,
    asset_id: str | None,
    spatial_scope: str | None = None,
    asset_role: str = "well_head",
) -> BindingReport:
    """Resolve/create Well entities for extracted rows and link the asset.

    ``asset_id=None`` (catalog not ready / legacy scan) still creates entities
    but defers linking — a later idempotent pass attaches links.
    """
    report = BindingReport()
    from paleo_workbench.project.domain import well_identity_overrides

    overrides = well_identity_overrides(project)
    for extract in extracts:
        candidate_wells = None
        if spatial_scope is not None:
            candidate_wells = [
                well
                for well in project.wells
                if str(getattr(well, "spatial_scope", "") or "") == spatial_scope
            ]
        outcome = resolve_well(
            project,
            name=extract.name,
            uwi=extract.uwi,
            overrides=overrides,
            candidate_wells=candidate_wells,
        )
        if outcome.ambiguous:
            report.ambiguous_assets += 1
            report.issues.append(
                f"井名歧义: {extract.name!r} 命中 {len(outcome.candidates)} 口既有井，已标记待治理"
            )
            if asset_id is not None:
                for candidate_id in outcome.candidates:
                    link, created = upsert_entity_asset_link(
                        project,
                        entity_type="well",
                        entity_id=candidate_id,
                        asset_id=asset_id,
                        role="other",
                        unresolved=True,
                        note=f"ambiguous_name:{extract.name}",
                    )
                    if created:
                        report.links_created += 1
                    else:
                        report.links_updated += 1
            continue

        well: WellEntity | None = None
        if outcome.matched:
            well = next((item for item in project.wells if item.id == outcome.well_id), None)
        if well is None:
            well = WellEntity(name=extract.name, uwi=extract.uwi)
            project.wells.append(well)
            report.wells_created += 1
        else:
            report.wells_updated += 1
            if extract.uwi and not well.uwi:
                well.uwi = extract.uwi

        _refresh_well_geometry(well, extract, project)
        if spatial_scope is not None:
            well.spatial_scope = spatial_scope
        else:
            inferred_scope = classify_well_spatial_scope(project, well)
            if inferred_scope is not None:
                well.spatial_scope = inferred_scope
        if asset_id is not None:
            link, created = upsert_entity_asset_link(
                project,
                entity_type="well",
                entity_id=well.id,
                asset_id=asset_id,
                role=asset_role,
                is_primary=True,
            )
            if created:
                report.links_created += 1
            else:
                report.links_updated += 1
        _stamp(well)
    return report


def _refresh_well_geometry(well: WellEntity, extract: WellExtract, project: Any) -> bool:
    """Fill/refresh coordinates + CRS projection. Returns True when changed."""
    changed = False
    project_crs = str(getattr(project.coordinate, "project_crs", "") or "")
    has_new_coords = extract.x is not None and extract.y is not None
    if has_new_coords and (
        well.surface_x != extract.x or well.surface_y != extract.y or not well.source_crs
    ):
        well.surface_x = extract.x
        well.surface_y = extract.y
        well.source_crs = extract.source_crs
        changed = True
    if has_new_coords:
        px, py, status = project_coordinates(
            extract.x,
            extract.y,
            source_crs=extract.source_crs,
            project_crs=project_crs,
        )
        if well.project_x != px or well.project_y != py or well.coordinate_status != status:
            well.project_x = px
            well.project_y = py
            well.coordinate_status = status
            changed = True
    return changed


def bind_survey_extract(
    project: Any,
    extract: SurveyExtract,
    *,
    asset_id: str | None,
) -> BindingReport:
    """Resolve/create the SeismicSurvey entity for a SEG-Y volume asset."""
    report = BindingReport()
    normalized = normalize_well_name(extract.name)
    survey = next(
        (item for item in project.seismic_surveys if normalize_well_name(item.name) == normalized),
        None,
    ) if normalized else None
    if survey is None:
        survey = SeismicSurveyEntity(
            name=extract.name,
            crs=extract.crs,
            extent=[list(corner) for corner in extract.corners],
            inline_range=list(extract.inline_range),
            crossline_range=list(extract.crossline_range),
            n_samples=extract.n_samples,
            dt_ms=extract.dt_ms,
            t0_ms=extract.t0_ms,
        )
        project.seismic_surveys.append(survey)
        report.surveys_created += 1
    else:
        # Freeze-upgrade: fill blanks, never clobber differing geometry.
        if not survey.extent and extract.corners:
            survey.extent = [list(corner) for corner in extract.corners]
            report.surveys_updated += 1
        if not survey.inline_range and extract.inline_range:
            survey.inline_range = list(extract.inline_range)
            report.surveys_updated += 1
        if not survey.crossline_range and extract.crossline_range:
            survey.crossline_range = list(extract.crossline_range)
            report.surveys_updated += 1
        if not survey.crs and extract.crs:
            survey.crs = extract.crs
    _stamp(survey)
    if asset_id is None:
        return report
    link, created = upsert_entity_asset_link(
        project,
        entity_type="seismic_survey",
        entity_id=survey.id,
        asset_id=asset_id,
        role="seismic_volume",
        is_primary=True,
    )
    if created:
        report.links_created += 1
    else:
        report.links_updated += 1
    return report


# ---------------------------------------------------------------------------
# Resource-level orchestration
#
# Split into two stages so heavy IO never touches the GUI thread AND the
# live ProjectDocument is only ever mutated on the GUI thread (P0 review
# finding #12):
#
#   stage_resources(...)   — worker thread: file parsing ONLY, returns plain
#                            dataclasses; never touches the document.
#   bind_staged(...)       — GUI thread: pure resolution/linking against the
#                            registries (dict lookups, no IO).
#
# ``bind_resources`` keeps the synchronous convenience composition for tests
# and headless callers.
# ---------------------------------------------------------------------------


@dataclass
class StagedResource:
    """Extraction result for one resource (plain data, document-free)."""

    resource_id: str
    resource_name: str
    wells: list[WellExtract] = field(default_factory=list)
    # XML well files are regional/reference deliveries by product contract.
    # Preserve that source semantic across the worker → GUI binding boundary.
    well_spatial_scope: str | None = None
    well_asset_role: str = "well_head"
    survey: SurveyExtract | None = None
    # Geological-entity hint (kind, entity_kind) for interpretation-type
    # resources (horizons/tops): no IO needed, just identity bookkeeping.
    geological: tuple[str, str] | None = None
    issues: list[str] = field(default_factory=list)


def stage_resources(
    project: Any,
    resources: Iterable[Any],
    *,
    path_resolver: PathResolver,
    engine: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> list[StagedResource]:
    """Parse geo-typed resources into plain payloads (worker-safe, no mutation).

    Reads only immutable attributes of the resources; safe to run beside the
    GUI thread as long as the caller passed a stable snapshot list.
    """
    staged: list[StagedResource] = []
    project_crs = str(getattr(project.coordinate, "project_crs", "") or "")
    for resource in resources:
        if cancel_event is not None and cancel_event.is_set():
            break
        rtype = str(getattr(resource, "type", "") or "")
        if rtype not in (
            *SEISMIC_TYPES,
            WELL_HEAD_TYPE,
            *WELL_LOG_TYPES,
            *GEOLOGICAL_TYPE_MAP,
        ):
            continue
        item = StagedResource(resource_id=str(resource.id), resource_name=str(resource.name))
        path = path_resolver(str(resource.path))
        if path.suffix.lower() == ".xml" and (
            rtype == WELL_HEAD_TYPE or rtype in WELL_LOG_TYPES
        ):
            item.well_spatial_scope = "reference"
        if not path.is_file():
            item.issues.append(f"源文件不存在，跳过元数据解析: {item.resource_name}")
            staged.append(item)
            continue
        if rtype == WELL_HEAD_TYPE:
            if path.suffix.lower() == ".xml":
                extracts, warnings = extract_wells_from_xml(path)
            else:
                extracts, warnings = extract_wells_from_dat(
                    resource,
                    path=path,
                    comparison_crs=project_crs,
                    engine=engine,
                )
            item.wells = extracts
            item.issues.extend(warnings)
        elif rtype in SEISMIC_TYPES:
            extract, warnings = extract_survey_from_segy(path, crs=resource.crs or project_crs)
            item.survey = extract
            item.issues.extend(warnings)
        elif rtype in WELL_LOG_TYPES:
            item.well_asset_role = "well_log"
            well_name = ""
            if path.suffix.lower() == ".xml":
                try:
                    from geoviz import load_xml_preview  # noqa: PLC0415

                    data = load_xml_preview(
                        str(path), max_curves=30, max_samples=100_000
                    )
                    well_name = str(
                        getattr(data, "well_name", "") or ""
                    ).strip()
                except Exception:
                    well_name = ""
            else:
                try:
                    from geoviz import inspect_las_file  # noqa: PLC0415

                    header = inspect_las_file(str(path))
                    well_name = str(
                        getattr(header, "well_name", "") or ""
                    ).strip()
                except Exception:
                    well_name = ""
            if not well_name:
                # Low-confidence auxiliary signal only (§22): LAS engines
                # themselves fall back to the stem, so this mirrors existing
                # behaviour rather than inventing a new identity scheme.
                well_name = path.stem
            item.wells = [WellExtract(name=well_name)]
        elif rtype in GEOLOGICAL_TYPE_MAP:
            kind, entity_kind, _role = GEOLOGICAL_TYPE_MAP[rtype]
            item.geological = (kind, entity_kind)
        staged.append(item)
    return staged


def _bind_geological(
    project: Any,
    item: "StagedResource",
    *,
    asset_id: str | None,
) -> BindingReport:
    """Resolve/create the geological DomainEntity for an interpretation asset."""
    from paleo_workbench.project.domain import DomainEntity

    report = BindingReport()
    if item.geological is None:
        return report
    kind, entity_kind = item.geological
    normalized = normalize_well_name(item.resource_name)
    entity = next(
        (
            e
            for e in getattr(project, "geological_entities", None) or []
            if normalize_well_name(e.name) == normalized and e.kind == kind
        ),
        None,
    ) if normalized else None
    if entity is None:
        entity = DomainEntity(kind=kind, name=item.resource_name, entity_kind=entity_kind)
        project.geological_entities.append(entity)
        report.entities_created += 1
        _stamp(entity)
    if asset_id is not None:
        link, created = upsert_entity_asset_link(
            project,
            entity_type="geological_entity",
            entity_id=entity.id,
            asset_id=asset_id,
            role=item.geological[1],
            is_primary=True,
        )
        if created:
            report.links_created += 1
        else:
            report.links_updated += 1
    return report


def bind_staged(
    project: Any,
    staged: Iterable[StagedResource],
    *,
    asset_id_by_legacy: dict[str, str],
) -> BindingReport:
    """Apply staged extractions to the registries (pure, GUI-thread safe)."""
    report = BindingReport()
    ensure_workarea(project)
    project_crs = str(getattr(project.coordinate, "project_crs", "") or "")
    del project_crs  # projection happens inside _refresh_well_geometry
    for item in staged:
        asset_id: str | None = asset_id_by_legacy.get(item.resource_id)
        report.issues.extend(item.issues)
        if item.wells:
            report.merge(
                bind_well_extracts(
                    project,
                    item.wells,
                    asset_id=asset_id,
                    spatial_scope=item.well_spatial_scope,
                    asset_role=item.well_asset_role,
                )
            )
        elif item.survey is not None:
            report.merge(bind_survey_extract(project, item.survey, asset_id=asset_id))
        elif item.geological is not None:
            report.merge(_bind_geological(project, item, asset_id=asset_id))
    return report


def reconcile_reference_only_staged(
    project: Any,
    staged: Iterable[StagedResource],
    *,
    asset_id_by_legacy: dict[str, str],
) -> BindingReport:
    """Repair XML wells persisted before the reference-only import contract.

    An old XML-only well can be safely reclassified in place. If the same
    entity also owns non-XML assets, preserve that WorkArea well, detach only
    the XML link, and let scoped binding create/reuse a separate reference
    well. Re-running is idempotent.
    """
    report = BindingReport()
    items = [
        item for item in staged
        if item.well_spatial_scope == "reference"
        and item.resource_id in asset_id_by_legacy
    ]
    reference_asset_ids = {
        asset_id_by_legacy[item.resource_id] for item in items
    }
    if not reference_asset_ids:
        return report
    wells_by_id = {
        well.id: well for well in getattr(project, "wells", None) or []
    }
    for item in items:
        asset_id = asset_id_by_legacy[item.resource_id]
        linked_well_ids = {
            link.entity_id
            for link in getattr(project, "entity_asset_links", None) or []
            if link.entity_type == "well" and link.asset_id == asset_id
        }
        for well_id in linked_well_ids:
            well = wells_by_id.get(well_id)
            if well is None:
                continue
            other_assets = (
                set(asset_ids_for_entity(project, "well", well_id))
                - reference_asset_ids
            )
            if other_assets:
                project.entity_asset_links[:] = [
                    link
                    for link in project.entity_asset_links
                    if not (
                        link.entity_type == "well"
                        and link.entity_id == well_id
                        and link.asset_id == asset_id
                    )
                ]
            elif well.spatial_scope != "reference":
                well.spatial_scope = "reference"
                _stamp(well)
                report.wells_updated += 1
        if item.wells:
            report.merge(
                bind_well_extracts(
                    project,
                    item.wells,
                    asset_id=asset_id,
                    spatial_scope="reference",
                    asset_role=item.well_asset_role,
                )
            )
    return report


def bind_resources(
    project: Any,
    resources: Iterable[Any],
    *,
    asset_id_by_legacy: dict[str, str],
    path_resolver: PathResolver,
    engine: Any | None = None,
) -> BindingReport:
    """Synchronous convenience composition: stage + bind (tests/headless)."""
    ensure_workarea(project)
    staged = stage_resources(project, resources, path_resolver=path_resolver, engine=engine)
    return bind_staged(project, staged, asset_id_by_legacy=asset_id_by_legacy)
