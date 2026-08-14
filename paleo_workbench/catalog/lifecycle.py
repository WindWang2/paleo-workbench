"""Business-to-catalog lifecycle helpers.

This module is the single place where the workbench's domain operations
(import / factor-map / prediction / export / finalize) are translated into
:class:`~paleo_workbench.catalog.port.CatalogPort` calls. Keeping the glue here
means each business module only calls a small, intention-revealing function
instead of every catalog primitive, and the mapping rules live in one auditable
spot.

Key mappings (domain → data provenance):

- ``ResourceItem`` (legacy) → managed RAW / external RAW ``DataVersionRef`` via
  :func:`register_resource_input`. Sets the legacy bridge so
  ``resolve_legacy_resource`` works.
- ``FactorMapTask`` interpolation → INTERMEDIATE version + ``factor_map`` run.
- ``PredictionTask`` → DERIVED version + ``prediction`` run consuming factor
  versions.
- ``ExportArtifact`` (any export) → OUTPUT version + ``export`` run, with
  lineage back to the source resource/task versions.
- ``VersionSet`` finalize → OUTPUT version for any produced result file.

These helpers degrade gracefully when no catalog backend is active (e.g. no
project open) — they no-op and the legacy code path keeps working — and when
legacy ids have no version yet.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from paleo_workbench.catalog import (
    CatalogPort,
    DataStage,
    DataVersionRef,
    get_catalog,
    sha256_file_or_none,
)

_log = logging.getLogger("paleo_workbench.catalog")

if TYPE_CHECKING:
    from paleo_workbench.project.models import (
        ExportArtifact,
        FactorMapTask,
        PredictionTask,
        ProjectDocument,
        ResourceItem,
        VersionSnapshot,
    )


# ---------------------------------------------------------------- inputs / legacy
def register_resource_input(
    resource: "ResourceItem",
    *,
    catalog: CatalogPort | None = None,
) -> DataVersionRef | None:
    """Register a legacy ``ResourceItem`` as a catalog input version.

    - Managed (``external=False``) → managed immutable RAW snapshot.
    - External (``external=True``) → unmanaged RAW link; the source may go missing.

    The resource's existing ``checksum`` is reused when present. When it is
    missing (the common case — ``import_service`` records ``checksum=None``),
    it is computed once from the on-disk file so that integrity verification
    and managed-input identity actually work for real imports. The legacy
    ``resource.id`` is recorded as the bridge key so
    ``resolve_legacy_resource`` finds this version.

    Returns None when no catalog backend is active (no project open).
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None
    checksum = resource.checksum
    if checksum is None:
        # Import does not hash; compute lazily so RAW immutability + integrity
        # are meaningful for real data (returns None if unreadable/missing).
        checksum = sha256_file_or_none(resource.path)
    return cat.register_input(
        name=resource.name,
        path=resource.path,
        checksum=checksum,
        kind=resource.type,
        format=resource.format,
        external=bool(resource.external),
        tags=list(resource.tags or []),
        legacy_resource_id=resource.id,
    )


def resolve_resource_version(
    resource_id: str,
    *,
    catalog: CatalogPort | None = None,
) -> DataVersionRef | None:
    """Resolve a legacy ``resource_id`` to its registered version (None if unknown)."""
    cat = catalog or get_catalog()
    if cat is None:
        return None
    return cat.resolve_legacy_resource(resource_id)


def migrate_project_resources(
    project: "ProjectDocument",
    *,
    catalog: CatalogPort | None = None,
) -> list[DataVersionRef]:
    """Register every legacy ``ResourceItem`` in a project as input versions.

    Used when opening a legacy (ResourceItem-only) project so the rest of the
    workflow can resolve inputs to versions. Idempotent: re-running on the same
    managed resource returns the existing version. Returns an empty list when
    no catalog backend is active.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return []
    refs = []
    for r in project.resources:
        ref = register_resource_input(r, catalog=cat)
        if ref is not None:
            refs.append(ref)
    return refs


def resolve_input_versions(
    resource_ids: list[str] | None,
    *,
    catalog: CatalogPort | None = None,
) -> list[str]:
    """Resolve a list of legacy resource ids to version ids.

    Unknown ids are dropped (with the assumption that the caller's legacy path
    still functions). Returns version ids ready for ``begin_run``.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return []
    out: list[str] = []
    for rid in resource_ids or []:
        ref = cat.resolve_legacy_resource(rid)
        if ref is not None:
            out.append(ref.version_id)
    return out


# -------------------------------------------------------------------- factor map
def register_factor_map_run(
    task: "FactorMapTask",
    *,
    catalog: CatalogPort | None = None,
    intermediate_path: str | None = None,
    intermediate_checksum: str | None = None,
    extra_input_version_ids: list[str] | None = None,
    interpretation_version_ids: list[str] | None = None,
    project: "ProjectDocument | None" = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register a factor-map interpolation run + its INTERMEDIATE output.

    ``task.input_resource_ids`` are resolved to versions (legacy bridge) and
    become the run's declared inputs. Horizon interpretation versions for the
    task's ``target_horizon`` (from *project* or *interpretation_version_ids*)
    are also declared so Stage-9 freshness can detect interpretation edits.
    The interpolation grid is registered as INTERMEDIATE only when a real
    persisted path is given; otherwise the run is recorded with no output
    version (the grid lives in ``task.parameters`` as in-memory domain state).

    Returns ``(run, version_or_None)``; ``(None, None)`` when no catalog
    backend is active.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    input_ids = resolve_input_versions(task.input_resource_ids, catalog=cat)
    seen = set(input_ids)
    for vid in list(extra_input_version_ids or []) + list(
        interpretation_version_ids or []
    ):
        if vid and vid not in seen:
            seen.add(vid)
            input_ids.append(vid)
    # Auto-collect matching horizon interpretation current versions from project.
    if project is not None and not interpretation_version_ids:
        target = (getattr(task, "target_horizon", None) or "").strip()
        for ref in getattr(project, "horizon_interpretations", None) or []:
            if target and getattr(ref, "horizon_key", "") != target:
                # Also match by name when keys differ slightly
                if getattr(ref, "name", "") != target:
                    continue
            vid = getattr(ref, "current_version_id", None)
            if vid and vid not in seen:
                seen.add(vid)
                input_ids.append(vid)
    run = cat.begin_run(
        operation="factor_map",
        input_version_ids=input_ids,
        parameters={
            "factor_type": task.factor_type,
            "target_horizon": task.target_horizon,
            "method": task.method,
        },
        generator_version=task.generator_version,
        domain_task_id=task.id,
        input_snapshot_hash=task.input_snapshot_hash or None,
    )
    version: DataVersionRef | None = None
    if intermediate_path:
        version = cat.register_intermediate(
            run_id=run.run_id,
            name=f"{task.name} grid",
            path=intermediate_path,
            checksum=intermediate_checksum,
            kind="factor_map_grid",
            format="npz",
            tags=[task.factor_type] if task.factor_type else [],
        )
    cat.complete_run(run.run_id)
    return run, version


def register_persisted_factor_grids(
    project: "ProjectDocument",
    *,
    catalog: CatalogPort | None = None,
) -> list[DataVersionRef]:
    """Register unversioned task-side grid artifacts as INTERMEDIATE outputs.

    Project save owns artifact creation; this helper owns the catalog half of that
    lifecycle.  It is idempotent for an existing live version id and intentionally
    never falls back to recomputing a missing artifact.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return []
    registered: list[DataVersionRef] = []
    for task in project.factor_map_tasks:
        path = getattr(task, "grid_artifact_path", None)
        if not path:
            continue
        existing = getattr(task, "grid_artifact_version_id", None)
        if existing and cat.resolve_version(existing) is not None:
            continue
        artifact = Path(path)
        if not artifact.is_file():
            _log.warning("factor-grid artifact missing; cannot register: %s", artifact)
            continue
        run, version = register_factor_map_run(
            task,
            catalog=cat,
            intermediate_path=artifact.as_posix(),
            intermediate_checksum=sha256_file_or_none(artifact),
            project=project,
        )
        if version is None:
            continue
        task.grid_artifact_path = version.path
        task.grid_artifact_version_id = version.version_id
        registered.append(version)
    return registered


def register_horizon_interpretation_run(
    *,
    name: str,
    path: str,
    checksum: str | None = None,
    source_version_ids: list[str] | None = None,
    parent_version_id: str | None = None,
    scientific_fingerprint: str | None = None,
    domain_task_id: str | None = None,
    catalog: CatalogPort | None = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register a horizon interpretation as DERIVED + lineage run.

    RAW sources are never overwritten; each save produces a new immutable version.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    inputs = list(source_version_ids or [])
    if parent_version_id and parent_version_id not in inputs:
        inputs.append(parent_version_id)
    run = cat.begin_run(
        operation="horizon_interpretation",
        input_version_ids=inputs,
        parameters={
            "scientific_fingerprint": scientific_fingerprint,
            "parent_version_id": parent_version_id,
        },
        generator_version="horizon-interp-v1",
        domain_task_id=domain_task_id,
        input_snapshot_hash=scientific_fingerprint,
    )
    try:
        version = cat.register_derived(
            run_id=run.run_id,
            name=name,
            path=path,
            checksum=checksum,
            kind="horizon_interpretation",
            format="npz",
            tags=["interpretation", "horizon"],
        )
    except Exception:
        # No orphan RUNNING run (H7 failure injection).
        try:
            cat.complete_run(run.run_id, status="failed")
        except Exception:
            pass
        raise
    cat.complete_run(run.run_id)
    return run, version


# --------------------------------------------------------------------- prediction
_COMPLETE_RUN_STATUSES = frozenset({"complete", "completed"})


def _versions_for_domain_tasks(
    task_ids: list[str],
    *,
    catalog: CatalogPort,
) -> list[str]:
    """Resolve domain task ids to version ids through the run graph.

    Uses only the latest **complete** DataRun per ``domain_task_id`` (catalog
    list order is oldest→newest). Prefer that run's output versions. When the
    latest complete run has no file outputs (in-memory-only factor grids),
    fall back to *that* run's declared input versions.

    Failed / cancelled / running later runs are ignored so a retry that dies
    cannot replace a real product with RAW ancestor ids.
    """
    wanted = set(task_ids)
    if not wanted:
        return []
    # Round-2 + round-3 combined semantics: the latest COMPLETE run per task
    # wins; a run WITH file outputs is preferred over a complete-but-empty
    # run (in-memory propagation). Failed/running/cancelled runs never stand
    # in for the product, and withdrawn (trashed) outputs are excluded (H5).
    latest_complete: dict[str, Any] = {}
    latest_with_outputs: dict[str, Any] = {}
    for run in catalog.list_runs():
        tid = run.domain_task_id
        if tid not in wanted:
            continue
        status = (getattr(run, "status", "") or "").lower()
        if status not in _COMPLETE_RUN_STATUSES:
            continue
        latest_complete[tid] = run
        if list(getattr(run, "output_version_ids", None) or []):
            latest_with_outputs[tid] = run
    out: list[str] = []
    seen: set[str] = set()
    for tid, run in latest_complete.items():
        chosen_run = latest_with_outputs.get(tid, run)
        outputs = list(chosen_run.output_version_ids or [])
        chosen = outputs if outputs else list(chosen_run.input_version_ids or [])
        for vid in chosen:
            if vid in seen:
                continue
            if outputs:
                ref = catalog.resolve_version(vid)
                if ref is not None and getattr(ref, "trashed", False):
                    # Withdrawn output must not enter a production run (H5-a).
                    continue
            seen.add(vid)
            out.append(vid)
    return out


def register_prediction_run(
    task: "PredictionTask",
    *,
    factor_versions: list[str] | None = None,
    factor_task_ids: list[str] | None = None,
    catalog: CatalogPort | None = None,
    result_path: str | None = None,
    result_checksum: str | None = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register a prediction run consuming factor-map versions.

    Prediction results today live in ``task.result_summary`` (in-memory domain
    state), so by default no file version is registered — the run records the
    provenance (inputs + generator_version + snapshot_hash). When a real result
    file exists (e.g. a serialized prediction payload), it is registered as
    DERIVED.

    ``factor_task_ids`` (domain task ids) are resolved to their registered
    DataRun output versions when ``factor_versions`` is not given directly.

    Returns ``(run, version_or_None)``; ``(None, None)`` when no catalog
    backend is active.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    if factor_versions is None and factor_task_ids:
        factor_versions = _versions_for_domain_tasks(factor_task_ids, catalog=cat)
    run = cat.begin_run(
        operation="prediction",
        input_version_ids=list(factor_versions or []),
        parameters={"adapter_kind": task.adapter_kind},
        generator_version=task.generator_version,
        domain_task_id=task.id,
        input_snapshot_hash=task.input_snapshot_hash or None,
    )
    version: DataVersionRef | None = None
    if result_path:
        version = cat.register_derived(
            run_id=run.run_id,
            name=f"{task.name} result",
            path=result_path,
            checksum=result_checksum,
            kind="prediction_result",
            format="json",
        )
    cat.complete_run(run.run_id)
    return run, version


# ------------------------------------------------------------------------ export
def resource_ids_for_paths(
    resources: Iterable[Any],
    paths: Iterable[Any],
    *,
    project_path: str | Path | None = None,
) -> list[str]:
    """Resource ids whose payload path matches any of *paths* (absolute form).

    Relative resource paths (the import contract stores project-relative
    paths) resolve against the PROJECT directory — never the process CWD —
    mirroring ``adapter.register_input``. When *project_path* is unknown,
    relative paths honestly match nothing rather than guessing via CWD.
    """
    base = Path(project_path).expanduser().resolve().parent if project_path else None

    def _abs(raw: Any) -> Path | None:
        try:
            p = Path(str(raw))
            if not p.is_absolute():
                if base is None:
                    return None
                p = base / p
            return p.resolve()
        except (OSError, RuntimeError):
            return None

    wanted = {_abs(p) for p in paths}
    wanted.discard(None)
    ids: list[str] = []
    for resource in resources or []:
        resource_path = _abs(getattr(resource, "path", ""))
        if resource_path is not None and resource_path in wanted:
            ids.append(resource.id)
    return ids


def _resolve_export_inputs(
    source_version_ids: list[str] | None,
    source_task_ids: list[str] | None,
    linked_id: str,
    *,
    catalog: CatalogPort,
) -> list[str]:
    """Resolve an export's declared inputs to version ids.

    Sources are resolved in three ways so the OUTPUT's lineage reaches back to
    real data even when intermediates are in-memory domain state:

    1. Explicit ``source_version_ids`` (direct version ids).
    2. ``linked_id`` + ``source_task_ids`` that are legacy resource ids
       (``resolve_legacy_resource``).
    3. ``source_task_ids`` that are domain task ids (factor/prediction) —
       resolved through the run graph via ``_versions_for_domain_tasks``,
       which propagates both the task's output versions and its declared
       inputs (so an in-memory-only result still links to its RAW ancestors).
    """
    declared: list[str] = list(source_version_ids or [])
    seen = set(declared)
    legacy_candidates = list(source_task_ids or [])
    if linked_id:
        legacy_candidates.append(linked_id)
    for tid in legacy_candidates:
        ref = catalog.resolve_legacy_resource(tid)
        if ref is not None and ref.version_id not in seen:
            seen.add(ref.version_id)
            declared.append(ref.version_id)
    # Domain task ids (factor/prediction) → versions through the run graph.
    task_versions = _versions_for_domain_tasks(list(source_task_ids or []), catalog=catalog)
    for vid in task_versions:
        if vid not in seen:
            seen.add(vid)
            declared.append(vid)
    return declared


def register_export_run(
    *,
    artifact: "ExportArtifact",
    source_version_ids: list[str] | None = None,
    source_task_ids: list[str] | None = None,
    catalog: CatalogPort | None = None,
) -> tuple[Any, DataVersionRef]:
    """Register an OUTPUT version for an export, with lineage to its sources.

    Backward-compatible surface for callers that need ``(run, version)``; the
    actual registration routes through :func:`register_export_output` so every
    production export path shares ONE implementation (no parallel provenance).

    Returns ``(run, version)``; ``(None, None)`` when no catalog backend is
    active.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    version = register_export_output(
        name=Path(artifact.output_path).name,
        output_path=artifact.output_path,
        fmt=artifact.format,
        source_version_ids=source_version_ids,
        source_task_ids=source_task_ids,
        linked_id=artifact.linked_id,
        catalog=cat,
    )
    run = None
    if version is not None and version.producing_run_id:
        run = cat.resolve_run(version.producing_run_id)
    return run, version


def register_export_output(
    *,
    name: str,
    output_path: str,
    fmt: str,
    source_version_ids: list[str] | None = None,
    source_task_ids: list[str] | None = None,
    linked_id: str = "",
    catalog: CatalogPort | None = None,
) -> DataVersionRef:
    """Register an OUTPUT version directly (no ExportArtifact required).

    Used by export paths that previously wrote a file with zero tracking
    (e.g. ``export_well_canvas``). Returns the registered version, or None
    when no catalog backend is active.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None
    declared = _resolve_export_inputs(source_version_ids, source_task_ids, linked_id, catalog=cat)
    run = cat.begin_run(
        operation="export",
        input_version_ids=declared,
        parameters={"format": fmt, "linked_id": linked_id},
        generator_version=None,
    )
    checksum = sha256_file_or_none(output_path)
    version = cat.register_output(
        run_id=run.run_id,
        name=name or Path(output_path).name,
        path=output_path,
        checksum=checksum,
        kind="export",
        format=fmt,
    )
    cat.complete_run(run.run_id)
    return version


# ---------------------------------------------------------------- map compile
def register_map_compile_run(
    *,
    name: str,
    input_version_ids: list[str] | None = None,
    source_task_ids: list[str] | None = None,
    domain_task_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    result_path: str | None = None,
    result_checksum: str | None = None,
    catalog: CatalogPort | None = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register a paleomap compilation DataRun (+ optional DERIVED version).

    Inputs should be the exact factor/prediction/interpretation version ids the
    map actually consumed — not every product in the project.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    declared = list(input_version_ids or [])
    if source_task_ids:
        for vid in _versions_for_domain_tasks(list(source_task_ids), catalog=cat):
            if vid not in declared:
                declared.append(vid)
    run = cat.begin_run(
        operation="map_compile",
        input_version_ids=declared,
        parameters=dict(parameters or {}),
        generator_version=(parameters or {}).get("generator_version")
        if parameters
        else None,
        domain_task_id=domain_task_id,
    )
    version: DataVersionRef | None = None
    if result_path:
        version = cat.register_derived(
            run_id=run.run_id,
            name=name,
            path=result_path,
            checksum=result_checksum or sha256_file_or_none(result_path),
            kind="paleomap",
            format="json",
        )
    cat.complete_run(run.run_id)
    return run, version


# -------------------------------------------------------------------------- qc
def register_qc_run(
    *,
    name: str,
    input_version_ids: list[str] | None = None,
    source_task_ids: list[str] | None = None,
    domain_task_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    report_path: str | None = None,
    report_checksum: str | None = None,
    catalog: CatalogPort | None = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register a QC DataRun bound to the exact result versions it checked."""
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    declared = list(input_version_ids or [])
    if source_task_ids:
        for vid in _versions_for_domain_tasks(list(source_task_ids), catalog=cat):
            if vid not in declared:
                declared.append(vid)
    run = cat.begin_run(
        operation="qc",
        input_version_ids=declared,
        parameters=dict(parameters or {}),
        generator_version="qc-v1",
        domain_task_id=domain_task_id,
    )
    version: DataVersionRef | None = None
    try:
        if report_path:
            version = cat.register_output(
                run_id=run.run_id,
                name=name,
                path=report_path,
                checksum=report_checksum or sha256_file_or_none(report_path),
                kind="qc_report",
                format="json",
                # One asset per checked document: re-running QC appends a
                # version instead of spawning a new single-version asset.
                reuse_legacy_id=(
                    f"qc-report-{domain_task_id}" if domain_task_id else None
                ),
            )
        cat.complete_run(run.run_id)
    except Exception:
        # No orphan RUNNING run when the output registration fails.
        try:
            cat.complete_run(run.run_id, status="failed")
        except Exception:
            pass
        raise
    return run, version


# ----------------------------------------------------------- version finalize
def register_finalize_run(
    port: CatalogPort | None = None,
    *,
    snapshot: "VersionSnapshot",
    operator: str = "",
    note: str = "",
    version_set_id: str | None = None,
) -> str | None:
    """Register a VersionSet finalization as a ``version_finalize`` DataRun.

    Input versions are resolved from the snapshot's map document through the
    run graph: the production map compile runs carry the map document id as
    their domain task id, so the finalized map's registered DERIVED version is
    reachable that way. The finalize itself produces no new file — the run
    records who signed off which snapshot over which map versions.

    Returns the run id, or None when no catalog backend is active or no input
    version could be resolved (never raises — an untraceable finalize is not
    registered rather than fabricating provenance; a skipped registration is
    logged as a warning so the gap stays discoverable).
    """
    cat = port or get_catalog()
    if cat is None:
        return None
    input_ids = _versions_for_domain_tasks(
        [snapshot.map_document_id], catalog=cat
    )
    if not input_ids:
        _log.warning(
            "version_finalize run skipped: no resolvable catalog inputs for map %s",
            snapshot.map_document_id,
        )
        return None
    run = cat.begin_run(
        operation="version_finalize",
        input_version_ids=input_ids,
        parameters={
            "version_set_id": version_set_id,
            "snapshot_id": snapshot.id,
            "operator": operator,
            "note": note,
            "content_fingerprint": snapshot.content_fingerprint,
        },
        generator_version="versioning-v1",
        domain_task_id=version_set_id,
    )
    try:
        cat.complete_run(run.run_id)
    except Exception:
        # No orphan RUNNING run if completion booking fails.
        try:
            cat.complete_run(run.run_id, status="failed")
        except Exception:
            pass
        raise
    return run.run_id


# ----------------------------------------------------- stratigraphic correlation
def register_stratigraphic_correlation_run(
    *,
    name: str,
    path: str,
    checksum: str | None = None,
    source_version_ids: list[str] | None = None,
    parent_version_id: str | None = None,
    scientific_fingerprint: str | None = None,
    domain_task_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    catalog: CatalogPort | None = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register multi-well correlation interpretation as DERIVED + lineage run."""
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    inputs = list(source_version_ids or [])
    if parent_version_id and parent_version_id not in inputs:
        inputs.append(parent_version_id)
    params = dict(parameters or {})
    params["scientific_fingerprint"] = scientific_fingerprint
    params["parent_version_id"] = parent_version_id
    run = cat.begin_run(
        operation="stratigraphic_correlation",
        input_version_ids=inputs,
        parameters=params,
        generator_version="strat-corr-v1",
        domain_task_id=domain_task_id,
        input_snapshot_hash=scientific_fingerprint,
    )
    try:
        version = cat.register_derived(
            run_id=run.run_id,
            name=name,
            path=path,
            checksum=checksum,
            kind="stratigraphic_correlation",
            format="json",
            tags=["interpretation", "correlation", "tops"],
        )
    except Exception:
        # No orphan RUNNING run (H7 failure injection).
        try:
            cat.complete_run(run.run_id, status="failed")
        except Exception:
            pass
        raise
    cat.complete_run(run.run_id)
    return run, version


def register_fault_interpretation_run(
    *,
    name: str,
    path: str,
    checksum: str | None = None,
    source_version_ids: list[str] | None = None,
    parent_version_id: str | None = None,
    scientific_fingerprint: str | None = None,
    domain_task_id: str | None = None,
    catalog: CatalogPort | None = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register fault interpretation polylines as DERIVED + lineage run."""
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    inputs = list(source_version_ids or [])
    if parent_version_id and parent_version_id not in inputs:
        inputs.append(parent_version_id)
    run = cat.begin_run(
        operation="fault_interpretation",
        input_version_ids=inputs,
        parameters={
            "scientific_fingerprint": scientific_fingerprint,
            "parent_version_id": parent_version_id,
        },
        generator_version="fault-interp-v1",
        domain_task_id=domain_task_id,
        input_snapshot_hash=scientific_fingerprint,
    )
    try:
        version = cat.register_derived(
            run_id=run.run_id,
            name=name,
            path=path,
            checksum=checksum,
            kind="fault_interpretation",
            format="json",
            tags=["interpretation", "fault"],
        )
    except Exception:
        # No orphan RUNNING run (H7 failure injection) — same compensation as
        # horizon / stratigraphic correlation registration.
        try:
            cat.complete_run(run.run_id, status="failed")
        except Exception:
            pass
        raise
    try:
        cat.complete_run(run.run_id)
    except Exception:
        # The version is committed; at least never leave a stuck RUNNING run.
        try:
            cat.complete_run(run.run_id, status="failed")
        except Exception:
            pass
        raise
    return run, version


# -------------------------------------------------------------------- modeling
def register_modeling_run(
    *,
    name: str,
    source: str = "synthetic/demo",
    demo: bool | None = None,
    parameters: dict[str, Any] | None = None,
    input_version_ids: list[str] | None = None,
    output_path: str | None = None,
    output_format: str = "",
    catalog: CatalogPort | None = None,
) -> tuple[Any, DataVersionRef | None]:
    """Register a 3D geological-modeling DataRun (and optional DERIVED version).

    Honesty contract (P2): the run's parameters always record ``source`` and
    ``demo``. Synthetic/demo modeling is registered as a run WITHOUT an output
    version (the demo result is in-memory); a real-data worker may attach a
    payload file via *output_path* (registered as DERIVED, P3 seam).

    Returns ``(run, version_or_None)``; ``(None, None)`` when no catalog
    backend is active.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    is_demo = source == "synthetic/demo" if demo is None else bool(demo)
    params = dict(parameters or {})
    params["source"] = source
    params["demo"] = is_demo
    run = cat.begin_run(
        operation="modeling",
        input_version_ids=list(input_version_ids or []),
        parameters=params,
        generator_version=None,
    )
    version: DataVersionRef | None = None
    if output_path:
        version = cat.register_derived(
            run_id=run.run_id,
            name=name,
            path=output_path,
            checksum=sha256_file_or_none(output_path),
            kind="geomodel",
            format=output_format,
        )
    cat.complete_run(run.run_id)
    return run, version
