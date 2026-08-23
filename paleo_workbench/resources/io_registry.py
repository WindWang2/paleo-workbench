"""Central import/export format registry for the workbench.

Maps file extensions and resource types to roles, labels, and export targets.
geo-viz-engine owns render/export of canvases; this registry owns project I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

# Resource type → Chinese label (shared by UI tables / import reports)
TYPE_LABELS: dict[str, str] = {
    "well_log": "测井",
    "seismic": "地震",
    "horizon": "层位",
    "well_head": "井位",
    "well_stratification": "井分层",
    "time_depth": "时深",
    "tabular": "表格",
    "spreadsheet": "电子表格",
    "document": "文档",
    "image_reference": "影像",
    "reference_map": "参考图",
    "well_reference": "测井参考",
    "archive": "压缩包",
    "vector": "矢量",
    "geojson": "GeoJSON矢量",
    "unknown": "未知",
}

# Import: extensions always accepted when importing folders (others still indexed)
PREFERRED_IMPORT_EXTENSIONS = frozenset(
    {
        "las",
        "sgy",
        "segy",
        "dat",
        "csv",
        "xlsx",
        "xls",
        "xml",
        "json",
        "geojson",
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "tif",
        "tiff",
        "bmp",
        "md",
        "markdown",
        "html",
        "htm",
        "txt",
        "shp",
        "gpkg",
        "wlp",
        "dfb",
        "zip",
    }
)

# artifact_role heuristics by type
ROLE_BY_TYPE: dict[str, str] = {
    "well_log": "input",
    "seismic": "input",
    "horizon": "input",
    "well_head": "input",
    "well_stratification": "input",
    "time_depth": "input",
    "tabular": "input",
    "spreadsheet": "input",
    "document": "reference",
    "image_reference": "reference",
    "reference_map": "reference",
    "well_reference": "reference",
    "archive": "reference",
    "vector": "reference",
    "geojson": "input",
    "unknown": "reference",
}


@dataclass(frozen=True)
class ExportFormatSpec:
    """One export target offered to users."""

    label: str  # shown in menus, e.g. "CSV"
    extension: str  # ".csv"
    category: str  # "convert" | "engine" | "project"
    description: str = ""


# Data conversion labels used by exporters registry
CONVERT_LABEL_EXT = {
    "CSV": ".csv",
    "JSON": ".json",
    "XLSX": ".xlsx",
    "PNG": ".png",
    "TXT": ".txt",
    "GeoJSON": ".geojson",
    "SUMMARY": ".summary.json",
    "INVENTORY": ".inventory.json",
}

# Visualization / engine canvas export (capability gated per Tab at runtime)
VIEW_EXPORT_FORMATS = (
    ExportFormatSpec("PNG", ".png", "engine", "当前视图栅格截图（全 Tab）"),
    ExportFormatSpec("SVG", ".svg", "engine", "矢量图（测井 / 连井 / 古地理）"),
    ExportFormatSpec("PDF", ".pdf", "engine", "矢量 PDF（测井 / 连井 / 古地理）"),
)
