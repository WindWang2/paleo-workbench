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
from typing import TYPE_CHECKING, Any

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
) -> tuple[Any, DataVersionRef | None]:
    """Register a factor-map interpolation run + its INTERMEDIATE output.

    ``task.input_resource_ids`` are resolved to versions (legacy bridge) and
    become the run's declared inputs. The interpolation grid is registered as
    INTERMEDIATE only when a real persisted path is given; otherwise the run is
    recorded with no output version (the grid lives in ``task.parameters`` as
    in-memory domain state, which is not a file DataVersion).

    Returns ``(run, version_or_None)``; ``(None, None)`` when no catalog
    backend is active.
    """
    cat = catalog or get_catalog()
    if cat is None:
        return None, None
    input_ids = resolve_input_versions(task.input_resource_ids, catalog=cat)
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


# --------------------------------------------------------------------- prediction
def _versions_for_domain_tasks(
    task_ids: list[str],
    *,
    catalog: CatalogPort,
) -> list[str]:
    """Resolve domain task ids to version ids through the run graph.

    A task's DataRun is linked via ``domain_task_id``. We return both its
    registered output versions AND its declared input versions: the outputs are
    the direct lineage, but when a task produces no file version (e.g. a factor
    grid that stays in ``task.parameters``), propagating its *inputs* keeps the
    lineage chain connected back to the source RAW data.
    """
    wanted = set(task_ids)
    if not wanted:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for run in catalog.list_runs():
        if run.domain_task_id in wanted:
            for vid in run.output_version_ids:
                if vid not in seen:
                    seen.add(vid)
                    out.append(vid)
            # Propagate the run's declared inputs so in-memory-only results
            # (no output version) do not break the ancestor chain.
            for vid in run.input_version_ids:
                if vid not in seen:
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
