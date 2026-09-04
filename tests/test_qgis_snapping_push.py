# -*- coding: utf-8 -*-
"""M3 Task 1: SnappingService → QGIS snappingUtils 配置投影（Python 侧构建器）。"""

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


class _FakeCanvas:
    """捕获 set_snapping_config 投影的鸭子类型画布。"""

    def __init__(self) -> None:
        self.configs: list[dict] = []

    def set_map_tool_controller(self, controller) -> None:
        pass

    def set_overlay_provider(self, provider) -> None:
        pass

    def set_snapping_config(self, config: dict) -> None:
        self.configs.append(config)


def test_push_snapping_config_maps_global_and_per_layer_state(qtbot):
    controller = CompositeEditController()
    canvas = _FakeCanvas()
    controller.attach_canvas(canvas)
    layer = controller.create_layer("井点", "point")

    assert canvas.configs, "attach_canvas/create_layer 应触发配置下推"
    config = canvas.configs[-1]
    assert config["enabled"] is False
    assert config["mode"] == "all_layers"
    assert config["tolerance_px"] == pytest.approx(10.0)
    assert set(config["types"]) == {"vertex", "segment", "midpoint"}
    # AdvancedConfiguration 语义：每个图层都有显式条目（未覆盖者落全局值）
    assert config["layers"][layer.id]["enabled"] is True
    assert config["layers"][layer.id]["tolerance_px"] == pytest.approx(10.0)
    assert config["reference_enabled"] is False

    snapping = controller.snapping
    snapping.pixel_tolerance = 25.0
    snapping.layer_enabled[layer.id] = False
    snapping.layer_tolerance[layer.id] = 5.0
    snapping.modes.add("reference")
    controller.set_snapping(True)

    config = canvas.configs[-1]
    assert config["enabled"] is True
    assert config["tolerance_px"] == pytest.approx(25.0)
    assert config["reference_enabled"] is True
    entry = config["layers"][layer.id]
    assert entry["enabled"] is False
    assert entry["tolerance_px"] == pytest.approx(5.0)


def test_push_snapping_config_active_layer_mode(qtbot):
    controller = CompositeEditController()
    canvas = _FakeCanvas()
    controller.attach_canvas(canvas)
    controller.create_layer("相带", "polygon")
    controller.snapping.current_layer_only = True
    controller.set_snapping(True)
    config = canvas.configs[-1]
    assert config["mode"] == "active_layer"
    assert "layers" not in config


def test_push_snapping_config_without_canvas_is_noop(qtbot):
    controller = CompositeEditController()
    controller.set_snapping(True)  # 无画布不抛异常
    assert controller.snapping.enabled is True
