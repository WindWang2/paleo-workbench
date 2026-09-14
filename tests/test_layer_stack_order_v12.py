# -*- coding: utf-8 -*-
"""V12 M3：栈序不变量（面板行序 == 镜像树序 == 组装序的反转）。

钉死 D-C：
1. ``_push_mirror_order`` 少了一次反转——``_layers`` 是组装序（自下而上），
   桥约定 top-first，漏反转会把整栈倒置（"置顶"实际落到底）。
2. 分组模式下该推送不生效：必须**如实返回 False**，调用方不得制造
   "已经置顶"的假象（静默 no-op 是这一条最坏的表现形态）。
3. 用户组/root 里的新成员并入头部（QGIS「新图层在最上」约定），系统组仍按
   角色带序尾部并入。
"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
     "properties": {}}]}


def _layer(layer_id, name, visible=True):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    return MapLayerSnapshot(
        id=layer_id, name=name, layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=(dict(_FC["features"][0]),), style={},
        visible=visible, opacity=1.0,
    )


def _panel(qtbot):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位"), _layer("doc-b", "边界")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 2, timeout=3000)
    return canvas, panel


def _tree_order(canvas):
    return list(canvas.stack.mirror_tree_order_top_first())


def test_move_layer_keeps_panel_and_canvas_in_sync(qtbot, qapp):
    """上移一层后：镜像树序 == 组装序反转（此前整栈被倒置）。"""
    canvas, panel = _panel(qtbot)
    before = _tree_order(canvas)
    assert set(before) == {"doc-a", "doc-b"}

    # direction=-1 = 上移（组装序 index+1；渲染自底向上，末位 = 最上）。
    assert panel.move_layer("doc-a", -1) is True
    qtbot.waitUntil(lambda: _tree_order(canvas) != before, timeout=2000)

    tree = _tree_order(canvas)
    assembly = [str(layer.id) for layer in panel._layers]
    assert tree == list(reversed(assembly)), (
        f"面板与画布栈序不一致：组装序 {assembly} / 树序 {tree}")


def test_move_layer_reports_when_group_mode_ignores_order(qtbot, qapp):
    """分组模式：move_layer 必须如实返回 False（不假装生效）。"""
    canvas, panel = _panel(qtbot)
    panel.set_group_controller(object())  # 只测分派分支，不需要真控制器行为
    order_before = _tree_order(canvas)
    assert panel.move_layer("doc-a", -1) is False
    qtbot.wait(60)
    assert _tree_order(canvas) == order_before, "分组模式下不得动镜像树"


class TestNewMemberPlacement:
    """新成员并入端：用户组/root 头部，系统组尾部（D9/R10）。"""

    def _records(self, extra=None):
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole
        from paleo_workbench.mapping_workspace.layer_tree_plan import PlanLayerRecord

        base = [
            PlanLayerRecord(layer_id="l_draft", role=LayerRole.INITIAL_FACIES_DRAFT,
                            created_stage="phase1", sub_order=0),
            PlanLayerRecord(layer_id="l_annot", role=LayerRole.INTERPRETATION_ANNOTATION,
                            created_stage="phase1", sub_order=1),
        ]
        return tuple(base + list(extra or ()))

    def test_system_group_keeps_band_order_for_new_member(self):
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole
        from paleo_workbench.mapping_workspace.layer_tree_plan import (
            LayerTreePlanInput, build_plan,
        )

        records = self._records([
            type(self._records()[0])(layer_id="l_new",
                                     role=LayerRole.INITIAL_FACIES_DRAFT,
                                     created_stage="phase1", sub_order=9),
        ])
        snap, _ = build_plan(LayerTreePlanInput(
            records=records, stage="facies_calibration",
            container_orders={"phase1.interpretation": ["l_draft", "l_annot"]},
        ))
        group = snap.find_group("phase1.interpretation")
        ids = [c.layer_id for c in group.children if hasattr(c, "layer_id")]
        assert ids[-1] == "l_new", f"系统组必须按带序尾部并入：{ids}"

    def test_user_group_puts_new_member_on_top(self):
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole
        from paleo_workbench.mapping_workspace.layer_tree_plan import (
            LayerTreePlanInput, PlanUserGroup, build_plan,
        )

        records = self._records([
            type(self._records()[0])(layer_id="l_new",
                                     role=LayerRole.INITIAL_FACIES_DRAFT,
                                     created_stage="phase1", sub_order=9),
        ])
        snap, _ = build_plan(LayerTreePlanInput(
            records=records, stage="facies_calibration",
            user_groups={"g1": PlanUserGroup(group_id="g1", name="我的组")},
            user_placements={"l_draft": "g1", "l_annot": "g1", "l_new": "g1"},
            container_orders={"g1": ["l_draft", "l_annot"]},
        ))
        group = snap.find_group("g1")
        ids = [c.layer_id for c in group.children if hasattr(c, "layer_id")]
        assert ids[0] == "l_new", f"用户组新成员应置顶：{ids}"
