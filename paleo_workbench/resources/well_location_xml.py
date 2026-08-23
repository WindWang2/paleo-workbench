"""Bounded, schema-tolerant extraction for XML well-location deliveries.

The importer deliberately recognizes only records with both a strong well
identity field and an X/Y coordinate pair.  That keeps ordinary XML, WITSML
curve logs, and generic map points out of the ``well_head`` path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

try:  # Prefer hardened parsing for external vendor deliveries when available.
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover - minimal runtime fallback
    import xml.etree.ElementTree as ET


_MAX_RECORDS = 100_000
_NAME_KEYS = {"well", "wellname", "wellid", "wellno", "uwi", "井名", "井号", "井号名称"}
_X_KEYS = {"x", "xcoord", "xcoordinate", "easting", "east", "经度", "东坐标", "x坐标", "longitude", "lon"}
_Y_KEYS = {"y", "ycoord", "ycoordinate", "northing", "north", "纬度", "北坐标", "y坐标", "latitude", "lat"}
_Z_KEYS = {"z", "elevation", "elev", "kb", "海拔", "井口高程", "高程"}
_UWI_KEYS = {"uwi", "api", "wellid", "井号"}
_CRS_KEYS = {"crs", "srs", "srsname", "coordinatesystem", "坐标系"}


@dataclass(frozen=True)
class XMLWellLocation:
    name: str
    x: float
    y: float
    z: float | None = None
    uwi: str = ""
    source_crs: str = ""


def _local_name(value: Any) -> str:
    text = str(value or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text


def _key(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", _local_name(value)).casefold()


def _first(values: dict[str, str], candidates: set[str]) -> str:
    for key in candidates:
        value = values.get(key, "").strip()
        if value:
            return value
    return ""


def _float_or_none(value: str) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _crs_from(values: dict[str, str], inherited: str, *, lon_lat: bool) -> str:
    value = _first(values, _CRS_KEYS) or inherited
    if not value and lon_lat:
        return "EPSG:4326"
    return value


def _record_from_values(
    values: dict[str, str],
    *,
    inherited_crs: str = "",
    allow_plain_name: bool = False,
) -> XMLWellLocation | None:
    name_key = next((key for key in _NAME_KEYS if values.get(key, "").strip()), "")
    name = values.get(name_key, "").strip() if name_key else ""
    # A plain ``name`` field is only trusted under an explicit <Well> element;
    # generic GIS point XML must not turn into wells just because it has names.
    if not name and allow_plain_name:
        name = values.get("name", "").strip()
    x_key = next((key for key in _X_KEYS if values.get(key, "").strip()), "")
    y_key = next((key for key in _Y_KEYS if values.get(key, "").strip()), "")
    x = _float_or_none(values.get(x_key, ""))
    y = _float_or_none(values.get(y_key, ""))
    if not name or x is None or y is None:
        return None
    z = _float_or_none(_first(values, _Z_KEYS))
    uwi = _first(values, _UWI_KEYS)
    lon_lat = x_key in {"longitude", "lon"} and y_key in {"latitude", "lat"}
    return XMLWellLocation(
        name=name,
        x=x,
        y=y,
        z=z,
        uwi=uwi,
        source_crs=_crs_from(values, inherited_crs, lon_lat=lon_lat),
    )


def _text_of_cell(cell) -> str:
    for descendant in cell.iter():
        if _key(descendant.tag) == "data" and descendant.text:
            return descendant.text.strip()
    return (cell.text or "").strip()


def _spreadsheet_records(root, inherited_crs: str) -> list[XMLWellLocation]:
    records: list[XMLWellLocation] = []
    for worksheet in root.iter():
        if _key(worksheet.tag) != "worksheet":
            continue
        rows: list[list[str]] = []
        for row in worksheet.iter():
            if _key(row.tag) != "row":
                continue
            cells = [_text_of_cell(cell) for cell in row if _key(cell.tag) == "cell"]
            if cells:
                rows.append(cells)
        if len(rows) < 2:
            continue
        headers = [_key(value) for value in rows[0]]
        values_by_header = [header for header in headers if header]
        # SpreadsheetML must name the well column explicitly; ``名称 + X + Y``
        # could be a generic place-name table rather than a well delivery.
        if not any(header in _NAME_KEYS for header in values_by_header):
            continue
        if not any(header in _X_KEYS for header in values_by_header) or not any(
            header in _Y_KEYS for header in values_by_header
        ):
            continue
        for row in rows[1:]:
            values = {
                header: row[index].strip()
                for index, header in enumerate(headers)
                if header and index < len(row) and row[index].strip()
            }
            record = _record_from_values(values, inherited_crs=inherited_crs)
            if record is not None:
                records.append(record)
            if len(records) >= _MAX_RECORDS:
                return records
    return records


def extract_well_locations_xml(path: Path | str) -> tuple[list[XMLWellLocation], list[str]]:
    """Extract explicit well-coordinate records from generic/SpreadsheetML XML.

    Returns no records for XML that does not advertise a well identity plus
    coordinates. Parsing failure is a user-facing warning, never an exception
    from the import worker.
    """
    source = Path(path)
    try:
        root = ET.parse(str(source)).getroot()
    except Exception as exc:
        return [], [f"XML 井位解析失败: {exc.__class__.__name__}"]

    root_values = {
        _key(key): str(value).strip()
        for key, value in getattr(root, "attrib", {}).items()
        if str(value).strip()
    }
    inherited_crs = _first(root_values, _CRS_KEYS)
    records = _spreadsheet_records(root, inherited_crs)
    if records:
        return records, []

    seen: set[tuple[str, float, float]] = set()
    for element in root.iter():
        tag = _key(element.tag)
        children = list(element)
        if not children:
            continue
        values = {
            _key(child.tag): (child.text or "").strip()
            for child in children
            if (child.text or "").strip()
        }
        values.update(
            {
                _key(key): str(value).strip()
                for key, value in getattr(element, "attrib", {}).items()
                if str(value).strip()
            }
        )
        # ``<well>``/``<wellHead>`` can safely use a plain child ``<name>``;
        # all other record shapes need an explicit well-name field.
        is_well_element = "well" in tag or "井" in tag
        record = _record_from_values(
            values,
            inherited_crs=inherited_crs,
            allow_plain_name=is_well_element,
        )
        if record is None:
            continue
        key = (record.name, record.x, record.y)
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
        if len(records) >= _MAX_RECORDS:
            break
    return records, []


def is_well_location_xml(path: Path | str) -> bool:
    """True only for XML with at least one explicit well-coordinate record."""
    records, _warnings = extract_well_locations_xml(path)
    return bool(records)
