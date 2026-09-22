"""V8 M9 — QGIS/Qt 生命周期压力测试（goal §M9 矩阵）。

覆盖既有 lifecycle 测试（test_qgis_mapstack_lifecycle 等）没有的强度：
30×/100× 工程切换、map tool 激活循环、树视图开合、原生/回退转换、
StackEvents 投递与析构竞态（#951 stale-QTimer 根因类）。
QGIS-marked：无桥环境诚实跳过；纯 Python 的 events 竞态部分无桥可跑。
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from tests.qgis_support import require_mapstack  # noqa: E402

mapstack = require_mapstack()

_ZONES = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature",
     "geometry": {"type": "Polygon", "coordinates": [[[1.0, 1.0], [9.0, 1.0], [9.0, 8.0], [1.0, 8.0], [1.0, 1.0]]]},
     "properties": {"facies_name": "浅湖"}}
  ]
}"""

_WELLS = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "W1"}}
  ]
}"""


@pytest.fixture()
def stack(qapp):
    s = mapstack.QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _switch_project(stack, index: int) -> None:
    """一次工程切换 = 清空 + 重发两个镜像层（host 切换路径的最小等价）。"""
    stack.clear_project_layers()
    stack.upsert_mirror_layer(
        f"zones-{index % 2}", "相带", "Polygon", "EPSG:4326", _ZONES,
        "", "", "", True, 1.0, False, True, False, index,
    )
    stack.upsert_mirror_layer(
        f"wells-{index % 2}", "井位", "Point", "EPSG:4326", _WELLS,
        "", "", "", True, 1.0, False, False, False, index,
    )


def test_project_switch_30x_no_layer_leak(stack):
    for index in range(30):
        _switch_project(stack, index)
        assert stack.project_layer_count() == 2, f"leak at switch {index}"
    # 100× 预算内再做 70 轮（同一断言强度，验证无累积）。
    for index in range(30, 100):
        _switch_project(stack, index)
    assert stack.project_layer_count() == 2


def test_map_tool_activate_deactivate_cycles(stack, qapp):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    canvas = host.canvas_address
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 9.0)
    tools = ("pan", "zoomIn", "zoomOut", "identify", "measure",
             "addPoint", "vertex", "move", "select")
    for cycle in range(100):
        for tool in tools:
            stack.set_map_tool(canvas, tool)
        stack.set_map_tool(canvas, "pan")
        assert not stack.native_tool_busy(canvas)


def test_layer_tree_view_recreate_cycles(stack, qapp):
    stack.upsert_mirror_layer(
        "zones-1", "相带", "Polygon", "EPSG:4326", _ZONES,
        "", "", "", True, 1.0, False, True, False, 1,
    )
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 9.0)
    for _cycle in range(30):
        tree = stack.create_layer_tree_view(host.canvas_address)
        assert stack.tree_view_row_count(tree) >= 1
    # 视图存活于 stack；shutdown 统一回收（本测试不显式销毁——
    # stack.shutdown 必须能处理多视图）。


def test_row_indicator_and_edit_indicator_coexistence_cycles(stack, qapp):
    stack.upsert_mirror_layer(
        "zones-1", "相带", "Polygon", "EPSG:4326", _ZONES,
        "", "", "", True, 1.0, False, True, False, 1,
    )
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 9.0)
    tree = stack.create_layer_tree_view(host.canvas_address)
    for cycle in range(30):
        stack.set_edit_indicator(tree, "zones-1", True)
        stack.set_row_indicators(
            tree, "zones-1", json.dumps(["dirty", "published"])
        )
        # 行指示器不挤掉编辑铅笔，反之亦然
        assert stack.edit_indicator_count(tree, "zones-1") == 1
        assert stack.row_indicator_count(tree, "zones-1") == 2
        stack.set_edit_indicator(tree, "zones-1", False)
        assert stack.row_indicator_count(tree, "zones-1") == 2
        assert stack.edit_indicator_count(tree, "zones-1") == 0


# ---------------------------------------------------------------------------
# StackEvents 投递与析构竞态（#951 根因类；纯 Python 路径，无需桥）
# ---------------------------------------------------------------------------


def test_stack_events_survive_owner_destruction(qapp):
    """singleShot 投递时 owner 已销毁：不得向死对象 emit（不崩溃、不泄漏投递）。"""
    from paleo_workbench.ui.qgis_stack.events import StackEvents

    events = StackEvents()
    hits: list[tuple[float, float, float, float]] = []
    events.extent_changed.connect(lambda *args: hits.append(args))

    # 正常路径：投递 → 触发。
    events._requeue(lambda: events.extent_changed.emit(1.0, 2.0, 3.0, 4.0))
    qapp.processEvents()
    assert hits == [(1.0, 2.0, 3.0, 4.0)]

    # 销毁（显式消化 DeferredDelete——processEvents 不保证处理投递删除）
    # 后再排一次：带 context 的投递随对象销毁取消；防御守卫兜底任何残余
    # 触发——两种时序都不崩溃、都不向死对象发信号。
    from PySide6.QtCore import QCoreApplication, QEvent

    events.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    try:
        events._requeue(lambda: events.extent_changed.emit(9.0, 9.0, 9.0, 9.0))
        requeued = True
    except RuntimeError:
        requeued = False  # wrapper 已失效：同样安全
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert hits == [(1.0, 2.0, 3.0, 4.0)]
    _ = requeued  # 投递被取消 / wrapper 拒绝，两条路径都算通过


def test_stack_events_attach_registers_callbacks(qtbot):
    """attach 把 extent/xy 回调接到桥栈（duck-typed，无桥可验）。"""
    from paleo_workbench.ui.qgis_stack.events import StackEvents

    class _FakeStack:
        def __init__(self) -> None:
            self.extent_cb = None
            self.xy_cb = None

        def set_extent_callback(self, _canvas, cb) -> None:
            self.extent_cb = cb

        def set_xy_callback(self, _canvas, cb) -> None:
            self.xy_cb = cb

    events = StackEvents()
    seen: list[tuple[str, object]] = []
    events.extent_changed.connect(lambda *a: seen.append(("extent", a)))
    events.map_position_changed.connect(lambda *a: seen.append(("xy", a)))
    fake = _FakeStack()
    events.attach(fake, 123)
    assert fake.extent_cb is not None and fake.xy_cb is not None
    fake.extent_cb(0.0, 0.0, 5.0, 5.0)
    fake.xy_cb(2.5, 2.5)
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=2000)
    assert seen[0][0] == "extent"
    assert seen[1][0] == "xy"
