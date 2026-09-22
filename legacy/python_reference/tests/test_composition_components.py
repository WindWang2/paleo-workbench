"""P0-D — cartographic composition component system.

Every component honors one contract: creatable, deletable, movable,
scalable, configurable, serializable, copyable, undoable, and templatable.
Templates are layout + component definitions + style/data bindings — never
bitmaps. Rendering stays in scene millimetres and honors the RenderContext
DPI/unit contract.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.composer.components import (
    ComposerError,
    CompositionEditSession,
    CompositionFactory,
    bind_template,
)
from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.templates import (
    TEMPLATE_LIBRARY,
    instantiate_template,
)


@pytest.fixture()
def session() -> CompositionEditSession:
    doc = MapCompositionDocument(id="comp-1", title="测试组图")
    return CompositionEditSession(doc)


class TestComponentContract:
    def test_create_every_component_type(self, session):
        for etype in ElementType:
            elem = session.add_element(etype)
            assert elem.element_type is etype
            assert elem.width_mm > 0 and elem.height_mm > 0

    def test_move_scale_configure_are_undoable(self, session):
        elem = session.add_element(ElementType.TITLE, x_mm=10, y_mm=10)
        session.move_element(elem.id, 40.0, 50.0)
        assert (elem.x_mm, elem.y_mm) == (40.0, 50.0)
        session.scale_element(elem.id, 120.0, 60.0)
        assert (elem.width_mm, elem.height_mm) == (120.0, 60.0)
        session.configure_element(elem.id, {"text": "新标题", "font_size": 10})
        assert elem.properties["text"] == "新标题"
        assert session.can_undo()
        session.undo()
        session.undo()
        session.undo()
        assert (elem.x_mm, elem.y_mm) == (10.0, 10.0)
        assert elem.properties.get("text") != "新标题"
        session.redo()
        session.redo()
        session.redo()
        assert (elem.x_mm, elem.y_mm) == (40.0, 50.0)
        assert elem.properties["text"] == "新标题"

    def test_delete_and_duplicate(self, session):
        original = session.add_element(ElementType.LEGEND, properties={"items": [{"label": "x"}]})
        copy = session.duplicate_element(original.id)
        assert copy.id != original.id
        assert copy.element_type is ElementType.LEGEND
        assert copy.properties == original.properties
        session.remove_element(original.id)
        assert session.document.get_element(original.id) is None
        assert session.document.get_element(copy.id) is not None
        session.undo()
        assert session.document.get_element(original.id) is not None

    def test_z_order_operations(self, session):
        a = session.add_element(ElementType.TITLE)
        b = session.add_element(ElementType.NORTH_ARROW)
        c = session.add_element(ElementType.SCALE_BAR)
        session.bring_to_front(a.id)
        assert session.document.elements[-1] is a
        session.send_to_back(c.id)
        assert session.document.elements[0] is c
        session.raise_element(b.id)
        session.undo()
        assert session.document.elements[-1] is a

    def test_serialization_roundtrip(self, session):
        session.add_element(ElementType.MAIN_MAP)
        session.add_element(ElementType.COLORBAR, properties={
            "title": "砂岩含量 (%)",
            "stops": [(0.0, "#fee0b6"), (1.0, "#b2182b")],
            "min": 0.0, "max": 100.0,
        })
        session.add_element(ElementType.STAT_CHART, properties={
            "chart_type": "bar",
            "title": "井点统计",
            "series": [{"label": "W1", "value": 3.2}, {"label": "W2", "value": 5.1}],
        })
        payload = session.document.to_dict()
        restored = MapCompositionDocument.from_dict(payload)
        assert restored.title == session.document.title
        assert len(restored.elements) == 3
        by_type = {e.element_type for e in restored.elements}
        assert {ElementType.MAIN_MAP, ElementType.COLORBAR, ElementType.STAT_CHART} <= by_type
        colorbar = next(e for e in restored.elements if e.element_type is ElementType.COLORBAR)
        assert colorbar.properties["title"] == "砂岩含量 (%)"
        # roundtrip is deterministic
        assert restored.to_dict() == payload

    def test_unfetched_document_is_forward_compatible(self):
        doc = MapCompositionDocument.from_dict({
            "id": "x", "title": "t", "schema_version": 99,
            "elements": [{"id": "e1", "element_type": "title", "x_mm": 0, "y_mm": 0,
                          "width_mm": 10, "height_mm": 5, "unknown_future_field": True}],
            "future_top_level": {"anything": 1},
        })
        assert doc.elements[0].element_type is ElementType.TITLE
        # unknown fields do not crash re-serialization
        assert doc.to_dict()["schema_version"] == 2

    def test_unknown_future_element_type_survives_roundtrip(self):
        payload = {
            "id": "e9", "element_type": "hologram_3d", "x_mm": 1, "y_mm": 1,
            "width_mm": 10, "height_mm": 5, "properties": {"foo": "bar"},
        }
        elem = ComposerElement.from_dict(payload)
        assert elem.to_dict()["element_type"] == "hologram_3d"


class TestLockContract:
    def test_lock_unlock_is_undoable_command(self, session):
        elem = session.add_element(ElementType.SCALE_BAR)
        session.set_locked(elem.id, True)
        with pytest.raises(ComposerError):
            session.configure_element(elem.id, {"length_km": 99})
        session.undo()  # 撤销锁定后恢复可编辑
        session.configure_element(elem.id, {"length_km": 99})
        assert elem.properties["length_km"] == 99

    def test_locked_roundtrip_through_document(self, session):
        elem = session.add_element(ElementType.STAT_CHART, properties={
            "chart_type": "pie",
            "series": [{"label": "A", "value": 1.0}, {"label": "B", "value": 3.0}],
        })
        session.set_locked(elem.id, True)
        restored = MapCompositionDocument.from_dict(session.document.to_dict())
        chart = restored.get_element(elem.id)
        assert chart.locked is True
        assert chart.properties["chart_type"] == "pie"
        assert chart.properties["series"][1] == {"label": "B", "value": 3.0}

    def test_new_components_are_creatable_and_mutable(self, session):
        # B5 新组件走同一组件契约：创建/配置/撤销。
        elem = session.add_element(ElementType.NEATLINE)
        assert elem.properties["double_line"] is False
        session.configure_element(elem.id, {"double_line": True, "line_width_mm": 1.4})
        assert elem.properties["double_line"] is True
        session.undo()
        assert elem.properties["double_line"] is False
        faults = session.add_element(ElementType.FAULT_SYMBOLS)
        assert len(faults.properties["items"]) == 3


class TestFactoryDefaults:
    def test_factory_mints_unique_ids(self):
        factory = CompositionFactory()
        a = factory.create(ElementType.TITLE)
        b = factory.create(ElementType.TITLE)
        assert a.id != b.id

    def test_paper_sizes(self):
        factory = CompositionFactory()
        doc = factory.create_document(paper_size="A3", orientation="portrait")
        assert doc.width_mm == pytest.approx(297.0)
        assert doc.height_mm == pytest.approx(420.0)


class TestTemplateSystem:
    def test_library_has_nine_categories(self):
        assert len(TEMPLATE_LIBRARY) >= 9
        categories = {t.category for t in TEMPLATE_LIBRARY.values()}
        assert categories >= {
            "single_factor", "contour", "heatmap", "well_location",
            "seismic_interpretation", "isopach", "lithofacies",
            "paleogeographic", "comprehensive",
        }

    def test_template_is_layout_not_bitmap(self):
        for template in TEMPLATE_LIBRARY.values():
            assert template.element_definitions, template.template_id
            assert isinstance(template.style_bindings, dict)
            assert isinstance(template.data_bindings, dict)

    def test_instantiate_builds_document(self):
        doc = instantiate_template(
            "paleogeographic",
            title="沙河街组三期古地理",
        )
        assert isinstance(doc, MapCompositionDocument)
        types = {e.element_type for e in doc.elements}
        assert ElementType.MAIN_MAP in types
        assert ElementType.LEGEND in types

    def test_unknown_template_raises(self):
        with pytest.raises(KeyError):
            instantiate_template("does-not-exist")

    def test_bind_template_resolves_data_binding(self):
        doc = instantiate_template("single_factor", title="厚度")
        colorbar = next(
            e for e in doc.elements if e.element_type is ElementType.COLORBAR
        )
        binding = colorbar.properties.get("data_binding")
        assert binding, "colorbar must carry a declarative data binding"
        bind_template(
            doc,
            binding_context={
                "factor.colorbar": {
                    "title": "地层厚度 (m)",
                    "stops": [(0.0, "#f7f7f7"), (0.5, "#92c5de"), (1.0, "#053061")],
                    "min": 0.0,
                    "max": 250.0,
                }
            },
        )
        assert colorbar.properties["title"] == "地层厚度 (m)"
        assert colorbar.properties["stops"][0] == (0.0, "#f7f7f7")


class TestRendering:
    def _doc_with(self, etype: ElementType, properties: dict) -> MapCompositionDocument:
        doc = MapCompositionDocument(id="r", title="渲染")
        doc.add_element(ComposerElement(
            id="e", element_type=etype, x_mm=10, y_mm=10,
            width_mm=60, height_mm=30, properties=properties,
        ))
        return doc

    def test_every_component_renders_non_placeholder_svg(self):
        from paleo_workbench.mapping.composer.renderer import composer_renderer

        samples = {
            ElementType.TEXT: {"text": "注释文本", "font_size": 4},
            ElementType.IMAGE: {"image_path": None, "image_data_png_b64": None},
            ElementType.INSET_MAP: {"locator_scale": 0.2},
            ElementType.STAT_CHART: {
                "chart_type": "bar",
                "series": [{"label": "A", "value": 2.0}, {"label": "B", "value": 4.0}],
            },
            ElementType.METADATA: {
                "fields": [("编制", "测试"), ("日期", "2026-08-31"), ("比例尺", "1:250000")],
            },
            ElementType.COLORBAR: {
                "title": "GR (API)", "min": 0.0, "max": 150.0,
                "stops": [(0.0, "#053061"), (1.0, "#67001f")],
            },
            ElementType.GRID: {"spacing_mm": 10.0},
            ElementType.ANNOTATION: {"text": "沉积中心", "leader": True},
        }
        for etype, props in samples.items():
            svg = composer_renderer.render_to_svg(self._doc_with(etype, props))
            assert f'id="e"' in svg, etype
            assert "stroke-dasharray" not in svg or etype is ElementType.GRID, (
                f"{etype} still renders the placeholder rect"
            )

    def test_hidden_element_renders_nothing(self):
        from paleo_workbench.mapping.composer.renderer import composer_renderer

        doc = self._doc_with(ElementType.TITLE, {"text": "x"})
        doc.elements[0].visible = False
        svg = composer_renderer.render_to_svg(doc)
        assert 'id="e"' not in svg


class TestExportContract:
    def test_png_pdf_svg_export_physical_size(self, qtbot, tmp_path):
        from paleo_workbench.mapping.composer.export import (
            composition_page_pixels,
            export_composition,
        )
        from paleo_workbench.mapping.composer.templates import instantiate_template

        doc = instantiate_template("single_factor", title="导出测试")
        w_px, h_px = composition_page_pixels(doc, dpi=300.0)
        assert w_px == round(297.0 / 25.4 * 300.0)
        assert h_px == round(210.0 / 25.4 * 300.0)

        png = export_composition(doc, tmp_path / "page.png", dpi=300.0)
        svg = export_composition(doc, tmp_path / "page.svg")
        pdf = export_composition(doc, tmp_path / "page.pdf", dpi=300.0)
        assert png.stat().st_size > 0 and svg.stat().st_size > 0 and pdf.stat().st_size > 0

        # DPI metadata must land in the PNG so printed size matches.
        from PySide6.QtGui import QImage

        image = QImage(str(png))
        assert image.dotsPerMeterX() == round(300.0 / 0.0254)

        # The SVG page carries the physical millimetre size.
        head = svg.read_text(encoding="utf-8")[:400]
        assert 'width="297.0mm"' in head and 'height="210.0mm"' in head

        # PNG pixel dimensions match the requested DPI fold.
        loaded = QImage(str(png))
        assert (loaded.width(), loaded.height()) == (w_px, h_px)
