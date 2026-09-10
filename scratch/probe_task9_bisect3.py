# -*- coding: utf-8 -*-
"""Task 9 探针 bisect3：严格复刻 test_identify_click_emits_native_identified 范式。"""
from __future__ import annotations

import sys
import time


def log(*args):
    print("[bisect3]", *args, flush=True)


_POLY_FEATURE = {
    "id": "f1",
    "geometry": {"type": "Polygon",
                 "coordinates": [[[5.0, 5.0], [8.0, 5.0], [8.0, 8.0],
                                  [5.0, 8.0], [5.0, 5.0]]]},
    "properties": {"name": "A"},
}


def _poly_snapshot():
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot, MapRenderSnapshot)
    layer = MapLayerSnapshot(
        id="doc-poly", name="相带", layer_type="vector",
        extent=(5.0, 5.0, 8.0, 8.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=(dict(_POLY_FEATURE),),
        style={"fill": "#ff0000", "stroke": "#ff0000", "stroke_width": 1.0},
        visible=True, opacity=1.0)
    return MapRenderSnapshot(project_crs="EPSG:4326", layers=(layer,))


class _FakeTools:
    def __init__(self):
        self.active_tool = None

    def set_active_tool(self, tool):
        self.active_tool = tool


class _IdentifyTool:
    tool_id = "identify"


def try_click(app, shim, label: str, point=(260, 140)) -> list:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    shim.set_layer_snapshot(_poly_snapshot())
    shim.set_current_layer("doc-poly")
    tools = _FakeTools()
    shim.set_map_tool_controller(tools)
    tools.set_active_tool(_IdentifyTool())
    app.processEvents()
    results: list = []
    shim.native_identified.connect(results.append)
    QTest.mouseClick(shim._canvas_viewport(), Qt.LeftButton,
                     Qt.NoModifier, QPoint(*point))
    t0 = time.time()
    while time.time() - t0 < 4 and not results:
        app.processEvents()
        time.sleep(0.05)
    log(label, "->", results or "SILENT")
    try:
        shim.native_identified.disconnect(results.append)
    except Exception:
        pass
    return results


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication(sys.argv)
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

    # C1：裸 shim + 完整范式（含 waitExposed）。
    s1 = QgisCanvasShim()
    s1.resize(400, 400)
    s1.show()
    QTest.qWaitForWindowExposed(s1, 5000)
    s1.set_extent((0.0, 0.0, 10.0, 10.0))
    app.processEvents()
    try_click(app, s1, "C1 shim+paradigm")

    # C2：同 C1 但不用 waitExposed（验证暴露等待是否关键）。
    s2 = QgisCanvasShim()
    s2.resize(400, 400)
    s2.show()
    app.processEvents()
    s2.set_extent((0.0, 0.0, 10.0, 10.0))
    app.processEvents()
    try_click(app, s2, "C2 shim no-waitExposed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
