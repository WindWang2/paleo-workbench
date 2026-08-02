from __future__ import annotations

from pathlib import Path

from geoviz import PreviewRequest

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import safe_file_stat


def request_from_resource(
    resource: ResourceItem,
    *,
    path: str | None = None,
    semantic_type: str | None = None,
    label: str | None = None,
    comparison_crs: str | None = None,
) -> PreviewRequest:
    """Build the canonical, versioned engine request for a project resource."""
    source_path = path if path is not None else resource.path
    stat = safe_file_stat(Path(source_path))
    version_parts = []
    if resource.checksum:
        version_parts.append(f"checksum:{resource.checksum}")
    if stat is not None:
        version_parts.append(f"stat:{stat[0]}:{stat[1]}")
    source_version = "|".join(version_parts)
    metadata = resource.parsed_summary or {}
    return PreviewRequest(
        resource_id=resource.id,
        path=source_path,
        semantic_type=semantic_type or resource.type,
        format=resource.format,
        label=resource.name if label is None else label,
        source_version=source_version,
        source_crs=str(resource.crs or ""),
        coordinate_units=str(
            metadata.get("coordinate_units")
            or metadata.get("units")
            or ""
        ),
        comparison_crs=(
            str(comparison_crs)
            if comparison_crs is not None
            else str(metadata.get("comparison_crs") or "")
        ),
    )


__all__ = ["request_from_resource"]
