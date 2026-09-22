"""Categorized fill renderer XML with SVG pattern overlays (native path).

Pure-Python builder for a QGIS ``<renderer-v2 type="categorizedSymbol">``
payload whose per-category ``<symbol type="fill">`` stacks a ``SimpleFill``
base colour with an ``SVGFill`` pattern tile on top.  The structure mirrors
current QGIS save output (``<Option type="Map">`` property maps, reference
verified against ``qgis_render_bridge.legacy_style_to_renderer_xml``), and
every payload is loadable via ``QgsFeatureRenderer::load``.

Property keys follow ``qgsfillsymbollayer.cpp`` (``QgsSVGFillSymbolLayer``):
the pattern width is written as ``width`` with its unit in
``pattern_width_unit`` — there is no ``pattern_width`` key on load (an
unknown key would silently fall back to the 20 mm default), so the
``pattern_width_mm`` argument is serialised into ``width``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from xml.sax.saxutils import quoteattr

from paleo_workbench.mapping.facies_patterns import FACIES_PATTERN_DIR

__all__ = [
    "SVG_FILL_LAYER_CLASS",
    "categorized_fill_renderer_xml",
]

#: Symbol-layer class name QGIS registers the pattern tile layer under.
SVG_FILL_LAYER_CLASS = "SVGFill"

#: QGIS map-unit-scale encoding for "no scale dependency" (verbatim from
#: standard QGIS save output).
_NO_SCALE = "3x:0,0,0,0,0,0"


def _stable_uuid(*parts: str) -> str:
    """Deterministic ``{uuid}`` id for one generated element.

    QGIS save output writes random uuids for symbol-layer/category ids, but
    this payload feeds the mirror publish ledger
    (:func:`qgis_mirror._style_signature` compares renderer XML verbatim): a
    fresh random id on every call would defeat the ledger no-op path and
    force a full republish + QGIS renderer reparse each time.  Deriving the
    id from the element identity keeps the ``{uuid}`` shape QGIS expects
    while making the output byte-stable for identical inputs.
    """
    seed = "\x1f".join(("paleo-facies-renderer", *parts))
    return "{" + str(uuid5(NAMESPACE_URL, seed)) + "}"

_EMPTY_DD_PROPS = (
    "<data_defined_properties><Option type=\"Map\">"
    "<Option name=\"name\" type=\"QString\" value=\"\"/>"
    "<Option name=\"properties\"/>"
    "<Option name=\"type\" type=\"QString\" value=\"collection\"/>"
    "</Option></data_defined_properties>"
)

_RENDERER_DD_PROPS = (
    "<data-defined-properties><Option type=\"Map\">"
    "<Option name=\"name\" type=\"QString\" value=\"\"/>"
    "<Option name=\"properties\"/>"
    "<Option name=\"type\" type=\"QString\" value=\"collection\"/>"
    "</Option></data-defined-properties>"
)


def _option(name: str, value: str) -> str:
    return (
        f"<Option name={quoteattr(name)} type=\"QString\" "
        f"value={quoteattr(value)}/>"
    )


def _simple_fill_layer(fill: str, outline_color: str, outline_width: float,
                       *, layer_id: str) -> str:
    width = f"{outline_width:g}"
    options = "".join((
        _option("border_width_map_unit_scale", _NO_SCALE),
        _option("color", fill),
        _option("joinstyle", "bevel"),
        _option("offset", "0,0"),
        _option("offset_map_unit_scale", _NO_SCALE),
        _option("offset_unit", "MM"),
        _option("outline_color", outline_color),
        _option("outline_style", "solid"),
        _option("outline_width", width),
        _option("outline_width_unit", "MM"),
        _option("style", "solid"),
    ))
    return (
        f"<layer class=\"SimpleFill\" enabled=\"1\" locked=\"0\" pass=\"0\" "
        f"id={quoteattr(layer_id)}>"
        f"<Option type=\"Map\">{options}</Option>{_EMPTY_DD_PROPS}</layer>"
    )


def _svg_fill_layer(svg_path: Path, outline_color: str, outline_width: float,
                    pattern_width_mm: float, *, layer_id: str) -> str:
    options = "".join((
        _option("angle", "0"),
        _option("color", "#000000"),
        _option("outline_color", outline_color),
        _option("outline_width", f"{outline_width:g}"),
        _option("outline_width_unit", "MM"),
        _option("outline_width_map_unit_scale", _NO_SCALE),
        _option("pattern_width_unit", "MM"),
        _option("pattern_width_map_unit_scale", _NO_SCALE),
        _option("svg_outline_width_unit", "MM"),
        _option("svg_outline_width_map_unit_scale", _NO_SCALE),
        _option("svgFile", str(svg_path)),
        _option("width", f"{pattern_width_mm:g}"),
    ))
    return (
        f"<layer class={quoteattr(SVG_FILL_LAYER_CLASS)} enabled=\"1\" "
        f"locked=\"0\" pass=\"0\" "
        f"id={quoteattr(layer_id)}>"
        f"<Option type=\"Map\">{options}</Option>{_EMPTY_DD_PROPS}</layer>"
    )


def categorized_fill_renderer_xml(
    *,
    field: str,
    categories: Iterable[tuple[str, str, str]],
    fill_patterns: Mapping[str, str] | None = None,
    pattern_dir: Path = FACIES_PATTERN_DIR,
    outline_color: str = "#26364d",
    outline_width: float = 0.26,
    pattern_width_mm: float = 4.0,
) -> str:
    """Build a categorized fill renderer XML string with SVG pattern overlays.

    Each category becomes a two-layer fill symbol (``SimpleFill`` base +
    ``SVGFill`` tile); categories without a resolvable pattern get the base
    layer only.  ``fill_patterns`` maps category values to pattern ids (SVG
    stems); a pattern applies only when ``pattern_dir/<id>.svg`` exists.
    """
    entries = [(str(value), str(fill), str(label)) for value, fill, label in categories]
    patterns = dict(fill_patterns or {})
    base = Path(pattern_dir)

    category_elems: list[str] = []
    symbol_elems: list[str] = []
    for index, (value, fill, label) in enumerate(entries):
        legend = label or value
        category_elems.append(
            f"<category label={quoteattr(legend)} render=\"true\" "
            f"symbol={quoteattr(str(index))} type=\"string\" "
            f"uuid={quoteattr(_stable_uuid('category', field, str(index), value))} "
            f"value={quoteattr(value)}/>"
        )
        layers = _simple_fill_layer(
            fill, outline_color, outline_width,
            layer_id=_stable_uuid("simplefill", field, str(index), value))
        pattern_id = patterns.get(value)
        if pattern_id:
            svg_path = base / f"{pattern_id}.svg"
            if svg_path.is_file():
                layers += _svg_fill_layer(
                    svg_path, outline_color, outline_width, pattern_width_mm,
                    layer_id=_stable_uuid(
                        "svgfill", field, str(index), value, pattern_id))
        symbol_elems.append(
            f"<symbol alpha=\"1\" clip_to_extent=\"1\" force_rhr=\"0\" "
            f"frame_rate=\"10\" is_animated=\"0\" "
            f"name={quoteattr(str(index))} type=\"fill\">"
            f"{_EMPTY_DD_PROPS}{layers}</symbol>"
        )
    return (
        f"<renderer-v2 attr={quoteattr(str(field))} enableorderby=\"0\" "
        f"forceraster=\"0\" referencescale=\"-1\" symbollevels=\"0\" "
        f"type=\"categorizedSymbol\">"
        f"<categories>{''.join(category_elems)}</categories>"
        f"<symbols>{''.join(symbol_elems)}</symbols>"
        f"<rotation/><sizescale/>{_RENDERER_DD_PROPS}</renderer-v2>"
    )
