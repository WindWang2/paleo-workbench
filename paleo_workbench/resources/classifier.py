from __future__ import annotations

from pathlib import Path


def classify_path(path: Path) -> tuple[str, str, str]:
    ext = path.suffix.lower().lstrip(".")
    name = path.name.lower()
    path_parts = tuple(part.lower() for part in path.parts)

    if ext == "las":
        return "well_log", ext, "indexed"

    if ext in {"sgy", "segy"}:
        return "seismic", ext, "indexed"

    if ext == "dat":
        if "td" in path_parts or any("时深" in part for part in path_parts):
            return "time_depth", ext, "indexed"
        if any("层位" in part for part in path_parts):
            return "horizon", ext, "indexed"
        if any("井分层" in part for part in path_parts):
            return "well_stratification", ext, "indexed"
        return "tabular", ext, "indexed"

    if ext in {"xlsx", "xls", "xml"}:
        return "spreadsheet", ext, "indexed"

    if ext in {"pdf", "ppt", "pptx"}:
        return "document", ext, "indexed_reference"

    if ext in {"png", "jpg", "jpeg", "tif", "tiff"}:
        return "image_reference", ext, "indexed_reference"

    if ext == "dfb" or "相图" in name:
        return "reference_map", ext or "unknown", "indexed_reference"

    if ext == "wlp":
        return "well_reference", ext, "indexed_reference"

    return "unknown", ext or "none", "indexed_reference"
