"""B6 — STAT_CHART 全面进入编图组件体系：图表类型、数据形态、序列化。

覆盖面：
- 全部 8 种 chart_type（bar/hbar/line/scatter/pie/donut/histogram/rose）
  用 fixture 序列渲染出非空 SVG（含类型特有图元断言）；
- line/scatter 三种 series 形态（{x,y} 数组 / [{x,y}] 点对 / 兼容的
  分类式 [{label,value}]）与 histogram 的 {values, bins} 形态；
- 坏数据（空、错类型、NaN/Inf、非数值坐标）不崩溃，渲染诚实空态占位；
- properties 经 to_dict/from_dict round-trip 不丢键不变形；
- properties.colors 覆盖 registry 缺省 6 色序列；
- registry 契约（choices ↔ 渲染器支持集、CHART_SERIES_SCHEMAS 全覆盖）
  与编辑面板的表格→JSON 自动退化。
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.composer.components import CompositionEditSession
from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.registry import (
    CHART_COLOR_SEQUENCE,
    CHART_SERIES_SCHEMAS,
    get_spec,
)
from paleo_workbench.mapping.composer.renderer import composer_renderer
from paleo_workbench.mapping.composer.templates import instantiate_template
from paleo_workbench.ui.pages.composition_panel import (
    CompositionPanel,
    _TABLE_SERIES_CHART_TYPES,
)

# 渲染器支持的全部 chart_type（registry choices 与之一致）。
CHART_TYPES = ("bar", "hbar", "line", "scatter", "pie", "donut", "histogram", "rose")


def _category_series() -> list[dict]:
    return [
        {"label": "井A", "value": 3.0},
        {"label": "井B", "value": 5.0},
        {"label": "井C", "value": 4.0},
    ]


def _share_series() -> list[dict]:
    return [
        {"label": "三角洲", "value": 50.0},
        {"label": "湖泊", "value": 30.0},
        {"label": "冲积扇", "value": 20.0},
    ]


def _rose_series() -> list[dict]:
    return [
        {"label": "北东", "angle_deg": 45.0, "value": 8.0},
        {"label": "南西", "angle_deg": 225.0, "value": 4.0},
    ]


# 各 chart_type 的 fixture 序列（形态即 registry CHART_SERIES_SCHEMAS 声明）。
FIXTURE_SERIES: dict[str, object] = {
    "bar": _category_series(),
    "hbar": _category_series(),
    "line": {"x": [0.0, 1.0, 2.0, 3.0], "y": [1.0, 3.0, 2.0, 5.0]},
    "scatter": [{"x": 1.0, "y": 2.0}, {"x": 2.5, "y": 3.5}, {"x": 4.0, "y": 1.0}],
    "pie": _share_series(),
    "donut": _share_series(),
    "histogram": {"values": [1.0, 1.2, 2.0, 2.4, 3.0, 5.2], "bins": 4},
    "rose": _rose_series(),
}

# 每种类型至少应出现的图元特征（类型特有，非占位即可满足的除外）。
TYPE_MARKERS: dict[str, callable] = {
    "bar": lambda svg: svg.count("<rect") >= 3,          # 背板 + ≥2 条形
    "hbar": lambda svg: svg.count("<rect") >= 3,
    "line": lambda svg: "<polyline" in svg,
    "scatter": lambda svg: svg.count("<circle") >= 3,    # 散点 ≥3
    "pie": lambda svg: svg.count("<path") >= 3 and "50%" in svg,
    "donut": lambda svg: svg.count("<path") >= 3 and 'fill="#ffffff"' in svg,
    "histogram": lambda svg: svg.count("<rect") >= 5,    # 背板 + ≥4 箱柱
    "rose": lambda svg: svg.count('fill-opacity="0.85"') == 2,
}


def _chart_element(properties: dict, width_mm: float = 80.0, height_mm: float = 50.0) -> ComposerElement:
    return ComposerElement(
        id="chart_e",
        element_type=ElementType.STAT_CHART,
        x_mm=10.0,
        y_mm=10.0,
        width_mm=width_mm,
        height_mm=height_mm,
        properties=dict(properties),
    )


def _chart_svg(properties: dict, width_mm: float = 80.0, height_mm: float = 50.0) -> str:
    doc = MapCompositionDocument(id="comp-charts", title="统计图")
    doc.add_element(_chart_element(properties, width_mm, height_mm))
    return composer_renderer.render_to_svg(doc)


# ---------------------------------------------------------------------------
# 每种 chart_type 渲染非空 SVG
# ---------------------------------------------------------------------------


class TestChartTypeRendering:
    @pytest.mark.parametrize("chart_type", CHART_TYPES)
    def test_fixture_series_renders_type_specific_svg(self, chart_type):
        svg = _chart_svg(
            {"chart_type": chart_type, "title": f"{chart_type} 示例", "series": FIXTURE_SERIES[chart_type]},
            width_mm=90.0 if chart_type in ("bar", "hbar", "line", "scatter", "histogram") else 70.0,
        )
        assert f'id="chart_e"' in svg
        assert "统计图（无数据）" not in svg, chart_type
        assert TYPE_MARKERS[chart_type](svg), chart_type
        assert svg.count("font-family") >= 1  # 标题/标签使用既有字体处理

    def test_donut_draws_white_hole_over_wedges(self):
        svg = _chart_svg({
            "chart_type": "donut",
            "series": _share_series(),
            "hole_ratio": 0.55,
        }, width_mm=60.0, height_mm=50.0)
        assert 'fill="#ffffff" stroke="#333333" stroke-width="0.15"' in svg  # 内孔
        assert svg.count("<path") >= 3  # 扇形环
        assert "50%" in svg and "20%" in svg  # 百分比标注叠在内孔之上仍存在

    def test_donut_without_hole_ratio_defaults_055(self):
        svg = _chart_svg({
            "chart_type": "donut",
            "series": _share_series(),
        }, width_mm=60.0, height_mm=50.0)
        # 缺省内孔即白芯覆盖圆（0.55r），无需显式 hole_ratio。
        assert 'fill="#ffffff" stroke="#333333" stroke-width="0.15"' in svg

    def test_donut_hole_zero_collapses_to_pie(self):
        svg = _chart_svg({
            "chart_type": "donut",
            "series": _share_series(),
            "hole_ratio": 0.0,
        }, width_mm=60.0, height_mm=50.0)
        assert '<path' in svg
        # 实心饼没有白芯圆（页面背景 rect 的 fill=#ffffff 不计入 circle）。
        assert '<circle' not in svg

    def test_unknown_chart_type_still_renders_as_bar(self):
        svg = _chart_svg({
            "chart_type": "violin", "series": _category_series(),
        })
        assert "统计图（无数据）" not in svg
        assert 'fill="#4c78a8"' in svg  # 缺省色序首色（bar 语义）

    def test_rendering_is_deterministic(self):
        props = {"chart_type": "rose", "series": _rose_series(), "colors": ["#111111", "#222222"]}
        assert _chart_svg(props) == _chart_svg(props)


# ---------------------------------------------------------------------------
# series 数据形态（line/scatter 三形态、histogram 回退、rose 缺省等分）
# ---------------------------------------------------------------------------


class TestSeriesShapes:
    def test_line_accepts_xy_dict_form(self):
        svg = _chart_svg({
            "chart_type": "line",
            "series": {"x": [10.0, 20.0, 40.0], "y": [2.0, 4.0, 3.0]},
        })
        assert "<polyline" in svg
        # 数值 x 轴两端范围标注。
        assert ">10</text>" in svg and ">40</text>" in svg

    def test_scatter_accepts_xy_pair_list_form(self):
        svg = _chart_svg({
            "chart_type": "scatter",
            "series": [{"x": 0.5, "y": 1.0}, {"x": 1.5, "y": 2.0}],
        })
        assert svg.count("<circle") >= 2
        assert ">0.5</text>" in svg and ">1.5</text>" in svg

    def test_line_keeps_category_label_value_compat(self):
        svg = _chart_svg({
            "chart_type": "line",
            "series": [{"label": "长6", "value": 2.0}, {"label": "长8", "value": 5.0}],
        })
        assert "<polyline" in svg
        assert "长6" in svg and "长8" in svg  # 分类式逐点标签

    def test_line_xy_dict_skips_non_numeric_entries(self):
        svg = _chart_svg({
            "chart_type": "line",
            "series": {"x": [1.0, "坏点", 3.0], "y": [1.0, 2.0, 3.0]},
        })
        assert "<polyline" in svg  # 诚实跳过非数值 x，剩余点仍成线

    def test_histogram_values_bins_on_properties_fallback(self):
        svg = _chart_svg({
            "chart_type": "histogram",
            "values": [1.0, 2.0, 2.5, 3.0],
            "bins": 3,
        })
        assert svg.count("<rect") >= 4  # 背板 + 3 箱柱

    def test_rose_defaults_to_equal_spans_without_angles(self):
        svg = _chart_svg({
            "chart_type": "rose",
            "series": [{"label": "北", "value": 2.0}, {"label": "东", "value": 4.0}],
        }, width_mm=70.0, height_mm=60.0)
        assert svg.count('fill-opacity="0.85"') == 2  # 缺省各占 180°
        assert "北" in svg and "东" in svg


# ---------------------------------------------------------------------------
# 坏数据：不崩溃 + 诚实空态
# ---------------------------------------------------------------------------

BAD_SERIES_PAYLOADS = [
    None,
    "",
    "不是序列",
    42,
    True,
    [],
    (),
    {},
    [1, 2, 3],                       # 非映射项
    [{"label": "只有标签"}],          # 缺 value → 0 值
    [{"value": "nan"}],              # NaN 字符串
    [{"value": "inf"}],
    {"x": "bad", "y": [1.0]},        # xy 数组坏 x
    {"x": [1.0, float("nan")], "y": [1.0, 2.0]},
    {"values": "不是数组"},           # histogram 坏 values
    {"values": [1.0, float("nan")], "bins": "坏箱数"},
    [{"label": "北", "angle_deg": "坏角度", "value": 3.0}],  # rose 坏角度
    [{"label": "北", "angle_deg": 45.0, "value": "inf"}],
]


class TestBadDataHonesty:
    @pytest.mark.parametrize("chart_type", CHART_TYPES)
    @pytest.mark.parametrize("bad_series", BAD_SERIES_PAYLOADS)
    def test_bad_series_never_crashes_and_stays_valid_svg(self, chart_type, bad_series):
        svg = _chart_svg({"chart_type": chart_type, "series": bad_series})
        # 文档结构完整（未中断渲染管线）。
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        assert 'id="chart_e"' in svg

    def test_empty_series_shows_placeholder_for_every_type(self):
        for chart_type in CHART_TYPES:
            svg = _chart_svg({"chart_type": chart_type, "series": []})
            assert "统计图（无数据）" in svg, chart_type

    def test_missing_series_shows_placeholder(self):
        for chart_type in CHART_TYPES:
            svg = _chart_svg({"chart_type": chart_type})
            assert "统计图（无数据）" in svg, chart_type

    def test_all_nonpositive_pie_shows_placeholder(self):
        for chart_type in ("pie", "donut"):
            svg = _chart_svg({
                "chart_type": chart_type,
                "series": [{"label": "a", "value": -1.0}, {"label": "b", "value": 0.0}],
            })
            assert "统计图（无数据）" in svg, chart_type

    def test_pie_skips_nonpositive_but_keeps_positive(self):
        svg = _chart_svg({
            "chart_type": "pie",
            "series": [
                {"label": "正", "value": 3.0},
                {"label": "负", "value": -2.0},
                {"label": "零", "value": 0.0},
            ],
        }, width_mm=60.0, height_mm=50.0)
        # 只剩单个正值 → 退化为整圆（arc path 不适用）。
        assert "<path" not in svg
        assert svg.count("<circle") == 1
        assert "100%" in svg
        assert "负" not in svg and "零" not in svg

    def test_nan_does_not_pollute_svg_geometry(self):
        svg = _chart_svg({
            "chart_type": "histogram",
            "series": {"values": [1.0, float("nan"), float("inf"), 3.0], "bins": 4},
        })
        low = svg.lower()
        assert "nan" not in low
        assert "inf" not in low


# ---------------------------------------------------------------------------
# round-trip：to_dict / from_dict 不丢 properties
# ---------------------------------------------------------------------------

ROUNDTRIP_CASES = {
    "bar": {"chart_type": "bar", "title": "厚度", "units": "m", "series": _category_series()},
    "line_xy": {"chart_type": "line", "series": {"x": [1.0, 2.0], "y": [3.0, 4.0]}, "units": "ms"},
    "scatter_pairs": {"chart_type": "scatter", "series": [{"x": 1.0, "y": 2.0}]},
    "donut": {"chart_type": "donut", "title": "岩相", "hole_ratio": 0.62, "series": _share_series()},
    "histogram": {"chart_type": "histogram", "series": {"values": [1.0, 2.0, 3.0], "bins": 5}},
    "rose": {"chart_type": "rose", "title": "物源", "series": _rose_series()},
    "colors": {"chart_type": "bar", "colors": ["#101010", "#202020"], "series": _category_series()},
}


class TestRoundTrip:
    @pytest.mark.parametrize("case_name", sorted(ROUNDTRIP_CASES))
    def test_properties_survive_document_roundtrip(self, case_name):
        doc = MapCompositionDocument(id="comp-rt", title="往返")
        doc.add_element(_chart_element(ROUNDTRIP_CASES[case_name]))
        payload = doc.to_dict()
        restored = MapCompositionDocument.from_dict(payload)
        chart = restored.get_element("chart_e")
        assert chart.element_type is ElementType.STAT_CHART
        assert chart.properties == doc.elements[0].properties
        # 二次序列化逐字节一致（含嵌套 series 结构）。
        assert restored.to_dict() == payload

    def test_session_roundtrip_keeps_colors_and_hole(self):
        session = CompositionEditSession(MapCompositionDocument(id="s", title="会话"))
        elem = session.add_element(ElementType.STAT_CHART, properties={
            "chart_type": "donut",
            "series": _share_series(),
            "colors": ["#123456", "#654321"],
            "hole_ratio": 0.7,
        })
        payload = session.document.to_dict()
        restored = MapCompositionDocument.from_dict(payload)
        chart = restored.get_element(elem.id)
        assert chart.properties["chart_type"] == "donut"
        assert chart.properties["hole_ratio"] == pytest.approx(0.7)
        assert chart.properties["colors"] == ["#123456", "#654321"]
        assert chart.properties["series"][0] == {"label": "三角洲", "value": 50.0}

    def test_factory_defaults_carry_chart_vocab(self):
        session = CompositionEditSession(MapCompositionDocument(id="s2", title="默认"))
        elem = session.add_element(ElementType.STAT_CHART)
        assert elem.properties["chart_type"] == "bar"
        assert elem.properties["hole_ratio"] == pytest.approx(0.55)
        payload = session.document.to_dict()
        restored = MapCompositionDocument.from_dict(payload)
        assert restored.get_element(elem.id).properties["chart_type"] == "bar"


# ---------------------------------------------------------------------------
# 颜色覆盖 properties.colors
# ---------------------------------------------------------------------------


class TestColorOverride:
    @pytest.mark.parametrize("chart_type", ["bar", "hbar", "pie", "donut", "rose"])
    def test_custom_colors_replace_sequence(self, chart_type):
        series = FIXTURE_SERIES[chart_type]
        svg = _chart_svg({
            "chart_type": chart_type,
            "series": series,
            "colors": ["#111111", "#222222", "#333333"],
        })
        assert 'fill="#111111"' in svg, chart_type
        assert 'fill="#222222"' in svg, chart_type
        for default_color in CHART_COLOR_SEQUENCE:
            assert f'fill="{default_color}"' not in svg, (chart_type, default_color)

    def test_line_scatter_use_first_custom_color(self):
        for chart_type in ("line", "scatter"):
            svg = _chart_svg({
                "chart_type": chart_type,
                "series": FIXTURE_SERIES[chart_type],
                "colors": ["#0f0f0f"],
            })
            assert 'fill="#0f0f0f"' in svg or 'stroke="#0f0f0f"' in svg, chart_type

    def test_blank_colors_entries_are_dropped(self):
        svg = _chart_svg({
            "chart_type": "bar",
            "series": _category_series(),
            "colors": ["", "  ", "#445566"],
        })
        assert 'fill="#445566"' in svg  # 空串被过滤，尾色回退到序列

    def test_default_sequence_used_without_colors(self):
        svg = _chart_svg({"chart_type": "bar", "series": _category_series()})
        assert f'fill="{CHART_COLOR_SEQUENCE[0]}"' in svg


# ---------------------------------------------------------------------------
# registry 契约：choices ↔ 渲染器、CHART_SERIES_SCHEMAS 全覆盖
# ---------------------------------------------------------------------------


class TestRegistryChartContract:
    def test_choices_match_renderer_supported_types(self):
        spec = get_spec(ElementType.STAT_CHART)
        choices_prop = next(p for p in spec.property_schema if p["name"] == "chart_type")
        assert tuple(choices_prop["choices"]) == CHART_TYPES

    def test_series_schema_describes_every_choice(self):
        assert set(CHART_SERIES_SCHEMAS) == set(CHART_TYPES)
        for chart_type, description in CHART_SERIES_SCHEMAS.items():
            assert description.strip(), chart_type

    def test_series_shape_descriptions_name_their_json_form(self):
        # 形态描述写清 JSON 编辑器可直接粘贴的形态。
        assert '"label"' in CHART_SERIES_SCHEMAS["bar"] and '"value"' in CHART_SERIES_SCHEMAS["bar"]
        assert '"x"' in CHART_SERIES_SCHEMAS["line"] and '"y"' in CHART_SERIES_SCHEMAS["scatter"]
        assert '"values"' in CHART_SERIES_SCHEMAS["histogram"] and '"bins"' in CHART_SERIES_SCHEMAS["histogram"]
        assert '"angle_deg"' in CHART_SERIES_SCHEMAS["rose"]
        assert "hole_ratio" in CHART_SERIES_SCHEMAS["donut"]

    def test_hole_ratio_in_schema_and_defaults(self):
        spec = get_spec(ElementType.STAT_CHART)
        names = {p["name"]: p for p in spec.property_schema}
        assert names["hole_ratio"]["type"] == "number"
        assert spec.default_properties["hole_ratio"] == pytest.approx(0.55)

    def test_table_capable_types_subset_of_choices(self):
        assert _TABLE_SERIES_CHART_TYPES <= set(CHART_TYPES)

    def test_shape_helpers_agree_with_degradation_rule(self):
        is_label_value = CompositionPanel._series_is_label_value
        assert is_label_value([]) and is_label_value(())
        assert is_label_value([{"label": "a", "value": 1.0}])
        assert not is_label_value({"values": [1.0], "bins": 2})          # histogram
        assert not is_label_value([{"label": "北", "angle_deg": 0.0, "value": 1.0}])  # rose
        assert not is_label_value([{"x": 1.0, "y": 2.0}])                # xy 点对
        assert not is_label_value("不是列表")


# ---------------------------------------------------------------------------
# 编辑面板：表格 ↔ JSON 自动退化 + 动态形态提示
# ---------------------------------------------------------------------------


@pytest.fixture()
def panel(qtbot) -> CompositionPanel:
    widget = CompositionPanel()
    qtbot.addWidget(widget)
    widget.resize(320, 800)
    return widget


class TestPanelSeriesEditors:
    def test_label_value_series_still_uses_table(self, panel, qtbot):
        from PySide6.QtWidgets import QTableWidget

        chart = panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "bar", "series": [{"label": "W1", "value": 1.0}],
        })
        table = panel._schema_editors["series"].findChild(QTableWidget)
        assert table is not None and table.rowCount() == 1
        table.item(0, 1).setText("7")
        assert chart.properties["series"][0]["value"] == pytest.approx(7.0)

    def test_line_xy_pairs_degrade_to_json_editor(self, panel):
        from PySide6.QtWidgets import QLineEdit

        panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "line", "series": [{"x": 1.0, "y": 2.0}],
        })
        assert isinstance(panel._schema_editors["series"], QLineEdit)

    def test_line_category_form_keeps_table_editor(self, panel):
        from PySide6.QtWidgets import QTableWidget

        panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "line", "series": [{"label": "P1", "value": 2.0}],
        })
        assert panel._schema_editors["series"].findChild(QTableWidget) is not None

    @pytest.mark.parametrize("chart_type", ["histogram", "rose"])
    def test_dict_and_angle_series_use_json_editor(self, panel, chart_type):
        from PySide6.QtWidgets import QLineEdit

        panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": chart_type, "series": FIXTURE_SERIES[chart_type],
        })
        assert isinstance(panel._schema_editors["series"], QLineEdit)

    def test_donut_with_label_value_series_uses_table(self, panel):
        from PySide6.QtWidgets import QTableWidget

        panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "donut", "series": _share_series(),
        })
        assert panel._schema_editors["series"].findChild(QTableWidget) is not None

    def test_series_tooltip_follows_chart_type_description(self, panel):
        chart = panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "histogram", "series": FIXTURE_SERIES["histogram"],
        })
        tooltip = panel._schema_editors["series"].toolTip()
        assert CHART_SERIES_SCHEMAS["histogram"] in tooltip

        combo = panel._schema_editors["chart_type"]
        combo.setCurrentText("rose")
        # 属性即时落盘；编辑器整表重建（正常经队列刷新，这里显式触发以
        # 脱离事件循环保持确定性）。
        assert chart.properties["chart_type"] == "rose"
        panel._refresh_property_editor()
        editor = panel._schema_editors["series"]
        assert CHART_SERIES_SCHEMAS["rose"] in editor.toolTip()

    def test_json_editor_accepts_histogram_shape(self, panel):
        chart = panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "histogram", "series": {"values": [1.0], "bins": 3},
        })
        editor = panel._schema_editors["series"]
        payload = json.dumps({"values": [1.0, 2.5, 3.5], "bins": 4})
        panel._on_schema_json_changed("series", payload)
        assert chart.properties["series"]["values"] == [1.0, 2.5, 3.5]
        assert chart.properties["series"]["bins"] == 4
        assert editor is panel._schema_editors["series"]

    def test_every_chart_type_selectable_and_previewable(self, panel):
        chart = panel._add_element(ElementType.STAT_CHART, properties={"series": FIXTURE_SERIES["bar"]})
        combo = panel._schema_editors["chart_type"]
        for chart_type in CHART_TYPES:
            combo.setCurrentText(chart_type)
            assert chart.properties["chart_type"] == chart_type
        # 最终预览仍可渲染（QSvgRenderer 校验在 _refresh_preview 内完成，
        # 异常会写 "预览渲染失败" 文本）。
        assert panel.preview_label.text() != "预览渲染失败"


# ---------------------------------------------------------------------------
# 模板统计图示例（paleogeographic 玫瑰图）
# ---------------------------------------------------------------------------


class TestTemplateStatChart:
    def test_paleogeographic_carries_rose_example(self):
        doc = instantiate_template("paleogeographic")
        roses = [
            e for e in doc.elements
            if e.element_type is ElementType.STAT_CHART and e.properties.get("chart_type") == "rose"
        ]
        assert len(roses) == 1
        assert roses[0].properties["title"] == "物源方向玫瑰图"
        entries = list(roses[0].properties["series"])
        assert entries and all("angle_deg" in e and "value" in e for e in entries)

    def test_paleogeographic_rose_renders_nonempty(self):
        svg = composer_renderer.render_to_svg(instantiate_template("paleogeographic"))
        assert "物源方向玫瑰图" in svg
        assert svg.count('fill-opacity="0.85"') == 4  # 模板示例 4 个方位扇区
        assert "统计图（无数据）" not in svg

    def test_paleogeographic_template_roundtrips(self):
        doc = instantiate_template("paleogeographic")
        restored = MapCompositionDocument.from_dict(doc.to_dict())
        svg = composer_renderer.render_to_svg(restored)
        assert "物源方向玫瑰图" in svg
        assert svg.count('fill-opacity="0.85"') == 4
