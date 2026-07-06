from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem


@dataclass(frozen=True)
class PreviewState:
    mode: str
    title: str
    lines: list[str]
    image_path: str | None = None
    warning: str = ""


def _display_path(path: str, base_path: Path | None = None) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or base_path is None:
        return path
    return (base_path.parent / candidate).resolve().as_posix()


def _summary_lines(name: str, path: str, fmt: str, size: object = None) -> list[str]:
    lines = [f"文件: {name}", f"格式: {fmt}", f"路径: {path}"]
    if size is not None:
        lines.append(f"大小: {size} bytes")
    return lines


def preview_for_resource(
    resource: ResourceItem,
    base_path: Path | None = None,
) -> PreviewState:
    path = _display_path(resource.path, base_path)
    size = resource.parsed_summary.get("size_bytes")
    lines = _summary_lines(resource.name, path, resource.format, size)
    image_types = {"image_reference"}
    image_formats = {"png", "jpg", "jpeg", "tif", "tiff"}
    table_types = {
        "spreadsheet",
        "tabular",
        "time_depth",
        "horizon",
        "well_stratification",
    }

    if resource.type in image_types or resource.format in image_formats:
        return PreviewState("image", resource.name, lines, image_path=path)
    if resource.type in table_types:
        return PreviewState("table", resource.name, lines)
    if resource.type == "well_log":
        return PreviewState("well_log", resource.name, lines + ["预览: 测井摘要"])
    if resource.type == "seismic":
        return PreviewState("seismic", resource.name, lines + ["预览: 地震体元数据"])
    if resource.type in {"document", "reference_map", "well_reference"}:
        return PreviewState(
            "metadata",
            resource.name,
            lines,
            warning="此类型使用外部工具预览",
        )
    return PreviewState("metadata", resource.name, lines, warning="暂不支持预览")


def preview_for_artifact(
    artifact: ExportArtifact,
    base_path: Path | None = None,
) -> PreviewState:
    path = _display_path(artifact.output_path, base_path)
    lines = [
        f"格式: {artifact.format}",
        f"路径: {path}",
        f"关联: {artifact.linked_id}",
    ]
    return PreviewState("artifact", f"成果文件 · {artifact.format}", lines)
