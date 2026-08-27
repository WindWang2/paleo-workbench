"""Vector and SVG/PDF layout renderer for Map Composer.

Unifies Map Canvas and Composer SVG export using the LayerRenderer pipeline.
"""

from __future__ import annotations

import html
import math
from typing import Any, Mapping

from paleo_workbench.mapping.color_ramps import get_color_ramp
from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.layers import (
    AnnotationMapLayer,
    ContourMapLayer,
    GridMapLayer,
    MapDocument,
    MapLayer,
    PolygonMapLayer,
    RasterMapLayer,
    VectorMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.mapping.renderers import (
    DEFAULT_RENDERER_REGISTRY,
    LegendItem,
    RenderContext,
    RenderUnit,
)


class MapComposerRenderer:
    """Renders a MapCompositionDocument to SVG vector output or raster painter."""

    def render_to_svg(self, doc: MapCompositionDocument) -> str:
        """Render the complete composed map into high-precision SVG vector markup."""
        w_px = doc.width_mm * 3.7795275591  # 1mm ~ 3.78px at 96 DPI
        h_px = doc.height_mm * 3.7795275591

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {doc.width_mm} {doc.height_mm}" width="{w_px}px" height="{h_px}px">',
            f'<rect width="{doc.width_mm}" height="{doc.height_mm}" fill="#ffffff" stroke="#333333" stroke-width="0.5"/>',
        ]

        # Extract main map layers to feed automatic dynamic legends if needed
        main_map_elem = None
        for elem in doc.elements:
            if elem.element_type == ElementType.MAIN_MAP and elem.visible:
                main_map_elem = elem
                break

        for elem in doc.elements:
            if not elem.visible:
                continue
            svg_parts.append(self._render_element_svg(elem, main_map_elem=main_map_elem))

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    def _render_element_svg(self, elem: ComposerElement, main_map_elem: ComposerElement | None = None) -> str:
        t = elem.element_type
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm

        if t == ElementType.MAIN_MAP:
            return self._render_main_map_svg(elem)
        elif t == ElementType.TITLE:
            title_text = elem.properties.get("text", "古地理图")
            escaped_title = html.escape(str(title_text))
            return (
                f'<g id="{elem.id}">'
                f'<text x="{x + w/2}" y="{y + h - 2}" font-family="SimSun, Times New Roman, sans-serif" font-size="8" font-weight="bold" fill="#000000" text-anchor="middle">{escaped_title}</text>'
                f'</g>'
            )
        elif t == ElementType.NORTH_ARROW:
            cx = x + w / 2
            cy = y + h / 2
            return (
                f'<g id="{elem.id}">'
                f'<polygon points="{cx},{y} {x + w},{y + h} {cx},{y + h * 0.75} {x},{y + h}" fill="#000000" stroke="#000000" stroke-width="0.2"/>'
                f'<text x="{cx}" y="{y - 1}" font-family="Arial, sans-serif" font-size="4" font-weight="bold" fill="#000000" text-anchor="middle">N</text>'
                f'</g>'
            )
        elif t == ElementType.SCALE_BAR:
            length_km = elem.properties.get("length_km", 50)
            return (
                f'<g id="{elem.id}">'
                f'<rect x="{x}" y="{y + h/2 - 1}" width="{w}" height="2" fill="#000000"/>'
                f'<rect x="{x}" y="{y + h/2 - 1}" width="{w/2}" height="2" fill="#ffffff" stroke="#000000" stroke-width="0.2"/>'
                f'<text x="{x}" y="{y + h - 1}" font-family="Arial, sans-serif" font-size="3" fill="#000000" text-anchor="start">0</text>'
                f'<text x="{x + w/2}" y="{y + h - 1}" font-family="Arial, sans-serif" font-size="3" fill="#000000" text-anchor="middle">{length_km//2}</text>'
                f'<text x="{x + w}" y="{y + h - 1}" font-family="Arial, sans-serif" font-size="3" fill="#000000" text-anchor="end">{length_km} km</text>'
                f'</g>'
            )
        elif t == ElementType.LEGEND:
            return self._render_legend_svg(elem, main_map_elem=main_map_elem)
        return f'<rect id="{elem.id}" x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#cccccc" stroke-dasharray="1,1"/>'

    def _render_main_map_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        inner_svg = [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#181c22" stroke="#444444" stroke-width="0.3"/>'
        ]

        map_doc = elem.properties.get("map_document")
        layers = elem.properties.get("layers", [])
        extent = elem.properties.get("extent", None)

        # 1. If a MapDocument instance is supplied
        if isinstance(map_doc, MapDocument):
            extent = map_doc.extent
            ctx = RenderContext(
                extent=extent, width=w, height=h, x_offset=x, y_offset=y,
                units=RenderUnit.MM,
            )
            for layer in map_doc.layers:
                if not layer.visible:
                    continue
                renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
                rendered = renderer.render_svg(layer, ctx)
                if rendered:
                    inner_svg.append(rendered)
            return f'<g id="{elem.id}">\n' + "\n".join(inner_svg) + f'\n</g>'

        # 2. If list of MapLayer instances is supplied
        if layers and isinstance(layers[0], MapLayer):
            if extent is None:
                # aggregate
                xmins = [lyr.extent[0] for lyr in layers if lyr.extent]
                ymins = [lyr.extent[1] for lyr in layers if lyr.extent]
                xmaxs = [lyr.extent[2] for lyr in layers if lyr.extent]
                ymaxs = [lyr.extent[3] for lyr in layers if lyr.extent]
                extent = (min(xmins), min(ymins), max(xmaxs), max(ymaxs)) if xmins else (0.0, 0.0, 1.0, 1.0)
            ctx = RenderContext(
                extent=extent, width=w, height=h, x_offset=x, y_offset=y,
                units=RenderUnit.MM,
            )
            for layer in layers:
                if not layer.visible:
                    continue
                renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
                rendered = renderer.render_svg(layer, ctx)
                if rendered:
                    inner_svg.append(rendered)
            return f'<g id="{elem.id}">\n' + "\n".join(inner_svg) + f'\n</g>'

        # 3. Fallback to dictionary layers (legacy compatibility)
        if layers and extent and len(extent) == 4:
            # Convert raw dicts into VectorMapLayer / GridMapLayer and render through registry
            ctx = RenderContext(
                extent=extent, width=w, height=h, x_offset=x, y_offset=y,
                units=RenderUnit.MM,
            )
            for lyr_dict in layers:
                if not isinstance(lyr_dict, Mapping):
                    continue
                features = lyr_dict.get("features", [])
                style_dict = lyr_dict.get("style") or {"fill": lyr_dict.get("color", "#4fc3f7"), "stroke": "#222222"}
                l_type = str(lyr_dict.get("layer_type") or "vector")
                v_layer = VectorMapLayer(
                    id=str(lyr_dict.get("id") or "vlyr"),
                    name=str(lyr_dict.get("name") or "Layer"),
                    layer_type=l_type,
                    extent=extent,
                    features=tuple(features),
                    style=style_dict,
                )
                renderer = DEFAULT_RENDERER_REGISTRY.resolve(v_layer)
                rendered = renderer.render_svg(v_layer, ctx)
                if rendered:
                    inner_svg.append(rendered)
        else:
            title = elem.properties.get("title", "主图画布 (Main Map Canvas)")
            escaped_title = html.escape(str(title))
            inner_svg.append(f'<text x="{x + w/2}" y="{y + h/2}" font-family="Arial, sans-serif" font-size="5" fill="#888888" text-anchor="middle">{escaped_title}</text>')

        return f'<g id="{elem.id}">\n' + "\n".join(inner_svg) + f'\n</g>'

    def _render_legend_svg(self, elem: ComposerElement, main_map_elem: ComposerElement | None = None) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        legend_items: list[LegendItem] = []

        # 1. Explicit items in properties
        raw_items = elem.properties.get("items", [])
        if raw_items:
            for it in raw_items:
                if isinstance(it, LegendItem):
                    legend_items.append(it)
                elif isinstance(it, Mapping):
                    legend_items.append(
                        LegendItem(
                            label=str(it.get("label") or "Item"),
                            color=str(it.get("color") or "#4fc3f7"),
                            symbol_type=str(it.get("symbol_type") or "polygon"),
                            gradient_stops=tuple(it.get("gradient_stops") or ()),
                        )
                    )

        # 2. Extract from main map if available and no explicit items
        if not legend_items and main_map_elem is not None:
            map_doc = main_map_elem.properties.get("map_document")
            layers = main_map_elem.properties.get("layers", [])
            if isinstance(map_doc, MapDocument):
                for lyr in map_doc.layers:
                    if lyr.visible:
                        renderer = DEFAULT_RENDERER_REGISTRY.resolve(lyr)
                        legend_items.extend(renderer.legend_items(lyr))
            elif layers and isinstance(layers[0], MapLayer):
                for lyr in layers:
                    if lyr.visible:
                        renderer = DEFAULT_RENDERER_REGISTRY.resolve(lyr)
                        legend_items.extend(renderer.legend_items(lyr))

        if not legend_items:
            legend_items = [
                LegendItem(label="三角洲砂体", color="#ffe082", symbol_type="polygon"),
                LegendItem(label="湖相泥岩", color="#b0bec5", symbol_type="polygon"),
            ]

        item_h = 6.0
        req_h = max(h, 10.0 + len(legend_items) * item_h)
        svg_lines = [
            f'<g id="{elem.id}">',
            f'<rect x="{x}" y="{y}" width="{w}" height="{req_h}" fill="#ffffff" stroke="#666666" stroke-width="0.2" fill-opacity="0.95"/>',
            f'<text x="{x + 4}" y="{y + 5.5}" font-family="SimSun, Arial, sans-serif" font-size="4" font-weight="bold" fill="#000000">图 例</text>',
        ]

        swatch_mm = 25.4 / 96.0  # px → mm at the 96 DPI authoring baseline
        for idx, it in enumerate(legend_items):
            iy = y + 9.0 + idx * item_h
            escaped_label = html.escape(str(it.label))
            if it.symbol_type == "gradient" and it.gradient_stops:
                # Continuous color bar in legend
                grad_id = f"grad_{idx}_{abs(hash(it.label)) % 10000}"
                stops_svg = "".join(f'<stop offset="{pos*100:.1f}%" stop-color="{col}"/>' for pos, col in it.gradient_stops)
                svg_lines.append(f'<defs><linearGradient id="{grad_id}" x1="0%" y1="0%" x2="100%" y2="0%">{stops_svg}</linearGradient></defs>')
                svg_lines.append(f'<rect x="{x + 4}" y="{iy}" width="14" height="3" fill="url(#{grad_id})" stroke="#333333" stroke-width="0.1"/>')
                svg_lines.append(f'<text x="{x + 21}" y="{iy + 2.5}" font-family="SimSun, Arial, sans-serif" font-size="2.6" fill="#000000">{escaped_label}</text>')
            elif it.symbol_type == "line":
                svg_lines.append(f'<line x1="{x + 4}" y1="{iy + 1.5}" x2="{x + 10}" y2="{iy + 1.5}" stroke="{it.color}" stroke-width="{max(0.2, it.stroke_width * swatch_mm):.2f}"/>')
                svg_lines.append(f'<text x="{x + 13}" y="{iy + 2.5}" font-family="SimSun, Arial, sans-serif" font-size="2.8" fill="#000000">{escaped_label}</text>')
            elif it.symbol_type == "point":
                svg_lines.append(f'<circle cx="{x + 7}" cy="{iy + 1.5}" r="2" fill="{it.color}" stroke="{it.stroke_color}" stroke-width="{max(0.1, it.stroke_width * swatch_mm):.2f}"/>')
                svg_lines.append(f'<text x="{x + 13}" y="{iy + 2.5}" font-family="SimSun, Arial, sans-serif" font-size="2.8" fill="#000000">{escaped_label}</text>')
            else:
                svg_lines.append(f'<rect x="{x + 4}" y="{iy}" width="6" height="3" fill="{it.color}" stroke="{it.stroke_color}" stroke-width="0.1"/>')
                svg_lines.append(f'<text x="{x + 13}" y="{iy + 2.5}" font-family="SimSun, Arial, sans-serif" font-size="2.8" fill="#000000">{escaped_label}</text>')

        svg_lines.append('</g>')
        return "\n".join(svg_lines)


composer_renderer = MapComposerRenderer()
