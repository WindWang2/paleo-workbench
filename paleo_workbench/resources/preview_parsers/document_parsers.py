from __future__ import annotations

import html
import io
from pathlib import Path
import re
from typing import TYPE_CHECKING

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.project.paths import safe_file_stat
from paleo_workbench.resources.preview_parsers.models import PreviewResult
from paleo_workbench.resources.preview_parsers.table_parsers import (
    parse_error_preview,
    read_preview_chunk,
)

if TYPE_CHECKING:
    from paleo_workbench.ui.pages.preview_settings import PreviewSettings

# Upper bound (px per side) for GeoTIFF preview reads: overview levels that
# would decode more than this are not used.
_GEOTIFF_MAX_READ_PX = 2048


def resource_revision_token(asset: ResourceItem, safe_stat_fn=safe_file_stat) -> tuple[object, ...]:
    path = Path(asset.path)
    return (
        "resource",
        asset.id,
        asset.path,
        asset.type,
        asset.format,
        asset.status,
        asset.checksum,
        safe_stat_fn(path),
    )


def artifact_preview(artifact: ExportArtifact) -> PreviewResult:
    title = Path(artifact.output_path).name or artifact.output_path
    return PreviewResult(
        mode="message",
        title=title,
        path=artifact.output_path,
        revision=safe_file_stat(Path(artifact.output_path)),
        format=artifact.format,
        status="generated",
        type_label="成果",
        message=f"成果文件 · 关联对象 {artifact.linked_id}",
    )


def image_fallback(resource: ResourceItem, revision, warning: str) -> PreviewResult:
    path = Path(resource.path)
    try:
        data = path.read_bytes()
    except OSError:
        data = b""
    return PreviewResult(
        mode="image",
        title=resource.name,
        path=resource.path,
        revision=revision,
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        image_bytes=data,
        warning=warning,
    )


def geotiff_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    path = Path(resource.path)
    revision = resource_revision_token(resource)
    try:
        import rasterio
    except ImportError:
        return image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
    try:
        with rasterio.open(str(path)) as dataset:
            crs = str(dataset.crs or "未知")
            bounds = dataset.bounds
            meta = (
                ("CRS", crs),
                (
                    "范围",
                    f"{bounds.left:.4f}, {bounds.bottom:.4f}, {bounds.right:.4f}, {bounds.top:.4f}",
                ),
                ("尺寸", f"{dataset.width} × {dataset.height} × {dataset.count}"),
                ("数据类型", str(dataset.dtypes[0]) if dataset.dtypes else "未知"),
                ("Nodata", str(dataset.nodata) if dataset.nodata is not None else "无"),
            )
            target_px = settings.geotiff_thumbnail_px
            long_side = max(dataset.width, dataset.height)
            decim = max(1, (long_side + target_px - 1) // target_px)
            overviews = dataset.overviews(1)
            # Bounded read: decode a built overview instead of the full
            # resolution raster (GB-scale MemoryError risk). Prefer the
            # smallest overview reaching the thumbnail decimation, kept
            # within ~2 k px per side; fall back to the most decimated
            # level available. The base level is used when no decimation
            # is needed (source already below target) or no overviews exist.
            level = 1
            if decim > 1 and overviews:
                bounded = [
                    v for v in overviews if long_side // v <= _GEOTIFF_MAX_READ_PX
                ]
                suitable_overview = next((v for v in bounded if v >= decim), None)
                if suitable_overview is None:
                    suitable_overview = max(bounded or overviews)
                level = int(suitable_overview)
            out_height = max(1, dataset.height // level)
            out_width = max(1, dataset.width // level)
            thumbnail = dataset.read(1, out_shape=(out_height, out_width))
            if max(out_height, out_width) > target_px:
                step = max(1, (max(out_height, out_width) + target_px - 1) // target_px)
                thumbnail = thumbnail[::step, ::step]
    except Exception:
        return image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
    try:
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(thumbnail).save(buf, format="PNG")
        image_bytes = buf.getvalue()
    except Exception:
        return image_fallback(resource, revision, "地理元数据读取失败，仅显示图像")
    return PreviewResult(
        mode="geotiff",
        title=resource.name,
        path=resource.path,
        revision=revision,
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        geo_metadata=meta,
        image_bytes=image_bytes,
    )


def markdown_rich_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    """Markdown -> HTML -> QTextBrowser (rich_text mode, no WebEngine)."""
    path = Path(resource.path)
    preview_bytes, truncated = read_preview_chunk(path, settings.text_limit_kib)
    markdown = preview_bytes.decode("utf-8", errors="replace")
    warning = f"仅显示前 {settings.text_limit_kib} KiB" if truncated else ""
    return PreviewResult(
        mode="rich_text",
        title=resource.name,
        path=resource.path,
        revision=safe_file_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        rich_html=markdown_to_html(markdown),
        warning=warning,
        truncated=truncated,
    )


def markdown_to_html(markdown: str) -> str:
    rendered: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag = ""
    code_lines: list[str] = []
    in_code_block = False

    def flush_paragraph() -> None:
        if paragraph:
            rendered.append(f"<p>{' '.join(paragraph)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_items:
            rendered.append(f"<{list_tag}>{''.join(list_items)}</{list_tag}>")
            list_items.clear()
        list_tag = ""

    for line in markdown.splitlines():
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code_block:
                code = "\n".join(code_lines)
                rendered.append(f"<pre><code>{code}</code></pre>")
                code_lines.clear()
            in_code_block = not in_code_block
            continue

        escaped = html.escape(line)
        if in_code_block:
            code_lines.append(escaped)
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            rendered.append(f"<h{level}>{html.escape(heading.group(2))}</h{level}>")
            continue

        unordered = re.match(r"^[-*]\s+(.*)$", line)
        ordered = re.match(r"^\d+\.\s+(.*)$", line)
        if unordered or ordered:
            next_list_tag = "ul" if unordered else "ol"
            if list_tag and list_tag != next_list_tag:
                flush_list()
            flush_paragraph()
            list_tag = next_list_tag
            item = unordered.group(1) if unordered else ordered.group(1)
            list_items.append(f"<li>{html.escape(item)}</li>")
            continue

        flush_list()
        paragraph.append(escaped)

    if in_code_block:
        code = "\n".join(code_lines)
        rendered.append(f"<pre><code>{code}</code></pre>")
    flush_paragraph()
    flush_list()
    return "\n".join(rendered)


def json_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    import json as json_lib

    path = Path(resource.path)
    limit = settings.json_limit_mib * 1024 * 1024
    try:
        size = path.stat().st_size
    except OSError:
        return parse_error_preview(resource, "文件不存在")
    truncated = size > limit
    try:
        with path.open("rb") as handle:
            # Read only up to the limit; for oversized files this yields the
            # first ``limit`` bytes so we can attempt a truncated parse below.
            raw_bytes = handle.read(limit if truncated else limit + 1)
    except OSError:
        return parse_error_preview(resource, "文件不存在")
    raw = raw_bytes.decode("utf-8", errors="replace")
    try:
        payload = json_lib.loads(raw)
    except (json_lib.JSONDecodeError, ValueError) as exc:
        if truncated:
            # Spec: oversized files parse the first ``limit`` bytes and show a
            # truncation warning; only fall back to an error when the truncated
            # prefix genuinely cannot be parsed.
            return parse_error_preview(
                resource,
                f"JSON 文件超过预览设置上限 {settings.json_limit_mib} MiB，"
                "请在预览设置中提高上限",
            )
        return parse_error_preview(
            resource, f"JSON 解析失败: {exc.__class__.__name__}"
        )
    return PreviewResult(
        mode="json_tree",
        title=resource.name,
        path=resource.path,
        revision=resource_revision_token(resource),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        json_payload=payload,
        json_truncated=truncated,
        warning=(
            f"JSON 文件超过预览设置上限 {settings.json_limit_mib} MiB，仅解析前 "
            f"{settings.json_limit_mib} MiB" if truncated else ""
        ),
    )


def audio_preview(resource: ResourceItem) -> PreviewResult:
    return PreviewResult(
        mode="media",
        title=resource.name,
        path=resource.path,
        revision=resource_revision_token(resource),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        media_path=resource.path,
    )
