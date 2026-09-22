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

    if ext == "geojson":
        return "geojson", ext, "indexed"

    if ext == "json":
        # Heuristic: paleomap / features json often named facies/map
        if any(k in name for k in ("facies", "paleo", "map", "geo")):
            return "geojson", "json", "indexed"
        return "tabular", "json", "indexed"

    if ext in {"shp", "gpkg"}:
        return "vector", ext, "indexed"

    if ext == "dat":
        if "td" in path_parts or any("时深" in part for part in path_parts):
            return "time_depth", ext, "indexed"
        if any("层位" in part for part in path_parts):
            return "horizon", ext, "indexed"
        if any("井分层" in part for part in path_parts):
            return "well_stratification", ext, "indexed"
        if any("井位" in part for part in path_parts) or "wellhead" in name or "well_head" in name:
            return "well_head", ext, "indexed"
        return "tabular", ext, "indexed"

    if ext in {"xlsx", "xls"}:
        return "spreadsheet", ext, "indexed"

    if ext == "xml":
        if any(k in name for k in ("well", "log", "测井", "曲线", "witsml", "las")) or any(
            any(k in part for k in ("well", "log", "测井", "曲线", "井曲线")) for part in path_parts
        ):
            return "well_log", ext, "indexed"
        return "spreadsheet", ext, "indexed"

    if ext == "csv":
        return "tabular", ext, "indexed"

    if ext in {"pdf", "ppt", "pptx", "docx", "doc"}:
        return "document", ext, "indexed_reference"

    if ext in {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}:
        return "image_reference", ext, "indexed_reference"

    if ext == "dfb" or "相图" in name:
        return "reference_map", ext or "unknown", "indexed_reference"

    if ext == "wlp":
        return "well_reference", ext, "indexed_reference"

    if ext == "zip":
        return "archive", ext, "indexed_reference"

    if ext in {"md", "markdown", "htm", "html"}:
        return "document", ext, "indexed_reference"

    if ext in {"wav", "mp3", "flac", "ogg", "m4a"}:
        return "unknown", ext, "indexed_reference"

    if ext in {"mp4", "mov", "webm", "mkv", "avi"}:
        return "video", ext, "indexed_reference"

    # Remaining: keep format for preview dispatch.
    return "unknown", ext or "none", "indexed_reference"


def classify_import_path(path: Path) -> tuple[str, str, str]:
    """Classify an import candidate, using XML content only when necessary.

    Filename-only XML hints cannot distinguish WITSML curves from finished
    well-location deliveries.  The bounded extractor claims XML as a
    ``well_head`` only when it finds a well identity together with X/Y.
    """
    if path.suffix.lower() == ".xml":
        try:
            from paleo_workbench.resources.well_location_xml import (
                is_well_location_xml,
            )

            if is_well_location_xml(path):
                return "well_head", "xml", "indexed"
            from paleo_workbench.resources.well_log_xml import is_well_log_xml

            if is_well_log_xml(path):
                return "well_log", "xml", "indexed"
        except Exception:
            # Preserve import robustness; the normal filename fallback still
            # indexes unreadable/vendor-specific XML as a generic resource.
            pass
    return classify_path(path)
