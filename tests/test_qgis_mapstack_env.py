"""M1 Task 1: vendored QGIS 桥在当前 Python 3.13 环境可用（硬依赖起点）。"""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


def test_bridge_importable_and_initializes(qapp):
    import qgis_render_bridge

    # V7：桥版本随 capability manifest 一起演进（0.3.0a0 起）——版本
    # 下限断言（V9 测试卫生：== 钉死会在每次版本演进时假红）。
    from packaging.version import Version
    assert Version(qgis_render_bridge.__version__) >= Version("0.3.0a0")
    manifest = qgis_render_bridge.capability_manifest()
    assert manifest["contract_version"] >= 2
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    assert bridge.initialized
    assert bridge.version  # vendored QGIS 版本串非空
    bridge.shutdown()
