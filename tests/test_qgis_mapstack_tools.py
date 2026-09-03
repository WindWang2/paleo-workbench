"""M1 Task 5: 原生 map tool 切换 + extent/坐标回调 marshal 成 Qt Signal。"""
import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_set_native_tool(stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    for kind in ("pan", "zoomIn", "zoomOut"):
        stack.set_map_tool(host.canvas_address, kind)  # 不抛异常即通过
    with pytest.raises(Exception):
        stack.set_map_tool(host.canvas_address, "not-a-tool")


def test_extent_callback_fires_as_signal(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.events import StackEvents
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    events = StackEvents()
    events.attach(stack, host.canvas_address)
    seen = []
    events.extent_changed.connect(lambda *a: seen.append(a))

    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 20.0, 20.0)
    qtbot.waitUntil(lambda: len(seen) > 0, timeout=2000)
    assert seen[-1][2] > 0  # xmax 有效


def test_extent_callback_no_duplicate_on_reregistration(qtbot, stack):
    """F4 回归: 重复注册 extent 回调不应累积 — 单次 extent 变更只应触发一次 signal。"""
    from paleo_workbench.ui.qgis_stack.events import StackEvents
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    events = StackEvents()
    events.attach(stack, host.canvas_address)
    events.attach(stack, host.canvas_address)

    seen = []
    events.extent_changed.connect(lambda *a: seen.append(a))

    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 20.0, 20.0)
    qtbot.waitUntil(lambda: len(seen) > 0, timeout=2000)
    qtbot.wait(300)
    assert len(seen) == 1, f"重复注册导致回调累积，预期 1 次收到 {len(seen)} 次: {seen}"
