"""P0-D — composition editor panel UI state.

B5: the inspector is schema-driven (registry property_schema generates the
editors), so these tests exercise the generic mechanism — number spin for
GRID spacing, JSON box for lists, series table for STAT_CHART — plus the
lock affordance and the registry-backed add menu.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.composer.components import ComposerError
from paleo_workbench.mapping.composer.models import ElementType
from paleo_workbench.mapping.composer.registry import get_spec
from paleo_workbench.ui.pages.composition_panel import CompositionPanel


@pytest.fixture()
def panel(qtbot) -> CompositionPanel:
    widget = CompositionPanel()
    qtbot.addWidget(widget)
    widget.resize(320, 800)
    return widget


def _element_of(panel, etype):
    return next(e for e in panel.document().elements if e.element_type is etype)


class TestCompositionPanel:
    def test_starts_with_template_document(self, panel):
        assert panel.session is not None
        assert panel.document() is not None
        types = {e.element_type for e in panel.document().elements}
        assert ElementType.MAIN_MAP in types

    def test_add_delete_undo_roundtrip(self, panel):
        before = len(panel.document().elements)
        # Panel-level operations keep the history buttons in sync.
        panel._add_element(ElementType.TEXT)
        assert len(panel.document().elements) == before + 1
        assert panel.undo_btn.isEnabled()
        panel._delete_selected()
        assert len(panel.document().elements) == before
        panel._undo()
        assert len(panel.document().elements) == before + 1
        assert panel.undo_btn.isEnabled()
        assert panel.redo_btn.isEnabled()

    def test_property_editor_follows_selection(self, panel):
        colorbar = _element_of(panel, ElementType.COLORBAR)
        panel._select_element(colorbar.id)
        # schema 驱动：COLORBAR 的 min 是 number 编辑器（QDoubleSpinBox）。
        editor = panel._schema_editors["min"]
        assert editor.isEnabled()
        assert float(editor.value()) == pytest.approx(colorbar.properties["min"])
        editor.setValue(12.5)
        assert colorbar.properties["min"] == pytest.approx(12.5)

    def test_schema_editor_for_grid_spacing(self, panel):
        grid = panel._add_element(ElementType.GRID)
        editor = panel._schema_editors["spacing_mm"]
        editor.setValue(33.0)
        assert grid.properties["spacing_mm"] == pytest.approx(33.0)
        # 修改走 session 命令：可撤销。
        assert panel.session.undo()
        assert grid.properties["spacing_mm"] != pytest.approx(33.0)

    def test_bindings_apply_to_colorbar(self, panel):
        resolved = panel.apply_bindings({
            "factor.colorbar": {
                "title": "孔隙度 (%)",
                "min": 2.0,
                "max": 18.0,
                "stops": [(0.0, "#ffffff"), (1.0, "#1a9850")],
            }
        })
        assert resolved >= 1
        colorbar = _element_of(panel, ElementType.COLORBAR)
        assert colorbar.properties["title"] == "孔隙度 (%)"
        assert colorbar.properties["max"] == pytest.approx(18.0)

    def test_template_switch_rebuilds(self, panel):
        panel.template_combo.setCurrentIndex(0)
        first_id = panel.document().id
        panel._new_from_template()
        assert panel.document().id != first_id

    def test_export_signal(self, panel, qtbot, tmp_path):
        exported = []
        panel.composition_exported.connect(lambda p: exported.append(p))
        monkey_path = tmp_path / "page.png"
        from paleo_workbench.mapping.composer.export import export_composition

        out = export_composition(panel.document(), monkey_path, fmt="png", dpi=150.0)
        assert out.exists() and out.stat().st_size > 0


class TestSchemaDrivenInspector:
    def test_editors_are_generated_for_every_registered_component(self, panel):
        for etype in ElementType:
            panel._add_element(etype)
            spec_editors = set(panel._schema_editors)
            assert spec_editors, f"{etype}: schema form must generate editors"
            expected = {p["name"] for p in get_spec(etype).property_schema}
            assert expected <= spec_editors, etype

    def test_list_property_uses_json_editor(self, panel):
        panel._add_element(ElementType.TIMESCALE)
        editor = panel._schema_editors["stages"]
        from PySide6.QtWidgets import QLineEdit
        assert isinstance(editor, QLineEdit)

    def test_choices_editor_configures_property(self, panel):
        chart = panel._add_element(ElementType.STAT_CHART)
        combo = panel._schema_editors["chart_type"]
        combo.setCurrentText("pie")
        assert chart.properties["chart_type"] == "pie"

    def test_stat_chart_series_table_edit(self, panel):
        chart = panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "bar",
            "series": [{"label": "W1", "value": 1.0}],
        })
        table_host = panel._schema_editors["series"]
        from PySide6.QtWidgets import QTableWidget
        table = table_host.findChild(QTableWidget)
        assert table is not None and table.rowCount() == 1
        table.item(0, 0).setText("W9")
        table.item(0, 1).setText("4.5")
        assert chart.properties["series"][0] == {"label": "W9", "value": 4.5}
        # 表格编辑同样可撤销（每个单元格是一条 configure 命令）。
        panel._undo()
        panel._undo()
        assert chart.properties["series"][0]["label"] == "W1"

    def test_histogram_uses_json_editor_for_series(self, panel):
        chart = panel._add_element(ElementType.STAT_CHART, properties={
            "chart_type": "histogram",
            "series": {"values": [1, 2, 3], "bins": 4},
        })
        from PySide6.QtWidgets import QLineEdit
        editor = panel._schema_editors["series"]
        assert isinstance(editor, QLineEdit)
        editor.setText('{"values": [1, 2, 3, 9], "bins": 4}')
        panel._on_schema_json_changed("series", editor.text())
        assert chart.properties["series"]["values"] == [1, 2, 3, 9]


class TestLocking:
    def test_toggle_lock_marks_element_and_list(self, panel):
        element = _element_of(panel, ElementType.MAIN_MAP)
        assert not element.locked
        panel._toggle_lock(element.id)
        assert element.locked
        labels = [panel.element_list.item(r).text()
                  for r in range(panel.element_list.count())]
        assert any("锁定" in label for label in labels)
        panel._toggle_lock(element.id)
        assert not element.locked

    def test_locked_element_refuses_panel_edits(self, panel):
        element = panel._add_element(ElementType.TEXT)
        panel._toggle_lock(element.id)
        # 几何与属性编辑器被禁用（session 层同样拒绝）。
        assert not panel.x_spin.isEnabled()
        assert all(not e.isEnabled() for e in panel._schema_editors.values())
        with pytest.raises(ComposerError):
            panel.session.move_element(element.id, 99.0, 99.0)
        with pytest.raises(ComposerError):
            panel.session.remove_element(element.id)

    def test_lock_is_undoable(self, panel):
        element = panel._add_element(ElementType.NEATLINE)
        panel._toggle_lock(element.id)
        assert element.locked
        panel._undo()
        assert not element.locked

    def test_add_menu_is_registry_driven(self, panel):
        menu = panel.add_btn.menu()
        actions = [a.text() for a in menu.actions()]
        # 分类分组（基础/地质/统计图表）来自注册表 categories()。
        assert {"基础组件", "地质组件", "统计图表"} <= set(actions)
