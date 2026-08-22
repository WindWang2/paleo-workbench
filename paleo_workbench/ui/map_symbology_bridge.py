"""Native QGIS symbology dialog host for the PySide6 shell.

The professional symbology editors (QgsSymbolSelectorDialog,
QgsRendererPropertiesDialog, QgsStyleManagerDialog) run inside the vendored
native bridge.  This module is the single Python-side entry point: it collects
the layer context, invokes the native modal dialog on the Qt GUI thread, and
returns the updated authoritative ``qgis_style`` payload for the caller to
apply through the normal style/revision path.

No QWidget crosses the boundary; ownership and event-loop handling stay in
C++.  Callers must be on the GUI thread (any PySide6 slot is).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from PySide6.QtWidgets import QWidget

from paleo_workbench.mapping.qgis_style import (
    QgisStylePayload,
    qgis_bridge_available,
)

__all__ = [
    "SymbologyBridgeError",
    "open_renderer_properties",
    "open_style_manager",
    "open_symbol_selector",
    "qgis_symbology_available",
]

logger = logging.getLogger(__name__)

_GEOMETRY_BY_TYPE = {
    "Point": "Point",
    "MultiPoint": "MultiPoint",
    "LineString": "LineString",
    "MultiLineString": "MultiLineString",
    "Polygon": "Polygon",
    "MultiPolygon": "MultiPolygon",
}


class SymbologyBridgeError(RuntimeError):
    """A native symbology dialog could not run or returned an invalid payload."""


def qgis_symbology_available() -> bool:
    """True when the native symbology dialogs can be opened."""
    return qgis_bridge_available()


def _native():
    try:
        import qgis_render_bridge as native
    except ImportError as exc:  # pragma: no cover - guarded by availability check
        raise SymbologyBridgeError(
            "qgis_render_bridge is not built; professional symbology editing "
            "requires the QGIS renderer bridge"
        ) from exc
    return native


def _geometry_type_for_layer(layer: Mapping[str, Any] | None) -> str:
    """Best-effort geometry type from a scene layer mapping."""
    if not layer:
        return "Polygon"
    for feature in layer.get("features") or ():
        geometry = feature.get("geometry") if isinstance(feature, Mapping) else None
        kind = str((geometry or {}).get("type") or "")
        if kind in _GEOMETRY_BY_TYPE:
            return kind
    return "Polygon"


def open_renderer_properties(
    parent: QWidget | None,
    *,
    title: str,
    features: tuple[Mapping[str, Any], ...] = (),
    crs: str = "",
    fields: tuple[str, ...] = (),
    style: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Open the native QGIS renderer properties dialog for one vector layer.

    Returns ``{"qgis_style": payload_dict, "opacity": float}`` when the user
    accepted, or None when cancelled.  Raises SymbologyBridgeError when the
    current payload cannot be edited natively.
    """
    del parent  # dialogs are owned natively; the shell only anchors modality
    native = _native()
    style = dict(style or {})
    payload = QgisStylePayload.from_dict(style.get("qgis_style"))
    geometry_type = _geometry_type_for_layer({"features": features})
    request: dict[str, Any] = {
        "title": title,
        "geometry_type": geometry_type,
        "crs": str(crs),
        "fields": [str(name) for name in fields],
        "fill": str(style.get("fill") or "#6c8ebf"),
        "stroke": str(style.get("stroke") or "#26364d"),
        "stroke_width": float(style.get("stroke_width") or 1.0),
        "marker_size": float(style.get("marker_size") or 6.0),
    }
    if payload is not None:
        request["renderer_xml"] = payload.renderer_xml
        if payload.labeling_xml:
            request["labeling_xml"] = payload.labeling_xml
    else:
        # Legacy layer without a payload yet: migrate the flat VectorStyle
        # vocabulary into real QGIS objects so the editor opens on an
        # equivalent renderer (lazy legacy_to_qgis_renderer migration).
        migrated = native.legacy_style_to_renderer_xml(style, geometry_type)
        if migrated:
            request["renderer_xml"] = str(migrated)
    try:
        result = native.run_renderer_properties_dialog(request)
    except Exception as exc:
        raise SymbologyBridgeError(f"QGIS renderer dialog failed: {exc}") from exc
    if not result or not result.get("ok"):
        return None
    renderer_xml = str(result.get("renderer_xml") or "")
    if not renderer_xml.strip():
        raise SymbologyBridgeError("the symbology editor returned an empty renderer")
    updated = QgisStylePayload(
        renderer_xml=renderer_xml,
        labeling_xml=payload.labeling_xml if payload is not None else "",
        name=payload.name if payload is not None else "",
        tags=payload.tags if payload is not None else (),
        revision=payload.revision + 1 if payload is not None else 1,
    )
    return {"qgis_style": updated.to_dict(), "opacity": float(result.get("opacity", 1.0))}


def open_symbol_selector(
    parent: QWidget | None,
    *,
    title: str,
    symbol_index: int,
    features: tuple[Mapping[str, Any], ...] = (),
    crs: str = "",
    fields: tuple[str, ...] = (),
    style: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Open the native QGIS symbol selector for one renderer symbol slot."""
    del parent
    native = _native()
    style = dict(style or {})
    payload = QgisStylePayload.from_dict(style.get("qgis_style"))
    if payload is None:
        raise SymbologyBridgeError(
            "symbol-level editing requires an existing QGIS style payload"
        )
    request: dict[str, Any] = {
        "title": title,
        "geometry_type": _geometry_type_for_layer({"features": features}),
        "crs": str(crs),
        "fields": [str(name) for name in fields],
        "renderer_xml": payload.renderer_xml,
    }
    try:
        result = native.run_symbol_selector_dialog(request, int(symbol_index))
    except Exception as exc:
        raise SymbologyBridgeError(f"QGIS symbol dialog failed: {exc}") from exc
    if not result or not result.get("ok"):
        return None
    renderer_xml = str(result.get("renderer_xml") or "")
    if not renderer_xml.strip():
        raise SymbologyBridgeError("the symbol editor returned an empty renderer")
    updated = QgisStylePayload(
        renderer_xml=renderer_xml,
        labeling_xml=payload.labeling_xml,
        name=payload.name,
        tags=payload.tags,
        revision=payload.revision + 1,
    )
    return {"qgis_style": updated.to_dict()}


def open_style_manager(parent: QWidget | None, *, style_db_path: str) -> bool:
    """Open the native QGIS style manager on a managed database file."""
    del parent
    native = _native()
    try:
        return bool(native.run_style_manager_dialog(str(style_db_path)))
    except Exception as exc:
        raise SymbologyBridgeError(f"QGIS style manager failed: {exc}") from exc
