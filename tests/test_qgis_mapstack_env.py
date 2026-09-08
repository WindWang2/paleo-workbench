"""M1 Task 1: vendored QGIS 桥在当前 Python 3.13 环境可用（硬依赖起点）。"""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


def test_bridge_importable_and_initializes(qapp):
    import qgis_render_bridge

    # V7：桥版本随 capability manifest 一起演进（0.3.0a0 起）。
    assert qgis_render_bridge.__version__ == "0.3.0a0"
    manifest = qgis_render_bridge.capability_manifest()
    assert manifest["contract_version"] >= 2
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    assert bridge.initialized
    assert bridge.version  # vendored QGIS 版本串非空
    bridge.shutdown()
