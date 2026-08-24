"""Vector and SVG/PDF layout renderer for Map Composer."""

from __future__ import annotations

import math
from typing import Any

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)


class MapComposerRenderer:
    """Renders a MapCompositionDocument to SVG vector output or raster painter."""

    def render_to_svg(self, doc: MapCompositionDocument) -> str:
        """Render the complete composed map into high-precision SVG vector markup."""
        w_px = doc.width_mm * 3.7795275591  # 1mm ~ 3.78px at 96 DPI
        h_px = doc.height_mm * 3.7795275591

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {doc.width_mm} {doc.height_mm}" width="{w_px}px" height="{h_px}px">',
            f'<rect width="{doc.width_mm}" height="{doc.height_mm}" fill="#ffffff" stroke="#333333" stroke-width="0.5"/>',
        ]

        for elem in doc.elements:
            if not elem.visible:
                continue
            svg_parts.append(self._render_element_svg(elem))

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    def _render_element_svg(self, elem: ComposerElement) -> str:
        t = elem.element_type
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm

        if t == ElementType.MAIN_MAP:
            layers = elem.properties.get("layers", [])
            extent = elem.properties.get("extent", None)
            inner_svg = [
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#181c22" stroke="#444444" stroke-width="0.3"/>'
            ]
            if layers and extent and len(extent) == 4:
                xmin, ymin, xmax, ymax = extent
                dx = xmax - xmin if (xmax > xmin) else 1.0
                dy = ymax - ymin if (ymax > ymin) else 1.0

                def _map_pt(px: float, py: float) -> tuple[float, float]:
                    mx = x + ((px - xmin) / dx) * w
                    my = y + h - ((py - ymin) / dy) * h
                    return mx, my

                for lyr in layers:
                    features = lyr.get("features", [])
                    lyr_color = lyr.get("color", "#4fc3f7")
                    for feat in features:
                        geom = feat.get("geometry", {})
                        gtype = geom.get("type", "")
                        coords = geom.get("coordinates", [])
                        props = feat.get("properties", {})
                        fcolor = props.get("color", lyr_color)

                        if gtype == "Polygon" and coords:
                            ring = coords[0]
                            pts_str = " ".join(f"{_map_pt(p[0], p[1])[0]:.2f},{_map_pt(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2)
                            inner_svg.append(f'<polygon points="{pts_str}" fill="{fcolor}" fill-opacity="0.7" stroke="#222222" stroke-width="0.1"/>')
                        elif gtype == "MultiPolygon" and coords:
                            for poly_coords in coords:
                                if poly_coords:
                                    ring = poly_coords[0]
                                    pts_str = " ".join(f"{_map_pt(p[0], p[1])[0]:.2f},{_map_pt(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2)
                                    inner_svg.append(f'<polygon points="{pts_str}" fill="{fcolor}" fill-opacity="0.7" stroke="#222222" stroke-width="0.1"/>')
                        elif gtype == "LineString" and coords:
                            pts_str = " ".join(f"{_map_pt(p[0], p[1])[0]:.2f},{_map_pt(p[0], p[1])[1]:.2f}" for p in coords if len(p) >= 2)
                            inner_svg.append(f'<polyline points="{pts_str}" fill="none" stroke="{fcolor}" stroke-width="0.2"/>')
                        elif gtype == "Point" and coords:
                            mx, my = _map_pt(coords[0], coords[1])
                            inner_svg.append(f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="0.8" fill="{fcolor}" stroke="#000000" stroke-width="0.1"/>')
            else:
                title = elem.properties.get("title", "主图画布 (Main Map Canvas)")
                inner_svg.append(f'<text x="{x + w/2}" y="{y + h/2}" font-family="Arial" font-size="5" fill="#888888" text-anchor="middle">{title}</text>')

            return f'<g id="{elem.id}">\n' + "\n".join(inner_svg) + f'\n</g>'
        elif t == ElementType.TITLE:
            title_text = elem.properties.get("text", "古地理图")
            return (
                f'<g id="{elem.id}">'
                f'<text x="{x + w/2}" y="{y + h - 2}" font-family="SimSun, Times New Roman" font-size="8" font-weight="bold" fill="#000000" text-anchor="middle">{title_text}</text>'
                f'</g>'
            )
        elif t == ElementType.NORTH_ARROW:
            cx = x + w / 2
            cy = y + h / 2
            return (
                f'<g id="{elem.id}">'
                f'<polygon points="{cx},{y} {x + w},{y + h} {cx},{y + h * 0.75} {x},{y + h}" fill="#000000" stroke="#000000" stroke-width="0.2"/>'
                f'<text x="{cx}" y="{y - 1}" font-family="Arial" font-size="4" font-weight="bold" fill="#000000" text-anchor="middle">N</text>'
                f'</g>'
            )
        elif t == ElementType.SCALE_BAR:
            length_km = elem.properties.get("length_km", 50)
            return (
                f'<g id="{elem.id}">'
                f'<rect x="{x}" y="{y + h/2 - 1}" width="{w}" height="2" fill="#000000"/>'
                f'<rect x="{x}" y="{y + h/2 - 1}" width="{w/2}" height="2" fill="#ffffff" stroke="#000000" stroke-width="0.2"/>'
                f'<text x="{x}" y="{y + h - 1}" font-family="Arial" font-size="3" fill="#000000" text-anchor="start">0</text>'
                f'<text x="{x + w/2}" y="{y + h - 1}" font-family="Arial" font-size="3" fill="#000000" text-anchor="middle">{length_km//2}</text>'
                f'<text x="{x + w}" y="{y + h - 1}" font-family="Arial" font-size="3" fill="#000000" text-anchor="end">{length_km} km</text>'
                f'</g>'
            )
        elif t == ElementType.LEGEND:
            legend_items = elem.properties.get("items", [])
            if not legend_items:
                legend_items = [
                    {"label": "三角洲砂体", "color": "#ffe082"},
                    {"label": "湖相泥岩", "color": "#b0bec5"},
                ]

            item_h = 5
            req_h = max(h, 8 + len(legend_items) * item_h)
            svg_lines = [
                f'<g id="{elem.id}">',
                f'<rect x="{x}" y="{y}" width="{w}" height="{req_h}" fill="#ffffff" stroke="#666666" stroke-width="0.2" fill-opacity="0.9"/>',
                f'<text x="{x + 4}" y="{y + 5}" font-family="SimSun, Arial" font-size="4" font-weight="bold" fill="#000000">图 例</text>',
            ]
            for idx, it in enumerate(legend_items):
                iy = y + 8 + idx * item_h
                label = it.get("label", f"图例 {idx+1}")
                color = it.get("color", "#ffe082")
                svg_lines.append(f'<rect x="{x + 4}" y="{iy}" width="6" height="3" fill="{color}" stroke="#333333" stroke-width="0.1"/>')
                svg_lines.append(f'<text x="{x + 13}" y="{iy + 2.5}" font-family="SimSun, Arial" font-size="2.8" fill="#000000">{label}</text>')
            svg_lines.append('</g>')
            return "\n".join(svg_lines)
        return f'<rect id="{elem.id}" x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#cccccc" stroke-dasharray="1,1"/>'


composer_renderer = MapComposerRenderer()
