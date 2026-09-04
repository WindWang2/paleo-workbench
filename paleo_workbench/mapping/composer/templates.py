"""Composition templates: layout + component definitions + bindings.

A template is NOT a bitmap. Each template declares the components it
instantiates (type, geometry, z-order), the style bindings it expects
(colormaps, line styles), and the data bindings its components resolve at
instantiate time (factor colorbars, statistics, metadata fields).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from paleo_workbench.mapping.composer.components import CompositionFactory
from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)


@dataclass(frozen=True)
class ElementDefinition:
    """One component slot inside a template layout."""

    element_type: ElementType
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    z_index: int = 0
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompositionTemplate:
    template_id: str
    category: str
    label: str
    description: str
    paper_size: str = "A4"
    orientation: str = "landscape"
    element_definitions: tuple[ElementDefinition, ...] = ()
    style_bindings: dict[str, Any] = field(default_factory=dict)
    data_bindings: dict[str, str] = field(default_factory=dict)


def _def(
    element_type: ElementType,
    x: float,
    y: float,
    w: float,
    h: float,
    z: int = 0,
    **properties: Any,
) -> ElementDefinition:
    return ElementDefinition(
        element_type=element_type,
        x_mm=x,
        y_mm=y,
        width_mm=w,
        height_mm=h,
        z_index=z,
        properties=dict(properties),
    )


def _base_map_frames(paper_w: float, paper_h: float) -> tuple[float, float, float, float]:
    margin = min(12.0, paper_w * 0.05)
    top = 24.0
    bottom = 34.0
    return (margin, top, paper_w - 2 * margin - 88.0, paper_h - top - bottom)


def _factor_map_components(
    *, colorbar_title: str, title: str, right_column_x: float, map_box: tuple[float, float, float, float]
) -> tuple[ElementDefinition, ...]:
    mx, my, mw, mh = map_box
    return (
        _def(ElementType.TITLE, mx, 6.0, mw, 12.0, z=40, text=title, font_size=9, align="center"),
        _def(ElementType.MAIN_MAP, mx, my, mw, mh, z=10),
        _def(ElementType.NORTH_ARROW, right_column_x + 62.0, 10.0, 12.0, 16.0, z=30, label="N"),
        _def(
            ElementType.SCALE_BAR,
            mx + 4.0,
            my + mh + 4.0,
            46.0,
            7.0,
            z=30,
            length_km=10,
            units="km",
        ),
        _def(ElementType.LEGEND, right_column_x, my + 44.0, 78.0, 56.0, z=30),
        _def(
            ElementType.COLORBAR,
            right_column_x + 30.0,
            my + 2.0,
            12.0,
            36.0,
            z=30,
            title=colorbar_title,
            min=0.0,
            max=1.0,
            discrete=False,
            data_binding={"key": "factor.colorbar"},
        ),
        _def(
            ElementType.METADATA,
            mx,
            my + mh + 12.0,
            min(160.0, mw),
            14.0,
            z=30,
            fields=(("编制", ""), ("日期", ""), ("比例尺", ""), ("数据来源", "")),
        ),
    )


def _build_templates() -> dict[str, CompositionTemplate]:
    templates: dict[str, CompositionTemplate] = {}

    def register(template: CompositionTemplate) -> None:
        templates[template.template_id] = template

    # Shared A4 landscape geometry.
    map_box = _base_map_frames(297.0, 210.0)
    right_x = map_box[0] + map_box[2] + 6.0

    common_style = {
        "colormap": "viridis",
        "contour.line_color": "#37474f",
        "well_symbol": "circle",
    }

    register(CompositionTemplate(
        template_id="single_factor",
        category="single_factor",
        label="单因素图",
        description="一个地质因素网格 + 色标 + 图例 + 图廓整饰",
        element_definitions=_factor_map_components(
            colorbar_title="因素值", title="单因素分析图", right_column_x=right_x, map_box=map_box
        ),
        style_bindings={**common_style, "renderer": "graduated"},
        data_bindings={"factor.colorbar": "factor grid colormap + range"},
    ))
    register(CompositionTemplate(
        template_id="contour",
        category="contour",
        label="等值线图",
        description="等值线主图 + 计曲线标注 + 井位",
        element_definitions=_factor_map_components(
            colorbar_title="等值线值", title="等值线图", right_column_x=right_x, map_box=map_box
        ),
        style_bindings={**common_style, "renderer": "contour", "contour.label": True},
        data_bindings={"factor.colorbar": "contour level range"},
    ))
    register(CompositionTemplate(
        template_id="heatmap",
        category="heatmap",
        label="热力图",
        description="连续栅格热力显示 + 连续色标",
        element_definitions=_factor_map_components(
            colorbar_title="强度", title="参数热力图", right_column_x=right_x, map_box=map_box
        ),
        style_bindings={**common_style, "renderer": "grid", "grid.interpolation": "bilinear"},
        data_bindings={"factor.colorbar": "grid value range"},
    ))
    register(CompositionTemplate(
        template_id="well_location",
        category="well_location",
        label="井位图",
        description="井位分布 + 井名标注 + 工区边界",
        element_definitions=(
            _def(ElementType.TITLE, map_box[0], 6.0, map_box[2], 12.0, z=40,
                 text="井位图", font_size=9, align="center"),
            _def(ElementType.MAIN_MAP, *map_box[:4], z=10),
            _def(ElementType.NORTH_ARROW, right_x + 62.0, 10.0, 12.0, 16.0, z=30),
            _def(ElementType.SCALE_BAR, map_box[0] + 4.0, map_box[1] + map_box[3] + 4.0,
                 46.0, 7.0, z=30, length_km=5, units="km"),
            _def(ElementType.LEGEND, right_x, map_box[1] + 2.0, 78.0, 46.0, z=30),
            _def(ElementType.INSET_MAP, right_x, map_box[1] + 52.0, 60.0, 44.0, z=30,
                 locator_scale=6.0),
            _def(ElementType.METADATA, map_box[0], map_box[1] + map_box[3] + 12.0,
                 160.0, 14.0, z=30, fields=(("井数", ""), ("工区", ""), ("日期", ""))),
        ),
        style_bindings={**common_style, "well.label": True},
        data_bindings={},
    ))
    register(CompositionTemplate(
        template_id="seismic_interpretation",
        category="seismic_interpretation",
        label="地震解释图",
        description="层位/断层解释成果 + 测线位置 + 层位图例",
        element_definitions=(
            _def(ElementType.TITLE, map_box[0], 6.0, map_box[2], 12.0, z=40,
                 text="地震解释成果图", font_size=9, align="center"),
            _def(ElementType.MAIN_MAP, *map_box[:4], z=10),
            _def(ElementType.NORTH_ARROW, right_x + 62.0, 10.0, 12.0, 16.0, z=30),
            _def(ElementType.SCALE_BAR, map_box[0] + 4.0, map_box[1] + map_box[3] + 4.0,
                 46.0, 7.0, z=30, length_km=10, units="km"),
            _def(ElementType.LEGEND, right_x, map_box[1] + 2.0, 78.0, 60.0, z=30),
            _def(ElementType.STAT_CHART, right_x, map_box[1] + 66.0, 78.0, 48.0, z=30,
                 chart_type="bar", title="层位闭合差 (ms)",
                 data_binding={"key": "interpretation.misfits"}),
            _def(ElementType.FAULT_SYMBOLS, right_x, map_box[1] + 118.0, 78.0, 26.0, z=30,
                 title="断层符号",
                 items=({"label": "正向断层", "pattern": "solid"},
                        {"label": "逆向断层", "pattern": "dash"},
                        {"label": "走滑断层", "pattern": "dashdot"})),
            _def(ElementType.METADATA, map_box[0], map_box[1] + map_box[3] + 12.0,
                 160.0, 14.0, z=30, fields=(("解释层位", ""), ("数据体", ""), ("解释人", ""))),
        ),
        style_bindings={**common_style, "horizon.line_color": "#d84315",
                        "fault.line_color": "#37474f", "fault.dash": "4,2"},
        data_bindings={"interpretation.misfits": "per-horizon misfit series"},
    ))
    register(CompositionTemplate(
        template_id="isopach",
        category="isopach",
        label="地层厚度图",
        description="厚度等值线 + 厚度色填充 + 钻井厚度校核",
        element_definitions=_factor_map_components(
            colorbar_title="厚度 (m)", title="地层厚度图（等厚图）",
            right_column_x=right_x, map_box=map_box,
        ) + (
            _def(ElementType.STAT_CHART, right_x, map_box[1] + 104.0, 78.0, 42.0, z=30,
                 chart_type="bar", title="井点厚度 (m)",
                 data_binding={"key": "factor.well_values"}),
        ),
        style_bindings={**common_style, "renderer": "graduated+contour"},
        data_bindings={
            "factor.colorbar": "thickness range",
            "factor.well_values": "per-well thickness series",
        },
    ))
    register(CompositionTemplate(
        template_id="lithofacies",
        category="lithofacies",
        label="岩相图",
        description="岩相分区 + 离散岩相图例 + 井点岩性",
        element_definitions=(
            _def(ElementType.TITLE, map_box[0], 6.0, map_box[2], 12.0, z=40,
                 text="岩相古地理图", font_size=9, align="center"),
            _def(ElementType.MAIN_MAP, *map_box[:4], z=10),
            _def(ElementType.NORTH_ARROW, right_x + 62.0, 10.0, 12.0, 16.0, z=30),
            _def(ElementType.SCALE_BAR, map_box[0] + 4.0, map_box[1] + map_box[3] + 4.0,
                 46.0, 7.0, z=30, length_km=10, units="km"),
            _def(ElementType.LEGEND, right_x, map_box[1] + 2.0, 78.0, 66.0, z=30),
            _def(ElementType.METADATA, map_box[0], map_box[1] + map_box[3] + 12.0,
                 160.0, 14.0, z=30, fields=(("相模式", ""), ("编图单元", ""), ("日期", ""))),
        ),
        style_bindings={**common_style, "renderer": "categorized",
                        "facies.palette": "lithofacies-v1"},
        data_bindings={},
    ))
    register(CompositionTemplate(
        template_id="paleogeographic",
        category="paleogeographic",
        label="古地理图",
        description="多因素古地理综合成果：岩相单元 + 等厚线 + 物源方向 + 水深",
        element_definitions=(
            _def(ElementType.TITLE, map_box[0], 6.0, map_box[2], 12.0, z=40,
                 text="古地理图", font_size=10, align="center"),
            _def(ElementType.MAIN_MAP, *map_box[:4], z=10),
            _def(ElementType.GRID, *map_box[:4], z=20, spacing_mm=30.0),
            _def(ElementType.NORTH_ARROW, right_x + 62.0, 10.0, 12.0, 16.0, z=30),
            _def(ElementType.SCALE_BAR, map_box[0] + 4.0, map_box[1] + map_box[3] + 4.0,
                 46.0, 7.0, z=30, length_km=25, units="km"),
            _def(ElementType.LEGEND, right_x, map_box[1] + 2.0, 78.0, 72.0, z=30),
            _def(ElementType.COLORBAR, right_x + 30.0, map_box[1] + 78.0, 12.0, 34.0, z=30,
                 title="水深 (m)", min=0.0, max=50.0,
                 stops=((0.0, "#b35806"), (0.5, "#fdbc8b"), (1.0, "#2c7bb6")),
                 data_binding={"key": "paleo.water_depth"}),
            _def(ElementType.ANNOTATION, map_box[0] + 18.0, map_box[1] + 16.0, 42.0, 8.0, z=35,
                 text="物源方向 →", leader=False),
            _def(ElementType.METADATA, map_box[0], map_box[1] + map_box[3] + 12.0,
                 170.0, 14.0, z=30,
                 fields=(("编图单元", ""), ("资料截止", ""), ("审校", ""), ("图件版本", ""))),
        ),
        style_bindings={**common_style, "renderer": "categorized+contour",
                        "paleo.palette": "paleogeographic-v1"},
        data_bindings={"paleo.water_depth": "water-depth factor colormap + range"},
    ))
    register(CompositionTemplate(
        template_id="comprehensive",
        category="comprehensive",
        label="综合地质图",
        description="多图面综合：主图 + 附图 + 统计 + 图例 + 完整元数据",
        element_definitions=(
            _def(ElementType.TITLE, map_box[0], 6.0, map_box[2], 12.0, z=40,
                 text="综合地质图", font_size=10, align="center"),
            _def(ElementType.MAIN_MAP, map_box[0], map_box[1], map_box[2] * 0.62, map_box[3], z=10),
            _def(ElementType.INSET_MAP, map_box[0] + map_box[2] * 0.65, map_box[1],
                 map_box[2] * 0.34, map_box[3] * 0.45, z=10, locator_scale=5.0),
            _def(ElementType.STAT_CHART, map_box[0] + map_box[2] * 0.65,
                 map_box[1] + map_box[3] * 0.5, map_box[2] * 0.34, map_box[3] * 0.46, z=10,
                 chart_type="bar", title="单因素统计",
                 data_binding={"key": "factor.well_values"}),
            _def(ElementType.NORTH_ARROW, right_x + 62.0, 10.0, 12.0, 16.0, z=30),
            _def(ElementType.LEGEND, right_x, map_box[1] + 2.0, 78.0, 84.0, z=30),
            _def(ElementType.DATASOURCE, right_x, map_box[1] + 90.0, 78.0, 26.0, z=30,
                 title="数据来源",
                 text="数据来源：\n井位/测线：\n解释成果："),
            _def(ElementType.TIME_CREDITS, right_x, map_box[1] + 120.0, 78.0, 18.0, z=30,
                 text="制图时间：\n编制：\n审核："),
            _def(ElementType.METADATA, map_box[0], map_box[1] + map_box[3] + 12.0,
                 190.0, 16.0, z=30,
                 fields=(("图名", ""), ("编图单元", ""), ("资料来源", ""), ("编制", ""),
                         ("审核", ""), ("日期", ""), ("比例尺", ""))),
        ),
        style_bindings={**common_style},
        data_bindings={"factor.well_values": "per-well factor series"},
    ))
    return templates


TEMPLATE_LIBRARY: dict[str, CompositionTemplate] = _build_templates()


def instantiate_template(
    template_id: str,
    *,
    title: str | None = None,
    paper_size: str | None = None,
    orientation: str | None = None,
    dpi: float | None = None,
) -> MapCompositionDocument:
    """Materialize a template into a fresh composition document.

    Live data objects are NOT attached here — components carry their
    declarative data bindings, and the host resolves them through
    :func:`paleo_workbench.mapping.composer.components.bind_template` with
    real data (factor grids, statistics, metadata) before rendering.
    """
    template = TEMPLATE_LIBRARY[template_id]
    factory = CompositionFactory()
    doc = factory.create_document(
        title=title or template.label,
        paper_size=paper_size or template.paper_size,
        orientation=orientation or template.orientation,
        dpi=dpi or 300.0,
    )
    doc.metadata["template_id"] = template.template_id
    doc.metadata["template_category"] = template.category
    for definition in sorted(template.element_definitions, key=lambda d: d.z_index):
        element = ComposerElement(
            id=f"el_{uuid.uuid4().hex[:10]}",
            element_type=definition.element_type,
            x_mm=definition.x_mm,
            y_mm=definition.y_mm,
            width_mm=definition.width_mm,
            height_mm=definition.height_mm,
            z_index=definition.z_index,
            properties=dict(definition.properties),
        )
        doc.add_element(element)
    if title:
        title_elem = next(
            (e for e in doc.elements if e.element_type is ElementType.TITLE), None
        )
        if title_elem is not None:
            title_elem.properties["text"] = title
    return doc
