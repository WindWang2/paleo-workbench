"""Standard Geological Factor Map cartographic templates for Map Composer."""

from __future__ import annotations

from typing import Any

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.layers import MapDocument


def create_geological_factor_map_template(
    map_doc: MapDocument,
    title: str | None = None,
    factor_name: str = "",
    unit: str = "",
    paper_size: str = "A4",
    orientation: str = "landscape",
) -> MapCompositionDocument:
    """Build a publication-quality cartographic composition for a single factor map."""
    is_landscape = (orientation.lower() == "landscape")
    width_mm = 297.0 if is_landscape else 210.0
    height_mm = 210.0 if is_landscape else 297.0

    margin_x = 12.0
    margin_y = 10.0
    title_h = 14.0

    # Layout dimensions
    map_w = width_mm - margin_x * 2 - 50.0  # Leave room on the right for legend
    map_h = height_mm - margin_y * 2 - title_h
    map_x = margin_x
    map_y = margin_y + title_h

    legend_x = map_x + map_w + 5.0
    legend_y = map_y
    legend_w = 45.0
    legend_h = min(map_h, 80.0)

    doc_title = title or map_doc.title or f"{factor_name} 平面分布图"

    composition = MapCompositionDocument(
        id=f"comp_{map_doc.id}",
        title=doc_title,
        paper_size=paper_size,
        orientation=orientation,
        width_mm=width_mm,
        height_mm=height_mm,
        dpi=300.0,
    )

    # 1. Title Element
    composition.add_element(
        ComposerElement(
            id="elem_title",
            element_type=ElementType.TITLE,
            x_mm=margin_x,
            y_mm=margin_y,
            width_mm=width_mm - margin_x * 2,
            height_mm=title_h,
            z_index=10,
            properties={"text": doc_title},
        )
    )

    # 2. Main Map Canvas Element (holding the full MapDocument)
    composition.add_element(
        ComposerElement(
            id="elem_main_map",
            element_type=ElementType.MAIN_MAP,
            x_mm=map_x,
            y_mm=map_y,
            width_mm=map_w,
            height_mm=map_h,
            z_index=1,
            properties={
                "map_document": map_doc,
                "extent": map_doc.extent,
            },
        )
    )

    # 3. North Arrow (placed in upper-left corner of the map)
    composition.add_element(
        ComposerElement(
            id="elem_north_arrow",
            element_type=ElementType.NORTH_ARROW,
            x_mm=map_x + 5.0,
            y_mm=map_y + 5.0,
            width_mm=10.0,
            height_mm=14.0,
            z_index=15,
            properties={},
        )
    )

    # 4. Scale Bar (placed in lower-left corner of the map)
    # Estimate reasonable scale length based on extent
    xmin, _, xmax, _ = map_doc.extent
    span = abs(xmax - xmin)
    length_km = max(5, int(span / 4.0)) if span > 10 else 10
    composition.add_element(
        ComposerElement(
            id="elem_scale_bar",
            element_type=ElementType.SCALE_BAR,
            x_mm=map_x + 6.0,
            y_mm=map_y + map_h - 12.0,
            width_mm=30.0,
            height_mm=8.0,
            z_index=15,
            properties={"length_km": length_km},
        )
    )

    # 5. Dynamic Legend Element (extracts items & color bars from map_doc)
    composition.add_element(
        ComposerElement(
            id="elem_legend",
            element_type=ElementType.LEGEND,
            x_mm=legend_x,
            y_mm=legend_y,
            width_mm=legend_w,
            height_mm=legend_h,
            z_index=10,
            properties={},
        )
    )

    return composition
