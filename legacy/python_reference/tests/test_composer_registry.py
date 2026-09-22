"""B5+B6 — component registry, locking, new components, stat charts.

The registry is the single source of truth: every ElementType has a spec
with default geometry/properties/schema, factories read from it, unknown
types degrade to the TEXT spec (matching models' forward-compat carrier).
Locking is enforced at the session layer. New geological components
(Neatline/DataSource/Timescale/FaultSymbols/LithologyLegend) render real
SVG, and STAT_CHART covers all seven chart types without matplotlib.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.composer.components import (
    ComposerError,
    CompositionEditSession,
    CompositionFactory,
    DEFAULT_GEOMETRY_MM,
    DEFAULT_PROPERTIES,
)
from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.registry import (
    CATEGORY_BASIC,
    CATEGORY_CHART,
    CATEGORY_GEOLOGICAL,
    CHART_COLOR_SEQUENCE,
    PALETTE_ALIASES,
    all_specs,
    categories,
    get_spec,
    resolve_palette,
)
from paleo_workbench.mapping.composer.renderer import composer_renderer
from paleo_workbench.mapping.composer.templates import (
    TEMPLATE_LIBRARY,
    instantiate_template,
)
from paleo_workbench.mapping.color_ramps import list_color_ramps


@pytest.fixture()
def session() -> CompositionEditSession:
    doc = MapCompositionDocument(id="comp-reg", title="注册表")
    return CompositionEditSession(doc)


def _doc_with(etype: ElementType, properties: dict, **geometry) -> MapCompositionDocument:
    doc = MapCompositionDocument(id="r", title="渲染")
    doc.add_element(ComposerElement(
        id="e", element_type=etype, x_mm=10, y_mm=10,
        width_mm=geometry.get("width_mm", 60), height_mm=geometry.get("height_mm", 30),
        properties=properties,
    ))
    return doc


def _svg(etype: ElementType, properties: dict, **geometry) -> str:
    return composer_renderer.render_to_svg(_doc_with(etype, properties, **geometry))


# ---------------------------------------------------------------------------
# Registry coverage
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_every_element_type_has_a_spec(self):
        for etype in ElementType:
            spec = get_spec(etype)
            assert spec is not None
            assert spec.element_type is etype, etype
            assert spec.label, etype
            assert spec.renderer_key, etype

    def test_all_specs_cover_entire_enum(self):
        assert {spec.element_type for spec in all_specs()} == set(ElementType)

    def test_categories_are_the_declared_vocabulary(self):
        assert set(categories()) == {CATEGORY_BASIC, CATEGORY_GEOLOGICAL, CATEGORY_CHART}
        geological = {s.element_type for s in all_specs() if s.category == CATEGORY_GEOLOGICAL}
        assert geological >= {
            ElementType.TIMESCALE,
            ElementType.FAULT_SYMBOLS,
            ElementType.FACIES_LEGEND,
            ElementType.LITHOLOGY_LEGEND,
            ElementType.STRAT_LABELS,
        }
        chart = {s.element_type for s in all_specs() if s.category == CATEGORY_CHART}
        assert chart == {ElementType.STAT_CHART}

    def test_default_geometry_is_positive_mm(self):
        for spec in all_specs():
            assert len(spec.default_geometry) == 4, spec.element_type
            assert all(v > 0 for v in spec.default_geometry), spec.element_type

    def test_default_properties_exist_for_typed_components(self):
        for spec in all_specs():
            assert isinstance(spec.default_properties, dict)
        # 关键默认值抽查（中文名/数据形状）。
        assert get_spec(ElementType.FACIES_LEGEND).default_properties["title"] == "沉积相图例"
        assert get_spec(ElementType.STAT_CHART).default_properties["chart_type"] == "bar"
        assert get_spec(ElementType.NEATLINE).default_properties["double_line"] is False

    def test_property_schema_entries_are_wellformed(self):
        for spec in all_specs():
            for prop in spec.property_schema:
                assert prop.get("name") and prop.get("label"), (spec.element_type, prop)
                assert prop.get("type") in {"str", "number", "bool", "choices", "text", "list"}, prop
                if prop["type"] == "choices":
                    assert prop.get("choices"), prop

    def test_unknown_type_falls_back_to_text_spec(self):
        # 与 models 的前向兼容降级一致：未知类型 → TEXT spec。
        spec = get_spec("hologram_3d")
        assert spec.element_type is ElementType.TEXT

    def test_registry_is_single_source_for_factory_defaults(self):
        for spec in all_specs():
            assert DEFAULT_GEOMETRY_MM[spec.element_type] == spec.default_geometry
            assert DEFAULT_PROPERTIES[spec.element_type] == spec.default_properties

    def test_factory_creates_registry_defaults(self):
        factory = CompositionFactory()
        elem = factory.create(ElementType.FAULT_SYMBOLS)
        assert elem.properties["title"] == "沉积相图例" or elem.properties["title"] == "断层符号"
        spec = get_spec(elem.element_type)
        assert (elem.width_mm, elem.height_mm) == (
            spec.default_geometry[2], spec.default_geometry[3],
        )

    def test_chart_color_sequence_has_six_colors(self):
        assert len(CHART_COLOR_SEQUENCE) == 6
        assert CHART_COLOR_SEQUENCE[0] == "#4c78a8"  # 既有 bar 首色不变
        assert all(c.startswith("#") for c in CHART_COLOR_SEQUENCE)


# ---------------------------------------------------------------------------
# Palette aliases (悬空调色板修复)
# ---------------------------------------------------------------------------


class TestPaletteAliases:
    def test_alias_keys_resolve_to_real_ramps(self):
        ramp_names = set(list_color_ramps())
        for key, target in PALETTE_ALIASES.items():
            assert target in ramp_names, key
            ramp = resolve_palette(key)
            assert ramp.name == target
            assert ramp.stops, key

    def test_unknown_palette_still_defaults_to_viridis(self):
        assert resolve_palette("no-such-ramp").name == "viridis"

    def test_template_palette_keys_resolve_not_viridis(self):
        # 模板 style_bindings 里的悬空键必须有非 viridis 的解析结果。
        assert resolve_palette("lithofacies-v1").name != "viridis"
        assert resolve_palette("paleogeographic-v1").name == "water_depth"

    def test_colorbar_uses_palette_alias_when_no_stops(self):
        svg = _svg(ElementType.COLORBAR, {
            "title": "岩相", "min": 0.0, "max": 1.0,
            "color_ramp": "lithofacies-v1",
        })
        assert 'stop-color="#00007f"' in svg  # jet 首停靠色
        assert 'stop-color="#7f0000"' in svg  # jet 末停靠色


# ---------------------------------------------------------------------------
# Locking (B5)
# ---------------------------------------------------------------------------


class TestLocking:
    def test_set_locked_command_and_undo(self, session):
        elem = session.add_element(ElementType.TEXT)
        assert elem.locked is False
        session.set_locked(elem.id, True)
        assert elem.locked is True
        session.undo()
        assert elem.locked is False
        session.redo()
        assert elem.locked is True

    def test_locked_element_refuses_mutations(self, session):
        elem = session.add_element(ElementType.LEGEND)
        session.set_locked(elem.id, True)
        revision = session.revision
        for attempt in (
            lambda: session.move_element(elem.id, 5.0, 5.0),
            lambda: session.scale_element(elem.id, 10.0, 10.0),
            lambda: session.configure_element(elem.id, {"title": "x"}),
            lambda: session.remove_element(elem.id),
            lambda: session.duplicate_element(elem.id),
        ):
            with pytest.raises(ComposerError):
                attempt()
        assert session.revision == revision  # 拒绝的命令不产生历史
        assert session.document.get_element(elem.id) is not None

    def test_unlock_restores_mutability(self, session):
        elem = session.add_element(ElementType.TEXT)
        session.set_locked(elem.id, True)
        session.set_locked(elem.id, False)
        session.move_element(elem.id, 42.0, 24.0)
        assert (elem.x_mm, elem.y_mm) == (42.0, 24.0)

    def test_visibility_and_zorder_still_allowed_when_locked(self, session):
        # 锁定保护内容与几何；显示/层级仍可操作。
        elem = session.add_element(ElementType.TEXT)
        session.set_locked(elem.id, True)
        session.set_element_visible(elem.id, False)
        assert elem.visible is False
        session.bring_to_front(elem.id)

    def test_serialization_roundtrip_keeps_locked(self, session):
        elem = session.add_element(ElementType.NEATLINE)
        session.set_locked(elem.id, True)
        payload = session.document.to_dict()
        locked_payload = next(e for e in payload["elements"] if e["id"] == elem.id)
        assert locked_payload["locked"] is True
        restored = MapCompositionDocument.from_dict(payload)
        assert restored.get_element(elem.id).locked is True
        assert restored.to_dict() == payload

    def test_missing_locked_field_defaults_false(self):
        elem = ComposerElement.from_dict({
            "id": "e1", "element_type": "text",
            "x_mm": 0, "y_mm": 0, "width_mm": 10, "height_mm": 5,
        })
        assert elem.locked is False

    def test_renderer_marks_locked_element(self):
        doc = _doc_with(ElementType.TEXT, {"text": "x"})
        doc.elements[0].locked = True
        svg = composer_renderer.render_to_svg(doc)
        assert 'data-locked="true"' in svg


# ---------------------------------------------------------------------------
# New component rendering (B5)
# ---------------------------------------------------------------------------


class TestNewComponentRendering:
    def test_neatline_draws_border_rectangle(self):
        svg = _svg(ElementType.NEATLINE, {
            "line_width_mm": 1.2, "color": "#123456", "double_line": True, "inner_gap_mm": 2.0,
        })
        assert 'stroke="#123456"' in svg
        assert 'stroke-width="1.20"' in svg
        # 双线图廓：外框 + 内框（页面背景 rect 占 1 个）。
        assert svg.count("<rect") == 3
        assert "stroke-dasharray" not in svg  # 非占位框

    def test_neatline_single_line_by_default(self):
        svg = _svg(ElementType.NEATLINE, {})
        assert svg.count("<rect") == 2  # 页面背景 + 单框

    def test_datasource_renders_title_and_multiline_text(self):
        svg = _svg(ElementType.DATASOURCE, {
            "title": "数据来源", "text": "井位数据：探井 12 口\n地震：三维 240 km²", "font_size": 2.8,
        })
        assert "数据来源" in svg
        assert "井位数据：探井 12 口" in svg
        assert "地震：三维 240 km²" in svg
        assert "<line" in svg  # 标题下分隔线

    def test_time_credits_renders_credit_lines(self):
        svg = _svg(ElementType.TIME_CREDITS, {
            "text": "制图时间：2026-09\n编制：测试\n审核：审核人",
        })
        assert "制图时间：2026-09" in svg
        assert "编制：测试" in svg

    def test_timescale_with_stages_renders_segments_and_labels(self):
        svg = _svg(ElementType.TIMESCALE, {
            "stages": [
                {"label": "Es3x", "color": "#c2804a", "start": 0.0, "end": 2.0},
                {"label": "Es3z", "color": "#7ba23f", "start": 2.0, "end": 5.0},
            ],
        })
        assert "Es3x" in svg and "Es3z" in svg
        assert 'fill="#c2804a"' in svg and 'fill="#7ba23f"' in svg
        assert "stroke-dasharray" not in svg  # 有数据 → 不再占位

    def test_timescale_empty_stays_placeholder(self):
        svg = _svg(ElementType.TIMESCALE, {"stages": ()})
        assert "stroke-dasharray" in svg  # 占位框
        assert "Es" not in svg

    def test_fault_symbols_render_line_samples_and_labels(self):
        svg = _svg(ElementType.FAULT_SYMBOLS, {
            "title": "断层符号",
            "items": [
                {"label": "正向断层", "pattern": "solid"},
                {"label": "逆向断层", "pattern": "dash"},
                {"label": "走滑断层", "pattern": "dashdot"},
            ],
        })
        assert "断层符号" in svg
        assert "正向断层" in svg and "逆向断层" in svg and "走滑断层" in svg
        assert svg.count("<line") >= 3  # 每项一条线样式样本
        assert 'stroke-dasharray="2.4,1.2"' in svg  # dash 样本
        assert 'stroke-dasharray="2.8,1.0,0.6,1.0"' in svg  # dashdot 样本

    def test_facies_legend_reuses_legend_renderer_with_own_title(self):
        svg = _svg(ElementType.FACIES_LEGEND, {
            "title": "沉积相图例",
            "items": [{"label": "辫状河三角洲", "color": "#ffe082", "symbol_type": "polygon"}],
        })
        assert "沉积相图例" in svg
        assert "辫状河三角洲" in svg
        assert 'fill="#ffe082"' in svg

    def test_lithology_legend_renders_swatch_texture_labels(self):
        svg = _svg(ElementType.LITHOLOGY_LEGEND, {
            "title": "岩性图例",
            "items": [
                {"label": "砂岩", "color": "#f2d38a", "pattern": "dots"},
                {"label": "泥岩", "color": "#9aa7b5", "pattern": "lines"},
            ],
        })
        assert "岩性图例" in svg
        assert "砂岩" in svg and "泥岩" in svg
        assert 'fill="#f2d38a"' in svg and 'fill="#9aa7b5"' in svg
        assert "<pattern" in svg  # 纹理叠加
        assert svg.count("url(#lith_") == 2

    def test_strat_labels_renders_multiline_text(self):
        svg = _svg(ElementType.STRAT_LABELS, {"text": "沙河街组\n三段", "font_size": 3.2})
        assert "沙河街组" in svg and "三段" in svg


# ---------------------------------------------------------------------------
# STAT_CHART — all seven chart types (B6)
# ---------------------------------------------------------------------------


def _pie_properties() -> dict:
    return {
        "chart_type": "pie",
        "title": "岩相占比",
        "series": [
            {"label": "三角洲", "value": 50.0},
            {"label": "湖泊", "value": 30.0},
            {"label": "冲积扇", "value": 20.0},
        ],
    }


class TestStatChartTypes:
    def test_bar_renders_bars_and_labels(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "bar", "series": [{"label": "W1", "value": 3.0}, {"label": "W2", "value": 5.0}],
        })
        assert "W1" in svg and "W2" in svg
        assert 'fill="#4c78a8"' in svg  # 缺省序列首色与既有 bar 一致
        assert svg.count("<rect") >= 2

    def test_hbar_renders_horizontal_bars(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "hbar", "series": [{"label": "A", "value": 1.0}, {"label": "B", "value": 2.0}],
        }, width_mm=80, height_mm=40)
        assert "A" in svg and "B" in svg
        assert svg.count("<rect") >= 3  # 背板 + 2 条

    def test_line_renders_axes_and_polyline(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "line", "series": [{"label": "P1", "value": 1.0}, {"label": "P2", "value": 3.0}],
        }, width_mm=80, height_mm=40)
        assert "<polyline" in svg
        assert svg.count("<line") >= 2  # 坐标轴
        assert "P1" in svg

    def test_scatter_renders_points_and_axes(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "scatter", "series": [{"label": "P1", "value": 1.0}, {"label": "P2", "value": 3.0}],
        }, width_mm=80, height_mm=40)
        assert svg.count("<circle") >= 2
        assert svg.count("<line") >= 2

    def test_pie_renders_sector_paths_and_percentages(self):
        svg = _svg(ElementType.STAT_CHART, _pie_properties(), width_mm=60, height_mm=50)
        assert svg.count("<path") >= 3  # 三个扇形 path
        assert "50%" in svg and "30%" in svg and "20%" in svg
        assert "三角洲" in svg

    def test_pie_single_full_slice_draws_circle(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "pie", "series": [{"label": "全部", "value": 4.0}],
        }, width_mm=60, height_mm=50)
        assert "100%" in svg
        assert "<circle" in svg  # 整圆退化处理

    def test_histogram_renders_bars_counts_and_range(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "histogram",
            "series": {"values": [1.0, 1.2, 2.0, 2.1, 2.2, 5.0], "bins": 4},
        }, width_mm=80, height_mm=45)
        assert svg.count("<rect") >= 5  # 背板 + ≥4 箱柱
        assert ">3</text>" in svg  # 计数标签（区间 [2,3.5) 含 3 个样本）
        assert ">1</text>" in svg and ">5</text>" in svg  # 数值范围标签

    def test_rose_renders_polar_wedges_and_labels(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "rose", "title": "物源方向玫瑰图",
            "series": [
                {"label": "北东", "angle_deg": 45.0, "value": 8.0},
                {"label": "南西", "angle_deg": 225.0, "value": 4.0},
            ],
        }, width_mm=70, height_mm=60)
        assert svg.count('fill-opacity="0.85"') == 2  # 两个极坐标扇环
        assert svg.count("<path") == 2
        assert "北东" in svg and "南西" in svg
        assert svg.count("<circle") >= 2  # 极坐标网格圈（外圈 + 半径圈）

    def test_custom_colors_override_sequence(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "bar", "colors": ["#111111", "#222222"],
            "series": [{"label": "a", "value": 1.0}, {"label": "b", "value": 2.0}],
        })
        assert 'fill="#111111"' in svg and 'fill="#222222"' in svg
        assert 'fill="#4c78a8"' not in svg

    def test_empty_data_keeps_placeholder_for_every_type(self):
        for chart_type in ("bar", "hbar", "line", "scatter", "pie", "histogram", "rose"):
            svg = _svg(ElementType.STAT_CHART, {"chart_type": chart_type, "series": ()})
            assert "统计图（无数据）" in svg, chart_type

    def test_unknown_chart_type_falls_back_to_bar(self):
        svg = _svg(ElementType.STAT_CHART, {
            "chart_type": "hologram", "series": [{"label": "x", "value": 1.0}],
        })
        assert 'fill="#4c78a8"' in svg  # 按 bar 渲染
        assert "统计图（无数据）" not in svg

    def test_chart_data_roundtrip_with_type_series_and_locked(self, session):
        elem = session.add_element(ElementType.STAT_CHART, properties={
            "chart_type": "rose",
            "title": "玫瑰",
            "series": [{"label": "北", "angle_deg": 0.0, "value": 3.0}],
        })
        session.set_locked(elem.id, True)
        payload = session.document.to_dict()
        restored = MapCompositionDocument.from_dict(payload)
        chart = restored.get_element(elem.id)
        assert chart.properties["chart_type"] == "rose"
        assert chart.properties["series"][0]["angle_deg"] == 0.0
        assert chart.locked is True


# ---------------------------------------------------------------------------
# Template instantiation with new components
# ---------------------------------------------------------------------------


class TestTemplatesWithNewComponents:
    def test_seismic_template_has_fault_symbols(self):
        doc = instantiate_template("seismic_interpretation")
        faults = [e for e in doc.elements if e.element_type is ElementType.FAULT_SYMBOLS]
        assert len(faults) == 1
        items = list(faults[0].properties["items"])
        assert len(items) == 3
        assert any(i["pattern"] == "dashdot" for i in items)

    def test_comprehensive_template_has_datasource_and_time_credits(self):
        doc = instantiate_template("comprehensive")
        types = {e.element_type for e in doc.elements}
        assert ElementType.DATASOURCE in types
        assert ElementType.TIME_CREDITS in types

    def test_every_template_element_type_is_registered(self):
        for template in TEMPLATE_LIBRARY.values():
            for definition in template.element_definitions:
                spec = get_spec(definition.element_type)
                assert spec.element_type is definition.element_type, (
                    template.template_id, definition.element_type,
                )

    def test_new_template_components_render_real_svg(self):
        doc = instantiate_template("comprehensive")
        svg = composer_renderer.render_to_svg(doc)
        assert "数据来源" in svg
        assert "制图时间" in svg
        seismic = instantiate_template("seismic_interpretation")
        seismic_svg = composer_renderer.render_to_svg(seismic)
        assert "断层符号" in seismic_svg
        assert "走滑断层" in seismic_svg

    def test_all_types_render_without_exception(self):
        # 冒烟：全部注册类型的默认属性直接可渲染。
        for spec in all_specs():
            doc = MapCompositionDocument(id="smoke", title="冒烟")
            doc.add_element(ComposerElement(
                id="e", element_type=spec.element_type,
                x_mm=10, y_mm=10, width_mm=60, height_mm=30,
                properties=dict(spec.default_properties),
            ))
            svg = composer_renderer.render_to_svg(doc)
            assert 'id="e"' in svg, spec.element_type
