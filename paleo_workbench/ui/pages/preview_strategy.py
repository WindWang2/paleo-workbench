from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.tokens import format_size

MAX_PREVIEW_BYTES = 8192
MAX_PREVIEW_LINES = 20
TEXT_FORMATS = {"txt", "xml"}
TABLE_FORMATS = {"csv", "dat"}
PDF_FORMATS = {"pdf"}
MARKDOWN_FORMATS = {"md", "markdown", "htm", "html"}
JSON_FORMATS = {"json", "geojson"}
AUDIO_FORMATS = {"wav", "mp3", "flac", "ogg", "m4a"}
PROFESSIONAL_FORMATS = {
    "las",
    "sgy",
    "segy",
    "xlsx",
    "xls",
    "ppt",
    "pptx",
    "wlp",
    "dfb",
}


@dataclass(frozen=True)
class PreviewState:
    mode: str
    title: str
    lines: list[str]
    image_path: str | None = None
    document_path: str | None = None
    warning: str = ""


def _display_path(path: str, base_path: Path | None = None) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or base_path is None:
        return path
    try:
        return (base_path.parent / candidate).resolve().as_posix()
    except OSError:
        # resolve() can raise on over-long/unprobeable paths; showing the
        # unresolved join keeps the detail panel alive (#891).
        return (base_path.parent / candidate).as_posix()


def _summary_lines(name: str, path: str, fmt: str, size: object = None) -> list[str]:
    lines = [f"文件: {name}", f"格式: {fmt}", f"路径: {path}"]
    if size is not None:
        try:
            formatted_size = format_size(int(size))
        except (ValueError, TypeError):
            formatted_size = str(size)
        lines.append(f"大小: {formatted_size}")
    return lines


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data


def _read_preview_lines(
    path: str,
    max_bytes: int = MAX_PREVIEW_BYTES,
    max_lines: int = MAX_PREVIEW_LINES,
) -> tuple[list[str], str]:
    try:
        data = Path(path).read_bytes()[:max_bytes]
    except OSError as exc:
        return [], f"{Path(path).name}: {exc.__class__.__name__}"
    if _looks_binary(data):
        return [], "内容看起来是二进制，使用安全摘要预览"
    text = data.decode("utf-8", errors="replace")
    raw_lines = text.splitlines()
    lines = raw_lines[:max_lines]
    warning = f"仅显示前 {max_lines} 行" if len(raw_lines) > max_lines else ""
    return lines, warning


def preview_for_resource(
    resource: ResourceItem,
    base_path: Path | None = None,
) -> PreviewState:
    path = _display_path(resource.path, base_path)
    fmt = resource.format.lower()
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

    # Unprobeable paths (over-long, EACCES) count as absent rather than
    # raising out of the detail-panel slot (#882/#891).
    try:
        path_exists = Path(path).exists()
    except OSError:
        path_exists = False

    if (
        not path_exists
        and fmt in TEXT_FORMATS | TABLE_FORMATS | PDF_FORMATS | PROFESSIONAL_FORMATS | MARKDOWN_FORMATS | JSON_FORMATS
    ):
        return PreviewState("metadata", resource.name, lines, warning="文件不存在")

    if resource.type in image_types or resource.format in image_formats:
        return PreviewState("image", resource.name, lines, image_path=path)
    if fmt == "pdf":
        return PreviewState("pdf", resource.name, lines, document_path=path)
    if fmt in AUDIO_FORMATS:
        return PreviewState("media", resource.name, lines)
    if fmt in MARKDOWN_FORMATS and path_exists:
        return PreviewState("rich_text", resource.name, lines)
    if fmt in JSON_FORMATS and path_exists:
        return PreviewState("json_tree", resource.name, lines)
    if fmt in TEXT_FORMATS:
        preview_lines, warning = _read_preview_lines(path)
        if preview_lines:
            return PreviewState(
                "text",
                resource.name,
                lines + preview_lines,
                warning=warning,
            )
        return PreviewState(
            "metadata",
            resource.name,
            lines,
            warning=warning or "暂不支持预览",
        )
    if fmt in TABLE_FORMATS:
        preview_lines, warning = _read_preview_lines(path)
        if preview_lines:
            return PreviewState(
                "table",
                resource.name,
                lines + preview_lines,
                warning=warning,
            )
        return PreviewState(
            "metadata",
            resource.name,
            lines,
            warning=warning or "暂不支持预览",
        )
    if fmt in PROFESSIONAL_FORMATS and resource.type not in {"well_log", "seismic"}:
        return PreviewState(
            "metadata",
            resource.name,
            lines,
            warning="此格式暂使用安全摘要预览",
        )
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
