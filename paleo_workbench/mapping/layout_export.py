"""Component graph → QgsLayout export bridge (M6/M7, decisions D1; V7 §13).

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
  counterpart; the whole page goes through the existing composer SVG
  renderer instead. A partial QGIS page would silently drop those elements,
  so the fallback is all-or-nothing, itemized per element type in the
  report's ``hybrid_items`` (V7 §13: the hybrid boundary is explicit, never
  a silent engine mix — the C++ builds one page, so two engines can never
  share a file).

When no bridge stack is available the composer renderer is used, and the
report says so.

Legend-family elements (V7 §13). COLORBAR, FACIES_LEGEND (the geological
legend) and WELL_LEGEND map onto the native ``legend`` item **bound to the
main map item** — the only link the C++ wire protocol supports
(``map_item``; accepted legend keys are exactly type/x/y/map_item/title/
resize_to_contents/background, see :data:`_LEGEND_ITEM_KEYS`). The bridge's
legend item has NO layer-filter key, so each of those legends lists EVERY
layer of the linked map (with its mirrored QGIS symbology — raster legends
included via the §5 raster mirror), not only the scalar/facies/well layer
the composer element was authored for. That is documented here, asserted by
tests, and disclosed as a warning on every export that uses the mapping.
``mirror_layers`` (the render snapshot mirrored into the stack) is the
honesty gate: a legend-backed element goes native only when the layer it
needs is provably in the mirror; without proof it stays on the composer
engine rather than rendering a wrong-but-pretty legend.
"""

from __future__ import annotations

import json
import logging
import tempfile
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

_NORTH_ARROW_SVG_NAME = "pwb_north_arrow.svg"


def _north_arrow_svg_path() -> str:
    """Materialise the built-in north indicator once per machine temp dir."""
    try:
        cache = Path(tempfile.gettempdir()) / _NORTH_ARROW_SVG_NAME
        if not cache.is_file() or cache.read_text(encoding="utf-8") != _NORTH_ARROW_SVG:
            cache.write_text(_NORTH_ARROW_SVG, encoding="utf-8")
        return str(cache)
    except OSError:
        logger.warning("could not materialise north arrow SVG", exc_info=True)
        return ""

__all__ = [
    "LayoutExportReport",
    "build_layout_spec",
    "export_composition_reported",
    "hybrid_element_types",
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

# Element types with NO native counterpart under any condition — the hard
# hybrid boundary. Rendered by the composer engine; each type is itemized in
# the export report's ``hybrid_items`` when present and visible.
_HYBRID_TYPES: frozenset[ElementType] = frozenset({
    ElementType.TIMESCALE,
    ElementType.INSET_MAP,
    ElementType.STAT_CHART,
    ElementType.PROFILE,
    ElementType.FAULT_SYMBOLS,   # hand-authored pattern swatch table
    ElementType.LITHOLOGY_LEGEND,  # hand-authored pattern swatch table
})

# Legend-backed elements (V7 §13): mapped onto the native legend item bound
# to the main map, gated on the required layer kind being in the mirror.
# The C++ legend cannot filter layers (no such wire key — see the module
# docstring), so the legend lists every layer of the linked map.
_SCALAR_LAYER_TYPES = frozenset({"scalar_grid"})
_FACIES_LAYER_TYPES = frozenset({"polygon", "facies"})
_WELL_LAYER_TYPES = frozenset({"well_point", "well"})


def _layer_field(layer: Any, name: str, default: Any = None) -> Any:
    if isinstance(layer, Mapping):
        return layer.get(name, default)
    return getattr(layer, name, default)


def _normalize_mirror_layers(mirror_layers: Any) -> list[Any]:
    """Accept a render snapshot (``.layers``) or a plain layer sequence."""
    if mirror_layers is None:
        return []
    layers = getattr(mirror_layers, "layers", None)
    if layers is not None:
        return list(layers)
    if isinstance(mirror_layers, Mapping):
        return []
    try:
        return [layer for layer in mirror_layers]
    except TypeError:
        return []


def _mirror_proves(
    element_type: ElementType, mirror_layers: Any
) -> bool:
    """Can the mirrored layer set prove this legend-backed element native?

    COLORBAR needs a scalar factor raster in the mirror (the §5 float-GeoTIFF
    path — its QGIS pseudocolor renderer is what the native legend draws, the
    same XML the canvas uses, so screen and export stay one symbol
    authority). FACIES_LEGEND (the geological legend) needs facies polygons
    or any categorized vector surface. WELL_LEGEND needs a well point layer.
    """
    layers = _normalize_mirror_layers(mirror_layers)
    layer_types = {
        str(_layer_field(layer, "layer_type", "") or "") for layer in layers
    }
    if element_type is ElementType.COLORBAR:
        return bool(layer_types & _SCALAR_LAYER_TYPES)
    if element_type is ElementType.FACIES_LEGEND:
        if layer_types & _FACIES_LAYER_TYPES:
            return True
        # Categorized vector surfaces (e.g. the facies classification
        # products) carry the legend content the composer element means.
        return any(
            str(_layer_field(layer, "layer_type", "") or "") == "vector"
            and isinstance(_layer_field(layer, "style", None), Mapping)
            and str(_layer_field(layer, "style", None).get("renderer") or "")
            == "categorized"
            for layer in layers
        )
    if element_type is ElementType.WELL_LEGEND:
        return bool(layer_types & _WELL_LAYER_TYPES)
    return False


#: Legend-backed elements (V7 §13) — see the module docstring for the
#: no-layer-filter limitation of the native legend item.
_LEGEND_BACKED_GATES: frozenset[ElementType] = frozenset({
    ElementType.COLORBAR,
    ElementType.FACIES_LEGEND,
    ElementType.WELL_LEGEND,
})

#: The complete key set the C++ legend branch parses (map_stack_service.cpp,
#: QgisMapStack::layoutExport, ``type == "legend"``). Anything else on the
#: wire is silently ignored — emitting keys outside this set would be
#: inventing protocol.
_LEGEND_ITEM_KEYS: frozenset[str] = frozenset({
    "type", "x", "y", "w", "h", "map_item", "title",
    "resize_to_contents", "background",
})

# Completeness guard (V7 §13 task: "verify each ElementType in _NATIVE_TYPES
# or explicitly listed as hybrid"): every ElementType value must fall in
# exactly one bucket — natively mapped, conditionally legend-backed, or an
# explicitly documented hybrid. An unaccounted type would be a *silent*
# hybrid; this assert fails at import instead (and tests re-assert it).
assert set(ElementType) == (
    set(_NATIVE_TYPES) | _HYBRID_TYPES | _LEGEND_BACKED_GATES
), "every ElementType must be native, legend-backed, or explicitly hybrid"


def _legend_backed_types(mirror_layers: Any) -> set[ElementType]:
    """Which legend-backed element types the mirror can prove natively."""
    return {
        element_type
        for element_type in _LEGEND_BACKED_GATES
        if _mirror_proves(element_type, mirror_layers)
    }


def hybrid_element_types(
    composition: MapCompositionDocument,
    *,
    mirror_layers: Any = None,
) -> list[str]:
    """Visible element types that force the composer engine, itemized.

    Returns the sorted distinct ``ElementType`` *values* of visible elements
    with no native layout counterpart under the given mirror description
    (legend-backed types without their layer in the mirror count as hybrid).
    This is the report's ``hybrid_items`` list — the explicit boundary of the
    all-or-nothing policy.
    """
    proven = _legend_backed_types(mirror_layers)
    types: set[str] = set()
    for element in _visible_elements(composition):
        etype = element.element_type
        if etype in _NATIVE_TYPES:
            continue
        if etype in _LEGEND_BACKED_GATES and etype in proven:
            continue
        types.add(str(etype.value))
    return sorted(types)


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
    # V7 §13 — the explicit hybrid boundary: element TYPES rendered by the
    # composer engine instead of QGIS, i.e. the visible types that forced
    # (or would force) the all-or-nothing fallback. Empty for a pure
    # ``qgis_layout`` export whose mapping is fully native.
    hybrid_items: list[str] = field(default_factory=list)

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
            "hybrid_items": list(self.hybrid_items),
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


# Rendered-pixel budget: A0 @600dpi is ~4e8 px; beyond ~2e8 the exporter
# allocates multi-GB rasters (review R3-P2 measured 8.7 GB RSS at 8.7e8 px).
MAX_EXPORT_PIXELS = 200_000_000


def _check_pixel_budget(composition: MapCompositionDocument, dpi: float) -> None:
    width_px = composition.width_mm / 25.4 * dpi
    height_px = composition.height_mm / 25.4 * dpi
    if width_px * height_px > MAX_EXPORT_PIXELS:
        suggested = 0.999 * MAX_EXPORT_PIXELS / max(1e-9, width_px * height_px) * dpi
        raise ValueError(
            f"export of {composition.width_mm}x{composition.height_mm} mm at "
            f"{dpi:g} dpi needs ~{width_px * height_px:.3g} px (budget "
            f"{MAX_EXPORT_PIXELS}); reduce dpi to ~{suggested:.0f} or smaller"
        )


def build_layout_spec(
    composition: MapCompositionDocument,
    *,
    map_extent: Sequence[float],
    crs: str | None,
    warnings: list[str] | None = None,
    mirror_layers: Any = None,
) -> dict[str, Any]:
    """Serialise the component graph into the bridge's layout spec JSON.

    ``mirror_layers`` is the render snapshot (or layer sequence) mirrored
    into the stack — the honesty gate for legend-backed elements
    (COLORBAR/FACIES_LEGEND/WELL_LEGEND): they map onto the native legend
    item only while their layer kind is provably in the mirror.

    Raises :class:`ValueError` when a visible element has no native layout
    counterpart — callers decide the fallback policy (see
    :func:`export_composition_reported`, which falls back to the composer
    renderer for the whole page).
    """

    def _warn(message: str) -> None:
        if warnings is not None:
            warnings.append(message)

    visible = _visible_elements(composition)
    proven_legend_types = _legend_backed_types(mirror_layers)
    unmapped = [
        el
        for el in visible
        if el.element_type not in _NATIVE_TYPES
        and el.element_type not in proven_legend_types
    ]
    if unmapped:
        names = ", ".join(sorted({el.element_type.value for el in unmapped}))
        raise ValueError(
            f"composition has elements with no native layout counterpart: {names}"
        )

    legend_backed_present = sorted(
        {
            el.element_type
            for el in visible
            if el.element_type in proven_legend_types
        },
        key=lambda etype: etype.value,
    )
    if legend_backed_present:
        # Documented limitation (module docstring): the C++ legend item has
        # no layer-filter key, so it lists EVERY layer of the linked map.
        names = ", ".join(etype.value for etype in legend_backed_present)
        _warn(
            f"{names} mapped to the native legend bound to the main map; "
            "the bridge legend item cannot filter layers, so it lists every "
            "layer of the linked map (not only the element's own layer)"
        )

    main_map = next(
        (el for el in visible if el.element_type is ElementType.MAIN_MAP), None
    )
    items: list[dict[str, Any]] = []
    grid_spacing_units: float | None = None
    for el in visible:
        if float(el.width_mm) <= 0 or float(el.height_mm) <= 0:
            raise ValueError(
                f"element {el.id} ({el.element_type.value}) has non-positive "
                "extent; fix the composition before export"
            )
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
        elif el.element_type in (
            ElementType.LEGEND,
            ElementType.COLORBAR,
            ElementType.FACIES_LEGEND,
            ElementType.WELL_LEGEND,
        ):
            # Native legend item. Only the keys the C++ parses are emitted
            # (map_stack_service.cpp layoutExport legend branch): type/x/y/
            # map_item/title/resize_to_contents/background. The legend binds
            # to the main map item — "map" — and lists every mirrored layer
            # (no filter key on the wire; see module docstring). Plain
            # LEGEND keeps its historical auto-size behaviour; the V7
            # legend-backed elements pin the composer-authored box instead.
            if el.element_type is ElementType.COLORBAR:
                title = str(props.get("title") or "图例")
                units = str(props.get("units") or "").strip()
                legend_title = f"{title} ({units})" if units else title
            else:
                legend_title = str(props.get("title") or "图例")
            legend_item: dict[str, Any] = {
                "type": "legend",
                "map_item": "map",
                "title": legend_title,
                "x": float(el.x_mm),
                "y": float(el.y_mm),
            }
            if el.element_type is ElementType.LEGEND:
                legend_item["w"] = float(el.width_mm)
                legend_item["h"] = float(el.height_mm)
            else:
                legend_item["resize_to_contents"] = False
            items.append(legend_item)
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
            converted = _map_grid_spacing_to_units(el, main_map, map_extent, crs)
            if converted is None:
                _warn(
                    f"grid element {el.id} has no main map to attach to; dropped"
                )
            else:
                grid_spacing_units = converted
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
            if float(el.width_mm) <= 0 or float(el.height_mm) <= 0:
                raise ValueError(
                    f"image element {el.id!r} has non-positive extent"
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
    geo_pdf: bool = False,
    mirror_layers: Any = None,
) -> LayoutExportReport:
    """Export the composition, preferring the native QgsLayout engine.

    ``stack`` is a :class:`qgis_render_bridge.mapstack.QgisMapStack` whose
    project already mirrors the map layers (the caller owns the mirror —
    canvas shim or a headless snapshot mirror). Without a stack, or when the
    composition carries elements with no native counterpart, the composer
    renderer produces the page and the report records the engine.
    ``mirror_layers`` is the render snapshot mirrored into that stack; it
    gates the legend-backed element mapping (COLORBAR / FACIES_LEGEND /
    WELL_LEGEND) and should be the SAME snapshot the canvas mirrors, so the
    export legend draws exactly what the screen shows.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    try:
        _check_pixel_budget(composition, float(dpi))
    except ValueError as exc:
        # A budget breach is a caller error, not an engine limitation —
        # raise rather than silently producing (or degrading to) a page.
        raise

    # V7 §13 — the hybrid boundary is computed up front so every exit path
    # reports WHICH element types forced (or would force) the composer
    # engine, not just that something did.
    proven_native = _legend_backed_types(mirror_layers)
    hybrid_types = hybrid_element_types(composition, mirror_layers=mirror_layers)
    counts: dict[str, int] = {}
    hybrid_element_ids: list[str] = []
    for el in _visible_elements(composition):
        if el.element_type in _NATIVE_TYPES or el.element_type in proven_native:
            continue
        counts[el.element_type.value] = counts.get(el.element_type.value, 0) + 1
        hybrid_element_ids.append(el.id)
    if hybrid_types:
        forced = ", ".join(f"{name}×{counts[name]}" for name in sorted(counts))
        warnings.append(
            f"composer fallback forced by unmapped elements: {forced}"
        )
        unproven = sorted(
            {
                el.element_type.value
                for el in _visible_elements(composition)
                if el.element_type in _LEGEND_BACKED_GATES
                and el.element_type not in proven_native
            }
        )
        if unproven:
            warnings.append(
                f"{', '.join(unproven)} element(s) have no matching layer "
                "in the mirror description (mirror_layers); a legend-backed "
                "element goes native only when its layer is provably mirrored"
            )

    can_use_layout = stack is not None and map_extent is not None
    if can_use_layout:
        try:
            spec = build_layout_spec(
                composition,
                map_extent=map_extent,
                crs=crs,
                warnings=warnings,
                mirror_layers=mirror_layers,
            )
            if geo_pdf:
                spec["geo_pdf"] = True
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
        unmapped_elements=hybrid_element_ids,
        hybrid_items=hybrid_types,
    )
