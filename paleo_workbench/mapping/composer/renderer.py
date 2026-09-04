"""Vector and SVG/PDF layout renderer for Map Composer.

Unifies Map Canvas and Composer SVG export using the LayerRenderer pipeline.
"""

from __future__ import annotations

import html
import math
from typing import Any, Mapping

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.registry import (
    CHART_COLOR_SEQUENCE,
    resolve_palette,
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
            if elem.locked:
                svg_parts.append(self._locked_marker_svg(elem))

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
        elif t == ElementType.TIMESCALE:
            return self._render_timescale_svg(elem)
        elif t == ElementType.NEATLINE:
            return self._render_neatline_svg(elem)
        elif t == ElementType.DATASOURCE:
            return self._render_datasource_svg(elem)
        elif t == ElementType.TIME_CREDITS:
            return self._render_time_credits_svg(elem)
        elif t == ElementType.STRAT_LABELS:
            return self._render_text_svg(elem)
        elif t == ElementType.FAULT_SYMBOLS:
            return self._render_fault_symbols_svg(elem)
        elif t == ElementType.FACIES_LEGEND:
            # 复用 LEGEND 渲染，仅默认标题不同（registry 注册「沉积相图例」）。
            return self._render_legend_svg(elem, main_map_elem=main_map_elem)
        elif t == ElementType.LITHOLOGY_LEGEND:
            return self._render_lithology_legend_svg(elem)
        return f'<rect id="{elem.id}" x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#cccccc" stroke-dasharray="1,1"/>'

    @staticmethod
    def _locked_marker_svg(elem: ComposerElement) -> str:
        """锁定元素的细角标：左上角小三角（不影响图面内容本身）。"""
        x, y = elem.x_mm, elem.y_mm
        return (
            f'<g data-locked="true" data-element="{elem.id}">'
            f'<path d="M {x:.2f} {y:.2f} L {x + 4.2:.2f} {y:.2f} L {x:.2f} {y + 4.2:.2f} Z"'
            f' fill="#2f6fab" fill-opacity="0.65"/></g>'
        )

    # ------------------------------------------------------------------
    # Component renderers (scene millimetres; SVG viewBox is mm-based)
    # ------------------------------------------------------------------

    def _render_text_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        text = str(elem.properties.get("text") or "")
        font_size = float(elem.properties.get("font_size") or 4.0)
        color = str(elem.properties.get("color") or "#000000")
        align = str(elem.properties.get("align") or "left")
        return self._multiline_text_svg(elem.id, x, y, w, h, text, font_size, color, align)

    @staticmethod
    def _multiline_text_svg(
        elem_id: str,
        x: float,
        y: float,
        w: float,
        h: float,
        text: str,
        font_size: float,
        color: str = "#000000",
        align: str = "left",
    ) -> str:
        """多行文本块（TEXT/STRAT_LABELS/TIME_CREDITS/DATASOURCE 共用）。"""
        anchor = {"left": "start", "center": "middle", "right": "end"}.get(align, "start")
        tx = {"left": x, "center": x + w / 2, "right": x + w}.get(align, x)
        lines = text.splitlines() or [""]
        parts = [f'<g id="{elem_id}">']
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

    def _render_neatline_svg(self, elem: ComposerElement) -> str:
        """图廓：独立边框元素（线宽/颜色/可选双线）。"""
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        line_width = max(0.05, float(elem.properties.get("line_width_mm") or 0.8))
        color = str(elem.properties.get("color") or "#000000")
        double_line = bool(elem.properties.get("double_line"))
        gap = max(0.5, float(elem.properties.get("inner_gap_mm") or 1.5))
        parts = [f'<g id="{elem.id}">']
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
            f' fill="none" stroke="{html.escape(color)}" stroke-width="{line_width:.2f}"/>'
        )
        if double_line:
            # 双线图廓：外粗内细，间距向内收缩。
            parts.append(
                f'<rect x="{x + gap:.2f}" y="{y + gap:.2f}" width="{max(0.5, w - 2 * gap):.2f}"'
                f' height="{max(0.5, h - 2 * gap):.2f}" fill="none"'
                f' stroke="{html.escape(color)}" stroke-width="{min(0.4, line_width * 0.5):.2f}"/>'
            )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_datasource_svg(self, elem: ComposerElement) -> str:
        """数据来源块：粗体标题 + 细分隔线 + 多行说明文本。"""
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        title = str(elem.properties.get("title") or "数据来源")
        text = str(elem.properties.get("text") or "")
        font_size = float(elem.properties.get("font_size") or 2.8)
        parts = [f'<g id="{elem.id}">']
        parts.append(
            f'<text x="{x:.2f}" y="{y + font_size + 0.6:.2f}" font-family="SimSun, Arial"'
            f' font-size="{font_size + 0.4:.2f}" font-weight="bold" fill="#000000">'
            f"{html.escape(title)}</text>"
        )
        rule_y = y + 2 * font_size + 1.4
        parts.append(
            f'<line x1="{x:.2f}" y1="{rule_y:.2f}" x2="{x + w:.2f}" y2="{rule_y:.2f}"'
            f' stroke="#666666" stroke-width="0.15"/>'
        )
        body = self._multiline_text_svg(
            elem.id + "_body", x, rule_y + 0.4, w, max(0.0, h - (rule_y - y)), text, font_size
        )
        parts.append(body)
        parts.append("</g>")
        return "\n".join(parts)

    def _render_time_credits_svg(self, elem: ComposerElement) -> str:
        """制图时间/责任署名小字块（缺省小字号、右对齐排版惯例）。"""
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        text = str(elem.properties.get("text") or "")
        font_size = float(elem.properties.get("font_size") or 2.6)
        return self._multiline_text_svg(
            elem.id, x, y, w, h, text, font_size, color="#333333", align="right"
        )

    def _render_timescale_svg(self, elem: ComposerElement) -> str:
        """年代地层条：水平分段色带 + 标签；空 stages 保持占位框。"""
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        stages = [
            s for s in (elem.properties.get("stages") or ()) if isinstance(s, Mapping)
        ]
        if not stages:
            return (
                f'<g id="{elem.id}">'
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
                f' fill="none" stroke="#cccccc" stroke-dasharray="1,1"/>'
                f'<text x="{x + w / 2:.2f}" y="{y + h / 2:.2f}" font-family="SimSun, Arial"'
                f' font-size="2.6" fill="#999999" text-anchor="middle">年代地层（未配置 stages）</text>'
                f"</g>"
            )
        # 分段宽度：有 start/end 时按跨度比例，否则等分。
        weights: list[float] = []
        for stage in stages:
            try:
                start = float(stage.get("start") or 0.0)
                end = float(stage.get("end") or 0.0)
            except (TypeError, ValueError):
                start, end = 0.0, 0.0
            span = end - start
            weights.append(span if span > 0 else 1.0)
        total = sum(weights)
        bar_h = min(h * 0.55, 6.0)
        bar_y = y + (h - bar_h - 3.2) / 2
        parts = [f'<g id="{elem.id}">']
        cx = x
        for stage, weight in zip(stages, weights):
            seg_w = w * weight / total
            color = str(stage.get("color") or "#b0bec5")
            parts.append(
                f'<rect x="{cx:.2f}" y="{bar_y:.2f}" width="{seg_w:.2f}"'
                f' height="{bar_h:.2f}" fill="{html.escape(color)}"'
                f' stroke="#37474f" stroke-width="0.15"/>'
            )
            label = str(stage.get("label") or "")
            if label:
                parts.append(
                    f'<text x="{cx + seg_w / 2:.2f}" y="{bar_y + bar_h + 2.8:.2f}"'
                    f' font-family="SimSun, Arial" font-size="2.4" fill="#000000"'
                    f' text-anchor="middle">{html.escape(label)}</text>'
                )
            cx += seg_w
        parts.append("</g>")
        return "\n".join(parts)

    def _render_fault_symbols_svg(self, elem: ComposerElement) -> str:
        """断层符号图例组：线样式样本（实/虚/点/点划）+ 标签。"""
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        title = str(elem.properties.get("title") or "断层符号")
        items = [i for i in (elem.properties.get("items") or ()) if isinstance(i, Mapping)]
        dash_map = {
            "solid": "",
            "dash": "2.4,1.2",
            "dot": "0.6,0.9",
            "dashdot": "2.8,1.0,0.6,1.0",
            "fault": "3.2,1.2",
        }
        parts = [
            f'<g id="{elem.id}">',
            f'<text x="{x:.2f}" y="{y + 4.2:.2f}" font-family="SimSun, Arial"'
            f' font-size="3.4" font-weight="bold" fill="#000000">{html.escape(title)}</text>',
        ]
        item_h = 5.2
        sample_len = min(12.0, w * 0.35)
        for idx, item in enumerate(items):
            iy = y + 7.0 + idx * item_h
            pattern = str(item.get("pattern") or "solid").lower()
            dash = dash_map.get(pattern, "")
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(
                f'<line x1="{x + 2.0:.2f}" y1="{iy:.2f}" x2="{x + 2.0 + sample_len:.2f}"'
                f' y2="{iy:.2f}" stroke="#1a1a1a" stroke-width="0.55"{dash_attr}/>'
            )
            label = str(item.get("label") or "")
            parts.append(
                f'<text x="{x + 2.0 + sample_len + 2.5:.2f}" y="{iy + 0.9:.2f}"'
                f' font-family="SimSun, Arial" font-size="2.6" fill="#000000">'
                f"{html.escape(label)}</text>"
            )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_lithology_legend_svg(self, elem: ComposerElement) -> str:
        """岩性图例：色块 + 纹理叠加（点/线/网格）+ 标签。"""
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        title = str(elem.properties.get("title") or "岩性图例")
        items = [i for i in (elem.properties.get("items") or ()) if isinstance(i, Mapping)]
        parts = [
            f'<g id="{elem.id}">',
            f'<text x="{x:.2f}" y="{y + 4.6:.2f}" font-family="SimSun, Arial"'
            f' font-size="3.6" font-weight="bold" fill="#000000">{html.escape(title)}</text>',
        ]
        item_h = 6.0
        swatch_w, swatch_h = 9.0, 3.6
        for idx, item in enumerate(items):
            iy = y + 7.0 + idx * item_h
            color = str(item.get("color") or "#cfd8dc")
            pattern = str(item.get("pattern") or "").lower()
            parts.append(
                f'<rect x="{x + 3.0:.2f}" y="{iy:.2f}" width="{swatch_w:.2f}"'
                f' height="{swatch_h:.2f}" fill="{html.escape(color)}"'
                f' stroke="#333333" stroke-width="0.15"/>'
            )
            if pattern in ("dots", "lines", "crosshatch"):
                # 纹理叠加：细小点/斜线/交叉线（打印可辨的岩性惯用纹理）。
                pat_id = f"lith_{abs(hash((elem.id, pattern, idx))) % 100000}"
                if pattern == "dots":
                    tile = (
                        f'<circle cx="0.5" cy="0.5" r="0.22" fill="#00000088"/>'
                        f'<circle cx="1.5" cy="1.5" r="0.22" fill="#00000088"/>'
                    )
                    size = 2.0
                elif pattern == "lines":
                    tile = '<line x1="0" y1="1.6" x2="1.6" y2="0" stroke="#00000077" stroke-width="0.18"/>'
                    size = 1.6
                else:  # crosshatch
                    tile = (
                        f'<line x1="0" y1="1.4" x2="1.4" y2="0" stroke="#00000077" stroke-width="0.15"/>'
                        f'<line x1="0" y1="0" x2="1.4" y2="1.4" stroke="#00000077" stroke-width="0.15"/>'
                    )
                    size = 1.4
                parts.append(
                    f'<defs><pattern id="{pat_id}" width="{size}" height="{size}"'
                    f' patternUnits="userSpaceOnUse">{tile}</pattern></defs>'
                )
                parts.append(
                    f'<rect x="{x + 3.0:.2f}" y="{iy:.2f}" width="{swatch_w:.2f}"'
                    f' height="{swatch_h:.2f}" fill="url(#{pat_id})"/>'
                )
            label = str(item.get("label") or "")
            parts.append(
                f'<text x="{x + 3.0 + swatch_w + 2.5:.2f}" y="{iy + 2.7:.2f}"'
                f' font-family="SimSun, Arial" font-size="2.8" fill="#000000">'
                f"{html.escape(label)}</text>"
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

    # ------------------------------------------------------------------
    # 统计图（B6）：bar/hbar/line/scatter/pie/donut/histogram/rose，
    # 纯几何绘制（无阴影、克制配色、确定性输出）
    # ------------------------------------------------------------------

    @staticmethod
    def _chart_colors(elem: ComposerElement) -> list[str]:
        """色序列：properties.colors 优先，缺省用 registry 内置 6 色。"""
        raw = elem.properties.get("colors")
        if isinstance(raw, (list, tuple)):
            colors = [str(c) for c in raw if str(c or "").strip()]
            if colors:
                return colors
        return list(CHART_COLOR_SEQUENCE)

    @staticmethod
    def _finite_or(value: float, default: float) -> float:
        """NaN/Inf 一律落回缺省值（float("nan") 不抛异常但会污染几何）。"""
        return value if math.isfinite(value) else default

    @staticmethod
    def _series_entries(series: Any) -> tuple[list[str], list[float]]:
        """[{label, value}] 分类序列归一化；非列表/坏项诚实跳过。"""
        if not isinstance(series, (list, tuple)):
            return [], []
        labels: list[str] = []
        values: list[float] = []
        for entry in series:
            if not isinstance(entry, Mapping):
                continue
            labels.append(str(entry.get("label", "")))
            try:
                value = float(entry.get("value", 0.0) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            values.append(MapComposerRenderer._finite_or(value, 0.0))
        return labels, values

    @staticmethod
    def _is_number(value: Any) -> bool:
        # bool 是 int 子类，显式排除（True/False 不是坐标）。
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @classmethod
    def _floats(cls, raw: Any) -> list[float]:
        """严格有限数值列表：非数值/NaN/Inf 一律跳过（拒绝猜测）。"""
        if not isinstance(raw, (list, tuple)):
            return []
        return [
            MapComposerRenderer._finite_or(float(v), 0.0)
            for v in raw
            if cls._is_number(v) and math.isfinite(float(v))
        ]

    @classmethod
    def _xy_series(cls, series: Any) -> tuple[list[float], list[float], list[str], bool]:
        """line/scatter 序列归一化为 ``(xs, ys, labels, x_is_value)``。

        支持三种形态（registry ``CHART_SERIES_SCHEMAS`` 有对应描述）：
          1. ``{x: [...], y: [...]}``      数值数组（x 轴按值缩放）；
          2. ``[{x: 数值, y: 数值}, ...]``  数值点对（x 轴按值缩放）；
          3. ``[{label: 类目, value: 数值}]`` 分类式（x 等距取序号，向后
             兼容既有图件）。
        非 MAPPING 项 / 非数值坐标一律跳过；空数据返回空 ys → 上层渲染
        诚实占位。
        """
        if isinstance(series, Mapping):
            xs, ys = cls._floats(series.get("x")), cls._floats(series.get("y"))
            count = min(len(xs), len(ys))
            return xs[:count], ys[:count], [""] * count, True
        if isinstance(series, (list, tuple)):
            entries = [s for s in series if isinstance(s, Mapping)]
            if entries and all(
                cls._is_number(s.get("x")) and cls._is_number(s.get("y")) for s in entries
            ):
                xs = [float(s["x"]) for s in entries]
                ys = [float(s["y"]) for s in entries]
                labels = [str(s.get("label") or "") for s in entries]
                return xs, ys, labels, True
            labels, values = cls._series_entries(series)
            return [float(i) for i in range(len(values))], values, labels, False
        return [], [], [], False

    @staticmethod
    def _hole_ratio(elem: ComposerElement) -> float:
        """donut 内孔半径比（0=实心饼；缺省/坏值 0.55，钳制 0~0.9）。"""
        try:
            hole = float(elem.properties.get("hole_ratio"))
        except (TypeError, ValueError):
            return 0.55
        if not math.isfinite(hole):
            return 0.55
        return min(0.9, max(0.0, hole))

    @staticmethod
    def _histogram_data(elem: ComposerElement) -> tuple[list[float], int]:
        """histogram 数据：series 为 {values: [...], bins: n}（或直接挂
        properties.values/bins），返回排序无关的原始值列表与箱数。"""
        series = elem.properties.get("series")
        if isinstance(series, Mapping):
            raw_values = series.get("values")
            raw_bins = series.get("bins") or elem.properties.get("bins") or 10
        else:
            raw_values = elem.properties.get("values")
            raw_bins = elem.properties.get("bins") or 10
        if not isinstance(raw_values, (list, tuple)):
            raw_values = ()
        values: list[float] = []
        for value in raw_values:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(parsed):
                continue
            values.append(parsed)
        try:
            bins = max(2, min(60, int(raw_bins)))
        except (TypeError, ValueError):
            bins = 10
        return values, bins

    @staticmethod
    def _polar(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
        """罗盘方位角（0=北, 顺时针）→ SVG 坐标。"""
        rad = math.radians(angle_deg)
        return cx + r * math.sin(rad), cy - r * math.cos(rad)

    def _render_stat_chart_svg(self, elem: ComposerElement) -> str:
        x, y, w, h = elem.x_mm, elem.y_mm, elem.width_mm, elem.height_mm
        chart_type = str(elem.properties.get("chart_type") or "bar").lower()
        title = str(elem.properties.get("title") or "")
        series = elem.properties.get("series")
        units = str(elem.properties.get("units") or "")
        colors = self._chart_colors(elem)
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
        plot_x, plot_y = x + 6.0, y + 8.0
        plot_w, plot_h = max(4.0, w - 10.0), max(4.0, h - 15.0)

        if chart_type in ("pie", "donut"):
            labels, values = self._series_entries(series)
            # 负值/零在占比语义下无扇区可言：诚实跳过（全非正 → 空态占位）。
            kept = [(label, value) for label, value in zip(labels, values) if value > 0.0]
            if not kept:
                parts.append(self._chart_placeholder(x, y, w, h))
            else:
                self._draw_pie(
                    parts, x, y, w, h, bool(title),
                    [label for label, _ in kept], [value for _, value in kept],
                    colors,
                    hole_ratio=self._hole_ratio(elem) if chart_type == "donut" else 0.0,
                )
        elif chart_type == "histogram":
            values, bins = self._histogram_data(elem)
            if not values:
                parts.append(self._chart_placeholder(x, y, w, h))
            else:
                self._draw_histogram(parts, plot_x, plot_y, plot_w, plot_h, values, bins)
        elif chart_type == "rose":
            entries = [
                s for s in (series if isinstance(series, (list, tuple)) else ())
                if isinstance(s, Mapping)
            ]
            if not entries:
                parts.append(self._chart_placeholder(x, y, w, h))
            else:
                self._draw_rose(parts, x, y, w, h, bool(title), entries, colors)
        elif chart_type in ("line", "scatter"):
            xs, ys, point_labels, x_is_value = self._xy_series(series)
            if not ys:
                parts.append(self._chart_placeholder(x, y, w, h))
            else:
                self._draw_line(parts, plot_x, plot_y, plot_w, plot_h, xs, ys,
                                point_labels, colors, units,
                                scatter=(chart_type == "scatter"), x_is_value=x_is_value)
        else:
            # bar / hbar 共用 [{label, value}] 序列；未知 chart_type 一律按
            # bar（前向兼容，与既有渲染一致）。
            labels, values = self._series_entries(series)
            if not values:
                parts.append(self._chart_placeholder(x, y, w, h))
            elif chart_type == "hbar":
                self._draw_hbar(parts, plot_x, plot_y, plot_w, plot_h, labels, values, colors)
            else:
                self._draw_bar(parts, plot_x, plot_y, plot_w, plot_h, labels, values,
                               colors, units)
        parts.append("</g>")
        return "\n".join(parts)

    @staticmethod
    def _chart_placeholder(x: float, y: float, w: float, h: float) -> str:
        return (
            f'<text x="{x + w / 2:.2f}" y="{y + h / 2:.2f}" font-family="SimSun, Arial"'
            f' font-size="3.0" fill="#888888" text-anchor="middle">统计图（无数据）</text>'
        )

    @staticmethod
    def _draw_axes(parts: list[str], px: float, py: float, pw: float, ph: float) -> None:
        parts.append(
            f'<line x1="{px:.2f}" y1="{py:.2f}" x2="{px:.2f}" y2="{py + ph:.2f}"'
            f' stroke="#444444" stroke-width="0.2"/>'
        )
        parts.append(
            f'<line x1="{px:.2f}" y1="{py + ph:.2f}" x2="{px + pw:.2f}" y2="{py + ph:.2f}"'
            f' stroke="#444444" stroke-width="0.2"/>'
        )

    def _draw_bar(
        self,
        parts: list[str],
        px: float, py: float, pw: float, ph: float,
        labels: list[str], values: list[float],
        colors: list[str], units: str,
    ) -> None:
        vmax = max(abs(v) for v in values) or 1.0
        bar_w = pw / max(1, len(values)) * 0.7
        gap = pw / max(1, len(values))
        for i, value in enumerate(values):
            bar_h = ph * abs(value) / vmax
            bx = px + i * gap + (gap - bar_w) / 2
            by = py + ph - bar_h
            parts.append(
                f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bar_w:.2f}"'
                f' height="{max(0.2, bar_h):.2f}" fill="{colors[i % len(colors)]}"'
                f' stroke="#333333" stroke-width="0.15"/>'
            )
            if labels and labels[i]:
                parts.append(
                    f'<text x="{bx + bar_w / 2:.2f}" y="{py + ph + 3.0:.2f}"'
                    f' font-family="Arial" font-size="2.2" fill="#333333"'
                    f' text-anchor="middle">{html.escape(labels[i])}</text>'
                )
        parts.append(
            f'<text x="{px + pw:.2f}" y="{py - 0.6:.2f}"'
            f' font-family="Arial" font-size="2.2" fill="#555555"'
            f' text-anchor="end">{vmax:g}{html.escape(units)}</text>'
        )

    def _draw_hbar(
        self,
        parts: list[str],
        px: float, py: float, pw: float, ph: float,
        labels: list[str], values: list[float],
        colors: list[str],
    ) -> None:
        vmax = max(abs(v) for v in values) or 1.0
        bar_h = ph / max(1, len(values)) * 0.65
        gap = ph / max(1, len(values))
        for i, value in enumerate(values):
            bar_w = pw * abs(value) / vmax * 0.8
            by = py + i * gap + (gap - bar_h) / 2
            parts.append(
                f'<rect x="{px:.2f}" y="{by:.2f}" width="{max(0.2, bar_w):.2f}"'
                f' height="{bar_h:.2f}" fill="{colors[i % len(colors)]}"'
                f' stroke="#333333" stroke-width="0.15"/>'
            )
            if labels and labels[i]:
                parts.append(
                    f'<text x="{px - 0.8:.2f}" y="{by + bar_h / 2 + 0.8:.2f}"'
                    f' font-family="Arial" font-size="2.2" fill="#333333"'
                    f' text-anchor="end">{html.escape(labels[i])}</text>'
                )

    def _draw_line(
        self,
        parts: list[str],
        px: float, py: float, pw: float, ph: float,
        xs: list[float], ys: list[float],
        labels: list[str],
        colors: list[str], units: str,
        *,
        scatter: bool,
        x_is_value: bool,
    ) -> None:
        """折线/散点：x_is_value 时 x 轴按数值缩放（两端标注范围），
        否则分类等距（标签逐点标注）——形态由 _xy_series 判定。"""
        vmax = max(abs(v) for v in ys) or 1.0
        self._draw_axes(parts, px, py, pw, ph)
        if x_is_value:
            xmin, xmax = min(xs), max(xs)
            span = xmax - xmin

            def mx_of(i: int) -> float:
                if span <= 0.0:
                    return px + pw / 2.0
                return px + (xs[i] - xmin) / span * pw
        else:
            step = pw / max(1, len(ys))

            def mx_of(i: int) -> float:
                return px + i * step + step / 2.0

        pts: list[tuple[float, float]] = [
            (mx_of(i), py + ph - abs(v) / vmax * ph)
            for i, v in enumerate(ys)
        ]
        if scatter:
            for (mx, my) in pts:
                parts.append(
                    f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="0.9"'
                    f' fill="{colors[0]}" stroke="#333333" stroke-width="0.1"/>'
                )
        else:
            polyline = " ".join(f"{mx:.2f},{my:.2f}" for mx, my in pts)
            parts.append(
                f'<polyline points="{polyline}" fill="none"'
                f' stroke="{colors[0]}" stroke-width="0.5"/>'
            )
            for (mx, my) in pts:
                parts.append(
                    f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="0.55"'
                    f' fill="{colors[0]}"/>'
                )
        for i, (mx, _my) in enumerate(pts):
            if labels and labels[i]:
                parts.append(
                    f'<text x="{mx:.2f}" y="{py + ph + 3.0:.2f}" font-family="Arial"'
                    f' font-size="2.2" fill="#333333"'
                    f' text-anchor="middle">{html.escape(labels[i])}</text>'
                )
        parts.append(
            f'<text x="{px + pw:.2f}" y="{py - 0.6:.2f}" font-family="Arial"'
            f' font-size="2.2" fill="#555555" text-anchor="end">'
            f'{vmax:g}{html.escape(units)}</text>'
        )
        if x_is_value:
            # 数值 x 轴的两端范围标注（分类式则逐点标签已覆盖）。
            parts.append(
                f'<text x="{px:.2f}" y="{py + ph + 3.0:.2f}" font-family="Arial"'
                f' font-size="2.0" fill="#555555" text-anchor="start">{xmin:g}</text>'
            )
            parts.append(
                f'<text x="{px + pw:.2f}" y="{py + ph + 3.0:.2f}" font-family="Arial"'
                f' font-size="2.0" fill="#555555" text-anchor="end">{xmax:g}</text>'
            )

    def _draw_pie(
        self,
        parts: list[str],
        x: float, y: float, w: float, h: float,
        has_title: bool,
        labels: list[str], values: list[float],
        colors: list[str],
        *,
        hole_ratio: float = 0.0,
    ) -> None:
        """饼图（hole_ratio=0）/ 环形图（donut，hole>0）。调用方保证
        values 全部 > 0。百分比/外标签最后绘制，确保叠在内孔之上。"""
        top_pad = 8.0 if has_title else 3.0
        cx = x + w / 2
        cy = y + top_pad + (h - top_pad) / 2
        r = max(3.0, min(w, h - top_pad) / 2 - 2.0)
        total = sum(values)
        angle = 0.0
        texts: list[str] = []
        for i, value in enumerate(values):
            span = 360.0 * value / total
            a0, a1 = angle, angle + span
            color = colors[i % len(colors)]
            if len(values) == 1 or span >= 359.99:
                # 单一整圆：arc path 会退化，直接画圆。
                parts.append(
                    f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}"'
                    f' fill="{color}" stroke="#333333" stroke-width="0.15"/>'
                )
            else:
                x0, y0 = self._polar(cx, cy, r, a0)
                x1, y1 = self._polar(cx, cy, r, a1)
                large = 1 if (a1 - a0) > 180.0 else 0
                parts.append(
                    f'<path d="M {cx:.2f} {cy:.2f} L {x0:.2f} {y0:.2f}'
                    f' A {r:.2f} {r:.2f} 0 {large} 1 {x1:.2f} {y1:.2f} Z"'
                    f' fill="{color}" stroke="#ffffff" stroke-width="0.2"/>'
                )
            pct = span / 360.0 * 100.0
            mid = (a0 + a1) / 2.0
            lx, ly = self._polar(cx, cy, r * 0.62, mid)
            texts.append(
                f'<text x="{lx:.2f}" y="{ly + 0.8:.2f}" font-family="Arial"'
                f' font-size="2.2" fill="#111111" text-anchor="middle">{pct:.0f}%</text>'
            )
            if labels and labels[i]:
                tx, ty = self._polar(cx, cy, r + 2.6, mid)
                anchor = "start" if tx > cx else ("end" if tx < cx else "middle")
                texts.append(
                    f'<text x="{tx:.2f}" y="{ty + 0.8:.2f}" font-family="SimSun, Arial"'
                    f' font-size="2.2" fill="#333333" text-anchor="{anchor}">'
                    f"{html.escape(labels[i])}</text>"
                )
            angle = a1
        if hole_ratio > 0.01:
            # 环形内孔：白芯覆盖扇心（无阴影、无渐变，保持克制配色）。
            hole_r = r * hole_ratio
            parts.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{hole_r:.2f}"'
                f' fill="#ffffff" stroke="#333333" stroke-width="0.15"/>'
            )
        parts.extend(texts)

    def _draw_rose(
        self,
        parts: list[str],
        x: float, y: float, w: float, h: float,
        has_title: bool,
        entries: list,
        colors: list[str],
    ) -> None:
        top_pad = 8.0 if has_title else 3.0
        cx = x + w / 2
        cy = y + top_pad + (h - top_pad) / 2
        r_max = max(3.0, min(w, h - top_pad) / 2 - 5.0)
        values: list[float] = []
        for entry in entries:
            try:
                raw_value = abs(float(entry.get("value", 0.0) or 0.0))
            except (TypeError, ValueError):
                raw_value = 0.0
            values.append(self._finite_or(raw_value, 0.0))
        vmax = max(values) or 1.0
        # 极坐标网格：外圈 + 半径半圈 + 十字线。
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_max:.2f}" fill="none"'
            f' stroke="#999999" stroke-width="0.12"/>'
        )
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_max / 2:.2f}" fill="none"'
            f' stroke="#bbbbbb" stroke-width="0.1"/>'
        )
        parts.append(
            f'<line x1="{cx - r_max:.2f}" y1="{cy:.2f}" x2="{cx + r_max:.2f}"'
            f' y2="{cy:.2f}" stroke="#bbbbbb" stroke-width="0.1"/>'
        )
        parts.append(
            f'<line x1="{cx:.2f}" y1="{cy - r_max:.2f}" x2="{cx:.2f}"'
            f' y2="{cy + r_max:.2f}" stroke="#bbbbbb" stroke-width="0.1"/>'
        )
        default_span = 360.0 / max(1, len(entries))
        for i, entry in enumerate(entries):
            try:
                center_angle = float(entry.get("angle_deg", i * default_span) or 0.0)
            except (TypeError, ValueError):
                center_angle = i * default_span
            center_angle = self._finite_or(center_angle, i * default_span)
            try:
                span = float(entry.get("angle_span") or default_span)
            except (TypeError, ValueError):
                span = default_span
            span = self._finite_or(span, default_span)
            span = min(max(span, 0.0), 360.0)
            r_i = r_max * values[i] / vmax
            if r_i <= 0.01:
                continue
            a0, a1 = center_angle - span / 2.0, center_angle + span / 2.0
            x0, y0 = self._polar(cx, cy, r_i, a0)
            x1, y1 = self._polar(cx, cy, r_i, a1)
            large = 1 if (a1 - a0) > 180.0 else 0
            parts.append(
                f'<path d="M {cx:.2f} {cy:.2f} L {x0:.2f} {y0:.2f}'
                f' A {r_i:.2f} {r_i:.2f} 0 {large} 1 {x1:.2f} {y1:.2f} Z"'
                f' fill="{colors[i % len(colors)]}" fill-opacity="0.85"'
                f' stroke="#333333" stroke-width="0.12"/>'
            )
            label = str(entry.get("label") or "")
            if label:
                tx, ty = self._polar(cx, cy, r_max + 2.4, center_angle)
                parts.append(
                    f'<text x="{tx:.2f}" y="{ty + 0.8:.2f}" font-family="SimSun, Arial"'
                    f' font-size="2.2" fill="#333333" text-anchor="middle">'
                    f"{html.escape(label)}</text>"
                )

    def _draw_histogram(
        self,
        parts: list[str],
        px: float, py: float, pw: float, ph: float,
        values: list[float],
        bins: int,
    ) -> None:
        vmin, vmax = min(values), max(values)
        if vmax <= vmin:
            vmin, vmax = vmin - 0.5, vmax + 0.5
        width = (vmax - vmin) / bins
        counts = [0] * bins
        for value in values:
            idx = int((value - vmin) / width)
            counts[min(bins - 1, max(0, idx))] += 1
        max_count = max(counts) or 1
        self._draw_axes(parts, px, py, pw, ph)
        bar_w = pw / bins * 0.88
        for i, count in enumerate(counts):
            bx = px + i * (pw / bins) + (pw / bins - bar_w) / 2
            bar_h = ph * count / max_count
            parts.append(
                f'<rect x="{bx:.2f}" y="{py + ph - bar_h:.2f}" width="{bar_w:.2f}"'
                f' height="{max(0.15, bar_h):.2f}" fill="#4c78a8"'
                f' stroke="#2b5a86" stroke-width="0.12"/>'
            )
            if bins <= 12 and count > 0:
                parts.append(
                    f'<text x="{bx + bar_w / 2:.2f}" y="{py + ph - bar_h - 0.5:.2f}"'
                    f' font-family="Arial" font-size="1.9" fill="#333333"'
                    f' text-anchor="middle">{count}</text>'
                )
        # 计数轴最大标签 + 数值范围标签。
        parts.append(
            f'<text x="{px + pw:.2f}" y="{py - 0.6:.2f}" font-family="Arial"'
            f' font-size="2.2" fill="#555555" text-anchor="end">{max_count}</text>'
        )
        parts.append(
            f'<text x="{px:.2f}" y="{py + ph + 3.0:.2f}" font-family="Arial"'
            f' font-size="2.0" fill="#555555" text-anchor="start">{vmin:g}</text>'
        )
        parts.append(
            f'<text x="{px + pw:.2f}" y="{py + ph + 3.0:.2f}" font-family="Arial"'
            f' font-size="2.0" fill="#555555" text-anchor="end">{vmax:g}</text>'
        )

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
            ramp_name = str(elem.properties.get("color_ramp") or "")
            if ramp_name:
                # 未给显式停靠点时按色带名解析（模板悬空键 lithofacies-v1/
                # paleogeographic-v1 经 composer 别名表落到实际色带，而非
                # get_color_ramp 的 viridis 缺省）。
                ramp = resolve_palette(ramp_name)
                stops = [(float(s.position), str(s.color)) for s in ramp.stops]
            else:
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
        # 标题可配置（FACIES_LEGEND 默认「沉积相图例」），普通图例保持「图 例」。
        legend_title = str(elem.properties.get("title") or "图 例")
        svg_lines = [
            f'<g id="{elem.id}">',
            f'<rect x="{x}" y="{y}" width="{w}" height="{req_h}" fill="#ffffff" stroke="#666666" stroke-width="0.2" fill-opacity="0.95"/>',
            f'<text x="{x + 4}" y="{y + 5.5}" font-family="SimSun, Arial, sans-serif" font-size="4" font-weight="bold" fill="#000000">{html.escape(legend_title)}</text>',
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
