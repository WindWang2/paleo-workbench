"""M1 Task 2: QgisMapStack 生命周期——初始化幂等、QgsProject 单例可达。"""
import pytest

pytest.importorskip("PySide6")


def test_mapstack_lifecycle(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    assert not stack.initialized
    stack.initialize()
    assert stack.initialized
    stack.initialize()  # 幂等：二次调用不抛异常
    assert stack.project_layer_count() == 0
    stack.shutdown()
