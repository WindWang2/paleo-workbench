"""Component graph → QgsLayout export bridge (M6/M7, decisions D1).

The composition component graph (``mapping/composer``) stays the single
authoritative, editable document. This module *maps* it, at export time, to
the narrow C++ layout spec consumed by ``QgisMapStack.layout_export`` (a
transient ``QgsPrintLayout`` built inside the bridge and discarded after the
page is written). The layout is never persisted and never editable — no
second composition authority exists.

Engine policy (recorded on every export report):

* ``qgis_layout`` — every VISIBLE element of the composition maps onto a
  native layout item; MAIN_MAP content renders through QGIS's own
  renderer/labeling, so screen (QGIS canvas) and export share one symbol
  authority.
* ``composer_fallback`` — at least one visible element has no native
  counterpart (timescale, stat chart, facies/lithology legend tables,
  colorbar, inset map …); the whole page goes through the existing composer
  SVG renderer instead. A partial QGIS page would silently drop those
  elements, so the fallback is all-or-nothing and reported.

When no bridge stack is available the composer renderer is used, and the
report says so.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from paleo_workbench.mapping.composer.export import export_composition
from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)

logger = logging.getLogger(__name__)

# The vendored QGIS install ships no arrow SVGs, so the layout bridge gets an
# explicit, minimal north indicator drawn here (a needle + N). Kept in the
# temp dir with stable contents keyed by this literal.
_NORTH_ARROW_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="20" height="30" viewBox="0 0 20 30">
  <path d="M10 1 L16 22 L10 17 L4 22 Z" fill="#1a1a1a" stroke="#1a1a1a" stroke-width="1"/>
  <text x="10" y="29" font-size="7" text-anchor="middle" font-family="sans-serif" fill="#1a1a1a">N</text>
</svg>
"""

_NORTH_ARROW_CACHE = Path("/tmp") / "pwb_north_arrow.svg"


def _north_arrow_svg_path() -> str:
    try:
        if not _NORTH_ARROW_CACHE.is_file() or _NORTH_ARROW_CACHE.read_text(
            encoding="utf-8"
        ) != _NORTH_ARROW_SVG:
            _NORTH_ARROW_CACHE.write_text(_NORTH_ARROW_SVG, encoding="utf-8")
        return str(_NORTH_ARROW_CACHE)
    except OSError:
        logger.warning("could not materialise north arrow SVG", exc_info=True)
        return ""

__all__ = [
    "LayoutExportReport",
    "build_layout_spec",
    "export_composition_reported",
]

# Element types with a native QgsLayout counterpart in the bridge spec.
_NATIVE_TYPES: dict[ElementType, str] = {
    ElementType.MAIN_MAP: "map",
    ElementType.LEGEND: "legend",
    ElementType.NORTH_ARROW: "north_arrow",
    ElementType.SCALE_BAR: "scalebar",
    ElementType.TITLE: "label",
    ElementType.TEXT: "label",
    ElementType.ANNOTATION: "label",
    ElementType.DATASOURCE: "label",
    ElementType.TIME_CREDITS: "label",
    ElementType.STRAT_LABELS: "label",
    ElementType.METADATA: "label",
    ElementType.SUBTITLE: "label",
    ElementType.IMAGE: "picture",
    ElementType.NEATLINE: "shape",
    ElementType.GRID: "map_grid",  # folded into the linked map item's grid
}


@dataclass(slots=True)
class LayoutExportReport:
    """Export outcome with the engine actually used + what mapped where."""

    engine: str  # "qgis_layout" | "composer_fallback"
    path: str
    format: str
    dpi: float
    ok: bool
    warnings: list[str] = field(default_factory=list)
    unmapped_elements: list[str] = field(default_factory=list)
    items: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "path": self.path,
            "format": self.format,
            "dpi": self.dpi,
            "ok": self.ok,
            "warnings": list(self.warnings),
            "unmapped_elements": list(self.unmapped_elements),
            "items": self.items,
        }


def _visible_elements(composition: MapCompositionDocument) -> list[ComposerElement]:
    return sorted(
        (el for el in composition.elements if el.visible),
        key=lambda el: el.z_index,
    )


def _map_grid_spacing_to_units(
    element: ComposerElement, main_map: ComposerElement | None, extent, crs_unused
) -> float | None:
    """Convert a GRID element's paper-mm spacing into map units.

    The grid interval lives on the map item in map units; the composition
    declares it in paper millimetres. The conversion uses the main map's
    extent-to-width scale — the same projection assumption the canvas makes.
    """
    if main_map is None or main_map.width_mm <= 0:
        return None
    spacing_mm = float(element.properties.get("spacing_mm") or 10.0)
    xmin, _ymin, xmax, _ymax = extent
    extent_width = max(1e-9, float(xmax) - float(xmin))
    return spacing_mm * extent_width / main_map.width_mm


def build_layout_spec(
    composition: MapCompositionDocument,
    *,
    map_extent: Sequence[float],
    crs: str | None,
) -> dict[str, Any]:
    """Serialise the component graph into the bridge's layout spec JSON.

    Raises :class:`ValueError` when a visible element has no native layout
    counterpart — callers decide the fallback policy (see
    :func:`export_composition_reported`, which falls back to the composer
    renderer for the whole page).
    """
    visible = _visible_elements(composition)
    unmapped = [
        el for el in visible if el.element_type not in _NATIVE_TYPES
    ]
    if unmapped:
        names = ", ".join(sorted({el.element_type.value for el in unmapped}))
        raise ValueError(
            f"composition has elements with no native layout counterpart: {names}"
        )

    main_map = next(
        (el for el in visible if el.element_type is ElementType.MAIN_MAP), None
    )
    items: list[dict[str, Any]] = []
    grid_spacing_units: float | None = None
    for el in visible:
        base = {
            "x": float(el.x_mm),
            "y": float(el.y_mm),
            "w": float(el.width_mm),
            "h": float(el.height_mm),
        }
        props = el.properties
        if el.element_type is ElementType.MAIN_MAP:
            items.append(
                {
                    "type": "map",
                    "key": "map",
                    **base,
                    "crs": crs or "",
                    "extent": [float(v) for v in map_extent],
                    "frame": True,
                }
            )
        elif el.element_type is ElementType.LEGEND:
            items.append(
                {
                    "type": "legend",
                    "map_item": "map",
                    "title": str(props.get("title") or "图例"),
                    **base,
                }
            )
        elif el.element_type is ElementType.NORTH_ARROW:
            items.append(
                {
                    "type": "north_arrow",
                    "map_item": "map",
                    "svg_path": _north_arrow_svg_path(),
                    **base,
                }
            )
        elif el.element_type is ElementType.SCALE_BAR:
            items.append(
                {
                    "type": "scalebar",
                    "map_item": "map",
                    "segments": 4,
                    "unit_label": str(props.get("units") or ""),
                    **base,
                }
            )
        elif el.element_type is ElementType.GRID:
            grid_spacing_units = _map_grid_spacing_to_units(
                el, main_map, map_extent, crs
            )
        elif el.element_type in (
            ElementType.TITLE,
            ElementType.SUBTITLE,
            ElementType.TEXT,
            ElementType.ANNOTATION,
            ElementType.DATASOURCE,
            ElementType.TIME_CREDITS,
            ElementType.STRAT_LABELS,
            ElementType.METADATA,
        ):
            if el.element_type is ElementType.METADATA and isinstance(
                props.get("fields"), Mapping
            ):
                text = "\n".join(
                    f"{key}: {value}"
                    for key, value in props["fields"].items()
                )
            else:
                text = str(props.get("text") or "")
            items.append(
                {
                    "type": "label",
                    "text": text,
                    "font_size": float(props.get("font_size") or 10.0),
                    "bold": el.element_type in (
                        ElementType.TITLE,
                        ElementType.SUBTITLE,
                    ),
                    "color": str(props.get("color") or "#000000"),
                    "halign": str(props.get("align") or "left"),
                    **base,
                }
            )
        elif el.element_type is ElementType.IMAGE:
            image_path = str(props.get("image_path") or "")
            if not image_path:
                raise ValueError(
                    f"image element {el.id!r} has no image_path; embedded "
                    "image data needs the composer renderer"
                )
            items.append({"type": "picture", "path": image_path, **base})
        elif el.element_type is ElementType.NEATLINE:
            items.append(
                {
                    "type": "shape",
                    "frame": True,
                    "fill": "#00000000",
                    **base,
                }
            )

    if grid_spacing_units is not None and main_map is not None:
        for item in items:
            if item["type"] == "map":
                item["grid"] = {
                    "enabled": True,
                    "interval_x": grid_spacing_units,
                    "interval_y": grid_spacing_units,
                    "annotation": True,
                }

    page = {"width_mm": float(composition.width_mm), "height_mm": float(composition.height_mm)}
    return {"page": page, "items": items}


def export_composition_reported(
    composition: MapCompositionDocument,
    path: str | Path,
    *,
    fmt: str = "pdf",
    dpi: float = 300.0,
    map_extent: Sequence[float] | None = None,
    crs: str | None = None,
    stack=None,
) -> LayoutExportReport:
    """Export the composition, preferring the native QgsLayout engine.

    ``stack`` is a :class:`qgis_render_bridge.mapstack.QgisMapStack` whose
    project already mirrors the map layers (the caller owns the mirror —
    canvas shim or a headless snapshot mirror). Without a stack, or when the
    composition carries elements with no native counterpart, the composer
    renderer produces the page and the report records the engine.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    can_use_layout = stack is not None and map_extent is not None
    if can_use_layout:
        try:
            spec = build_layout_spec(
                composition, map_extent=map_extent, crs=crs
            )
        except ValueError as exc:
            warnings.append(str(exc))
            can_use_layout = False
    else:
        if stack is None:
            warnings.append("no QGIS map stack available")
        if map_extent is None:
            warnings.append("no map extent provided")

    if can_use_layout:
        assert stack is not None and map_extent is not None
        try:
            report_json = stack.layout_export(
                json.dumps(spec, ensure_ascii=False), str(out), fmt, float(dpi)
            )
            payload = json.loads(report_json)
            return LayoutExportReport(
                engine="qgis_layout",
                path=str(out),
                format=fmt,
                dpi=float(dpi),
                ok=bool(payload.get("ok")),
                warnings=warnings,
                items=int(payload.get("items") or 0),
            )
        except Exception as exc:
            warnings.append(f"qgis layout export failed: {exc}")
            logger.warning("QgsLayout export failed; falling back", exc_info=True)

    export_composition(composition, out, fmt=fmt, dpi=dpi)
    return LayoutExportReport(
        engine="composer_fallback",
        path=str(out),
        format=fmt,
        dpi=float(dpi),
        ok=True,
        warnings=warnings,
    )
