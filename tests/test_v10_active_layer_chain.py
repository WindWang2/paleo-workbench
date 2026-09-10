"""V10 M-G：活动图层链不变量（host-side，控制器级 + 记录画布假体）。

链路：QgsLayerTreeView current（原生侧）↔ Paleo active layer
（CompositeEditController）↔ 画布 current layer（set_current_layer 推送）。
本文件钉住控制器侧的两端一致：任何改变活动层的路径（创建/复制/删除/
显式设置）都必须把同一结论推给画布——空结论 = 显式清除，不是 no-op。
"""

from __future__ import annotations

import pytest

from paleo_workbench.ui.workstation.composite_editing import (
    CompositeEditController,
)


class _RecordingCanvas:
    """记录 set_current_layer 调用的画布假体（鸭子类型即可）。"""

    def __init__(self):
        self.current_calls: list[str] = []

    def set_current_layer(self, doc_id):
        self.current_calls.append(str(doc_id))

    def set_snapping_config(self, config):
        pass

    def set_map_tool_controller(self, controller):
        pass

    def set_overlay_provider(self, provider):
        pass

    def native_tool_busy(self):
        return False


@pytest.fixture()
def controller():
    return CompositeEditController(project_crs="EPSG:4490")


@pytest.fixture()
def canvas(controller):
    fake = _RecordingCanvas()
    controller.attach_canvas(fake)
    return fake


def test_create_layer_pushes_canvas_current(controller, canvas):
    layer = controller.create_layer(name="新层", kind="line")
    assert canvas.current_calls[-1] == layer.id


def test_duplicate_layer_pushes_canvas_current(controller, canvas):
    original = controller.create_layer(name="原层", kind="line")
    canvas.current_calls.clear()
    copy = controller.duplicate_layer(original.id)
    assert canvas.current_calls[-1] == copy.id


def test_remove_layer_reassigns_and_pushes(controller, canvas):
    first = controller.create_layer(name="一", kind="line")
    second = controller.create_layer(name="二", kind="line")
    assert controller.active_layer_id == second.id
    canvas.current_calls.clear()
    controller.remove_layer(second.id)
    # 剩余层接管活动层 + 画布 current 同步（不再只 rebind 工具）
    assert controller.active_layer_id == first.id
    assert canvas.current_calls[-1] == first.id


def test_explicit_clear_pushes_empty(controller, canvas):
    layer = controller.create_layer(name="层", kind="line")
    controller.set_active_layer(None)
    assert canvas.current_calls[-1] == ""
    controller.set_active_layer(layer.id)
    assert canvas.current_calls[-1] == layer.id


def test_unknown_id_maps_to_none_and_clears(controller, canvas):
    controller.create_layer(name="层", kind="line")
    controller.set_active_layer("no-such-layer")
    assert controller.active_layer_id is None
    assert canvas.current_calls[-1] == ""
