"""M1 Task 1: vendored QGIS 桥在当前 Python 3.13 环境可用（硬依赖起点）。"""
import pytest

pytest.importorskip("PySide6")


def test_bridge_importable_and_initializes(qapp):
    import qgis_render_bridge

    assert qgis_render_bridge.__version__ == "0.2.17a0"
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    assert bridge.initialized
    assert bridge.version  # vendored QGIS 版本串非空
    bridge.shutdown()
