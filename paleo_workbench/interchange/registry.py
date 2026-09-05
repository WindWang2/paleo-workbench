"""Interchange adapter registry with content-based format sniffing.

Format identity is decided by a bounded header/magic probe *combined with* the
extension; the extension alone is never authoritative. Sniffing reads at most
:const:`SNIFF_PREFIX_BYTES` bytes from the start of a file (plus fixed small
offsets such as the SEG-Y binary header), so it stays cheap for huge files.
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Iterable

from paleo_workbench.interchange.contracts import (
    CancelToken,
    ExportPlan,
    ExportVerification,
    FormatCapability,
    FormatNotSupportedError,
    ImportExecutionResult,
    ImportPlan,
    InspectionResult,
    NULL_CANCEL,
    ProgressCallback,
    SniffResult,
    _null_progress,
)

# Bounded probe: never read a whole file to identify it.
SNIFF_PREFIX_BYTES = 8192
_SQITE_MAGIC = b"SQLite format 3\x00"


class FormatAdapter(ABC):
    """Contract every interchange adapter implements.

    Adapters wrap existing parsers/writers (geoviz, segyio, GDAL, lasio,
    openpyxl, geomodel exporters); they never duplicate a parser that already
    exists elsewhere in the repo.
    """

    format_id: str = ""
    display_name: str = ""
    extensions: tuple[str, ...] = ()

    # -- identity -----------------------------------------------------------
    def sniff(self, path: Path) -> SniffResult:
        """Content probe; default returns low-confidence extension match."""
        return SniffResult(
            format_id=self.format_id,
            confidence="low",
            evidence="extension",
            extension=path.suffix.lower().lstrip("."),
        )

    def matches_extension(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in self.extensions

    # -- capability ---------------------------------------------------------
    @abstractmethod
    def capability(self) -> FormatCapability: ...

    # -- inspect ------------------------------------------------------------
    @abstractmethod
    def inspect(self, path: Path) -> InspectionResult: ...

    # -- plan / execute -----------------------------------------------------
    def plan_import(
        self,
        path: Path,
        inspection: InspectionResult,
        *,
        managed: bool = True,
        asset_name: str | None = None,
        options: dict | None = None,
    ) -> ImportPlan:
        """Default plan: managed copy (or external link) with inspection warnings."""
        if not inspection.ok:
            action = "unsupported"
        else:
            action = "managed_copy" if managed else "link_external"
        return ImportPlan(
            format_id=self.format_id,
            source_path=str(path),
            action=action,
            asset_name=asset_name or path.name,
            warnings=list(inspection.warnings),
            estimated_bytes=inspection.size_bytes,
            metadata=inspection.metadata,
            options=dict(options or {}),
        )

    def import_data(
        self,
        path: Path,
        plan: ImportPlan,
        *,
        work_dir: Path,
        catalog,
        cancel: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ImportExecutionResult:
        raise FormatNotSupportedError(f"{self.format_id}: import not supported")

    def plan_export(
        self,
        source_path: Path,
        target_path: Path,
        *,
        options: dict | None = None,
    ) -> ExportPlan:
        raise FormatNotSupportedError(f"{self.format_id}: export not supported")

    def export_data(
        self,
        source_path: Path,
        plan: ExportPlan,
        *,
        work_dir: Path,
        cancel: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> Path:
        raise FormatNotSupportedError(f"{self.format_id}: export not supported")

    def verify_output(self, target_path: Path, plan: ExportPlan) -> ExportVerification:
        raise FormatNotSupportedError(f"{self.format_id}: verification not supported")


class InterchangeRegistry:
    """Registry of :class:`FormatAdapter` instances keyed by format id."""

    def __init__(self) -> None:
        self._adapters: dict[str, FormatAdapter] = {}

    def register(self, adapter: FormatAdapter, *, replace: bool = False) -> None:
        if not adapter.format_id:
            raise ValueError("adapter must define format_id")
        if adapter.format_id in self._adapters and not replace:
            raise ValueError(f"duplicate adapter format_id: {adapter.format_id}")
        self._adapters[adapter.format_id] = adapter

    def get(self, format_id: str) -> FormatAdapter | None:
        return self._adapters.get(format_id)

    def adapters(self) -> list[FormatAdapter]:
        return list(self._adapters.values())

    def adapter_for_extension(self, path: Path) -> FormatAdapter | None:
        ext = path.suffix.lower().lstrip(".")
        for adapter in self._adapters.values():
            if ext in adapter.extensions:
                return adapter
        return None

    def capability_matrix(self) -> list[dict]:
        rows = []
        for adapter in self._adapters.values():
            cap = adapter.capability()
            rows.append(
                {
                    "format_id": adapter.format_id,
                    "display_name": adapter.display_name,
                    "extensions": list(adapter.extensions),
                    "read": cap.read,
                    "inspect": cap.inspect,
                    "import": cap.import_data,
                    "export": cap.export,
                    "roundtrip_verify": cap.roundtrip_verify,
                    "notes": cap.notes,
                }
            )
        return rows


# ---------------------------------------------------------------------------
# Content sniffing
# ---------------------------------------------------------------------------


def _read_prefix(path: Path, limit: int = SNIFF_PREFIX_BYTES) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(limit)


def _printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    printable = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13))
    return printable / len(data)


def _decode_prefix(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _sniff_gpkg(data: bytes, path: Path) -> SniffResult | None:
    # SQLite magic + GPKG application id at offset 68 (big-endian "GPKG").
    if len(data) >= 72 and data.startswith(_SQITE_MAGIC) and data[68:72] == b"GPKG":
        return SniffResult("gpkg", "high", "sqlite-gpkg-app-id", path.suffix.lower().lstrip("."))
    return None


def _sniff_zip_family(data: bytes, path: Path) -> SniffResult | None:
    if not data.startswith(b"PK\x03\x04"):
        return None
    ext = path.suffix.lower().lstrip(".")
    # Local file headers start at 0: scan the prefix for first entry names to
    # disambiguate OOXML (.xlsx) from numpy .npz (factor grid) from generic zip.
    names: list[str] = []
    offset = 0
    while offset + 30 <= len(data) and len(names) < 8:
        if data[offset : offset + 4] != b"PK\x03\x04":
            break
        name_len = struct.unpack_from("<H", data, offset + 26)[0]
        extra_len = struct.unpack_from("<H", data, offset + 28)[0]
        name = data[offset + 30 : offset + 30 + name_len]
        names.append(name.decode("utf-8", errors="replace"))
        offset = offset + 30 + name_len + extra_len
    joined = " ".join(names)
    if "[Content_Types].xml" in joined or "xl/workbook.xml" in joined:
        return SniffResult("xlsx", "high", "zip-ooxml-content-types", ext)
    if any("__descriptor__" in name for name in names):
        return SniffResult("factor_grid", "high", "zip-npz-descriptor", ext)
    return SniffResult("zip", "medium", "zip-generic", ext)


def _sniff_text(data: bytes, path: Path) -> SniffResult | None:
    if _printable_ratio(data) < 0.9:
        return None
    text = _decode_prefix(data)
    ext = path.suffix.lower().lstrip(".")
    stripped = text.lstrip("﻿ \t\r\n")
    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    first = lines[0] if lines else ""

    # GeoJSON: JSON object declaring FeatureCollection/Feature markers. The
    # prefix is usually shorter than the document, so this stays a marker
    # probe; the adapter's inspect() does the authoritative parse.
    if first.startswith("{"):
        probe = stripped[:4096]
        if '"FeatureCollection"' in probe:
            return SniffResult("geojson", "high", "json-featurecollection", ext)
        if '"type"' in probe and '"Feature"' in probe and '"geometry"' in probe:
            return SniffResult("geojson", "medium", "json-feature", ext)
        return None

    # LAS: version section marker near the top.
    head = text[:2048].upper()
    if first.startswith("~V") or first.startswith("VERS."):
        return SniffResult("las", "high", "las-version-section", ext)
    if "~VERSION" in head or ("WRAP" in head and "ASCII" in head and "~" in head):
        return SniffResult("las", "medium", "las-section-markers", ext)

    # FLAC3D / Abaqus writers of this repo.
    if first.startswith("*HEADING") or first.startswith("*NODE"):
        return SniffResult("abaqus_inp", "high", "abaqus-keyword", ext)
    if first.startswith("G ") and ext == "f3grid":
        return SniffResult("flac3d_f3grid", "medium", "flac3d-gridpoint-line", ext)

    # SEG-Y can be pure ASCII in the textual header (rare but legal): treat as
    # low-confidence candidate only when the size also fits a SEG-Y framing.
    if path.stat().st_size >= 3600 and ext in ("sgy", "segy"):
        return SniffResult("segy", "low", "segy-extension-size", ext)
    return None


def sniff_format(path: Path, registry: InterchangeRegistry | None = None) -> SniffResult:
    """Identify a file by content first, extension second.

    Returns a :class:`SniffResult`; ``format_id`` is "" when nothing matched.
    A high-confidence content match wins even when the extension disagrees —
    callers turn that disagreement into a warning, never into a silent guess.
    """
    path = Path(path)
    if not path.is_file():
        return SniffResult("", "low", "missing-file", path.suffix.lower().lstrip("."))

    prefix = _read_prefix(path)
    candidates: list[SniffResult] = []

    gpkg = _sniff_gpkg(prefix, path)
    if gpkg:
        candidates.append(gpkg)
    zip_family = _sniff_zip_family(prefix, path)
    if zip_family:
        candidates.append(zip_family)

    # TIFF family (GeoTIFF is TIFF + geo tags; magic decides the family).
    if prefix.startswith(b"II*\x00") or prefix.startswith(b"MM\x00*"):
        ext = path.suffix.lower().lstrip(".")
        confidence = "high" if ext in ("tif", "tiff") else "medium"
        evidence = "tiff-magic" if ext in ("tif", "tiff") else "tiff-magic-extension-mismatch"
        candidates.append(SniffResult("geotiff", confidence, evidence, ext))

    # Shapefile: file code 9994 big-endian in the first 4 bytes.
    if len(prefix) >= 4:
        (file_code,) = struct.unpack_from(">I", prefix, 0)
        if file_code == 9994:
            candidates.append(
                SniffResult("shapefile", "high", "shapefile-magic", path.suffix.lower().lstrip("."))
            )

    text = _sniff_text(prefix, path)
    if text:
        candidates.append(text)

    # SEG-Y heuristic: 3200-byte textual header + 400-byte binary header with
    # the SEG Y revision marker in the binary header (rev>=1) or a mostly
    # printable/EBCDIC textual block. Bounded and advisory; segyio confirms.
    if len(prefix) >= 3600:
        textual = prefix[:3200]
        binary_marker = prefix[3500:3504]
        ratio = _printable_ratio(textual)
        if binary_marker.startswith(b"SEG") or ratio > 0.75:
            ext = path.suffix.lower().lstrip(".")
            confidence = "high" if ext in ("sgy", "segy") else "medium"
            evidence = "segy-binary-revision" if binary_marker.startswith(b"SEG") else "segy-textual-header"
            candidates.append(SniffResult("segy", confidence, evidence, ext))

    if not candidates:
        return SniffResult("", "low", "no-match", path.suffix.lower().lstrip("."))

    rank = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: rank[c.confidence])
    return candidates[0]


def default_registry() -> InterchangeRegistry:
    """Build a registry with every built-in adapter registered."""
    from paleo_workbench.interchange.adapters import build_default_registry

    return build_default_registry()
