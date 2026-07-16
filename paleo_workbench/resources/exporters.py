"""Format conversion exporters for the data page."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from paleo_workbench.project.models import ExportArtifact, ResourceItem


class ExportError(Exception):
    """Raised when a format conversion fails."""


# Input format sets
_LAS_FORMATS = {"las"}
_TABLE_FORMATS = {"csv", "xlsx", "xls"}
_IMAGE_FORMATS = {"tif", "tiff", "png", "jpg", "jpeg", "bmp"}
_TEXT_FORMATS = {"txt", "md", "markdown", "json", "xml", "log", "dat"}


def las_to_csv(input_path: Path, output_path: Path) -> None:
    try:
        import lasio
        import pandas as pd
        las = lasio.read(str(input_path))
        df = las.df()
        df.to_csv(output_path, index=True)
    except Exception as exc:
        raise ExportError(f"LAS -> CSV 失败: {exc}") from exc


def table_to_json(input_path: Path, output_path: Path) -> None:
    try:
        import pandas as pd
        ext = input_path.suffix.lower().lstrip(".")
        if ext == "csv":
            df = pd.read_csv(input_path)
        else:
            df = pd.read_excel(input_path)
        df.to_json(output_path, orient="records", force_ascii=False)
    except Exception as exc:
        raise ExportError(f"表格 -> JSON 失败: {exc}") from exc


def image_to_png(input_path: Path, output_path: Path) -> None:
    try:
        from PIL import Image
        with Image.open(input_path) as img:
            img.save(output_path, "PNG")
    except Exception as exc:
        raise ExportError(f"图像 -> PNG 失败: {exc}") from exc


def text_to_txt(input_path: Path, output_path: Path) -> None:
    try:
        text = input_path.read_text(encoding="utf-8", errors="replace")
        output_path.write_text(text, encoding="utf-8")
    except Exception as exc:
        raise ExportError(f"文本 -> TXT 失败: {exc}") from exc


# Registry: (label, input_formats, convert_fn)
_CONVERTERS: list[tuple[str, set[str], Callable]] = [
    ("CSV", _LAS_FORMATS, las_to_csv),
    ("JSON", _TABLE_FORMATS, table_to_json),
    ("PNG", _IMAGE_FORMATS, image_to_png),
    ("TXT", _TEXT_FORMATS, text_to_txt),
]


def get_available_formats(asset: ResourceItem | ExportArtifact) -> list[tuple[str, Callable]]:
    """Return [(label, convert_fn), ...] for formats the asset can export to."""
    if isinstance(asset, ExportArtifact):
        return []
    fmt = asset.format.lower()
    return [(label, fn) for label, inputs, fn in _CONVERTERS if fmt in inputs]
