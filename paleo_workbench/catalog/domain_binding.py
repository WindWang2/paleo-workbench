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
from typing import Any, Callable, Iterable

from paleo_workbench.project.domain import (
    CoordinateStatus,
    SeismicSurveyEntity,
    WellEntity,
    ensure_workarea,
    normalize_well_name,
    resolve_well,
    upsert_entity_asset_link,
)

# Resource types that carry geological identity worth binding.
WELL_HEAD_TYPE = "well_head"
SEISMIC_TYPES = {"seismic", "segy"}
WELL_LOG_TYPES = {"well_log"}

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
    links_created: int = 0
    links_updated: int = 0
    ambiguous_assets: int = 0
    issues: list[str] = field(default_factory=list)

    def merge(self, other: "BindingReport") -> None:
        self.wells_created += other.wells_created
        self.wells_updated += other.wells_updated
        self.surveys_created += other.surveys_created
        self.surveys_updated += other.surveys_updated
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
    count = min(len(names), len(xs), len(ys))
    wells: list[WellExtract] = []
    for index in range(count):
        row = source_rows[index] if index < len(source_rows) else None
        wells.append(
            WellExtract(
                name=str(names[index]),
                x=float(xs[index]),
                y=float(ys[index]),
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
    if not project_crs or _crs_equivalent(source_crs, project_crs):
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


def _crs_equivalent(left: str, right: str) -> bool:
    """pyproj ``CRS.equals`` semantics with a case-insensitive fallback."""
    if left == right:
        return True
    try:
        from pyproj import CRS  # noqa: PLC0415

        return bool(CRS.from_user_input(left).equals(CRS.from_user_input(right)))
    except Exception:
        return left.strip().casefold() == right.strip().casefold()


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
) -> BindingReport:
    """Resolve/create Well entities for extracted rows and link the asset.

    ``asset_id=None`` (catalog not ready / legacy scan) still creates entities
    but defers linking — a later idempotent pass attaches links.
    """
    report = BindingReport()
    for extract in extracts:
        outcome = resolve_well(project, name=extract.name, uwi=extract.uwi)
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
        if asset_id is not None:
            link, created = upsert_entity_asset_link(
                project,
                entity_type="well",
                entity_id=well.id,
                asset_id=asset_id,
                role="well_head",
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
# Resource-level orchestration (import pipeline + migration share this)
# ---------------------------------------------------------------------------


def bind_resources(
    project: Any,
    resources: Iterable[Any],
    *,
    asset_id_by_legacy: dict[str, str],
    path_resolver: PathResolver,
    engine: Any | None = None,
) -> BindingReport:
    """Bind imported/legacy resources to domain entities.

    ``asset_id_by_legacy`` maps ``ResourceItem.id`` (== catalog
    ``legacy_resource_id``) to the owning catalog DataAsset id.  Resources
    without a catalog asset yet still produce entities; only the link waits
    for a later idempotent pass once registration completes.
    """
    report = BindingReport()
    ensure_workarea(project)
    project_crs = str(getattr(project.coordinate, "project_crs", "") or "")
    for resource in resources:
        asset_id: str | None = asset_id_by_legacy.get(resource.id)
        rtype = str(getattr(resource, "type", "") or "")
        path = path_resolver(str(resource.path))
        if rtype in (*SEISMIC_TYPES, WELL_HEAD_TYPE, *WELL_LOG_TYPES) and not path.is_file():
            report.issues.append(f"源文件不存在，跳过元数据解析: {resource.name}")
            continue
        if rtype == WELL_HEAD_TYPE and path.is_file():
            extracts, warnings = extract_wells_from_dat(
                resource,
                path=path,
                comparison_crs=project_crs,
                engine=engine,
            )
            report.issues.extend(warnings)
            if extracts:
                report.merge(bind_well_extracts(project, extracts, asset_id=asset_id))
        elif rtype in SEISMIC_TYPES and path.is_file():
            extract, warnings = extract_survey_from_segy(path, crs=resource.crs or project_crs)
            report.issues.extend(warnings)
            if extract is not None:
                report.merge(bind_survey_extract(project, extract, asset_id=asset_id))
        elif rtype in WELL_LOG_TYPES and path.is_file():
            report.merge(_bind_well_log(project, resource, path=path, asset_id=asset_id))
    return report


def _bind_well_log(
    project: Any,
    resource: Any,
    *,
    path: Path,
    asset_id: str,
) -> BindingReport:
    """Match a LAS/XML log against wells by header well_name (create when new)."""
    well_name = ""
    try:
        from geoviz import inspect_las_file  # noqa: PLC0415

        header = inspect_las_file(str(path))
        well_name = str(getattr(header, "well_name", "") or "").strip()
    except Exception:
        well_name = ""
    if not well_name:
        well_name = path.stem
    extracts = [WellExtract(name=well_name)]
    return bind_well_extracts(project, extracts, asset_id=asset_id)
