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
    _MM_PER_PX,
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
        elif t == ElementType.TEXT:
            return self._render_text_svg(elem)
        elif t == ElementType.IMAGE:
            return self._render_image_svg(elem)
        elif t == ElementType.INSET_MAP:
            return self._render_inset_map_svg(elem)
        elif t == ElementType.STAT_CHART:
            return self._render_stat_chart_svg(elem)
        elif t == ElementType.METADATA:
            return self._render_metadata_svg(elem)
        elif t == ElementType.COLORBAR:
            return self._render_colorbar_svg(elem)
        elif t == ElementType.GRID:
            return self._render_grid_svg(elem)
        elif t == ElementType.ANNOTATION:
            return self._render_annotation_svg(elem)
        return f'<rect id="{elem.id}" x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#cccccc" stroke-dasharray="1,1"/>'

    # ------------------------------------------------------------------
    # Component renderers (scene millimetres; SVG viewBox is mm-based)
    # ------------------------------------------------------------------

    def _render_text_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        text = str(elem.properties.get("text") or "")
        font_size = float(elem.properties.get("font_size") or 4.0)
        color = str(elem.properties.get("color") or "#000000")
        align = str(elem.properties.get("align") or "left")
        anchor = {"left": "start", "center": "middle", "right": "end"}.get(align, "start")
        tx = {"left": x, "center": x + w / 2, "right": x + w}.get(align, x)
        lines = text.splitlines() or [""]
        parts = [f'<g id="{elem.id}">']
        for i, line in enumerate(lines):
            ly = y + font_size + i * font_size * 1.35
            if ly > y + h + 0.01:
                break
            parts.append(
                f'<text x="{tx:.2f}" y="{ly:.2f}" font-family="SimSun, Arial, sans-serif"'
                f' font-size="{font_size}" fill="{color}" text-anchor="{anchor}">'
                f"{html.escape(line)}</text>"
            )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_annotation_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        text = str(elem.properties.get("text") or "")
        font_size = float(elem.properties.get("font_size") or 3.5)
        leader = bool(elem.properties.get("leader", True))
        anchor_x = x + w
        anchor_y = y + h
        parts = [f'<g id="{elem.id}">']
        if leader:
            parts.append(
                f'<line x1="{anchor_x:.2f}" y1="{anchor_y:.2f}"'
                f' x2="{x + w * 0.2:.2f}" y2="{y + h * 0.35:.2f}"'
                f' stroke="#555555" stroke-width="0.2"/>'
            )
            parts.append(
                f'<circle cx="{anchor_x:.2f}" cy="{anchor_y:.2f}" r="0.5" fill="#555555"/>'
            )
        parts.append(
            f'<text x="{x:.2f}" y="{y + font_size:.2f}" font-family="SimSun, Arial, sans-serif"'
            f' font-size="{font_size}" fill="#111111">{html.escape(text)}</text>'
        )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_grid_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        spacing = max(2.0, float(elem.properties.get("spacing_mm") or 20.0))
        color = str(elem.properties.get("color") or "#9aa4b2")
        width_mm = float(elem.properties.get("line_width_mm") or 0.2)
        parts = [f'<g id="{elem.id}">']
        index = 0
        gx = x + spacing
        while gx < x + w - 0.01:
            parts.append(
                f'<line x1="{gx:.2f}" y1="{y:.2f}" x2="{gx:.2f}" y2="{y + h:.2f}"'
                f' stroke="{color}" stroke-width="{width_mm}"'
                f' stroke-dasharray="1.5,1"/>'
            )
            gx += spacing
            index += 1
        gy = y + spacing
        while gy < y + h - 0.01:
            parts.append(
                f'<line x1="{x:.2f}" y1="{gy:.2f}" x2="{x + w:.2f}" y2="{gy:.2f}"'
                f' stroke="{color}" stroke-width="{width_mm}"'
                f' stroke-dasharray="1.5,1"/>'
            )
            gy += spacing
            index += 1
        # Frame belongs to the graticule card: solid outline.
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f' fill="none" stroke="#444444" stroke-width="0.35"/>'
        )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_image_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        import base64

        b64 = elem.properties.get("image_data_png_b64")
        path = elem.properties.get("image_path")
        href = ""
        if b64:
            href = f"data:image/png;base64,{b64}"
        elif path:
            href = str(path)
        if not href:
            return (
                f'<g id="{elem.id}">'
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
                f' fill="#f2f4f7" stroke="#999999" stroke-width="0.2"/>'
                f'<text x="{x + w / 2:.2f}" y="{y + h / 2:.2f}" font-family="Arial" font-size="3.4"'
                f' fill="#777777" text-anchor="middle">图像占位（未绑定）</text></g>'
            )
        return (
            f'<g id="{elem.id}">'
            f'<image x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f' xlink:href="{html.escape(href)}" preserveAspectRatio="xMidYMid meet"/>'
            f"</g>"
        )

    def _render_inset_map_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        parts = [
            f'<g id="{elem.id}">',
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f' fill="#ffffff" stroke="#444444" stroke-width="0.35"/>',
            f'<text x="{x + 2:.2f}" y="{y + 4.4:.2f}" font-family="SimSun, Arial"'
            f' font-size="3.2" fill="#333333">附图</text>',
        ]
        map_doc = elem.properties.get("map_document")
        layers = elem.properties.get("layers", [])
        renderable = None
        if isinstance(map_doc, MapDocument):
            renderable = [lyr for lyr in map_doc.layers if lyr.visible]
        elif layers and isinstance(layers[0], MapLayer):
            renderable = [lyr for lyr in layers if lyr.visible]
        if renderable:
            extent = elem.properties.get("extent")
            if extent is None:
                xmins = [lyr.extent[0] for lyr in renderable if lyr.extent]
                ymins = [lyr.extent[1] for lyr in renderable if lyr.extent]
                xmaxs = [lyr.extent[2] for lyr in renderable if lyr.extent]
                ymaxs = [lyr.extent[3] for lyr in renderable if lyr.extent]
                extent = (
                    (min(xmins), min(ymins), max(xmaxs), max(ymaxs))
                    if xmins
                    else (0.0, 0.0, 1.0, 1.0)
                )
            ctx = RenderContext(
                extent=extent, width=w, height=h, x_offset=x, y_offset=y,
                units=RenderUnit.MM,
            )
            for layer in renderable:
                renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
                rendered = renderer.render_svg(layer, ctx)
                if rendered:
                    parts.append(rendered)
        # Locator rectangle hinting the main-map window inside the inset.
        locator = elem.properties.get("locator_rect")
        if isinstance(locator, (list, tuple)) and len(locator) == 4:
            lx, ly, lw, lh = (float(v) for v in locator)
            parts.append(
                f'<rect x="{x + lx * w:.2f}" y="{y + ly * h:.2f}"'
                f' width="{lw * w:.2f}" height="{lh * h:.2f}"'
                f' fill="none" stroke="#d84315" stroke-width="0.4"/>'
            )
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f' fill="none" stroke="#444444" stroke-width="0.35"/>'
        )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_stat_chart_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        chart_type = str(elem.properties.get("chart_type") or "bar")
        title = str(elem.properties.get("title") or "")
        series = list(elem.properties.get("series") or [])
        units = str(elem.properties.get("units") or "")
        parts = [
            f'<g id="{elem.id}">',
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f' fill="#ffffff" stroke="#666666" stroke-width="0.25"/>',
        ]
        if title:
            parts.append(
                f'<text x="{x + w / 2:.2f}" y="{y + 4.6:.2f}" font-family="SimSun, Arial"'
                f' font-size="3.4" font-weight="bold" fill="#000000"'
                f' text-anchor="middle">{html.escape(title)}</text>'
            )
        values = [float(s.get("value", 0.0) or 0.0) for s in series if isinstance(s, Mapping)]
        labels = [str(s.get("label", "")) for s in series if isinstance(s, Mapping)]
        if values:
            plot_x, plot_y = x + 6.0, y + 8.0
            plot_w, plot_h = w - 10.0, h - 15.0
            vmax = max(abs(v) for v in values) or 1.0
            if chart_type == "bar":
                bar_w = plot_w / max(1, len(values)) * 0.7
                gap = plot_w / max(1, len(values))
                for i, value in enumerate(values):
                    bar_h = plot_h * abs(value) / vmax
                    bx = plot_x + i * gap + (gap - bar_w) / 2
                    by = plot_y + plot_h - bar_h
                    parts.append(
                        f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bar_w:.2f}"'
                        f' height="{max(0.2, bar_h):.2f}" fill="#4c78a8"'
                        f' stroke="#2b5a86" stroke-width="0.15"/>'
                    )
                    if labels and labels[i]:
                        parts.append(
                            f'<text x="{bx + bar_w / 2:.2f}" y="{plot_y + plot_h + 3.0:.2f}"'
                            f' font-family="Arial" font-size="2.2" fill="#333333"'
                            f' text-anchor="middle">{html.escape(labels[i])}</text>'
                        )
                # value axis max label
                parts.append(
                    f'<text x="{plot_x + plot_w:.2f}" y="{plot_y - 0.6:.2f}"'
                    f' font-family="Arial" font-size="2.2" fill="#555555"'
                    f' text-anchor="end">{vmax:g}{html.escape(units)}</text>'
                )
            else:  # horizontal bars
                bar_h = plot_h / max(1, len(values)) * 0.65
                gap = plot_h / max(1, len(values))
                for i, value in enumerate(values):
                    bar_w = plot_w * abs(value) / vmax * 0.8
                    by = plot_y + i * gap + (gap - bar_h) / 2
                    parts.append(
                        f'<rect x="{plot_x:.2f}" y="{by:.2f}" width="{max(0.2, bar_w):.2f}"'
                        f' height="{bar_h:.2f}" fill="#4c78a8"'
                        f' stroke="#2b5a86" stroke-width="0.15"/>'
                    )
                    if labels and labels[i]:
                        parts.append(
                            f'<text x="{plot_x - 0.8:.2f}" y="{by + bar_h / 2 + 0.8:.2f}"'
                            f' font-family="Arial" font-size="2.2" fill="#333333"'
                            f' text-anchor="end">{html.escape(labels[i])}</text>'
                        )
        else:
            parts.append(
                f'<text x="{x + w / 2:.2f}" y="{y + h / 2:.2f}" font-family="SimSun, Arial"'
                f' font-size="3.0" fill="#888888" text-anchor="middle">统计图（无数据）</text>'
            )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_metadata_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        fields = list(elem.properties.get("fields") or [])
        font_size = float(elem.properties.get("font_size") or 3.0)
        parts = [f'<g id="{elem.id}">']
        # Two-column key/value grid; extra fields wrap into further columns.
        per_column = max(1, int(h // (font_size * 1.6)))
        columns = max(1, (len(fields) + per_column - 1) // per_column)
        column_w = w / columns
        for i, entry in enumerate(fields):
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            key, value = str(entry[0]), str(entry[1])
            column = i // per_column
            row = i % per_column
            fx = x + column * column_w
            fy = y + font_size * (row + 1) * 1.6
            parts.append(
                f'<text x="{fx:.2f}" y="{fy:.2f}" font-family="SimSun, Arial"'
                f' font-size="{font_size}" fill="#000000">'
                f"{html.escape(key)}: {html.escape(value)}</text>"
            )
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f' fill="none" stroke="#999999" stroke-width="0.2"/>'
        )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_colorbar_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        title = str(elem.properties.get("title") or "")
        vmin = float(elem.properties.get("min") or 0.0)
        vmax = float(elem.properties.get("max") or 1.0)
        stops = list(elem.properties.get("stops") or ())
        discrete = bool(elem.properties.get("discrete", False))
        bar_w = min(10.0, w * 0.8)
        title_h = 6.0 if title else 0.0
        label_h = 10.0
        bar_y = y + title_h
        bar_h = max(4.0, h - title_h - label_h)
        parts = [f'<g id="{elem.id}">']
        bar_x = x + 4.0 if title else x
        if title:
            parts.append(
                f'<text x="{x - 1.2:.2f}" y="{bar_y + bar_h / 2:.2f}"'
                f' font-family="SimSun, Arial" font-size="3.2" fill="#000000"'
                f' text-anchor="middle" transform="rotate(-90 {x - 1.2:.2f}'
                f' {bar_y + bar_h / 2:.2f})">{html.escape(title)}</text>'
            )
        if not stops:
            stops = [(0.0, "#053061"), (1.0, "#67001f")]
        if discrete:
            n = len(stops)
            seg_h = bar_h / max(1, n)
            for i, (_pos, color) in enumerate(stops):
                parts.append(
                    f'<rect x="{bar_x:.2f}" y="{bar_y + i * seg_h:.2f}"'
                    f' width="{bar_w:.2f}" height="{seg_h + 0.02:.2f}"'
                    f' fill="{color}" stroke="#333333" stroke-width="0.08"/>'
                )
        else:
            grad_id = f"cbar_{abs(hash(elem.id)) % 100000}"
            ordered = sorted(stops, key=lambda s: float(s[0]))
            stops_svg = "".join(
                f'<stop offset="{float(pos) * 100:.1f}%" stop-color="{color}"/>'
                for pos, color in ordered
            )
            parts.append(
                f'<defs><linearGradient id="{grad_id}" x1="0%" y1="100%"'
                f' x2="0%" y2="0%">{stops_svg}</linearGradient></defs>'
            )
            parts.append(
                f'<rect x="{bar_x:.2f}" y="{bar_y:.2f}" width="{bar_w:.2f}"'
                f' height="{bar_h:.2f}" fill="url(#{grad_id})"'
                f' stroke="#333333" stroke-width="0.2"/>'
            )
        # End labels (bottom = min, top = max for vertical bars).
        parts.append(
            f'<text x="{bar_x + bar_w + 1.5:.2f}" y="{bar_y + bar_h + 0.8:.2f}"'
            f' font-family="Arial" font-size="2.4" fill="#000000">{vmin:g}</text>'
        )
        parts.append(
            f'<text x="{bar_x + bar_w + 1.5:.2f}" y="{bar_y + 2.4:.2f}"'
            f' font-family="Arial" font-size="2.4" fill="#000000">{vmax:g}</text>'
        )
        parts.append("</g>")
        return "\n".join(parts)

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

        swatch_mm = _MM_PER_PX  # px → mm at the 96 DPI authoring baseline
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
