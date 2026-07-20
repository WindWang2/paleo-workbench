from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import numpy as np

MAX_TEXT_PREVIEW_BYTES = 256 * 1024
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 40

PreviewMode = Literal[
    "empty",
    "geoviz",
    "pdf",
    "image",
    "text",
    "table",
    "well_log",
    "seismic",
    "message",
    "rich_text",
    "json_tree",
    "geotiff",
    "media",
    "web_document",
]

TEXT_FORMATS = {"txt", "text", "log", "dat", "xml"}
TABLE_FORMATS = {"csv", "tsv"}
EXCEL_FORMATS = {"xlsx", "xls"}
IMAGE_FORMATS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}
PDF_FORMATS = {"pdf"}
LAS_FORMATS = {"las"}
SEGY_FORMATS = {"sgy", "segy"}
MARKDOWN_FORMATS = {"md", "markdown", "htm", "html"}
HTML_FORMATS = {"htm", "html"}
JSON_FORMATS = {"json", "geojson"}
GEOTIFF_FORMATS = {"tif", "tiff"}
AUDIO_FORMATS = {"wav", "mp3", "flac", "ogg", "m4a"}
MAX_JSON_PARSE_BYTES = 5 * 1024 * 1024
JSON_ARRAY_COLLAPSE_THRESHOLD = 100


@dataclass(frozen=True)
class PreviewResult:
    mode: PreviewMode
    title: str
    path: str = ""
    revision: tuple[object, ...] | None = None
    format: str = ""
    status: str = ""
    type_label: str = ""
    message: str = ""
    warning: str = ""
    text: str = ""
    table_headers: tuple[str, ...] = field(default_factory=tuple)
    table_rows: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    summary_rows: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    sheets: tuple[str, ...] = field(default_factory=tuple)
    truncated: bool = False
    # Media file bytes loaded off the UI thread; decoded/loaded on the UI.
    image_bytes: bytes = b""
    pdf_bytes: bytes = b""
    rich_html: str = ""
    json_payload: object | None = None
    json_truncated: bool = False
    geo_metadata: tuple[tuple[str, str], ...] = ()
    media_path: str = ""
    engine_preview: object | None = None
    estimated_bytes: int = 0
    visualization_available: bool = False
    # Transient build failures must be retried, never retained in memory/disk.
    cacheable: bool = True
    retryable: bool = False
    data_headers: tuple[str, ...] = field(default_factory=tuple)
    data_rows: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    seismic_volume: np.ndarray | None = None
