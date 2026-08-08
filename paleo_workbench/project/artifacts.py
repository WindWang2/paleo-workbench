from __future__ import annotations

from paleo_workbench.project.models import ExportArtifact, ProjectDocument


def record_export(
    project: ProjectDocument,
    linked_id: str,
    output_path: str,
    fmt: str,
    source_task_ids: list[str],
    *,
    source_resource_ids: list[str] | None = None,
    register_catalog: bool = True,
    catalog_output_path: str | None = None,
) -> ExportArtifact:
    """Register an export artifact and (optionally) an OUTPUT DataVersion.

    This is the single choke point through which every export flows. It keeps
    the backward-compatible ``ExportArtifact`` record (the domain surface the
    UI already shows) AND registers the catalog OUTPUT version with lineage to
    the inputs that fed the export.

    ``output_path`` is the path stored on the artifact (relativized for
    portability by some callers). ``catalog_output_path`` is the *absolute*
    path used for catalog hashing/integrity — when None, falls back to
    ``output_path``. Passing the absolute path matters because the catalog
    verifies integrity against the on-disk file, which is at the absolute
    location, not the project-relative one.

    Lineage inputs are resolved from:
      - ``source_resource_ids`` (legacy ResourceItem ids → RAW/EXTERNAL versions)
      - ``linked_id`` when it is itself a legacy resource id
      - ``source_task_ids`` (domain task ids; resolved through the run graph
        and the legacy resource bridge)

    ``register_catalog=False`` skips catalog registration (used by tests that
    only assert on the domain artifact). The artifact always carries
    ``catalog_version_id`` when registered.
    """
    artifact = ExportArtifact(
        linked_id=linked_id,
        format=fmt,
        output_path=output_path,
        included_map_elements=["legend", "north_arrow", "scale_bar"],
        source_task_ids=list(source_task_ids),
    )
    project.export_artifacts.append(artifact)

    if register_catalog:
        _register_catalog_output(
            artifact,
            source_resource_ids,
            catalog_output_path or output_path,
        )
    return artifact


def _register_catalog_output(
    artifact: ExportArtifact,
    source_resource_ids: list[str] | None,
    catalog_output_path: str,
) -> None:
    """Register the OUTPUT DataVersion for an artifact and store its version id.

    Wrapped defensively: the catalog is an adapter seam, and a registration
    failure (e.g. the file not yet on disk) must never break the export path.
    The artifact still records the export; only the provenance version is lost.
    """
    try:
        # Imported lazily so project.models has no catalog import cycle.
        from paleo_workbench.catalog import get_catalog
        from paleo_workbench.catalog.lifecycle import register_export_output

        declared: list[str] = list(source_resource_ids or [])
        if artifact.linked_id and artifact.linked_id not in declared:
            declared.append(artifact.linked_id)
        for tid in artifact.source_task_ids:
            if tid and tid not in declared:
                declared.append(tid)

        version = register_export_output(
            name=_export_name(artifact),
            output_path=catalog_output_path,
            fmt=artifact.format,
            source_version_ids=None,
            source_task_ids=declared,
            linked_id=artifact.linked_id,
            catalog=get_catalog(),
        )
        # Store the absolute path on the version so integrity resolves on disk;
        # the ExportArtifact keeps its (possibly relative) path for portability.
        version.path = catalog_output_path
        artifact.catalog_version_id = version.version_id
    except Exception:
        # Provenance is best-effort; the domain ExportArtifact is the source of
        # truth for "did the export happen". Do not raise.
        artifact.catalog_version_id = None


def _export_name(artifact: ExportArtifact) -> str:
    raw = artifact.output_path or ""
    # Works for both posix and Windows-style separators.
    for sep in ("/", "\\"):
        if sep in raw:
            raw = raw.rsplit(sep, 1)[-1]
    return raw or artifact.format or "export"
