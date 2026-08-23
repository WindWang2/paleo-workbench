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
            return (
                f'<g id="{elem.id}">'
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#181c22" stroke="#444444" stroke-width="0.3"/>'
                f'<text x="{x + w/2}" y="{y + h/2}" font-family="Arial" font-size="6" fill="#888888" text-anchor="middle">主图画布 (Main Map Canvas)</text>'
                f'</g>'
            )
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
            return (
                f'<g id="{elem.id}">'
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff" stroke="#666666" stroke-width="0.2" fill-opacity="0.9"/>'
                f'<text x="{x + 4}" y="{y + 6}" font-family="Arial" font-size="4" font-weight="bold" fill="#000000">图 例</text>'
                f'<rect x="{x + 4}" y="{y + 9}" width="8" height="4" fill="#ffe082" stroke="#333333" stroke-width="0.1"/>'
                f'<text x="{x + 15}" y="{y + 12}" font-family="Arial" font-size="3" fill="#000000">三角洲砂体</text>'
                f'<rect x="{x + 4}" y="{y + 15}" width="8" height="4" fill="#b0bec5" stroke="#333333" stroke-width="0.1"/>'
                f'<text x="{x + 15}" y="{y + 18}" font-family="Arial" font-size="3" fill="#000000">湖相泥岩</text>'
                f'</g>'
            )
        return f'<rect id="{elem.id}" x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#cccccc" stroke-dasharray="1,1"/>'


composer_renderer = MapComposerRenderer()
