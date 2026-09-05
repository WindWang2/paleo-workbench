"""M1 Task 2: QgisMapStack 生命周期——初始化幂等、QgsProject 单例可达。"""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


def test_mapstack_lifecycle(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    assert not stack.initialized
    stack.initialize()
    assert stack.initialized
    stack.initialize()  # 幂等：二次调用不抛异常
    assert stack.project_layer_count() == 0
    stack.shutdown()


def test_destroyed_canvas_address_stays_rejected(qapp):
    """#1134: destroy 后旧地址的任何调用必须稳定抛错，不得 reinterpret 悬空指针。"""
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    stack.initialize()
    try:
        addr = stack.create_canvas()
        stack.set_canvas_white_background(addr)  # 存活时可用
        stack.destroy_canvas(addr)
        with pytest.raises(ValueError):
            stack.set_canvas_white_background(addr)
        with pytest.raises(ValueError):
            stack.canvas_extent(addr)
        # 二次 destroy 不得复活该地址。
        stack.destroy_canvas(addr)
        with pytest.raises(ValueError):
            stack.set_canvas_white_background(addr)
    finally:
        stack.shutdown()


def test_bridge_and_stack_share_one_qgis_init(qapp):
    """#1155: render bridge 与 map stack 共存时 init 只跑一次。"""
    import qgis_render_bridge
    from qgis_render_bridge.mapstack import QgisMapStack

    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    stack = QgisMapStack()
    try:
        stack.initialize()
        stack.initialize()  # 幂等
        assert stack.initialized
        addr = stack.create_canvas()
        stack.set_canvas_white_background(addr)
        stack.destroy_canvas(addr)
    finally:
        stack.shutdown()
        bridge.shutdown()


def test_nan_inputs_rejected_at_mapstack_boundary(qapp):
    """#1165: NaN/inf 不得进入 extent 与屏幕坐标换算（UB 防护）。"""
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    stack.initialize()
    try:
        addr = stack.create_canvas()
        with pytest.raises(ValueError):
            stack.set_canvas_extent(addr, float("nan"), 0.0, 1.0, 1.0)
        with pytest.raises(ValueError):
            stack.set_canvas_extent(addr, 0.0, 0.0, float("inf"), 1.0)
        with pytest.raises(ValueError):
            stack.screen_to_map(addr, float("nan"), 0.0)
        # 有限值照常工作（画布做 aspect-fit，值不必逐字相等）。
        stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
        import math

        assert all(math.isfinite(v) for v in stack.canvas_extent(addr))
        stack.destroy_canvas(addr)
    finally:
        stack.shutdown()
