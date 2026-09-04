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
