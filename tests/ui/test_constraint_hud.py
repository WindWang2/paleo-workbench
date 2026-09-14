"""M3 单因素约束 HUD + 连井剖面光标联动（无桥 fallback 路径）。

对应 docs/development/paleo-ui-workbench/03-tdd-ui-test-plan.md 矩阵 M3 与
01-interaction-specs.md S3 验收标准（60ms 合并节流 / O(1) 采样 / echo 断路 /
300ms 延迟清除防闪烁）。
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("numpy")

import numpy as np
from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.ui.components.constraint_factor_hud import (  # noqa: E402
    ConstraintFactorHud,
    HudController,
    bilinear_sample,
    confidence_from_variance,
    local_slope_degrees,
    nearest_well,
)


def _grid(z, *, variance=None, dx=10.0, dy=10.0, origin=(0.0, 0.0)):
    z = np.asarray(z, dtype=np.float32)
    height, width = z.shape
    x0, y0 = origin
    return SimpleNamespace(
        grid_z=z,
        grid_x=np.array([x0 + i * dx for i in range(width)]),
        grid_y=np.array([y0 + j * dy for j in range(height)]),
        variance_grid=(
            np.asarray(variance, dtype=np.float32) if variance is not None else None
        ),
        factor_name="砂地比",
        unit="%",
    )


# ---------------------------------------------------------------------------
# 纯函数：O(1) 网格采样（D7）
# ---------------------------------------------------------------------------

def test_bilinear_sample_plane_and_bounds():
    # z = x + y 的平面：任意内点采样 == 解析值
    z = [[0.0, 10.0], [10.0, 20.0]]
    grid = _grid(z)
    assert bilinear_sample(grid, 5.0, 5.0) == pytest.approx(10.0)
    assert bilinear_sample(grid, 0.0, 0.0) == pytest.approx(0.0)
    assert bilinear_sample(grid, 10.0, 10.0) == pytest.approx(20.0)
    # 网格外 → None（不外推）
    assert bilinear_sample(grid, -1.0, 5.0) is None
    assert bilinear_sample(grid, 5.0, 99.0) is None


def test_bilinear_sample_nodata_is_none():
    grid = _grid([[0.0, float("nan")], [10.0, 20.0]])
    assert bilinear_sample(grid, 0.0, 0.0) == pytest.approx(0.0)
    assert bilinear_sample(grid, 10.0, 0.0) is None  # NaN 单元 → 无数据


def test_local_slope_matches_gradient():
    # z = 0.01·x（dx=10, dy=10）→ 坡度 = atan(0.01)
    z = [[0.0, 0.1], [0.0, 0.1]]
    grid = _grid(z)
    slope = local_slope_degrees(grid, 5.0, 5.0)
    assert slope is not None
    assert slope == pytest.approx(math.degrees(math.atan(0.01)), rel=1e-3)
    assert local_slope_degrees(None, 1.0, 1.0) is None


def test_confidence_monotonic_in_variance():
    base = _grid([[1.0, 2.0], [3.0, 4.0]])
    low = _grid([[1.0, 2.0], [3.0, 4.0]], variance=[[0.0, 0.0], [0.0, 0.0]])
    high = _grid([[1.0, 2.0], [3.0, 4.0]], variance=[[4.0, 4.0], [4.0, 4.0]])
    c_low = confidence_from_variance(low, 5.0, 5.0)
    c_high = confidence_from_variance(high, 5.0, 5.0)
    assert c_low == pytest.approx(1.0)
    assert c_high is not None and c_high < c_low
    assert confidence_from_variance(base, 5.0, 5.0) is None  # 无方差 → 诚实 None


def test_nearest_well_radius_gate():
    wells = [
        SimpleNamespace(name="W-1", x=0.0, y=0.0),
        SimpleNamespace(name="W-2", x=100.0, y=0.0),
    ]
    assert nearest_well(wells, 3.0, 0.0, 50.0) == ("W-1", pytest.approx(3.0))
    assert nearest_well(wells, 50.0, 0.0, 30.0) is None  # 两井均在容差外
    assert nearest_well([], 0.0, 0.0, 50.0) is None


# ---------------------------------------------------------------------------
# HUD 部件：诚实降级 / 内存零增长
# ---------------------------------------------------------------------------

def _hud(qtbot):
    hud = ConstraintFactorHud()
    qtbot.addWidget(hud)
    hud.resize(260, 96)
    hud.show()
    qtbot.wait(20)
    return hud


def test_hud_missing_data_shows_dash(qtbot):
    hud = _hud(qtbot)
    hud.apply_values({})
    assert hud.value_of("sand_ratio") == "—"
    assert hud.value_of("slope") == "—"
    assert hud.value_of("nearest_well") == "—"
    assert hud.value_of("confidence") == "—"
    hud.apply_values({"sand_ratio": "62.4%", "slope": "0.8°",
                      "nearest_well": "W-17（相别 —）",
                      "confidence": "0.81"})
    assert hud.value_of("sand_ratio") == "62.4%"


def test_hud_transparent_for_mouse_and_permanent_rows(qtbot):
    hud = _hud(qtbot)
    assert hud.testAttribute(
        __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    # 行标签固定创建：burst 更新不新增子控件
    before = len(hud.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    for _ in range(50):
        hud.apply_values({"sand_ratio": "1%", "slope": "2°",
                          "nearest_well": "W", "confidence": "0.5"})
    after = len(hud.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert before == after == 8  # 4 行 × (字段名 + 值)


# ---------------------------------------------------------------------------
# HudController：60ms 合并节流 / 联动发布 / echo 断路 / 延迟清除
# ---------------------------------------------------------------------------

class FakeViewCoordination:
    def __init__(self):
        self.publishes: list[tuple[str, str]] = []

    def publish_section_cursor(self, well, *, source):
        self.publishes.append((str(well), str(source)))


def _controller(qtbot, *, grid=None, wells=None, radius=50.0):
    hud = ConstraintFactorHud()
    qtbot.addWidget(hud)
    hud.show()
    vc = FakeViewCoordination()
    controller = HudController(parent=None)
    controller.bind(
        hud=hud,
        factor_grid_provider=lambda: grid,
        wells_provider=lambda: wells or [],
        view_coordination=vc,
        section_well_radius=radius,
    )
    return controller, hud, vc


def test_hud_throttled_refresh_under_burst(qtbot, monkeypatch):
    grid = _grid([[50.0, 60.0], [70.0, 80.0]])
    controller, hud, _ = _controller(qtbot, grid=grid)
    calls: list[dict] = []
    original = hud.apply_values
    monkeypatch.setattr(hud, "apply_values",
                        lambda values: (calls.append(values), original(values)))
    # 同步 1000 点 burst（间隔 < 60ms）→ 只保留最新点，刷新合并
    for i in range(1000):
        controller.handle_position(float(i % 10), float(i % 10))
    qtbot.wait(120)
    assert len(calls) == 1
    assert calls[0]["sand_ratio"]  # 最新点已求值（非空）


def test_hud_no_top_level_widget_growth(qtbot):
    controller, _, _ = _controller(qtbot, grid=_grid([[1.0]]))
    before = len(QApplication.topLevelWidgets())
    for i in range(500):
        controller.handle_position(0.0, 0.0)
    qtbot.wait(120)
    after = len(QApplication.topLevelWidgets())
    assert before == after


def test_section_link_publish_and_delayed_clear(qtbot):
    wells = [SimpleNamespace(name="W-17", x=10.0, y=10.0)]
    controller, _, vc = _controller(qtbot, wells=wells, radius=50.0)
    controller.handle_position(10.0, 12.0)
    qtbot.wait(120)
    assert vc.publishes == [("W-17", "mapping_cursor")]
    # 离开容差 → 300ms 延迟清除（防闪烁）
    controller.handle_position(500.0, 500.0)
    qtbot.wait(100)
    assert len(vc.publishes) == 1  # 300ms 未到不发布清除
    qtbot.wait(400)
    assert vc.publishes[-1] == ("", "mapping_cursor")


def test_section_link_wobble_clears_once(qtbot):
    wells = [SimpleNamespace(name="W-17", x=10.0, y=10.0)]
    controller, _, vc = _controller(qtbot, wells=wells, radius=50.0)
    for point in ((10.0, 10.0), (400.0, 400.0), (10.0, 10.0), (400.0, 400.0)):
        controller.handle_position(*point)
        qtbot.wait(80)
    qtbot.wait(400)
    publishes = vc.publishes
    assert publishes.count(("", "mapping_cursor")) == 1  # 清除恰一次
    assert publishes[0] == ("W-17", "mapping_cursor")


def test_section_link_echo_break(qtbot):
    wells = [SimpleNamespace(name="W-17", x=10.0, y=10.0)]
    controller, hud, vc = _controller(qtbot, wells=wells)
    controller.handle_position(10.0, 10.0)
    qtbot.wait(120)
    count = len(vc.publishes)
    # 模拟剖面侧 sink 回写/其它视图再广播——不得引发地图侧二次发布
    vc.publish_section_cursor("W-17", source="section_view")
    vc.publishes.clear()
    vc.publishes.append(("W-17", "section_view"))
    qtbot.wait(120)
    mapping_publishes = [p for p in vc.publishes if p[1] == "mapping_cursor"]
    assert len(mapping_publishes) == 0


def test_same_well_no_republish(qtbot):
    wells = [SimpleNamespace(name="W-17", x=10.0, y=10.0)]
    controller, _, vc = _controller(qtbot, wells=wells)
    for _ in range(20):
        controller.handle_position(11.0, 9.0)
        qtbot.wait(10)
    qtbot.wait(200)
    same = [p for p in vc.publishes if p == ("W-17", "mapping_cursor")]
    assert len(same) == 1  # 井未变 → 不重复发布


# ---------------------------------------------------------------------------
# 协调总线：ViewCoordinationController 节流/去重路由（真实控制器 + fake sink）
# ---------------------------------------------------------------------------

def test_view_coordination_section_cursor_routing(qtbot):
    from paleo_workbench.ui.view_coordination import ViewCoordinationController
    from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
    from paleo_workbench.viz.selection_context import SelectionContext

    controller = ViewCoordinationController(
        SelectionContext(), CoordinateTransformHub(), parent=None)
    sink_calls: list[str] = []
    controller.set_section_cursor_sink(sink_calls.append)
    controller.publish_section_cursor("W-1", source="mapping_cursor")
    controller.publish_section_cursor("W-1", source="mapping_cursor")  # 去重
    assert sink_calls == ["W-1"]
    controller.publish_section_cursor("", source="mapping_cursor")  # 清除
    assert sink_calls == ["W-1", ""]
    controller.publish_section_cursor("", source="mapping_cursor")  # 清除幂等
    assert sink_calls == ["W-1", ""]
    controller.publish_section_cursor("W-1", source="mapping_cursor")
    assert sink_calls == ["W-1", "", "W-1"]


# ---------------------------------------------------------------------------
# 集成：CompositeDocument 挂载（HUD 挂画布、光标信号驱动）
# ---------------------------------------------------------------------------

def test_hud_mounted_in_composite(qtbot, monkeypatch):
    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("HUD 测试"))
    qtbot.addWidget(doc)
    doc.resize(1200, 800)
    doc.show()
    qtbot.wait(30)

    hud = doc.constraint_hud
    assert hud.parent() is doc.canvas
    # 直接发射光标坐标 → 节流刷新不炸、值诚实（空工程 → —）
    doc.canvas.map_position_changed.emit((3.0, 4.0))
    qtbot.wait(120)
    assert hud.value_of("sand_ratio") == "—"
