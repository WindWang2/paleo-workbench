"""Professional batch/directory ingest planning (V11 §13 / docs 08).

Two strict phases with ZERO side effects before user confirmation:

- :func:`build_ingest_plan` (worker-safe, pure) — scan → classify →
  family-group → identity-match → role-infer → duplicate-detect → a
  serializable :class:`IngestPlan` the UI can present and edit.
- :func:`execute_ingest_plan` (GUI/worker) — registered chunks, entity
  binding, primary selection; cancellable and idempotent on re-run
  (already-imported path+sha pairs are skipped, so an interrupted ingest
  can simply be executed again).

Scientific semantics are never guessed silently: identity matches the
registry via ``resolve_well``'s deterministic chain, ambiguous or unmatched
files land in ``plan.unresolved`` for the user to settle, and directory
names are only LOW-confidence hints (LAS/DAT header identity wins).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, TYPE_CHECKING

from paleo_workbench.resources.import_service import classify_import_path
from paleo_workbench.resources.io_registry import PREFERRED_IMPORT_EXTENSIONS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from paleo_workbench.catalog.service import DataCatalogService

# Files above this size skip plan-level full hashing (the import path's
# content-addressed store still dedups at execute time); their duplicate
# verdict is honest "unknown" rather than a guessed "new".
PLAN_HASH_LIMIT_BYTES = 256 * 1024 * 1024

# Extensions that group into one logical bundle (shapefile family).
SHAPEFILE_MEMBER_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn"}
SHAPEFILE_REQUIRED = {".shp", ".shx", ".dbf"}

WELL_BOUND_TYPES = {"well_log", "well_head", "well_stratification", "time_depth"}
SURVEY_BOUND_TYPES = {"seismic", "segy"}


@dataclass
class IdentityProposal:
    """Proposed entity binding with confidence + strategy."""

    entity_type: str = ""  # well | seismic_survey | geological_entity | ""
    entity_id: str | None = None
    entity_name: str = ""
    new_entity: bool = False  # proposal creates a new entity
    strategy: str = ""  # canonical_name | uwi | directory_hint | none | ambiguous
    confidence: str = "low"  # high | medium | low
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BundleSuggestion:
    """Proposed compound-asset grouping (e.g. shapefile family)."""

    member_paths: list[Path] = field(default_factory=list)
    kind: str = "shapefile_family"

    @property
    def primary_path(self) -> Path | None:
        for path in self.member_paths:
            if path.suffix.lower() == ".shp":
                return path
        return self.member_paths[0] if self.member_paths else None


@dataclass
class PlannedItem:
    path: Path
    type: str
    format: str
    size_bytes: int | None = None
    sha256: str | None = None
    bundle: BundleSuggestion | None = None
    identity: IdentityProposal = field(default_factory=IdentityProposal)
    role: str = "other"
    primary: bool = False
    duplicate_of_version: str | None = None
    duplicate_of_asset: str | None = None
    decision: str = "pending"  # pending | accept | skip | as_new_version
    note: str = ""


@dataclass
class IngestPlan:
    root: Path
    items: list[PlannedItem] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def unresolved(self) -> list[PlannedItem]:
        return [i for i in self.items if i.identity.strategy == "ambiguous"]

    @property
    def duplicates(self) -> list[PlannedItem]:
        return [i for i in self.items if i.duplicate_of_version]

    def accepted(self) -> list[PlannedItem]:
        return [i for i in self.items if i.decision == "accept"]

    def to_dict(self) -> dict[str, Any]:
        import dataclasses

        def _encode(obj: Any) -> Any:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {
                    f.name: _encode(getattr(obj, f.name))
                    for f in dataclasses.fields(obj)
                }
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, list):
                return [_encode(v) for v in obj]
            return obj

        return _encode(self)

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.items),
            "duplicates": len(self.duplicates),
            "unresolved": len(self.unresolved),
            "bundles": sum(1 for i in self.items if i.bundle and i.bundle.primary_path == i.path),
        }


# ---------------------------------------------------------------------------
# Phase 1 — plan (pure, worker-safe)
# ---------------------------------------------------------------------------


def build_ingest_plan(
    root: str | Path,
    project: Any,
    *,
    preferred_only: bool = True,
    service: "DataCatalogService | None" = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> IngestPlan:
    """Scan *root* (directory or single file) and propose an ingest plan."""
    from paleo_workbench.project.roles import infer_role_for_type

    root = Path(root)
    plan = IngestPlan(root=root)
    paths = sorted(root.rglob("*")) if root.is_dir() else [root]
    files = [p for p in paths if _is_candidate_file(p)]

    # ---- family grouping (shapefile) ------------------------------------
    # Runs on the UNFILTERED candidate set: sidecar extensions (.shx/.dbf/
    # .prj) are not import-preferred on their own, but a detected family
    # adopts its members wholesale (a bundle never drops files).
    by_stem_dir: dict[tuple[Path, str], list[Path]] = {}
    for path in files:
        if path.suffix.lower() in SHAPEFILE_MEMBER_EXTENSIONS:
            by_stem_dir.setdefault((path.parent, path.stem), []).append(path)
    family_paths: set[Path] = set()
    family_of: dict[Path, BundleSuggestion] = {}
    for (_dir, _stem), members in by_stem_dir.items():
        extensions = {m.suffix.lower() for m in members}
        if ".shp" in extensions and SHAPEFILE_REQUIRED <= extensions:
            suggestion = BundleSuggestion(
                member_paths=sorted(members), kind="shapefile_family"
            )
            for member in members:
                family_of[member] = suggestion
                family_paths.add(member)

    if preferred_only:
        files = [
            p for p in files
            if p in family_paths
            or p.suffix.lower().lstrip(".") in PREFERRED_IMPORT_EXTENSIONS
        ]
    total = len(files)

    # ---- classification + hashing ----------------------------------------
    for index, path in enumerate(files):
        if cancel is not None and cancel():
            plan.issues.append("计划构建被取消（部分结果）")
            break
        if progress is not None:
            progress(index, total)
        resource_type, resource_format, status = classify_import_path(path)
        item = PlannedItem(
            path=path,
            type=resource_type,
            format=resource_format,
            role=(
                infer_role_for_type(
                    resource_type, file_suffix=path.suffix, file_name=path.name
                )
                or "other"
            ),
        )
        if status != "indexed":
            item.note = f"classify status: {status}"
        try:
            stat = path.stat()
            item.size_bytes = stat.st_size
        except OSError as exc:
            plan.issues.append(f"{path.name}: {exc}")
            continue
        if family_of.get(path) is not None:
            item.bundle = family_of[path]
            item.type = "geojson" if resource_type == "unknown" else resource_type
        # Duplicate detection: hash bounded-size files; the blob store
        # dedups the rest at execute time.
        if item.size_bytes and 0 < item.size_bytes <= PLAN_HASH_LIMIT_BYTES:
            try:
                item.sha256 = _sha256_of(path)
            except OSError as exc:
                plan.issues.append(f"{path.name}: 哈希失败 {exc}")
        plan.items.append(item)

    # ---- identity matching -----------------------------------------------
    _propose_identities(plan, project)
    # ---- duplicate matching against catalog ------------------------------
    if service is not None:
        _match_duplicates(plan, service)
    # ---- primary selection proposal --------------------------------------
    _propose_primaries(plan, project)
    return plan


def _is_candidate_file(path: Path) -> bool:
    try:
        if not path.is_file() or path.name.startswith("._"):
            return False
        return path.stat().st_size > 0
    except OSError:
        return False


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_well_name(path: Path, resource_type: str) -> str:
    """Header-based well name (engine first, stem as documented fallback)."""
    if path.suffix.lower() == ".xml":
        try:
            from geoviz import load_xml_preview  # noqa: PLC0415

            data = load_xml_preview(str(path), max_curves=30, max_samples=100_000)
            name = str(getattr(data, "well_name", "") or "").strip()
            if name:
                return name
        except Exception:
            pass
        return ""
    if resource_type == "well_log":
        try:
            from geoviz import inspect_las_file  # noqa: PLC0415

            header = inspect_las_file(str(path))
            name = str(getattr(header, "well_name", "") or "").strip()
            if name:
                return name
        except Exception:
            pass
    # Directory hint (LOW confidence only — never overrides a header hit).
    return ""


def _directory_hint(path: Path) -> str:
    parent = path.parent
    return parent.name if parent.name not in {"", ".", "/"} else ""


def _propose_identities(plan: IngestPlan, project: Any) -> None:
    from paleo_workbench.project.domain import resolve_well

    # Track per (entity, role) member order so primaries can be proposed.
    for item in plan.items:
        if item.type in WELL_BOUND_TYPES:
            name = _extract_well_name(item.path, item.type)
            confidence = "high" if name else "low"
            strategy_hint = "header"
            if not name:
                name = _directory_hint(item.path) or item.path.stem
                strategy_hint = "directory_hint"
            outcome = resolve_well(project, name=name)
            if outcome.matched:
                item.identity = IdentityProposal(
                    entity_type="well",
                    entity_id=outcome.well_id,
                    entity_name=name,
                    strategy=outcome.strategy,
                    confidence="high" if strategy_hint == "header" else "medium",
                )
            elif outcome.ambiguous:
                item.identity = IdentityProposal(
                    entity_type="well",
                    entity_name=name,
                    strategy="ambiguous",
                    confidence=confidence,
                    candidates=[
                        {"well_id": cid, "name": _well_name(project, cid)}
                        for cid in outcome.candidates
                    ],
                )
            else:
                item.identity = IdentityProposal(
                    entity_type="well",
                    entity_name=name,
                    new_entity=True,
                    strategy=strategy_hint,
                    confidence=confidence if strategy_hint == "header" else "low",
                )
        elif item.type in SURVEY_BOUND_TYPES:
            from paleo_workbench.project.domain import normalize_well_name as _norm
            from paleo_workbench.project.domain import survey_registry

            stem = item.path.stem
            registry = survey_registry(project)
            survey = registry.by_key(stem)
            if survey is not None:
                item.identity = IdentityProposal(
                    entity_type="seismic_survey",
                    entity_id=survey.id,
                    entity_name=survey.name,
                    strategy="canonical_name",
                    confidence="medium",
                )
            else:
                item.identity = IdentityProposal(
                    entity_type="seismic_survey",
                    entity_name=stem,
                    new_entity=True,
                    strategy="file_stem",
                    confidence="low",
                )
        elif item.type in {"horizon", "fault", "faults", "well_stratification"}:
            item.identity = IdentityProposal(
                entity_type="geological_entity",
                entity_name=item.path.stem,
                new_entity=True,
                strategy="file_stem",
                confidence="low",
            )
        else:
            item.identity = IdentityProposal(entity_type="", strategy="none")


def _well_name(project: Any, well_id: str) -> str:
    for well in getattr(project, "wells", None) or ():
        if well.id == well_id:
            return well.name
    return well_id


def _match_duplicates(plan: IngestPlan, service: "DataCatalogService") -> None:
    """Mark items whose content already exists as managed RAW versions."""
    maps = service._ensure_maps()
    sha_index: dict[str, tuple[str, str]] = {}  # sha -> (asset_id, version_id)
    path_index: dict[str, tuple[str, str]] = {}
    for version in maps.version_by_id.values():
        if version.trashed or not version.managed:
            continue
        if version.stage.value != "raw":
            continue
        if version.sha256:
            sha_index.setdefault(version.sha256, (version.asset_id, version.id))
        if version.source_uri:
            path_index.setdefault(
                Path(version.source_uri).name, (version.asset_id, version.id)
            )
    for item in plan.items:
        if item.decision != "pending":
            continue
        hit = None
        if item.sha256:
            hit = sha_index.get(item.sha256)
        if hit is None:
            # Same-basename heuristic ONLY flags a possible duplicate for the
            # user; the decision stays theirs (no silent skip).
            same_name = path_index.get(item.path.name)
            if same_name is not None and _same_size(maps, same_name[1], item.size_bytes):
                item.note = (item.note + " " if item.note else "") + (
                    f"同名已导入资产 {same_name[0]}（内容未验证）"
                )
        if hit is not None:
            item.duplicate_of_asset, item.duplicate_of_version = hit
            item.decision = "skip"
            item.note = (item.note + " " if item.note else "") + "内容与已导入 RAW 相同"


def _same_size(maps: Any, version_id: str, size: int | None) -> bool:
    if size is None:
        return False
    version = maps.version_by_id.get(version_id)
    return version is not None and version.size_bytes == size


def _propose_primaries(plan: IngestPlan, project: Any) -> None:
    """First member of a role becomes primary when the entity has none yet."""
    from paleo_workbench.project.domain import asset_ids_for_entity

    seen: set[tuple[str, str, str]] = set()
    for item in plan.items:
        identity = item.identity
        if not identity.entity_id or identity.entity_id in {None, ""}:
            continue
        if item.decision != "pending":
            continue
        key = (identity.entity_type, identity.entity_id, item.role)
        existing = asset_ids_for_entity(
            project, identity.entity_type, identity.entity_id, role=item.role
        )
        if key not in seen and not existing:
            item.primary = True
            seen.add(key)


# ---------------------------------------------------------------------------
# Phase 2 — execute (mutations, cancellable, idempotent)
# ---------------------------------------------------------------------------


@dataclass
class IngestExecuteReport:
    imported_version_ids: list[str] = field(default_factory=list)
    asset_id_by_path: dict[str, str] = field(default_factory=dict)
    bound_links: int = 0
    created_entities: int = 0
    skipped: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    cancelled: bool = False


def execute_ingest_plan(
    plan: IngestPlan,
    service: "DataCatalogService",
    project: Any,
    *,
    bind: bool = True,
    chunk_size: int = 64,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> IngestExecuteReport:
    """Execute the (user-confirmed) plan: import → bind → primary.

    Idempotent on re-run: a path whose content is already registered (the
    catalog's managed-RAW dedup) resolves to the existing version and is
    recorded as skipped-with-reference rather than imported twice.
    """
    report = IngestExecuteReport()

    pending = [
        item for item in plan.items
        if item.decision in ("accept", "pending") or (
            item.decision == "skip" and item.duplicate_of_version
        )
    ]
    total = len(pending)
    done = 0
    staged_bindings: list[tuple[PlannedItem, str]] = []  # (item, asset_id)

    for start in range(0, len(pending), chunk_size):
        if cancel is not None and cancel():
            report.cancelled = True
            break
        chunk = pending[start : start + chunk_size]
        with service.batch_save():
            for item in chunk:
                done += 1
                if progress is not None:
                    progress(done, total)
                if item.decision == "skip":
                    report.skipped.append(str(item.path))
                    if item.duplicate_of_asset:
                        report.asset_id_by_path[str(item.path)] = item.duplicate_of_asset
                        staged_bindings.append((item, item.duplicate_of_asset))
                    continue
                try:
                    version = service.import_raw(
                        item.path,
                        name=item.path.name,
                        type=item.type,
                        format=item.format,
                        known_sha256=item.sha256,
                    )
                except Exception as exc:
                    report.issues.append(
                        f"{item.path.name}: 导入失败 {exc.__class__.__name__}: {exc}"
                    )
                    continue
                report.imported_version_ids.append(version.id)
                asset_id = version.asset_id
                report.asset_id_by_path[str(item.path)] = asset_id
                staged_bindings.append((item, asset_id))

    if bind and staged_bindings:
        _bind_plan_items(project, staged_bindings, report)
    return report


def _bind_plan_items(
    project: Any,
    staged: list[tuple[PlannedItem, str]],
    report: IngestExecuteReport,
) -> None:
    from paleo_workbench.catalog.domain_binding import (
        SurveyExtract,
        WellExtract,
        bind_survey_extract,
        bind_well_extracts,
    )

    wells_by_item: list[tuple[PlannedItem, str]] = []
    for item, asset_id in staged:
        identity = item.identity
        if identity.entity_type == "well" and identity.entity_id:
            wells_by_item.append((item, asset_id))
        elif identity.entity_type == "well" and identity.new_entity:
            wells_by_item.append((item, asset_id))
        elif identity.entity_type == "seismic_survey":
            survey = _ensure_survey(project, identity, report)
            if survey is not None:
                bind_survey_extract(
                    project,
                    SurveyExtract(name=survey.name),
                    asset_id=asset_id,
                )
                report.bound_links += 1
        elif identity.entity_type == "geological_entity":
            _ensure_geological(project, item, asset_id, report)

    # Batch well binding: group extracts per (well scope) to reuse one pass.
    by_scope: dict[tuple[str | None, str], list[tuple[WellExtract, str, str]]] = {}
    for item, asset_id in wells_by_item:
        identity = item.identity
        well_id = identity.entity_id
        extracts = [WellExtract(name=identity.entity_name or item.path.stem)]
        key = ("reference" if item.path.suffix.lower() == ".xml" else None, item.role)
        by_scope.setdefault(key, []).append((extracts[0], asset_id, well_id or ""))

    for (scope, role), entries in by_scope.items():
        # bind_well_extracts resolves by name; when the plan already fixed a
        # well id we resolve directly to avoid re-matching ambiguity.
        unresolved = []
        for extract, asset_id, well_id in entries:
            if well_id:
                from paleo_workbench.project.domain import (
                    upsert_entity_asset_link,
                )

                _, created = upsert_entity_asset_link(
                    project,
                    entity_type="well",
                    entity_id=well_id,
                    asset_id=asset_id,
                    role=role or "other",
                    is_primary=False,
                )
                report.bound_links += 1 if created else 0
            else:
                unresolved.append((extract, asset_id))
        if unresolved:
            binding_report = bind_well_extracts(
                project,
                [e for e, _ in unresolved],
                asset_id=None,
                spatial_scope=scope,
                asset_role=role or "well_log",
            )
            report.created_entities += binding_report.wells_created
            # bind_well_extracts without asset_id only creates entities; link
            # them explicitly afterwards.
            from paleo_workbench.project.domain import resolve_well, upsert_entity_asset_link

            for extract, asset_id in unresolved:
                outcome = resolve_well(project, name=extract.name)
                if outcome.matched and outcome.well_id:
                    _, created = upsert_entity_asset_link(
                        project,
                        entity_type="well",
                        entity_id=outcome.well_id,
                        asset_id=asset_id,
                        role=role or "well_log",
                        is_primary=False,
                    )
                    report.bound_links += 1 if created else 0
                else:
                    report.issues.append(
                        f"{extract.name}: 井身份无法确定，资产 {asset_id} 未绑定"
                    )

    # Primary selection for items the plan marked primary.
    from paleo_workbench.project.domain import upsert_entity_asset_link

    for item, asset_id in staged:
        if not item.primary:
            continue
        identity = item.identity
        if identity.entity_type == "well" and identity.entity_id:
            upsert_entity_asset_link(
                project,
                entity_type="well",
                entity_id=identity.entity_id,
                asset_id=asset_id,
                role=item.role or "other",
                is_primary=True,
            )
        elif identity.entity_type == "seismic_survey" and identity.entity_id:
            upsert_entity_asset_link(
                project,
                entity_type="seismic_survey",
                entity_id=identity.entity_id,
                asset_id=asset_id,
                role=item.role or "seismic_volume",
                is_primary=True,
            )


def _ensure_survey(project: Any, identity: IdentityProposal, report: IngestExecuteReport):
    from paleo_workbench.project.domain import SeismicSurveyEntity, survey_registry

    registry = survey_registry(project)
    survey = registry.by_key(identity.entity_name) if identity.entity_name else None
    if survey is not None:
        return survey
    if not identity.new_entity:
        report.issues.append(
            f"调查 {identity.entity_name!r} 未匹配且未标记新建，跳过绑定"
        )
        return None
    survey = SeismicSurveyEntity(name=identity.entity_name)
    project.seismic_surveys.append(survey)
    report.created_entities += 1
    return survey


def _ensure_geological(
    project: Any, item: PlannedItem, asset_id: str, report: IngestExecuteReport
) -> None:
    from paleo_workbench.catalog.domain_binding import normalize_well_name
    from paleo_workbench.project.domain import DomainEntity, upsert_entity_asset_link

    kind, entity_kind, role = {
        "horizon": ("geological", "horizon", "horizon"),
        "fault": ("geological", "fault", "fault"),
        "faults": ("geological", "fault", "fault"),
        "well_stratification": ("geological", "tops", "tops"),
    }.get(item.type, ("geological", item.type, "other"))
    normalized = normalize_well_name(item.identity.entity_name)
    entity = next(
        (
            e
            for e in getattr(project, "geological_entities", None) or ()
            if normalize_well_name(e.name) == normalized and e.kind == kind
        ),
        None,
    )
    if entity is None:
        entity = DomainEntity(kind=kind, name=item.identity.entity_name, entity_kind=entity_kind)
        project.geological_entities.append(entity)
        report.created_entities += 1
    _, created = upsert_entity_asset_link(
        project,
        entity_type="geological_entity",
        entity_id=entity.id,
        asset_id=asset_id,
        role=role,
        is_primary=True,
    )
    report.bound_links += 1 if created else 0
