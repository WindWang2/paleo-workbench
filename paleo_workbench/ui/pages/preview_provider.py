from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from paleo_workbench.project.models import ExportArtifact, ResourceItem

MAX_TEXT_PREVIEW_BYTES = 256 * 1024
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 40

PreviewMode = Literal["empty", "pdf", "image", "text", "table", "message"]

TEXT_FORMATS = {"txt", "text", "log", "dat", "json", "xml"}
TABLE_FORMATS = {"csv", "tsv"}
IMAGE_FORMATS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}
PDF_FORMATS = {"pdf"}


@dataclass(frozen=True)
class PreviewResult:
    mode: PreviewMode
    title: str
    path: str = ""
    revision: tuple[int, int] | None = None
    format: str = ""
    status: str = ""
    type_label: str = ""
    message: str = ""
    warning: str = ""
    text: str = ""
    table_headers: tuple[str, ...] = field(default_factory=tuple)
    table_rows: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    truncated: bool = False


class PreviewProvider:
    def __init__(self) -> None:
        self._cache: dict[tuple, PreviewResult] = {}

    def clear(self) -> None:
        self._cache.clear()

    def preview(self, asset: ResourceItem | ExportArtifact | None) -> PreviewResult:
        if asset is None:
            return PreviewResult(
                mode="empty",
                title="请选择数据项",
                message="从列表中选择一个数据、成果或文件",
            )

        key = self._cache_key(asset)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        result = self._build_preview(asset)
        self._cache[key] = result
        return result

    def _cache_key(self, asset: ResourceItem | ExportArtifact) -> tuple:
        if isinstance(asset, ExportArtifact):
            path = Path(asset.output_path)
            return (
                "artifact",
                asset.id,
                asset.output_path,
                asset.format,
                self._safe_stat(path),
            )

        path = Path(asset.path)
        return (
            "resource",
            asset.id,
            asset.path,
            asset.type,
            asset.format,
            asset.status,
            asset.checksum,
            self._safe_stat(path),
        )

    def _safe_stat(self, path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    def _build_preview(self, asset: ResourceItem | ExportArtifact) -> PreviewResult:
        if isinstance(asset, ExportArtifact):
            return self._artifact_preview(asset)

        path = Path(asset.path)
        revision = self._safe_stat(path)
        fmt = asset.format.lower()
        title = asset.name

        if not path.exists():
            return PreviewResult(
                mode="message",
                title=title,
                path=asset.path,
                revision=revision,
                format=asset.format,
                status="missing",
                type_label=asset.type,
                message="文件不存在",
            )

        if fmt in PDF_FORMATS:
            return PreviewResult(
                mode="pdf",
                title=title,
                path=asset.path,
                revision=revision,
                format=asset.format,
                status=asset.status,
                type_label=asset.type,
            )

        if fmt in IMAGE_FORMATS or asset.type in {"image_reference", "reference_map"}:
            return PreviewResult(
                mode="image",
                title=title,
                path=asset.path,
                revision=revision,
                format=asset.format,
                status=asset.status,
                type_label=asset.type,
            )

        if fmt in TABLE_FORMATS:
            delimiter = "\t" if fmt == "tsv" else ","
            return self._table_preview(asset, delimiter=delimiter)

        if fmt in TEXT_FORMATS:
            return self._text_preview(asset)

        return PreviewResult(
            mode="message",
            title=title,
            path=asset.path,
            revision=revision,
            format=asset.format,
            status=asset.status,
            type_label=asset.type,
            message="此格式暂不支持内置阅读，可使用打开目录定位文件",
        )

    def _artifact_preview(self, artifact: ExportArtifact) -> PreviewResult:
        title = Path(artifact.output_path).name or artifact.output_path
        return PreviewResult(
            mode="message",
            title=title,
            path=artifact.output_path,
            revision=self._safe_stat(Path(artifact.output_path)),
            format=artifact.format,
            status="generated",
            type_label="成果",
            message=f"成果文件 · 关联对象 {artifact.linked_id}",
        )

    def _text_preview(self, resource: ResourceItem) -> PreviewResult:
        path = Path(resource.path)
        preview_bytes, truncated = self._read_preview_chunk(path)
        text = preview_bytes.decode("utf-8", errors="replace")
        warning = f"仅显示前 {MAX_TEXT_PREVIEW_BYTES // 1024} KiB" if truncated else ""
        return PreviewResult(
            mode="text",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            text=text,
            warning=warning,
            truncated=truncated,
        )

    def _table_preview(self, resource: ResourceItem, delimiter: str) -> PreviewResult:
        path = Path(resource.path)
        preview_bytes, truncated = self._read_preview_chunk(path)
        preview_text = preview_bytes.decode("utf-8", errors="replace")
        parsed_rows: list[tuple[str, ...]] = []

        with io.StringIO(preview_text, newline="") as buffer:
            reader = csv.reader(buffer, delimiter=delimiter)
            for row_index, row in enumerate(reader):
                if row_index > MAX_TABLE_ROWS:
                    truncated = True
                    break

                if len(row) > MAX_TABLE_COLUMNS:
                    truncated = True
                parsed_rows.append(tuple(row[:MAX_TABLE_COLUMNS]))

        headers = parsed_rows[0] if parsed_rows else ()
        body = tuple(parsed_rows[1:]) if parsed_rows else ()
        warning = "表格预览已按行列上限截断" if truncated else ""
        return PreviewResult(
            mode="table",
            title=resource.name,
            path=resource.path,
            revision=self._safe_stat(path),
            format=resource.format,
            status=resource.status,
            type_label=resource.type,
            table_headers=headers,
            table_rows=body,
            warning=warning,
            truncated=truncated,
        )

    def _read_preview_chunk(self, path: Path) -> tuple[bytes, bool]:
        stat = path.stat()
        with path.open("rb") as handle:
            data = handle.read(MAX_TEXT_PREVIEW_BYTES)
        return data, stat.st_size > MAX_TEXT_PREVIEW_BYTES
