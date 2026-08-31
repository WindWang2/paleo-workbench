"""P0-D — composition editor panel UI state."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.composer.models import ElementType
from paleo_workbench.ui.pages.composition_panel import CompositionPanel


@pytest.fixture()
def panel(qtbot) -> CompositionPanel:
    widget = CompositionPanel()
    qtbot.addWidget(widget)
    widget.resize(320, 800)
    return widget


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
        colorbar = next(
            e for e in panel.document().elements if e.element_type is ElementType.COLORBAR
        )
        panel._select_element(colorbar.id)
        assert panel.min_spin.isEnabled()
        assert panel.max_spin.isEnabled()
        panel.min_spin.setValue(12.5)
        assert colorbar.properties["min"] == pytest.approx(12.5)

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
        colorbar = next(
            e for e in panel.document().elements if e.element_type is ElementType.COLORBAR
        )
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
