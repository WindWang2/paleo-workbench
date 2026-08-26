"""Mapping Engine 2.0: Unified Renderer Registry and Layer Renderers.

Decouples styling and layer rendering from monolithic backends and composer loops.
Both QPainter (Screen/Canvas/PDF) and SVG (Vector Composer/Export) paths share
the exact same symbol and style interpretation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import html
import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from paleo_workbench.mapping.color_ramps import ColorRamp, get_color_ramp
from paleo_workbench.mapping.layers import (
    AnnotationMapLayer,
    ContourMapLayer,
    GridMapLayer,
    MapLayer,
    PolygonMapLayer,
    RasterMapLayer,
    VectorMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.mapping.map_styles import (
    LinePattern,
    MarkerSymbol,
    TextStyle,
    VectorStyle,
    default_style_for,
)


@dataclass(frozen=True, slots=True)
class LegendItem:
    """A single legend entry produced by a LayerRenderer."""
    label: str
    color: str
    symbol_type: str = "polygon"  # polygon | line | point | gradient
    stroke_color: str = "#333333"
    stroke_width: float = 0.5
    marker_symbol: str = "circle"
    gradient_stops: tuple[tuple[float, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Viewport context for coordinate transformations during rendering."""
    extent: tuple[float, float, float, float]
    width: float
    height: float
    dpi: float = 96.0
    x_offset: float = 0.0
    y_offset: float = 0.0

    @property
    def scale_x(self) -> float:
        xmin, _, xmax, _ = self.extent
        dx = xmax - xmin
        return self.width / dx if dx > 0 else 1.0

    @property
    def scale_y(self) -> float:
        _, ymin, _, ymax = self.extent
        dy = ymax - ymin
        return self.height / dy if dy > 0 else 1.0

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        """Transform world coordinates (x, y) to screen pixels."""
        xmin, ymin, _, ymax = self.extent
        sx = self.x_offset + (x - xmin) * self.scale_x
        # Map Y is inverted in standard top-left screen space
        sy = self.y_offset + (ymax - y) * self.scale_y
        return sx, sy


class LayerRenderer(ABC):
    """Protocol / ABC for all layer renderers."""

    renderer_type: str = "generic"

    @abstractmethod
    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        """Return legend items for cartographic legend generation."""
        return []

    @abstractmethod
    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        """Render layer directly into SVG group string."""
        return ""


class SingleSymbolRenderer(LayerRenderer):
    """Renders vector features using a single unified style."""

    renderer_type: str = "single"

    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        style = VectorStyle.from_dict(layer.style)
        return [
            LegendItem(
                label=layer.name,
                color=style.fill if style.fill != "transparent" else style.stroke,
                symbol_type="polygon" if style.fill != "transparent" else "line",
                stroke_color=style.stroke,
                stroke_width=style.stroke_width,
                marker_symbol=style.marker.value,
            )
        ]

    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        if not layer.visible or layer.opacity <= 0.0:
            return ""
        style = VectorStyle.from_dict(layer.style)
        features = getattr(layer, "features", ())
        if not features:
            return ""

        parts = [f'<g id="layer_{layer.id}" opacity="{layer.opacity:.2f}">']
        for feat in features:
            geom = feat.get("geometry") if isinstance(feat, Mapping) else None
            if not geom:
                continue
            gtype = geom.get("type", "")
            coords = geom.get("coordinates", [])
            props = feat.get("properties") or {}

            if gtype == "Polygon" and coords:
                ring = coords[0]
                pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2]
                if pts:
                    parts.append(
                        f'<polygon points="{" ".join(pts)}" fill="{style.fill}" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"/>'
                    )
            elif gtype == "MultiPolygon" and coords:
                for poly in coords:
                    if poly:
                        ring = poly[0]
                        pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2]
                        if pts:
                            parts.append(
                                f'<polygon points="{" ".join(pts)}" fill="{style.fill}" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"/>'
                            )
            elif gtype == "LineString" and coords:
                pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in coords if len(p) >= 2]
                if pts:
                    dash_attr = ""
                    if style.line_pattern is LinePattern.FAULT or style.line_pattern is LinePattern.DASH:
                        dash_attr = ' stroke-dasharray="6,2"'
                    elif style.line_pattern is LinePattern.DOT:
                        dash_attr = ' stroke-dasharray="2,2"'
                    parts.append(
                        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"{dash_attr}/>'
                    )
            elif gtype == "Point" and coords and len(coords) >= 2:
                sx, sy = ctx.world_to_screen(float(coords[0]), float(coords[1]))
                r = max(1.0, style.marker_size / 2.0)
                if style.marker is MarkerSymbol.WELL:
                    parts.append(
                        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="none" stroke="{style.stroke}" stroke-width="1"/>'
                        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{max(0.5, r*0.4):.2f}" fill="{style.fill}" stroke="none"/>'
                    )
                elif style.marker is MarkerSymbol.SQUARE:
                    parts.append(
                        f'<rect x="{sx - r:.2f}" y="{sy - r:.2f}" width="{r*2:.2f}" height="{r*2:.2f}" fill="{style.fill}" stroke="{style.stroke}" stroke-width="0.5"/>'
                    )
                else:
                    parts.append(
                        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{style.fill}" stroke="{style.stroke}" stroke-width="0.5"/>'
                    )

                if style.labels and style.labels.visible and style.labels.field:
                    lbl_text = str(props.get(style.labels.field) or props.get("name") or "").strip()
                    if lbl_text:
                        escaped_lbl = html.escape(lbl_text)
                        parts.append(
                            f'<text x="{sx + r + 2:.2f}" y="{sy + 3:.2f}" font-family="{style.labels.font_family or "Arial"}" font-size="{style.labels.size:.1f}" fill="{style.labels.color}">{escaped_lbl}</text>'
                        )

        parts.append("</g>")
        return "\n".join(parts)


class CategorizedRenderer(LayerRenderer):
    """Renders features classified by attribute values."""

    renderer_type: str = "categorized"

    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        style = VectorStyle.from_dict(layer.style)
        items = []
        for val, fill, lbl in style.categories:
            items.append(
                LegendItem(
                    label=str(lbl or val),
                    color=fill,
                    symbol_type="polygon" if getattr(layer, "layer_type", "") in ("polygon", "facies") else "point",
                    stroke_color=style.stroke,
                    stroke_width=style.stroke_width,
                    marker_symbol=style.marker.value,
                )
            )
        return items

    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        if not layer.visible or layer.opacity <= 0.0:
            return ""
        style = VectorStyle.from_dict(layer.style)
        cat_map = {str(val): str(fill) for val, fill, _ in style.categories}
        features = getattr(layer, "features", ())
        if not features:
            return ""

        field_name = style.field or "facies_name"
        parts = [f'<g id="layer_{layer.id}" opacity="{layer.opacity:.2f}">']
        for feat in features:
            geom = feat.get("geometry") if isinstance(feat, Mapping) else None
            if not geom:
                continue
            props = feat.get("properties") or {}
            val_key = str(props.get(field_name) or props.get("facies") or props.get("category") or "")
            fill_color = cat_map.get(val_key, style.fill)

            gtype = geom.get("type", "")
            coords = geom.get("coordinates", [])
            if gtype == "Polygon" and coords:
                ring = coords[0]
                pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2]
                if pts:
                    parts.append(
                        f'<polygon points="{" ".join(pts)}" fill="{fill_color}" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"/>'
                    )
            elif gtype == "MultiPolygon" and coords:
                for poly in coords:
                    if poly:
                        ring = poly[0]
                        pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2]
                        if pts:
                            parts.append(
                                f'<polygon points="{" ".join(pts)}" fill="{fill_color}" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"/>'
                            )
            elif gtype == "LineString" and coords:
                pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in coords if len(p) >= 2]
                if pts:
                    parts.append(
                        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{fill_color}" stroke-width="{style.stroke_width:.2f}"/>'
                    )
            elif gtype == "Point" and coords and len(coords) >= 2:
                sx, sy = ctx.world_to_screen(float(coords[0]), float(coords[1]))
                r = max(1.0, style.marker_size / 2.0)
                parts.append(
                    f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{fill_color}" stroke="{style.stroke}" stroke-width="0.5"/>'
                )

        parts.append("</g>")
        return "\n".join(parts)


class GraduatedRenderer(LayerRenderer):
    """Renders vector features classified by numerical range bins."""

    renderer_type: str = "graduated"

    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        style = VectorStyle.from_dict(layer.style)
        items: list[LegendItem] = []
        ranges = style.ranges
        for entry in ranges:
            lo, hi, fill = entry[0], entry[1], entry[2]
            lbl = entry[3] if len(entry) > 3 and entry[3] else f"{lo:.1f} ~ {hi:.1f}"
            items.append(
                LegendItem(
                    label=lbl,
                    color=fill,
                    symbol_type="polygon" if getattr(layer, "layer_type", "") in ("polygon", "facies") else "point",
                    stroke_color=style.stroke,
                    stroke_width=style.stroke_width,
                    marker_symbol=style.marker.value,
                )
            )
        if not items:
            items.append(
                LegendItem(
                    label=layer.name,
                    color=style.fill,
                    symbol_type="polygon",
                    stroke_color=style.stroke,
                    stroke_width=style.stroke_width,
                )
            )
        return items

    def _match_range(self, val: float, ranges: Sequence[tuple[float, float, str, ...]]) -> tuple[str, str] | None:
        """Find matching range and return (fill_color, label)."""
        for entry in ranges:
            if len(entry) >= 3:
                lo, hi, col = float(entry[0]), float(entry[1]), str(entry[2])
                lbl = str(entry[3]) if len(entry) > 3 else ""
                if lo <= val <= hi:
                    return col, lbl
        return None

    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        if not layer.visible or layer.opacity <= 0.0:
            return ""
        style = VectorStyle.from_dict(layer.style)
        ranges = style.ranges
        field_name = style.field or "value"
        features = getattr(layer, "features", ())
        if not features:
            return ""

        parts = [f'<g id="layer_{layer.id}" opacity="{layer.opacity:.2f}">']
        for feat in features:
            geom = feat.get("geometry") if isinstance(feat, Mapping) else None
            if not geom:
                continue
            props = feat.get("properties") or {}
            raw_val = props.get(field_name) if props.get(field_name) is not None else props.get("value")
            fill_color = style.fill
            if raw_val is not None:
                try:
                    v = float(raw_val)
                    matched = self._match_range(v, ranges)
                    if matched is not None:
                        fill_color = matched[0]
                except (TypeError, ValueError):
                    pass

            gtype = geom.get("type", "")
            coords = geom.get("coordinates", [])

            if gtype == "Polygon" and coords:
                ring = coords[0]
                pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2]
                if pts:
                    parts.append(
                        f'<polygon points="{" ".join(pts)}" fill="{fill_color}" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"/>'
                    )
            elif gtype == "MultiPolygon" and coords:
                for poly in coords:
                    if poly:
                        ring = poly[0]
                        pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in ring if len(p) >= 2]
                        if pts:
                            parts.append(
                                f'<polygon points="{" ".join(pts)}" fill="{fill_color}" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"/>'
                            )
            elif gtype == "LineString" and coords:
                pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in coords if len(p) >= 2]
                if pts:
                    dash_attr = ""
                    if style.line_pattern is LinePattern.FAULT or style.line_pattern is LinePattern.DASH:
                        dash_attr = ' stroke-dasharray="6,2"'
                    elif style.line_pattern is LinePattern.DOT:
                        dash_attr = ' stroke-dasharray="2,2"'
                    parts.append(
                        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{fill_color}" stroke-width="{style.stroke_width:.2f}"{dash_attr}/>'
                    )
            elif gtype == "Point" and coords and len(coords) >= 2:
                sx, sy = ctx.world_to_screen(float(coords[0]), float(coords[1]))
                r = max(1.0, style.marker_size / 2.0)
                if style.marker is MarkerSymbol.WELL:
                    parts.append(
                        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="none" stroke="{style.stroke}" stroke-width="1"/>'
                        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{max(0.5, r*0.4):.2f}" fill="{fill_color}" stroke="none"/>'
                    )
                elif style.marker is MarkerSymbol.SQUARE:
                    parts.append(
                        f'<rect x="{sx - r:.2f}" y="{sy - r:.2f}" width="{r*2:.2f}" height="{r*2:.2f}" fill="{fill_color}" stroke="{style.stroke}" stroke-width="0.5"/>'
                    )
                else:
                    parts.append(
                        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{fill_color}" stroke="{style.stroke}" stroke-width="0.5"/>'
                    )

                if style.labels and style.labels.visible and style.labels.field:
                    lbl_text = str(props.get(style.labels.field) or props.get("name") or "").strip()
                    if lbl_text:
                        escaped_lbl = html.escape(lbl_text)
                        parts.append(
                            f'<text x="{sx + r + 2:.2f}" y="{sy + 3:.2f}" font-family="{style.labels.font_family or "Arial"}" font-size="{style.labels.size:.1f}" fill="{style.labels.color}">{escaped_lbl}</text>'
                        )

        parts.append("</g>")
        return "\n".join(parts)


class GridRenderer(LayerRenderer):
    """Renders 2D continuous scalar grid with a smooth color ramp and colormap legend."""

    renderer_type: str = "grid"

    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        ramp_name = layer.style.get("color_ramp") or getattr(layer, "color_ramp_name", "viridis")
        ramp = get_color_ramp(ramp_name)
        val_range = layer.style.get("value_range") or getattr(layer, "value_range", (0.0, 100.0))
        vmin, vmax = val_range if val_range is not None else (0.0, 100.0)
        unit = layer.style.get("unit") or getattr(layer, "unit", "")

        stops = tuple((s.position, s.color) for s in ramp.stops)
        unit_str = f" ({unit})" if unit else ""
        return [
            LegendItem(
                label=f"{layer.name}{unit_str}: {vmin:.1f} ~ {vmax:.1f}",
                color=ramp.stops[-1].color,
                symbol_type="gradient",
                gradient_stops=stops,
            )
        ]

    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        if not layer.visible or layer.opacity <= 0.0:
            return ""
        grid_z = getattr(layer, "grid_z", None)
        grid_x = getattr(layer, "grid_x", None)
        grid_y = getattr(layer, "grid_y", None)
        if grid_z is None or grid_x is None or grid_y is None:
            return ""

        ramp_name = layer.style.get("color_ramp") or getattr(layer, "color_ramp_name", "viridis")
        ramp = get_color_ramp(ramp_name)
        val_range = layer.style.get("value_range") or getattr(layer, "value_range", None)
        finite = grid_z[np.isfinite(grid_z)]
        if finite.size == 0:
            return ""
        vmin, vmax = val_range if val_range is not None else (float(finite.min()), float(finite.max()))

        h, w = grid_z.shape
        xmin, ymin, xmax, ymax = layer.extent
        sx0, sy1 = ctx.world_to_screen(xmin, ymin)
        sx1, sy0 = ctx.world_to_screen(xmax, ymax)
        box_w = abs(sx1 - sx0)
        box_h = abs(sy1 - sy0)

        # For SVG export, emit base64 PNG
        import base64
        import io
        from PIL import Image

        rgba = getattr(layer, "rasterize_rgba", None)
        if callable(rgba):
            arr = layer.rasterize_rgba()
        else:
            table = np.array(ramp.sample_table(256), dtype=np.uint8)
            norm = np.clip((grid_z - vmin) / max(1e-6, vmax - vmin), 0.0, 1.0)
            norm[~np.isfinite(grid_z)] = 0.0
            idx = (norm * 255.0).astype(np.int32)
            arr = np.zeros((h, w, 4), dtype=np.uint8)
            arr[np.isfinite(grid_z)] = table[idx[np.isfinite(grid_z)]]

        img = Image.fromarray(np.flipud(arr), "RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64_png = base64.b64encode(buf.getvalue()).decode("ascii")

        return (
            f'<g id="layer_{layer.id}" opacity="{layer.opacity:.2f}">\n'
            f'  <image x="{min(sx0, sx1):.2f}" y="{min(sy0, sy1):.2f}" width="{box_w:.2f}" height="{box_h:.2f}" '
            f'xlink:href="data:image/png;base64,{b64_png}" preserveAspectRatio="none"/>\n'
            f'</g>'
        )


class ContourRenderer(LayerRenderer):
    """Renders isoline contour lines with elevation/attribute value annotations."""

    renderer_type: str = "contour"

    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        style = VectorStyle.from_dict(layer.style)
        return [
            LegendItem(
                label=f"{layer.name} (等值线)",
                color=style.stroke,
                symbol_type="line",
                stroke_color=style.stroke,
                stroke_width=style.stroke_width,
            )
        ]

    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        if not layer.visible or layer.opacity <= 0.0:
            return ""
        style = VectorStyle.from_dict(layer.style)
        features = getattr(layer, "features", ())
        if not features:
            return ""

        parts = [f'<g id="layer_{layer.id}" opacity="{layer.opacity:.2f}">']
        for feat in features:
            geom = feat.get("geometry") if isinstance(feat, Mapping) else None
            if not geom:
                continue
            coords = geom.get("coordinates", [])
            props = feat.get("properties") or {}
            level = props.get("level")

            pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in coords if len(p) >= 2]
            if len(pts) >= 2:
                parts.append(
                    f'<polyline points="{" ".join(pts)}" fill="none" stroke="{style.stroke}" stroke-width="{style.stroke_width:.2f}"/>'
                )
                # Label middle point
                if style.labels and style.labels.visible and level is not None:
                    mid_idx = len(coords) // 2
                    mx, my = ctx.world_to_screen(coords[mid_idx][0], coords[mid_idx][1])
                    escaped_level = html.escape(f"{float(level):.1f}")
                    parts.append(
                        f'<text x="{mx:.2f}" y="{my:.2f}" font-family="{style.labels.font_family or "Arial"}" font-size="{style.labels.size:.1f}" fill="{style.labels.color}" text-anchor="middle">{escaped_level}</text>'
                    )

        parts.append("</g>")
        return "\n".join(parts)


class WellSymbolRenderer(LayerRenderer):
    """Renders professional oil & gas well symbols and well name labels."""

    renderer_type: str = "well_symbol"

    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        style = VectorStyle.from_dict(layer.style)
        return [
            LegendItem(
                label=layer.name,
                color=style.fill,
                symbol_type="point",
                stroke_color=style.stroke,
                stroke_width=style.stroke_width,
                marker_symbol=style.marker.value,
            )
        ]

    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        if not layer.visible or layer.opacity <= 0.0:
            return ""
        style = VectorStyle.from_dict(layer.style)
        features = getattr(layer, "features", ())
        if not features:
            return ""

        parts = [f'<g id="layer_{layer.id}" opacity="{layer.opacity:.2f}">']
        for feat in features:
            geom = feat.get("geometry") if isinstance(feat, Mapping) else None
            if not geom:
                continue
            coords = geom.get("coordinates", [])
            props = feat.get("properties") or {}
            if not coords or len(coords) < 2:
                continue
            sx, sy = ctx.world_to_screen(float(coords[0]), float(coords[1]))
            r = max(1.5, style.marker_size / 2.0)

            # Geological well point symbol
            parts.append(
                f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="#ffffff" stroke="{style.stroke}" stroke-width="1"/>'
                f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{max(0.8, r*0.4):.2f}" fill="{style.fill}" stroke="none"/>'
            )

            # Well Name & Value Labels
            well_name = str(props.get("name") or props.get("well") or "").strip()
            val = props.get("value")
            val_str = f" ({val:.2f})" if (val is not None and isinstance(val, (int, float))) else ""
            display_text = f"{well_name}{val_str}"
            if display_text and style.labels and style.labels.visible:
                escaped_text = html.escape(display_text)
                parts.append(
                    f'<text x="{sx + r + 3:.2f}" y="{sy + 3:.2f}" font-family="{style.labels.font_family or "Arial"}" font-size="{style.labels.size:.1f}" fill="{style.labels.color}">{escaped_text}</text>'
                )

        parts.append("</g>")
        return "\n".join(parts)


class AnnotationRenderer(LayerRenderer):
    """Renders cartographic text annotations, labels, and marker callouts."""

    renderer_type: str = "annotation"

    def legend_items(self, layer: MapLayer) -> list[LegendItem]:
        style = VectorStyle.from_dict(layer.style)
        return [
            LegendItem(
                label=layer.name,
                color=style.fill if style.fill != "transparent" else style.stroke,
                symbol_type="point",
                stroke_color=style.stroke,
                stroke_width=style.stroke_width,
            )
        ]

    def render_svg(self, layer: MapLayer, ctx: RenderContext) -> str:
        if not layer.visible or layer.opacity <= 0.0:
            return ""
        style = VectorStyle.from_dict(layer.style)
        features = getattr(layer, "features", ())
        if not features:
            return ""

        parts = [f'<g id="layer_{layer.id}" opacity="{layer.opacity:.2f}">']
        for feat in features:
            geom = feat.get("geometry") if isinstance(feat, Mapping) else None
            if not geom:
                continue
            props = feat.get("properties") or {}
            gtype = geom.get("type", "")
            coords = geom.get("coordinates", [])

            text = str(props.get("text") or props.get("label") or props.get("name") or "").strip()
            font_size = float(props.get("font_size") or props.get("size") or (style.labels.size if style.labels else 10.0))
            color = str(props.get("color") or (style.labels.color if style.labels else style.stroke or "#000000"))
            font_family = str(props.get("font_family") or (style.labels.font_family if style.labels else "Arial, sans-serif"))
            bold = bool(props.get("bold") or (style.labels.bold if style.labels else False))
            font_weight = "bold" if bold else "normal"
            rotation = float(props.get("rotation") or 0.0)

            escaped_text = html.escape(text) if text else ""

            if gtype == "Point" and coords and len(coords) >= 2:
                sx, sy = ctx.world_to_screen(float(coords[0]), float(coords[1]))
                transform_attr = f' transform="rotate({rotation:.1f} {sx:.2f} {sy:.2f})"' if rotation != 0.0 else ""

                if style.marker_size > 0 and style.fill != "transparent" and props.get("show_marker", False):
                    r = max(1.0, style.marker_size / 2.0)
                    parts.append(
                        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{style.fill}" stroke="{style.stroke}" stroke-width="0.5"/>'
                    )

                if escaped_text:
                    parts.append(
                        f'<text x="{sx:.2f}" y="{sy:.2f}" font-family="{font_family}" font-size="{font_size:.1f}" font-weight="{font_weight}" fill="{color}"{transform_attr}>{escaped_text}</text>'
                    )
            elif gtype == "LineString" and coords:
                pts = [f"{ctx.world_to_screen(p[0], p[1])[0]:.2f},{ctx.world_to_screen(p[0], p[1])[1]:.2f}" for p in coords if len(p) >= 2]
                if pts:
                    parts.append(
                        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="{style.stroke_width:.2f}"/>'
                    )
                if escaped_text and len(coords) >= 2:
                    mid_idx = len(coords) // 2
                    mx, my = ctx.world_to_screen(coords[mid_idx][0], coords[mid_idx][1])
                    transform_attr = f' transform="rotate({rotation:.1f} {mx:.2f} {my:.2f})"' if rotation != 0.0 else ""
                    parts.append(
                        f'<text x="{mx:.2f}" y="{my:.2f}" font-family="{font_family}" font-size="{font_size:.1f}" font-weight="{font_weight}" fill="{color}" text-anchor="middle"{transform_attr}>{escaped_text}</text>'
                    )

        parts.append("</g>")
        return "\n".join(parts)


class RendererRegistry:
    """Registry managing layer renderer resolvers and factories."""

    def __init__(self) -> None:
        self._renderers: dict[str, LayerRenderer] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        single = SingleSymbolRenderer()
        cat = CategorizedRenderer()
        grad = GraduatedRenderer()
        annotation = AnnotationRenderer()
        grid = GridRenderer()
        contour = ContourRenderer()
        well = WellSymbolRenderer()

        self._renderers["single"] = single
        self._renderers["categorized"] = cat
        self._renderers["graduated"] = grad
        self._renderers["annotation"] = annotation
        self._renderers["label"] = annotation
        self._renderers["grid"] = grid
        self._renderers["scalar_grid"] = grid
        self._renderers["contour"] = contour
        self._renderers["well"] = well
        self._renderers["well_point"] = well
        self._renderers["polygon"] = single
        self._renderers["facies"] = cat
        self._renderers["vector"] = single

    def register(self, key: str, renderer: LayerRenderer) -> None:
        """Register a renderer instance for a layer type or style keyword."""
        self._renderers[str(key).lower()] = renderer

    def resolve(self, layer: MapLayer) -> LayerRenderer:
        """Resolve the most suitable renderer for a given MapLayer."""
        ltype = str(layer.layer_type).lower()

        # 1. Specialized layer types take precedence
        if ltype in ("grid", "scalar_grid", "contour", "well_point", "well", "annotation"):
            return self._renderers.get(ltype, self._renderers["single"])

        # 2. Check if style specifies an explicit non-single renderer keyword (e.g. categorized, graduated)
        style_renderer = str(layer.style.get("renderer") or "").lower()
        if style_renderer and style_renderer in self._renderers and style_renderer != "single":
            return self._renderers[style_renderer]

        # 3. Check if layer style specifies ranges or categories directly
        if layer.style.get("ranges"):
            return self._renderers["graduated"]

        # 4. Check general layer type (vector, polygon, facies)
        if ltype in self._renderers:
            return self._renderers[ltype]

        # 5. Fallback to single symbol
        return self._renderers["single"]


# Global default registry instance
DEFAULT_RENDERER_REGISTRY = RendererRegistry()
