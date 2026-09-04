"""M1 Task 3: QgsMapCanvas 经地址边界嵌入 PySide6 布局，白底。"""
import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_canvas_embeds_as_child_widget(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    assert host.canvas.parentWidget() is host
    assert host.canvas.width() > 0
    # 白底：QWidget 基色即画布底色（#ffffff）。
    assert host.canvas.palette().color(host.canvas.backgroundRole()).name() == "#ffffff"


def test_canvas_extent_roundtrip(qtbot, stack):
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()

    stack.set_destination_crs(host.canvas_address, "EPSG:4326")
    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 10.0)
    extent = stack.canvas_extent(host.canvas_address)
    assert extent == pytest.approx([0.0, 0.0, 10.0, 10.0], abs=2.0)  # 画布按宽高比扩展
    point = stack.screen_to_map(host.canvas_address, 320.0, 240.0)
    assert point == pytest.approx([5.0, 5.0], abs=1.5)


def test_screen_to_map_subpixel_precision(qtbot, stack):
    """M3 Task 6（M2 移交项）：screen_to_map 不再 int 截断亚像素坐标。"""
    from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

    host = QgisCanvasHost(stack)
    qtbot.addWidget(host)
    host.resize(400, 400)
    host.show()

    stack.set_canvas_extent(host.canvas_address, 0.0, 0.0, 10.0, 10.0)
    a = stack.screen_to_map(host.canvas_address, 100.0, 100.0)[0]
    half = stack.screen_to_map(host.canvas_address, 100.5, 100.0)[0]
    full = stack.screen_to_map(host.canvas_address, 101.0, 100.0)[0]
    px = full - a
    assert px != 0.0
    # 半像素偏移必须体现为半像素地图位移（截断实现下 half == a）。
    assert half - a == pytest.approx(px / 2.0, rel=0.05)
