"""相图右键换相（V12 任务3）：相带家族判定 + 上游相选择列表组装。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.mapping.facies_taxonomy import FaciesTaxonomy
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.composite_editing import (
    CompositeEditController,
    is_facies_family_layer,
)


def _controller() -> CompositeEditController:
    return CompositeEditController(project_crs="EPSG:32650")


def _square(x0: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x0, 0.0], [x0 + 1.0, 0.0], [x0 + 1.0, 1.0],
        [x0, 1.0], [x0, 0.0]]]}


def test_family_covers_template_and_roles() -> None:
    assert is_facies_family_layer({"l": "facies"}, "l", "")
    assert is_facies_family_layer({}, "l", LayerRole.WELL_FACIES_PREDICTION)
    assert is_facies_family_layer({}, "l", "initial_facies_draft")
    assert is_facies_family_layer({}, "l", LayerRole.INTEGRATED_FACIES)
    assert not is_facies_family_layer({}, "l", "")
    assert not is_facies_family_layer({}, "l", LayerRole.FACIES_BOUNDARY)
    assert not is_facies_family_layer({}, "l", "user_general")


def _host(qtbot):
    from PySide6.QtWidgets import QWidget

    controller = _controller()
    taxonomy = FaciesTaxonomy.builtin()
    anchor_names = taxonomy.names("facies")
    assert anchor_names, "内置词表相级为空"
    layer = controller.create_layer(
        "地震预测相", "polygon", role=LayerRole.SEISMIC_FACIES_PREDICTION)
    controller.import_layer_features(layer.id, [
        VectorFeature("f1", _square(0.0), {"facies_name": anchor_names[0]}),
    ])
    # QMenu(self) 要求宿主是 QWidget：裸 QWidget + 属性挂载。
    host = QWidget()
    qtbot.addWidget(host)
    host.edit_controller = controller
    host.facies_taxonomy = lambda: taxonomy
    host._facies_features = CompositeDocument._facies_features.__get__(host)
    host._facies_level_values = (
        CompositeDocument._facies_level_values.__get__(host))
    host._facies_layer_anchor_level = (
        CompositeDocument._facies_layer_anchor_level.__get__(host))
    host._build_facies_context_menu = (
        CompositeDocument._build_facies_context_menu.__get__(host))
    return host, layer, anchor_names[0]


def test_build_facies_context_menu_checks_current(qtbot) -> None:
    """右键相选择列表：当前值打勾 + 级联弹窗入口（不 exec）。"""
    host, layer, current = _host(qtbot)
    menu, actions = host._build_facies_context_menu(layer.id, "f1")
    try:
        by_text = {action.text(): action for action in menu.actions()
                   if action.text()}
        assert current in by_text
        assert by_text[current].isCheckable()
        assert by_text[current].isChecked()
        cascade = next(
            text for text in by_text
            if text.startswith("更改相"))
        assert actions[by_text[cascade]] is None
    finally:
        menu.close()
