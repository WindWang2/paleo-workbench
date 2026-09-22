# -*- coding: utf-8 -*-
"""Task 9 探针 bisect2：空白 QgisCanvasShim 起步，逐步叠加文档侧操作。"""
from __future__ import annotations

import json
import sys
import time

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "geometry": {"type": "Polygon", "coordinates":
                  [[[5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0], [5.0, 5.0]]]},
     "properties": {"__pwb_fid": "f1", "name": "A"}}]}


def log(*args):
    print("[bisect2]", *args, flush=True)


def try_click(app, shim, label: str) -> list:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from paleo_workbench.ui.qgis_stack.widgets import canvas_viewport
    raw: list = []
    shim.stack.set_selection_callback(
        shim.canvas_address,
        lambda action, payload: raw.append((action, json.loads(payload))))
    shim.stack.upsert_mirror_layer("bx:poly", "面", "Polygon", "EPSG:4326",
                                   json.dumps(_FC), "", "", "", True, 1.0,
                                   is_reference=False, is_editable=True)
    shim.set_extent((0.0, 0.0, 10.0, 10.0))
    app.processEvents()
    shim.stack.set_current_layer(shim.canvas_address, "bx:poly")
    shim.stack.set_map_tool(shim.canvas_address, "identify")
    app.processEvents()
    vp = canvas_viewport(shim.canvas) or shim.canvas
    scr = shim.stack.map_to_screen(shim.canvas_address, 6.5, 6.5)
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(scr[0]), int(scr[1])))
    t0 = time.time()
    while time.time() - t0 < 4 and not raw:
        app.processEvents()
        time.sleep(0.05)
    log(label, "->", [(a, p.get("feature_id")) for a, p in raw] or "SILENT")
    return raw


def main() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    shim = QgisCanvasShim()
    shim.resize(400, 400)
    shim.show()
    app.processEvents()

    try_click(app, shim, "S0 plain-shim")
    # S1：目标 CRS。
    shim.stack.set_destination_crs(shim.canvas_address, "EPSG:4326")
    app.processEvents()
    try_click(app, shim, "S1 +destination-crs")
    # S2：工区快照镜像（含 21 口井 + 边界 + 地震工区）。
    import os
    import shutil as _sh
    _src = "/home/kevin/projects/paleo_project/data/project_area"
    _tmp = "/tmp/probe_task9c/project_area"
    if os.path.isdir("/tmp/probe_task9c"):
        _sh.rmtree("/tmp/probe_task9c")
    _sh.copytree(_src, _tmp)
    with open(os.path.join(_tmp, "project_area.paleo.json"), encoding="utf-8") as fh:
        from paleo_workbench.project.models import ProjectDocument
        project = ProjectDocument.model_validate(json.load(fh))
    from paleo_workbench.mapping.workarea_map_snapshot import build_workarea_map_snapshot
    from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot
    snap = build_workarea_map_snapshot(project)
    log("snapshot layers:", [(layer.id, len(layer.features)) for layer in snap.layers])
    shim.set_layer_snapshot(MapRenderSnapshot(project_crs="EPSG:4326", layers=snap.layers))
    app.processEvents()
    t0 = time.time()
    while time.time() - t0 < 3:
        app.processEvents()
        time.sleep(0.05)
    try_click(app, shim, "S2 +workarea-mirror")
    # S3：图层树视图。
    tree_addr = shim.stack.create_layer_tree_view(shim.canvas_address)
    log("tree view addr:", tree_addr)
    app.processEvents()
    try_click(app, shim, "S3 +tree-view")
    # S4：工具控制器绑定 + 经 controller 激活 identify（生产路径）。
    from types import SimpleNamespace

    class _Tools:
        def __init__(self):
            self.active_tool = None

        def set_active_tool(self, tool):
            self.active_tool = tool

    tools = _Tools()
    shim.set_map_tool_controller(SimpleNamespace(tools=tools))
    app.processEvents()
    ident = SimpleNamespace(tool_id="identify")
    tools.set_active_tool(ident)  # 经 shim _wrapped -> 桥 identify
    app.processEvents()
    log("S4 _last_native_tool:", getattr(shim, "_last_native_tool", None))
    try_click(app, shim, "S4 +tool-controller")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
