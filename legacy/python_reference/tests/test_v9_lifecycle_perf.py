"""V9 生命周期/性能压测 — 新权威面的重复循环稳定性。

Review-3 面（goal §24/§26）：V9 新增的 role lookup 注入、捕捉 profile 应用、
拓扑计数缓存、数字化 CRS 守卫钩子在工程切换/工具循环/大量上下文构建下：

* 不泄漏（层数/缓存条目数有界）；
* 上下文构建代价不随循环退化（evaluate_all 仍线性廉价——既有 V8 门
  ``test_evaluate_all_linear_and_cheap`` 的 V9 补充面）；
* 缓存语义在会话终结/层删除后正确回收。

headless（无桥依赖）：控制器 + 假画布鸭子类型。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.tool_availability import evaluate_all
from paleo_workbench.mapping.tool_context import build_tool_context
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


def _bad_polygon_feature(fid: str) -> VectorFeature:
    return VectorFeature(
        fid,
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
        {},
    )


@pytest.fixture()
def controller(qtbot):
    return CompositeEditController(project_crs="EPSG:4326")


def test_role_lookup_cycles_do_not_leak_layers(controller):
    """100× 建层（带角色）+ 删除：层数/快照/计数缓存全回收。"""
    controller.set_role_lookup(lambda lid: "fault_constraint")
    for cycle in range(100):
        layer = controller.create_layer(f"断层{cycle}", "line")
        controller.apply_capture_spec(layer.id)
        session = controller.ensure_layer_session(layer.id)[0]
        session.add_feature(_bad_polygon_feature(f"f{cycle}"))
        controller._topology.refresh_error_count(layer)
        assert len(controller._layers) == 1
        controller.remove_layer(layer.id)
    assert len(controller._layers) == 0
    assert controller._topology._error_counts == {}
    assert controller._snapping.layer_modes == {}


def test_topology_count_cache_bounded_across_refreshes(controller):
    """刷新点重复触发：缓存每层恰好一个条目（覆写不累积）。"""
    layer = controller.create_layer("L", "polygon")
    session = controller.ensure_layer_session(layer.id)[0]
    session.add_feature(_bad_polygon_feature("f1"))
    for _ in range(50):
        controller._topology.refresh_error_count(layer)
    assert list(controller._topology._error_counts) == [layer.id]
    assert controller._topology.cached_error_count([layer]) >= 1
    session.commit_changes()
    assert controller._topology.cached_error_count([layer]) == 0


def test_context_build_stable_across_tool_cycles(controller, qtbot):
    """30× 工具激活 + 上下文构建循环：v3 事实稳定、无状态漂移。"""
    layer = controller.create_layer("L", "line")
    controller.set_role_lookup(lambda lid: "provenance_direction")
    last_scale = None
    for cycle in range(30):
        controller.activate_tool("add_line" if cycle % 2 == 0 else "pan")
        ctx = build_tool_context(
            controller_state=controller.tool_context_inputs(),
            layer_facts={"active_layer_id": layer.id},
            native_canvas_available=False,
        )
        assert ctx.project_crs == "EPSG:4326"
        assert ctx.layer_crs == "EPSG:4326"
        verdicts = evaluate_all(ctx)
        assert verdicts["pan"].enabled
        last_scale = ctx.scale_denominator
    assert last_scale == 0.0  # 无画布 → 诚实未知，不因循环漂移


def test_project_reload_keeps_snap_profiles_within_layer_lifetime(controller):
    """load_from_project 重建层集后，旧层 profile 覆盖不复活。"""
    layer = controller.create_layer("断层", "line")
    controller.set_role_lookup(lambda lid: "fault_constraint")
    controller.apply_capture_spec(layer.id)
    assert layer.id in controller._snapping.layer_modes

    class _EmptyProject:
        user_vector_layers = []

    controller.load_from_project(_EmptyProject())
    assert layer.id not in controller._layers
    assert layer.id not in controller._snapping.layer_modes


def test_blocking_task_label_reads_scheduler_snapshot(controller):
    """调度器 statuses() 快照只读：无任务时空串（不创建调度器状态）。"""
    from paleo_workbench.ui.workstation.composite_document import (
        CompositeDocument,
    )

    label = CompositeDocument._mapping_blocking_task_label
    # 未初始化调度器的独立调用（document 未构造）：except 路径返回空串
    class _Bare:
        _mapping_blocking_task_label = label

    assert _Bare()._mapping_blocking_task_label() == ""
