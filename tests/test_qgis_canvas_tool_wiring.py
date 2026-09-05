# -*- coding: utf-8 -*-
"""B8：QGIS 画布 identify/measure/export 接线真机回归。

- identify：shim 工具映射表直连桥 QgsMapToolIdentifyFeature（kind
  "identify"），点击命中经 native_identified 信号回到 Python；
- measure：桥无原生量距工具——激活期画布视口鼠标事件被
  _CanvasMouseRouter 换算成地图坐标喂给活动 Python 工具，分段距离经
  measure_segment/measure_preview 信号给出，且画布不再被拖动；
- export：export_service 经能力探测识别 QgisCanvasShim，PNG 真出图，
  SVG/PDF 走桥级矢量导出（retained 快照），无快照时诚实只报 PNG。
"""
import math

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_POLY_FEATURE = {
    "id": "f1",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0], [5.0, 5.0]]],
    },
    "properties": {"name": "A"},
}


def _red_polygon_snapshot():
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot,
        MapRenderSnapshot,
    )

    layer = MapLayerSnapshot(
        id="doc-poly",
        name="相带",
        layer_type="vector",
        extent=(5.0, 5.0, 8.0, 8.0),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=(dict(_POLY_FEATURE),),
        style={"fill": "#ff0000", "stroke": "#ff0000", "stroke_width": 1.0},
        visible=True,
        opacity=1.0,
    )
    return MapRenderSnapshot(project_crs="EPSG:4326", layers=(layer,))


class _FakeTools:
    """直传工具栈形态（attach_canvas 走后者）：shim 包装其 set_active_tool。"""

    def __init__(self):
        self.active_tool = None

    def set_active_tool(self, tool):
        if self.active_tool is not None and hasattr(self.active_tool, "active"):
            self.active_tool.active = False
        self.active_tool = tool
        if tool is not None and hasattr(tool, "active"):
            tool.active = True


class _IdentifyTool:
    """桥级 identify 映射专用的最小工具桩（Python 侧无 identify 工具类）。"""

    tool_id = "identify"


@pytest.fixture()
def shim(qtbot):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

    s = QgisCanvasShim()
    qtbot.addWidget(s)
    s.resize(400, 400)
    s.show()
    qtbot.waitExposed(s)
    s.set_extent((0.0, 0.0, 10.0, 10.0))
    yield s
    try:
        s.shutdown()
    except Exception:
        pass


def _viewport(shim):
    """画布视口（shiboken 首包装类型是 QWidget，viewport() 不可达）。"""
    vp = shim._canvas_viewport()
    assert vp is not None, "未能解析画布视口控件"
    return vp


def _send_mouse(shim, etype, pos, *, button, buttons, modifiers=None):
    """向画布视口显式投递鼠标事件（QTest.mouseMove 不带 buttons 状态）。"""
    from PySide6.QtCore import QPointF, QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    vp = _viewport(shim)
    event = QMouseEvent(
        etype,
        QPointF(pos),
        QPointF(vp.mapToGlobal(pos)),
        button,
        buttons,
        modifiers or Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(vp, event)


# -- 工具映射 ------------------------------------------------------------------


def test_shim_maps_identify_and_measure_tools(qtbot, monkeypatch):
    """identify → 桥 identify 工具；measure → pan + 视口事件路由激活。"""
    from qgis_render_bridge.mapstack import QgisMapStack

    from paleo_workbench.mapping.map_tools import MeasureDistanceTool, PanTool
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

    calls = []
    original = QgisMapStack.set_map_tool

    def spy(self, addr, kind):
        calls.append((int(addr), kind))
        return original(self, addr, kind)

    monkeypatch.setattr(QgisMapStack, "set_map_tool", spy)

    s = QgisCanvasShim()
    qtbot.addWidget(s)
    tools = _FakeTools()
    s.set_map_tool_controller(tools)
    addr = int(s.canvas_address)

    def kinds():
        return [kind for a, kind in calls if a == addr]

    tools.set_active_tool(_IdentifyTool())
    assert kinds()[-1] == "identify", f"identify 应映射原生 kind identify，实际 {kinds()}"
    assert not s._measure_router.active

    tools.set_active_tool(MeasureDistanceTool())
    assert kinds()[-1] == "pan", "measure 无原生工具：原生侧应落 pan 清占用"
    assert s._measure_router.active, "measure 激活期应挂视口事件路由"

    tools.set_active_tool(PanTool())
    assert kinds()[-1] == "pan"
    assert not s._measure_router.active, "切走 measure 后路由应解除"


# -- identify 端到端 ------------------------------------------------------------


def test_identify_click_emits_native_identified(qtbot, shim):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    shim.set_layer_snapshot(_red_polygon_snapshot())
    shim.set_current_layer("doc-poly")
    tools = _FakeTools()
    shim.set_map_tool_controller(tools)
    tools.set_active_tool(_IdentifyTool())

    results = []
    shim.native_identified.connect(results.append)

    # 面内 (6.5,6.5) → (260,140)（400x400 画布，extent 0..10）
    QTest.mouseClick(_viewport(shim), Qt.LeftButton,
                     Qt.NoModifier, QPoint(260, 140))
    qtbot.waitUntil(lambda: bool(results), timeout=4000)
    payload = results[-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] == "f1"


# -- measure 端到端 -------------------------------------------------------------


def test_measure_routing_emits_segment_and_keeps_extent(qtbot, shim):
    from PySide6.QtCore import QEvent, QPoint, Qt

    from paleo_workbench.mapping.map_tools import MeasureDistanceTool

    shim.set_layer_snapshot(_red_polygon_snapshot())
    tools = _FakeTools()
    shim.set_map_tool_controller(tools)
    tool = MeasureDistanceTool()
    tools.set_active_tool(tool)
    segments, previews = [], []
    shim.measure_segment.connect(segments.append)
    shim.measure_preview.connect(previews.append)

    # 快照镜像会异步把画布 fit 到图层范围——先泵稳，避免测试中途 extent 漂移
    qtbot.wait(150)
    base_extent = tuple(shim.view_extent)

    # 起点 (100,200)；拖到 (200,200) 只出预览
    _send_mouse(shim, QEvent.Type.MouseButtonPress, QPoint(100, 200),
                button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton)
    assert tool.start is not None, "press 未路由到 Python measure 工具"
    _send_mouse(shim, QEvent.Type.MouseMove, QPoint(200, 200),
                button=Qt.NoButton, buttons=Qt.MouseButton.NoButton)
    assert tool.current is not None
    assert previews, "移动期应发出实时预览信号"

    # 第二次按下 (300,200)：完成分段（MeasureDistanceTool 链式把 start 挪到本点）
    _send_mouse(shim, QEvent.Type.MouseButtonPress, QPoint(300, 200),
                button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton)
    assert segments, "完成分段应发出 measure_segment"
    # 路由换算与画布 screen_to_map 必须同源：工具收到的坐标就是映射坐标
    p1 = shim.screen_to_map((100, 200))
    p2 = shim.screen_to_map((300, 200))
    assert abs(p1[1] - p2[1]) < 1e-9, "同一屏幕行 → 同一地图 y"
    assert abs(tool.start[0] - p2[0]) < 1e-9 and abs(tool.start[1] - p2[1]) < 1e-9
    assert abs(segments[-1] - math.dist(p1, p2)) < 1e-9
    assert math.dist(p1, p2) > 0.1

    # 事件被路由消费：画布没有进入拖动（extent 保持原状）
    assert tuple(shim.view_extent) == base_extent

    # 右键取消 → 会话清空
    _send_mouse(shim, QEvent.Type.MouseButtonPress, QPoint(150, 150),
                button=Qt.MouseButton.RightButton, buttons=Qt.MouseButton.RightButton)
    assert tool.start is None
    assert tool.last_distance is None


# -- export 接线 ----------------------------------------------------------------


def _wait_rendered(qtbot, shim):
    shim.stack.refresh_canvas(shim.canvas_address)
    qtbot.waitUntil(
        lambda: not shim.stack.is_canvas_rendering(shim.canvas_address),
        timeout=8000,
    )
    qtbot.wait(200)


def test_export_service_recognizes_shim_and_exports_real_png(qtbot, shim, tmp_path):
    from PySide6.QtGui import QImage

    from paleo_workbench.resources.export_service import (
        export_widget_snapshot,
        view_export_capabilities,
    )

    shim.set_layer_snapshot(_red_polygon_snapshot())
    _wait_rendered(qtbot, shim)

    caps = view_export_capabilities(shim)
    assert "PNG" in caps
    assert {"SVG", "PDF"} <= set(caps), "有快照 + 桥可用时 SVG/PDF 应如实声明"

    out = tmp_path / "qgis_canvas.png"
    result = export_widget_snapshot(shim, out, "PNG")
    assert result.success, result.message
    assert out.is_file() and out.stat().st_size > 1000

    image = QImage(str(out))
    assert not image.isNull()
    # 面内 (6.5,6.5) → (260,140) 应为红色填充（真出图而非空白帧）
    c = image.pixelColor(260, 140)
    assert c.red() > 200 and c.green() < 80 and c.blue() < 80, (
        f"PNG 中心像素不是多边形填充色: {c.red()},{c.green()},{c.blue()}"
    )


def test_shim_exports_real_vector_svg_pdf(qtbot, shim, tmp_path):
    from paleo_workbench.resources.export_service import export_widget_snapshot

    shim.set_layer_snapshot(_red_polygon_snapshot())
    _wait_rendered(qtbot, shim)

    svg_out = tmp_path / "qgis_canvas.svg"
    svg_result = export_widget_snapshot(shim, svg_out, "SVG")
    assert svg_result.success, svg_result.message
    svg = svg_out.read_text(encoding="utf-8", errors="replace")
    assert "<path" in svg.lower(), "SVG 应为桥级真矢量输出"
    assert "#ff0000" in svg or "255,0,0" in svg

    pdf_out = tmp_path / "qgis_canvas.pdf"
    pdf_result = export_widget_snapshot(shim, pdf_out, "PDF")
    assert pdf_result.success, pdf_result.message
    payload = pdf_out.read_bytes()
    assert payload.startswith(b"%PDF")
    assert len(payload) > 500


def test_shim_without_snapshot_claims_png_only(qtbot, tmp_path):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.resources.export_service import (
        export_widget_snapshot,
        view_export_capabilities,
    )

    s = QgisCanvasShim()
    qtbot.addWidget(s)
    try:
        assert view_export_capabilities(s) == {"PNG"}
        result = export_widget_snapshot(s, tmp_path / "x.svg", "SVG")
        assert not result.success
        assert "不支持" in result.message
    finally:
        try:
            s.shutdown()
        except Exception:
            pass
