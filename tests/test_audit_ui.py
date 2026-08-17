"""Regression tests for UI-zone audit fixes."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

from paleo_workbench.project.models import (
    FactorMapTask,
    MapReferenceLayer,
    PaleoMapDocument,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog
from paleo_workbench.ui.pages.json_tree_preview_widget import JsonTreePreviewWidget
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel


def test_json_tree_caps_deep_nesting(qtbot):
    """Audit F7: unbounded JSON nesting must not overflow the interpreter stack."""
    widget = JsonTreePreviewWidget()
    qtbot.addWidget(widget)
    # At the cap depth, _build_row must render a placeholder val instead of
    # recursing further; the prior recursive impl overflowed the stack here.
    row = widget._build_row("root", {"a": 1}, depth=widget._MAX_BUILD_DEPTH)
    key_item, val_item = row
    assert val_item.text() == "…"
    assert key_item.rowCount() == 0  # no children materialized past the cap

    # A normal-depth call still recurses (no regression in the common case).
    row2 = widget._build_row("root", {"a": 1}, depth=0)
    assert row2[0].rowCount() == 1
    assert row2[1].text().startswith("{object")


def test_map_layer_properties_shows_managed_when_no_provenance(qtbot):
    """Audit F18: str(None) is truthy so the fallback showed literal 'None'."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QLabel

    # Build a minimal layer duck-type (the dialog reads id/name/type/source_ref/...).
    layer = SimpleNamespace(
        id="ref", name="ref", type=SimpleNamespace(name="VectorGrid"),
        crs="", opacity=1.0, source_ref="", data_revision=1, style_revision=1,
        provenance_ref="", metadata={},
    )
    dlg = MapLayerPropertiesDialog(layer)
    qtbot.addWidget(dlg)
    label_texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    # The dialog should show "managed" for empty provenance, never a bare "None".
    assert any("managed" in t for t in label_texts)
    assert not any(t == "None" for t in label_texts)
    dlg.deleteLater()


def test_sequence_target_panel_emits_on_commit_not_keystroke(qtbot):
    """Audit F8: editable target combo must fire only on Enter / selection.

    Previously currentTextChanged cascaded apply_stratigraphy_scheme on every
    keystroke, rebuilding the combo under the user mid-word.
    """
    panel = SequenceTargetPanel()
    qtbot.addWidget(panel)
    fired: list[str] = []
    panel.target_changed.connect(fired.append)

    # Typing into the editable line edit must NOT fire target_changed.
    line = panel.target_combo.lineEdit()
    line.setText("H")
    line.setText("Ho")
    line.setText("Hor")
    assert fired == []

    # Pressing Enter commits the edit.
    qtbot.keyClick(line, Qt.Key.Key_Return)
    assert fired == ["Hor"]


def test_native_layer_tree_opacity_clamps(qtbot):
    """Audit F14: out-of-range opacity must clamp to [0, 1] on assignment."""
    pytest.importorskip("layer_model_core")
    import layer_model_core
    from paleo_workbench.ui.native_layer_tree import NativeLayerTree

    registry = layer_model_core.LayerRegistry()
    registry.add_layer(
        "surface", "surface", layer_model_core.LayerType.ScalarGrid,
    )
    tree = NativeLayerTree(registry)
    qtbot.addWidget(tree)

    layer = registry.layers()[0]
    opacity_index = tree.model.index(0, 1)
    tree.model.setData(opacity_index, 5.0, Qt.ItemDataRole.EditRole)
    assert layer.opacity == 1.0
    tree.model.setData(opacity_index, -3.0, Qt.ItemDataRole.EditRole)
    assert layer.opacity == 0.0


def _vector_layer():
    from types import SimpleNamespace

    return SimpleNamespace(
        id="ref", name="ref", type=SimpleNamespace(name="VectorGrid"),
        crs="", opacity=1.0, source_ref="", data_revision=1, style_revision=1,
        provenance_ref="", metadata={},
    )


def test_layer_properties_apply_blocks_invalid_classes_json(qtbot):
    """#652: Apply must not emit a style that silently dropped Classes JSON."""
    dlg = MapLayerPropertiesDialog(_vector_layer())
    qtbot.addWidget(dlg)
    received = []
    dlg.properties_applied.connect(lambda _id, payload: received.append(payload))

    dlg.renderer_combo.setCurrentText("categorized")
    dlg.classes_edit.setPlainText('{"delta": #6c8ebf}')
    dlg.apply()

    assert received == []
    assert not dlg.classes_error_label.isHidden()
    assert "Invalid Classes JSON" in dlg.classes_error_label.text()


def test_layer_properties_ok_blocks_invalid_classes_json(qtbot):
    """Audit C83: OK must not silently close over unparseable Classes JSON;
    an inline error appears next to the field instead."""
    from PySide6.QtWidgets import QDialog

    dlg = MapLayerPropertiesDialog(_vector_layer())
    qtbot.addWidget(dlg)

    dlg.renderer_combo.setCurrentText("categorized")
    dlg.classes_edit.setPlainText('{"delta": #6c8ebf}')
    assert dlg.classes_json_error() is not None

    dlg._accept_after_apply()

    assert dlg.result() != QDialog.DialogCode.Accepted
    assert not dlg.classes_error_label.isHidden()
    assert "Invalid Classes JSON" in dlg.classes_error_label.text()
    # Editing the text again hides the error and allows acceptance.
    dlg.classes_edit.setPlainText('{"delta": "#6c8ebf"}')
    assert dlg.classes_error_label.isHidden()
    assert dlg.classes_json_error() is None


def test_layer_properties_ok_applies_valid_classes_json(qtbot):
    """Valid Classes JSON still applies categories and closes the dialog."""
    from PySide6.QtWidgets import QDialog

    dlg = MapLayerPropertiesDialog(_vector_layer())
    qtbot.addWidget(dlg)
    received = []
    dlg.properties_applied.connect(lambda layer_id, payload: received.append(payload))

    dlg.renderer_combo.setCurrentText("categorized")
    dlg.classes_edit.setPlainText('{"delta": "#6c8ebf"}')

    dlg._accept_after_apply()

    assert received
    assert received[0]["style"]["categories"] == {"delta": "#6c8ebf"}
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg.deleteLater()
