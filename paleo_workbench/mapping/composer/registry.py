"""Component registry: the single source of truth for composer components.

Every cartographic component declares itself once here — Chinese label,
menu category, default geometry (mm), default properties, a lightweight
property schema (plain dicts, no pydantic), and the renderer branch that
draws it. Factories (:mod:`.components`) and UI editors
(:mod:`paleo_workbench.ui.pages.composition_panel`) both read from this
registry, so adding a component is a registration plus a renderer branch —
never a hand-written form.

Forward compatibility mirrors :mod:`.models`: an unregistered/unknown type
degrades to the TEXT spec instead of raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.mapping.color_ramps import get_color_ramp
from paleo_workbench.mapping.composer.models import ElementType

# 组件分类（添加菜单分组用）。
CATEGORY_BASIC = "basic"
CATEGORY_GEOLOGICAL = "geological"
CATEGORY_CHART = "chart"

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_BASIC: "基础组件",
    CATEGORY_GEOLOGICAL: "地质组件",
    CATEGORY_CHART: "统计图表",
}

# 统计图缺省 6 色序列（properties.colors 可覆盖）。首色保持既有 bar 的
# #4c78a8，老图件渲染结果不变。
CHART_COLOR_SEQUENCE: tuple[str, ...] = (
    "#4c78a8",
    "#f58518",
    "#e45756",
    "#72b7b2",
    "#54a24b",
    "#eeca3b",
)

# 模板悬空调色板键 → 内置色带别名。这些键出现在模板 style_bindings 中
# 但 color_ramps.py 未注册实现，get_color_ramp 会静默回退 viridis；在
# composer 层做别名解析（不改 color_ramps.py）：
#   lithofacies-v1 → jet：岩相分区是离散分类填色，需要高对比、各类间
#     易分辨的多色序列，内置色带中 jet 的全谱离散色最接近岩相图惯例；
#   paleogeographic-v1 → water_depth：古地理图的核心变量是水深，
#     water_depth（滨岸浅黄→浅湖绿→半深湖青→深湖蓝）语义完全一致。
PALETTE_ALIASES: dict[str, str] = {
    "lithofacies-v1": "jet",
    "paleogeographic-v1": "water_depth",
}


def resolve_palette(name: str):
    """Resolve a palette name through the composer alias table.

    Unknown names still fall through to ``get_color_ramp``'s viridis
    default — the alias table only rescues the template-declared keys.
    """
    key = str(name or "").lower()
    return get_color_ramp(PALETTE_ALIASES.get(key, key))


@dataclass
class ComponentSpec:
    """Declarative description of one composer component.

    ``property_schema`` entries are plain dicts: ``name``/``label``/``type``
    plus optional ``choices``/``min``/``max``. Types: str, number, bool,
    choices, text (multiline), list (JSON-edited).
    """

    element_type: ElementType
    label: str
    category: str
    default_geometry: tuple[float, float, float, float]
    default_properties: dict[str, Any] = field(default_factory=dict)
    property_schema: tuple[dict[str, Any], ...] = ()
    renderer_key: str = ""


def _spec(
    element_type: ElementType,
    label: str,
    category: str,
    geometry: tuple[float, float, float, float],
    properties: dict[str, Any],
    schema: tuple[dict[str, Any], ...],
    renderer_key: str,
) -> ComponentSpec:
    return ComponentSpec(
        element_type=element_type,
        label=label,
        category=category,
        default_geometry=geometry,
        default_properties=dict(properties),
        property_schema=schema,
        renderer_key=renderer_key,
    )


def _build_registry() -> dict[ElementType, ComponentSpec]:
    specs: list[ComponentSpec] = [
        _spec(
            ElementType.MAIN_MAP, "主图", CATEGORY_BASIC,
            (15.0, 30.0, 180.0, 140.0),
            {"title": "主图"},
            ({"name": "title", "label": "标题", "type": "str"},),
            "main_map",
        ),
        _spec(
            ElementType.LEGEND, "图例", CATEGORY_BASIC,
            (205.0, 30.0, 80.0, 60.0),
            {},
            ({"name": "title", "label": "标题", "type": "str"},
             {"name": "items", "label": "图例项 (JSON)", "type": "list"}),
            "legend",
        ),
        _spec(
            ElementType.NORTH_ARROW, "指北针", CATEGORY_BASIC,
            (250.0, 15.0, 14.0, 18.0),
            {"label": "N"},
            ({"name": "label", "label": "方位标签", "type": "str"},),
            "north_arrow",
        ),
        _spec(
            ElementType.SCALE_BAR, "比例尺", CATEGORY_BASIC,
            (20.0, 180.0, 50.0, 8.0),
            {"length_km": 10, "units": "km"},
            ({"name": "length_km", "label": "长度 (km)", "type": "number", "min": 0.1},
             {"name": "units", "label": "单位", "type": "str"}),
            "scale_bar",
        ),
        _spec(
            ElementType.GRID, "坐标网格", CATEGORY_BASIC,
            (15.0, 30.0, 180.0, 140.0),
            {"spacing_mm": 20.0, "color": "#9aa4b2", "line_width_mm": 0.2},
            ({"name": "spacing_mm", "label": "间距 (mm)", "type": "number", "min": 2.0, "max": 200.0},
             {"name": "color", "label": "颜色", "type": "str"},
             {"name": "line_width_mm", "label": "线宽 (mm)", "type": "number", "min": 0.05, "max": 5.0}),
            "grid",
        ),
        _spec(
            ElementType.TITLE, "图名", CATEGORY_BASIC,
            (15.0, 8.0, 180.0, 14.0),
            {"text": "图件标题", "font_size": 8, "align": "center"},
            ({"name": "text", "label": "文本", "type": "text"},
             {"name": "font_size", "label": "字号", "type": "number", "min": 2.0, "max": 72.0},
             {"name": "align", "label": "对齐", "type": "choices", "choices": ["left", "center", "right"]}),
            "title",
        ),
        _spec(
            ElementType.ANNOTATION, "注释", CATEGORY_BASIC,
            (60.0, 90.0, 45.0, 8.0),
            {"text": "注释", "leader": True, "font_size": 3.5},
            ({"name": "text", "label": "文本", "type": "text"},
             {"name": "leader", "label": "引线", "type": "bool"},
             {"name": "font_size", "label": "字号", "type": "number", "min": 1.0, "max": 36.0}),
            "annotation",
        ),
        _spec(
            ElementType.TEXT, "文本", CATEGORY_BASIC,
            (30.0, 160.0, 80.0, 8.0),
            {"text": "文本", "font_size": 4, "align": "left", "color": "#000000"},
            ({"name": "text", "label": "文本", "type": "text"},
             {"name": "font_size", "label": "字号", "type": "number", "min": 1.0, "max": 72.0},
             {"name": "align", "label": "对齐", "type": "choices", "choices": ["left", "center", "right"]},
             {"name": "color", "label": "颜色", "type": "str"}),
            "text",
        ),
        _spec(
            ElementType.IMAGE, "图像", CATEGORY_BASIC,
            (200.0, 110.0, 70.0, 50.0),
            {"image_path": None, "image_data_png_b64": None, "fit": "contain"},
            ({"name": "image_path", "label": "图像路径", "type": "str"},
             {"name": "fit", "label": "适配", "type": "choices", "choices": ["contain", "cover", "stretch"]}),
            "image",
        ),
        _spec(
            ElementType.INSET_MAP, "附图", CATEGORY_BASIC,
            (210.0, 140.0, 60.0, 50.0),
            {"locator_scale": 4.0},
            ({"name": "locator_scale", "label": "定位缩放", "type": "number", "min": 0.1, "max": 50.0},
             {"name": "locator_rect", "label": "定位框 (JSON)", "type": "list"}),
            "inset_map",
        ),
        _spec(
            ElementType.METADATA, "责任表", CATEGORY_BASIC,
            (15.0, 188.0, 150.0, 16.0),
            {"fields": (("编制", ""), ("日期", ""), ("比例尺", "")), "font_size": 3.0},
            ({"name": "fields", "label": "字段 (JSON)", "type": "list"},
             {"name": "font_size", "label": "字号", "type": "number", "min": 1.0, "max": 12.0}),
            "metadata",
        ),
        _spec(
            ElementType.COLORBAR, "色标", CATEGORY_BASIC,
            (200.0, 90.0, 12.0, 80.0),
            {
                "title": "数值",
                "min": 0.0,
                "max": 1.0,
                "stops": ((0.0, "#053061"), (0.5, "#f7f7f7"), (1.0, "#67001f")),
                "discrete": False,
                "data_binding": {"key": "factor.colorbar"},
            },
            ({"name": "title", "label": "标题", "type": "str"},
             {"name": "min", "label": "最小值", "type": "number"},
             {"name": "max", "label": "最大值", "type": "number"},
             {"name": "discrete", "label": "离散", "type": "bool"},
             {"name": "stops", "label": "色带停靠点 (JSON)", "type": "list"},
             {"name": "color_ramp", "label": "色带名", "type": "str"}),
            "colorbar",
        ),
        # ---- B5 基础补充组件 ------------------------------------------
        _spec(
            ElementType.NEATLINE, "图廓", CATEGORY_BASIC,
            (12.0, 12.0, 273.0, 186.0),
            {"line_width_mm": 0.8, "color": "#000000", "double_line": False, "inner_gap_mm": 1.5},
            ({"name": "line_width_mm", "label": "线宽 (mm)", "type": "number", "min": 0.1, "max": 5.0},
             {"name": "color", "label": "颜色", "type": "str"},
             {"name": "double_line", "label": "双线图廓", "type": "bool"},
             {"name": "inner_gap_mm", "label": "内线间距 (mm)", "type": "number", "min": 0.5, "max": 10.0}),
            "neatline",
        ),
        _spec(
            ElementType.DATASOURCE, "数据来源", CATEGORY_BASIC,
            (15.0, 170.0, 120.0, 18.0),
            {"title": "数据来源", "text": "数据来源：\n编制方法：", "font_size": 2.8},
            ({"name": "title", "label": "标题", "type": "str"},
             {"name": "text", "label": "说明文本", "type": "text"},
             {"name": "font_size", "label": "字号", "type": "number", "min": 1.0, "max": 12.0}),
            "datasource",
        ),
        _spec(
            ElementType.TIME_CREDITS, "制图责任", CATEGORY_BASIC,
            (230.0, 182.0, 55.0, 16.0),
            {"text": "制图时间：\n编制：\n审核：", "font_size": 2.6},
            ({"name": "text", "label": "责任文本", "type": "text"},
             {"name": "font_size", "label": "字号", "type": "number", "min": 1.0, "max": 12.0}),
            "time_credits",
        ),
        # ---- 地质组件 --------------------------------------------------
        _spec(
            ElementType.TIMESCALE, "年代地层", CATEGORY_GEOLOGICAL,
            (15.0, 175.0, 180.0, 12.0),
            {"stages": ()},
            ({"name": "stages", "label": "阶段子句 (JSON)", "type": "list"},),
            "timescale",
        ),
        _spec(
            ElementType.FAULT_SYMBOLS, "断层符号", CATEGORY_GEOLOGICAL,
            (210.0, 100.0, 75.0, 40.0),
            {
                "title": "断层符号",
                "items": (
                    {"label": "正断层", "pattern": "solid"},
                    {"label": "逆断层", "pattern": "dash"},
                    {"label": "走滑断层", "pattern": "dashdot"},
                ),
            },
            ({"name": "title", "label": "标题", "type": "str"},
             {"name": "items", "label": "符号项 (JSON)", "type": "list"}),
            "fault_symbols",
        ),
        _spec(
            ElementType.FACIES_LEGEND, "沉积相图例", CATEGORY_GEOLOGICAL,
            (210.0, 30.0, 78.0, 66.0),
            # 复用 LEGEND 渲染：items 留空时同样回退主图提取/示例项。
            {"title": "沉积相图例", "items": ()},
            ({"name": "title", "label": "标题", "type": "str"},
             {"name": "items", "label": "相图例项 (JSON)", "type": "list"}),
            "legend",
        ),
        _spec(
            ElementType.LITHOLOGY_LEGEND, "岩性图例", CATEGORY_GEOLOGICAL,
            (210.0, 30.0, 78.0, 66.0),
            {
                "title": "岩性图例",
                "items": (
                    {"label": "砂岩", "color": "#f2d38a", "pattern": "dots"},
                    {"label": "泥岩", "color": "#9aa7b5", "pattern": "lines"},
                    {"label": "灰岩", "color": "#d3dbe0", "pattern": "crosshatch"},
                ),
            },
            ({"name": "title", "label": "标题", "type": "str"},
             {"name": "items", "label": "岩性项 (JSON)", "type": "list"}),
            "lithology_legend",
        ),
        _spec(
            ElementType.STRAT_LABELS, "地层标注", CATEGORY_GEOLOGICAL,
            (60.0, 90.0, 50.0, 20.0),
            {"text": "地层：\n  组\n  段", "font_size": 3.2},
            ({"name": "text", "label": "标注文本", "type": "text"},
             {"name": "font_size", "label": "字号", "type": "number", "min": 1.0, "max": 24.0}),
            "text",
        ),
        # ---- 统计图（B6）----------------------------------------------
        _spec(
            ElementType.STAT_CHART, "统计图", CATEGORY_CHART,
            (210.0, 30.0, 75.0, 55.0),
            {"chart_type": "bar", "title": "统计", "series": ()},
            ({"name": "chart_type", "label": "图表类型", "type": "choices",
              "choices": ["bar", "hbar", "line", "scatter", "pie", "histogram", "rose"]},
             {"name": "title", "label": "标题", "type": "str"},
             {"name": "series", "label": "数据系列", "type": "list"},
             {"name": "units", "label": "单位", "type": "str"},
             {"name": "colors", "label": "色序列 (JSON)", "type": "list"}),
            "stat_chart",
        ),
    ]
    return {spec.element_type: spec for spec in specs}


_REGISTRY: dict[ElementType, ComponentSpec] = _build_registry()


def register_spec(spec: ComponentSpec) -> None:
    """Register or replace a component spec (extension point for plugins)."""
    _REGISTRY[spec.element_type] = spec


def get_spec(element_type: ElementType | str) -> ComponentSpec:
    """Look up a component spec; unknown types degrade to the TEXT spec.

    Mirrors :meth:`ComposerElement.from_dict`'s forward-compat carrier:
    an unknown type is never rejected, it falls back to TEXT semantics.
    """
    if isinstance(element_type, ElementType):
        key = element_type
    else:
        try:
            key = ElementType(str(element_type).strip().lower())
        except ValueError:
            return _REGISTRY[ElementType.TEXT]
    spec = _REGISTRY.get(key)
    if spec is None:
        spec = _REGISTRY[ElementType.TEXT]
    return spec


def all_specs() -> list[ComponentSpec]:
    """Every registered spec (registration order = menu order)."""
    return list(_REGISTRY.values())


def specs_by_category(category: str) -> list[ComponentSpec]:
    return [spec for spec in _REGISTRY.values() if spec.category == category]


def categories() -> list[str]:
    """Distinct categories in registration order."""
    seen: list[str] = []
    for spec in _REGISTRY.values():
        if spec.category not in seen:
            seen.append(spec.category)
    return seen
