"""V13 顺序契约（W-K）：tree == render == legend == export == save/reopen。

在 V11/V12 已有 parity 测试（test_layer_order_parity_v11 /
test_layer_stack_order_v12 / test_label_order_v12）之上补齐缺口：

1. 组模式：领域期望树（LayerGroupController.build_desired_tree）的
   DFS 序 == 原生 ``mirror_tree_order_top_first``（树序即绘制序唯一来源）；
2. degraded（无原生栈）投影：``flatten_for_render`` 是 fallback 的规范
   投影——top-first DFS，反转即 fallback 画笔堆叠序（后绘在上）；
3. 图例：legend-backed 元素的 ``filter_layers`` 来自同一镜像层序；
4. save→reopen：工程 XML 信封往返后组结构与顺序保真。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")


def _fc(x: float):
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point",
                                         "coordinates": [x, 1.0]},
         "properties": {}}]})


# ---------------------------------------------------------------------------
# 纯域：degraded 投影契约


class TestDegradedProjectionContract:
    def test_flatten_for_render_is_top_first_tree_walk(self):
        from paleo_workbench.mapping_workspace.layer_group_controller import (
            LayerGroupController,
        )
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole
        from paleo_workbench.mapping_workspace.stage_state import (
            MappingWorkspaceState,
        )

        state = MappingWorkspaceState()
        controller = LayerGroupController(state)
        controller.register_layer("draft", LayerRole.INITIAL_FACIES_DRAFT)
        controller.register_layer("base", LayerRole.BASE_REFERENCE)
        snapshots = [
            SimpleNamespace(id="base", name="Base"),
            SimpleNamespace(id="draft", name="Draft"),
        ]
        desired = controller.build_desired_tree(snapshots)
        tree_walk = list(desired.iter_layers())
        flat = [layer.id for layer in desired.flatten_for_render(snapshots)]
        # 规范投影：flatten == 树 DFS（top-first）——反转即 fallback 堆叠序
        assert flat == tree_walk
        assert flat == ["draft", "base"]
        # fallback 画笔按列表序绘制（后绘在上）→ 最上 = flat[0]
        fallback_bottom_up = list(reversed(flat))
        assert fallback_bottom_up[-1] == "draft"
        # 不丢未入树图层
        extra = SimpleNamespace(id="unlisted", name="New")
        flat2 = [layer.id
                 for layer in desired.flatten_for_render(snapshots + [extra])]
        assert "unlisted" in flat2


# ---------------------------------------------------------------------------
# 图例：filter_layers 与镜像层序同源（纯）


class TestLegendFilterOrderContract:
    def test_legend_filter_doc_ids_follow_mirror_order(self):
        from paleo_workbench.mapping.composer.models import ElementType
        from paleo_workbench.mapping.layout_export import _legend_filter_doc_ids

        mirror_layers = [
            {"id": "bottom", "layer_type": "grid"},
            {"id": "wells_a", "layer_type": "well_point"},
            {"id": "wells_b", "layer_type": "well_point"},
            {"id": "top", "layer_type": "grid"},
        ]
        ids = _legend_filter_doc_ids(ElementType.WELL_LEGEND, mirror_layers)
        # 过滤表保持镜像层序（自下而上）：wells_a 在 wells_b 之下
        assert ids == ["wells_a", "wells_b"]


# ---------------------------------------------------------------------------
# 原生（qgis-marked）：组模式 parity + 信封往返顺序


@pytest.mark.qgis
class TestNativeGroupedOrderParity:
    def test_domain_tree_order_equals_native_tree_walk(self, qapp):
        pytest.importorskip("qgis_render_bridge.mapstack")
        from qgis_render_bridge import mapstack

        from paleo_workbench.mapping_workspace.layer_group_controller import (
            LayerGroupController,
        )
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole
        from paleo_workbench.mapping_workspace.stage_state import (
            MappingWorkspaceState,
        )

        stack = mapstack.QisMapStack() if hasattr(mapstack, "QisMapStack") \
            else mapstack.QgisMapStack()
        try:
            stack.initialize()
            canvas = stack.create_canvas()
            state = MappingWorkspaceState()
            controller = LayerGroupController(state)
            # 角色路由：draft → phase1 组；base → 基础参考组
            controller.register_layer("d1", LayerRole.INITIAL_FACIES_DRAFT)
            controller.register_layer("d2", LayerRole.INITIAL_FACIES_DRAFT)
            controller.register_layer("b1", LayerRole.BASE_REFERENCE)
            snapshots = [
                SimpleNamespace(id="b1", name="B1"),
                SimpleNamespace(id="d2", name="D2"),
                SimpleNamespace(id="d1", name="D1"),
            ]
            desired = controller.build_desired_tree(snapshots)
            domain_order = list(desired.iter_layers())

            # 把期望树应用到真实栈：创建组 + 放置 + 组内序推送
            for name in domain_order:
                stack.upsert_mirror_layer(
                    name, name, "Point", "EPSG:4326",
                    _fc(1.0), "", "", "", True, 1.0)
            for group in desired.iter_groups():
                stack.upsert_group(group.group_id, group.name, "")
            placements = []
            for group in desired.iter_groups():
                for index, layer_id in enumerate(
                        _group_layer_ids(desired, group.group_id)):
                    stack.move_layer_to_group(layer_id, group.group_id, index)
                    placements.append(
                        {"layerId": layer_id, "groupId": group.group_id,
                         "index": index})
            native_top_first = stack.mirror_tree_order_top_first()
            assert native_top_first == domain_order, (
                f"native {native_top_first} != domain {domain_order}")
            # layout 应用序 = 树顶序反转（同一来源的另一半约定）
            layout_order = json.loads(stack.layout_map_layer_order())
            assert layout_order == list(reversed(native_top_first))
        finally:
            try:
                stack.remove_groups_except([])
            except Exception:
                pass
            stack.shutdown()

    def test_envelope_roundtrip_preserves_grouped_order(self, qapp, qtbot):
        pytest.importorskip("qgis_render_bridge.mapstack")
        from qgis_render_bridge import mapstack

        from paleo_workbench.mapping_workspace.layer_groups import (
            BASE_REFERENCE_GROUP_ID,
        )

        stack = mapstack.QgisMapStack()
        try:
            stack.initialize()
            canvas = stack.create_canvas()
            for name in ("wells", "boundary", "grid"):
                stack.upsert_mirror_layer(
                    name, name, "Point", "EPSG:4326",
                    _fc(1.0), "", "", "", True, 1.0)
            # 组创建序按语义带（解释组 order 50 在基础参考 900 之上）
            stack.upsert_group("phase1.interpretation", "解释", "")
            stack.move_layer_to_group("grid", "phase1.interpretation", 0)
            stack.upsert_group(BASE_REFERENCE_GROUP_ID, "基础与参考", "")
            stack.move_layer_to_group("wells", BASE_REFERENCE_GROUP_ID, 0)
            stack.move_layer_to_group("boundary", BASE_REFERENCE_GROUP_ID, 1)
            qtbot.wait(50)
            before = stack.mirror_tree_order_top_first()
            assert before[0] == "grid"  # 组间：解释组在基础参考组之上

            xml = stack.write_project_xml()
            assert "<qgis" in xml
            stack.apply_project_xml(xml)
            qtbot.wait(300)  # 排队注册表注销只在事件循环触发（#1154 教训）
            after = stack.mirror_tree_order_top_first()
            assert after == before, (
                f"信封往返丢失组序: {after} != {before}")
        finally:
            try:
                stack.remove_groups_except([])
            except Exception:
                pass
            stack.shutdown()


def _group_layer_ids(snapshot, group_id: str) -> list[str]:
    for group in snapshot.iter_groups():
        if group.group_id == group_id:
            return [child.layer_id for child in group.children
                    if hasattr(child, "layer_id")]
    return []
