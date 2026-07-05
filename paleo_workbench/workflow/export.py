from __future__ import annotations

from paleo_workbench.project.models import ExportArtifact, ProjectDocument


def record_export(
    project: ProjectDocument,
    linked_id: str,
    output_path: str,
    fmt: str,
    source_task_ids: list[str],
) -> ExportArtifact:
    artifact = ExportArtifact(
        linked_id=linked_id,
        format=fmt,
        output_path=output_path,
        included_map_elements=["legend", "north_arrow", "scale_bar"],
        source_task_ids=source_task_ids,
    )
    project.export_artifacts.append(artifact)
    return artifact