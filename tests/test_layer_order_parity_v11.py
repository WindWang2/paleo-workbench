"""V11 顺序一致性合同：canvas == tree == legend == layout，同一来源。

平价断言（native，非计时）：
1. 全树 doc 序（``mirror_tree_order_top_first``）包含组内图层（P0 修复：
   布局导出不再丢 grouped 层——map 图层集来自同一走查）。
2. 平铺模式：快照装配序（自下而上）→ 桥推送（top-first）→ 树序反转 =
   fallback 画笔堆叠（后绘在上）。两侧最上层一致。
3. 组模式：树序（top-first）与全树走查一致。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


def _fc(x: float):
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point",
                                         "coordinates": [x, 1.0]},
         "properties": {}}]})


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge import mapstack

    s = mapstack.QgisMapStack()
    s.initialize()
    yield s
    try:
        s.remove_groups_except([])
    except Exception:
        pass
    s.shutdown()


class TestTreeOrderSource:
    def test_tree_order_includes_grouped_layers(self, stack, qapp):
        canvas = stack.create_canvas()
        stack.upsert_mirror_layer("g_layer", "组内层", "Point", "EPSG:4326",
                                  _fc(1.0), "", "", "", True, 1.0)
        stack.upsert_mirror_layer("root_layer", "根层", "Point", "EPSG:4326",
                                  _fc(2.0), "", "", "", True, 1.0)
        stack.upsert_group("g1", "组一", "")
        stack.move_layer_to_group("g_layer", "g1", 0)
        # root-only 走查不含组内层（legacy 语义）；全树走查必须含
        assert "g_layer" not in stack.mirror_order_top_first()
        full = stack.mirror_tree_order_top_first()
        assert "g_layer" in full and "root_layer" in full

    def test_tree_order_is_top_first(self, stack, qapp):
        canvas = stack.create_canvas()
        stack.upsert_mirror_layer("bottom", "底", "Point", "EPSG:4326",
                                  _fc(1.0), "", "", "", True, 1.0)
        stack.upsert_mirror_layer("top", "顶", "Point", "EPSG:4326",
                                  _fc(2.0), "", "", "", True, 1.0)
        # 桥约定：set_mirror_layer_order 输入即 top-first（input[0] 在顶）
        stack.set_mirror_layer_order(["bottom", "top"])
        assert stack.mirror_tree_order_top_first() == ["bottom", "top"]


class TestFlatParityWithFallbackPainter:
    def test_flat_push_matches_fallback_stacking(self, stack, qapp):
        """同一 bottom-up 装配序：native 树序与 fallback 画笔堆叠一致。

        fallback 画笔按列表序绘制（后绘在上）→ 最上 = 装配序[-1]；
        native：reversed(装配序) 推送 → 树序[0]（最上）= 装配序[-1]。
        """
        canvas = stack.create_canvas()
        assembly_bottom_up = ["base", "reference", "draft"]
        for name in assembly_bottom_up:
            stack.upsert_mirror_layer(name, name, "Point", "EPSG:4326",
                                      _fc(1.0), "", "", "", True, 1.0)
        # qgis_mirror 平铺推送（V11 修复后）：
        stack.set_mirror_layer_order(list(reversed(assembly_bottom_up)))
        native_top_first = stack.mirror_tree_order_top_first()
        fallback_topmost = assembly_bottom_up[-1]
        assert native_top_first[0] == fallback_topmost == "draft"


class TestLayoutExportWithGroups:
    def test_layout_export_includes_grouped_layers(self, stack, qapp, tmp_path):
        # R4-P1：装配验证（非输入断言）——layout_map_layer_order 与导出
        # 装配同源（注释交叉引用），组内层必须在列（旧代码 doc_id 直喂
        # mapLayer()，ordered 恒空，setLayers 从未执行）。
        canvas = stack.create_canvas()
        stack.upsert_mirror_layer("in_group", "组内层", "Point", "EPSG:4326",
                                  _fc(1.0), "", "", "", True, 1.0)
        stack.upsert_mirror_layer("at_root", "根层", "Point", "EPSG:4326",
                                  _fc(2.0), "", "", "", True, 1.0)
        stack.upsert_group("lg", "布局组", "")
        stack.move_layer_to_group("in_group", "lg", 0)
        spec = {
            "page": {"width_mm": 200.0, "height_mm": 150.0},
            "items": [
                {"type": "map", "x_mm": 10.0, "y_mm": 10.0,
                 "width_mm": 180.0, "height_mm": 130.0,
                 "extent": [0.0, 0.0, 3.0, 2.0]},
            ],
        }
        out = tmp_path / "layout_with_groups.png"
        stack.layout_export(json.dumps(spec), str(out), "png", 96)
        assert out.exists() and out.stat().st_size > 0
        order = json.loads(stack.layout_map_layer_order())
        # 组内层在导出 map 集内（bottom-first 应用序：树顶 at_root 后画，
        # 故组内 in_group 先画——与 mirror_tree_order_top_first 反转一致）
        assert "in_group" in order and "at_root" in order
        tree_top_first = stack.mirror_tree_order_top_first()
        assert order == list(reversed(tree_top_first))[:len(order)]
