"""Strong, bounded content recognition for XML well-log deliveries."""

from __future__ import annotations

from pathlib import Path

try:  # Prefer hardened parsing for untrusted vendor XML when available.
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover - minimal runtime fallback
    import xml.etree.ElementTree as ET


_MAX_ELEMENTS = 200_000
_SPREADSHEET_NAMES = {"测井曲线", "welllog", "well log", "log curves"}


def _local_name(value: object) -> str:
    text = str(value or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text.strip().casefold()


def is_well_log_xml(path: Path | str) -> bool:
    """Return true only for explicit WITSML or well-log SpreadsheetML XML.

    Ordinary XML spreadsheets remain spreadsheets.  Filename hints are not
    used, so vendor files such as ``regional_delivery.xml`` are recognized by
    their actual payload semantics.
    """
    try:
        root = ET.parse(str(path)).getroot()
    except Exception:
        return False

    tags: set[str] = set()
    has_log_element = False
    has_log_curve_info = False
    has_log_data = False
    has_named_well_log_sheet = False
    for index, element in enumerate(root.iter()):
        if index >= _MAX_ELEMENTS:
            break
        tag = _local_name(getattr(element, "tag", ""))
        tags.add(tag)
        has_log_element = has_log_element or tag == "log"
        has_log_curve_info = has_log_curve_info or tag in {
            "logcurveinfo",
            "curveinfo",
        }
        has_log_data = has_log_data or tag == "logdata"
        if tag == "worksheet":
            names = [
                str(value).strip().casefold()
                for value in getattr(element, "attrib", {}).values()
                if str(value).strip()
            ]
            has_named_well_log_sheet = has_named_well_log_sheet or any(
                name in _SPREADSHEET_NAMES for name in names
            )

    root_tag = _local_name(getattr(root, "tag", ""))
    is_witsml = "witsml" in root_tag or "witsml" in tags
    return bool(
        (has_log_element and has_log_curve_info and has_log_data)
        or (is_witsml and has_log_curve_info and has_log_data)
        or has_named_well_log_sheet
    )


__all__ = ["is_well_log_xml"]
