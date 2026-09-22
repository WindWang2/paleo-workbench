"""复制验货 + RAW 删除入口（无 C++ 重编的 Python 侧补挂）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMenu

QApplication.instance() or QApplication([])

from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


def _controller() -> CompositeEditController:
    controller = CompositeEditController(project_crs="EPSG:32650")
    layer = controller.create_layer("源", "polygon")
    controller.import_layer_features(layer.id, [
        VectorFeature("a", {"type": "Polygon", "coordinates": [
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]}),
        VectorFeature("b", {"type": "Polygon", "coordinates": [
            [[2.0, 2.0], [3.0, 2.0], [3.0, 3.0], [2.0, 3.0], [2.0, 2.0]]]}),
    ])
    return controller


class _Host:
    uses_native_stack = True
    edit_controller = None
    canvas = None


def _host(controller, facts):
    host = _Host()
    host.edit_controller = controller
    host.canvas = SimpleNamespace(
        mirror_provider_facts=lambda doc_id: facts.get(doc_id))
    return host


def test_verify_skipped_without_native_stack() -> None:
    host = _Host()
    host.uses_native_stack = False
    assert CompositeDocument._verify_duplicate_mirror(host, "c", "s") == ""


def _copied(controller):
    layer_id = next(iter(controller.layer_ids()))
    copy = controller.duplicate_layer(layer_id)
    assert copy is not None
    return copy.id


def test_verify_reports_missing_mirror() -> None:
    controller = _controller()
    copy_id = _copied(controller)
    host = _host(controller, {})
    text = CompositeDocument._verify_duplicate_mirror(host, copy_id, "s")
    assert "未上镜像" in text and "快照2要素" in text


def test_verify_reports_counts_match() -> None:
    controller = _controller()
    copy_id = _copied(controller)
    facts = {copy_id: {"exists": True, "feature_count": 2,
                       "geometry_type": "Polygon", "field_count": 3,
                       "is_valid": True}}
    host = _host(controller, facts)
    text = CompositeDocument._verify_duplicate_mirror(host, copy_id, "s")
    assert "快照2→镜像2" in text
    assert "对不上" not in text


def test_verify_flags_count_mismatch() -> None:
    controller = _controller()
    copy_id = _copied(controller)
    facts = {copy_id: {"exists": True, "feature_count": 0,
                       "geometry_type": "Polygon", "field_count": 0,
                       "is_valid": True}}
    host = _host(controller, facts)
    text = CompositeDocument._verify_duplicate_mirror(host, copy_id, "s")
    assert "快照2→镜像0" in text
    assert "对不上" in text


def test_raw_delete_action_added_for_raw_protected() -> None:
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    panel = QgisLayerTreePanel()
    menu = QMenu()
    fired: list[str] = []
    panel.remove_layer_requested.connect(fired.append)
    facts = SimpleNamespace(raw_protected=True)
    panel._add_raw_delete_action(menu, "doc-1", facts)
    texts = [action.text() for action in menu.actions()]
    assert "删除图层" in texts
    next(action for action in menu.actions()
         if action.text() == "删除图层").trigger()
    assert fired == ["doc-1"]
    # 幂等：已有不重复加。
    panel._add_raw_delete_action(menu, "doc-1", facts)
    assert texts.count("删除图层") == 1


def test_raw_delete_action_skipped_when_not_raw() -> None:
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    panel = QgisLayerTreePanel()
    menu = QMenu()
    panel._add_raw_delete_action(
        menu, "doc-1", SimpleNamespace(raw_protected=False))
    assert "删除图层" not in [action.text() for action in menu.actions()]
